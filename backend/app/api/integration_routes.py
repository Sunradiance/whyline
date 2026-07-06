"""Integration ingest endpoints — email, transcript, docs, GitHub, Teams, Linear, Salesforce, Slack slash."""
import json
import re

from flask import jsonify, request

from flask import g

from ..auth import (
    require_email_secret,
    require_github_webhook,
    require_header_secret,
    require_linear_secret,
    require_salesforce_secret,
    require_teams_secret,
)
from ..auth_identity import require_csrf, require_workspace
from ..config import Config
from ..services import llm
from ..services.email_parse import email_to_messages, parse_email_payload
from ..services.ingest import persist_extracted
from ..services.webhook_workspace import webhook_workspace_id
from ..services.retrieval import score_decisions
from ..services.slack_async import enqueue_slack_slash
from ..services.triggers import linear_human_text, should_extract
from ..services.slack_verify import verify_slack_signature
from ..store import store
from . import api_bp

require_linear_webhook = require_linear_secret


def _ws():
    return getattr(g, 'workspace_id', None) or store.get_default_workspace_id()
require_salesforce_webhook = require_salesforce_secret
require_teams_webhook = require_teams_secret


def _transcript_segments(body: dict) -> list[dict]:
    if body.get('segments'):
        return body['segments']
    text = (body.get('text') or '').strip()
    if not text:
        return []
    segments = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^(.+?)\s*[\(\[](\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{3})?)[\)\]]\s*:\s*(.+)$', line)
        if not m:
            m = re.match(r'^(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{3})?)\s+(.+?):\s*(.+)$', line)
            if m:
                segments.append({'speaker': m.group(2).strip(), 'timestamp': m.group(1), 'text': m.group(3).strip()})
                continue
        if m:
            segments.append({'speaker': m.group(1).strip(), 'timestamp': m.group(2), 'text': m.group(3).strip()})
        else:
            segments.append({'speaker': 'unknown', 'text': line})
    return segments


# --- Universal: decisions@ email ---

def _ingest_email_body(payload: dict, raw: bytes | None = None) -> dict:
    parsed = parse_email_payload(payload, raw)
    if not parsed.get('body') and not parsed.get('subject'):
        raise ValueError('email body or subject required')
    messages = email_to_messages(parsed)
    extracted = llm.extract_decision_from_thread(messages, source_hint='email')
    data = extracted.model_dump()
    mid = parsed.get('message_id') or ''
    source_key = f'email:{mid}' if mid else None
    sources = [{
        'sourceType': 'email',
        'externalRef': mid or parsed.get('subject', '')[:80],
        'url': parsed.get('url', ''),
        'excerpt': parsed.get('body', '')[:500],
    }]
    return persist_extracted(data, 'email', sources, source_key=source_key, workspace_id=_ws())


@api_bp.route('/integrations/email/capture', methods=['POST'])
@require_workspace('create')
@require_csrf
def email_capture():
    """UI / manual: paste forwarded email."""
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    try:
        d = _ingest_email_body(body)
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/integrations/email/ingest', methods=['POST'])
@require_email_secret
def email_ingest():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    payload = request.get_json(silent=True) or {}
    try:
        d = _ingest_email_body(payload, request.get_data() if not payload else None)
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Meeting transcripts ---

@api_bp.route('/integrations/transcript/ingest', methods=['POST'])
@require_workspace('create')
@require_csrf
def transcript_ingest():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    segments = _transcript_segments(body)
    if not segments:
        return jsonify({'error': 'text or segments required'}), 400
    try:
        meta = {'title': body.get('title', ''), 'url': body.get('url', ''), 'provider': body.get('provider', 'manual')}
        extracted = llm.extract_decision_from_transcript(segments, meta)
        data = extracted.model_dump()
        sk = body.get('source_key') or (f"transcript:{body.get('url')}" if body.get('url') else None)
        sources = [{
            'sourceType': 'transcript',
            'externalRef': meta.get('title') or meta.get('provider', 'meeting'),
            'url': meta.get('url', ''),
            'excerpt': ' '.join(s.get('text', '') for s in segments[:6])[:500],
        }]
        d = persist_extracted(data, 'transcript', sources, source_key=sk, workspace_id=_ws())
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Docs: Notion / Confluence / Google Docs ---

@api_bp.route('/integrations/doc/ingest', methods=['POST'])
@require_workspace('create')
@require_csrf
def doc_ingest():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    title = (body.get('title') or 'Untitled doc').strip()
    text = (body.get('text') or body.get('body') or '').strip()
    source_type = (body.get('sourceType') or body.get('source') or 'doc').strip().lower()
    url = (body.get('url') or '').strip()
    if not text:
        return jsonify({'error': 'text required'}), 400
    if source_type not in ('notion', 'confluence', 'gdocs', 'doc', 'google_docs'):
        source_type = 'doc'
    if source_type == 'google_docs':
        source_type = 'gdocs'
    try:
        extracted = llm.extract_decision_from_doc(title, text, source_type)
        data = extracted.model_dump()
        sk = f'{source_type}:{url}' if url else None
        sources = [{'sourceType': source_type, 'externalRef': title, 'url': url, 'excerpt': text[:500]}]
        d = persist_extracted(data, source_type, sources, source_key=sk, workspace_id=_ws())
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- GitHub / GitLab (GitHub webhook signature; GitLab via secret header) ---

@api_bp.route('/integrations/github/webhook', methods=['POST'])
@require_github_webhook
def github_webhook():
    payload = request.get_json(silent=True) or {}
    event = request.headers.get('X-GitHub-Event', '')
    normalized = {'event': event, 'action': payload.get('action'), 'repository': payload.get('repository', {}).get('full_name')}

    body_text = ''
    labels = []
    path = ''

    if event == 'issue_comment':
        ic = payload.get('issue', {})
        c = payload.get('comment', {})
        body_text = c.get('body') or ''
        labels = [l.get('name', '') for l in ic.get('labels', [])]
        normalized.update({
            'issue_number': ic.get('number'),
            'title': ic.get('title'),
            'body': body_text,
            'url': c.get('html_url'),
            'user': c.get('user', {}).get('login'),
        })
        source_key = f"github:issue:{normalized.get('repository')}:{ic.get('number')}"
    elif event in ('pull_request_review_comment', 'pull_request_review'):
        pr = payload.get('pull_request', {})
        c = payload.get('comment', payload.get('review', {}))
        body_text = c.get('body') or pr.get('body') or ''
        normalized.update({
            'pr_number': pr.get('number'),
            'title': pr.get('title'),
            'body': body_text,
            'url': c.get('html_url') or pr.get('html_url'),
            'user': (c.get('user') or {}).get('login'),
        })
        source_key = f"github:pr:{normalized.get('repository')}:{pr.get('number')}"
    else:
        normalized.update({
            'title': payload.get('issue', payload.get('pull_request', {})).get('title'),
            'body': json.dumps(payload)[:4000],
            'url': payload.get('html_url', ''),
        })
        body_text = normalized.get('body', '')
        source_key = None

    if not should_extract(body_text, labels, path):
        return jsonify({'ok': True, 'skipped': True, 'reason': 'no decision trigger — use [decision] or decision: label'})
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400

    try:
        extracted = llm.extract_decision_from_github(normalized)
        data = extracted.model_dump()
        sources = [{
            'sourceType': 'github',
            'externalRef': f"{normalized.get('repository', '')} #{normalized.get('issue_number') or normalized.get('pr_number', '')}".strip(),
            'url': normalized.get('url', ''),
            'excerpt': (normalized.get('body') or '')[:500],
        }]
        d = persist_extracted(data, 'github', sources, source_key=source_key,
                              workspace_id=webhook_workspace_id(payload))
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/integrations/gitlab/webhook', methods=['POST'])
@require_header_secret('GITHUB_WEBHOOK_SECRET', header_name='X-Gitlab-Token', env_name='GITHUB_WEBHOOK_SECRET')
def gitlab_webhook():
    """GitLab: set X-Gitlab-Token to GITHUB_WEBHOOK_SECRET (or add GITLAB_WEBHOOK_SECRET later)."""
    payload = request.get_json(silent=True) or {}
    obj = payload.get('object_attributes', payload.get('issue', payload.get('merge_request', {})))
    body_text = obj.get('description') or payload.get('description', payload.get('note', ''))
    normalized = {
        'event': payload.get('object_kind', 'note'),
        'title': obj.get('title') or payload.get('title', ''),
        'body': body_text,
        'url': obj.get('url') or payload.get('url', ''),
        'project': (payload.get('project', {}) or {}).get('path_with_namespace', ''),
    }
    if not should_extract(body_text):
        return jsonify({'ok': True, 'skipped': True, 'reason': 'no decision trigger'})
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    try:
        extracted = llm.extract_decision_from_github(normalized)
        data = extracted.model_dump()
        sk = f"gitlab:{normalized.get('url')}" if normalized.get('url') else None
        sources = [{'sourceType': 'gitlab', 'externalRef': normalized.get('title', '')[:80],
                    'url': normalized.get('url', ''), 'excerpt': (normalized.get('body') or '')[:500]}]
        d = persist_extracted(data, 'gitlab', sources, source_key=sk,
                              workspace_id=webhook_workspace_id(payload))
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- MS Teams ---

def _ingest_teams_body(body: dict, workspace_id: str = None) -> dict:
    messages = body.get('messages') or [{'text': body.get('text', ''), 'from': body.get('from', 'teams')}]
    if not any(m.get('text') for m in messages):
        raise ValueError('messages or text required')
    extracted = llm.extract_decision_from_thread(messages, source_hint='teams')
    data = extracted.model_dump()
    url = body.get('url', '')
    sk = f"teams:{url}" if url else body.get('source_key')
    sources = [{'sourceType': 'teams', 'externalRef': body.get('thread_id', 'teams-thread'),
                'url': url, 'excerpt': '\n'.join(m.get('text', '') for m in messages[:5])[:500]}]
    ws = workspace_id or store.get_default_workspace_id()
    return persist_extracted(data, 'teams', sources, source_key=sk, workspace_id=ws)


@api_bp.route('/integrations/teams/capture', methods=['POST'])
@require_workspace('create')
@require_csrf
def teams_capture():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    try:
        d = _ingest_teams_body(body)
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/integrations/teams/ingest', methods=['POST'])
@require_teams_webhook
def teams_ingest():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    try:
        d = _ingest_teams_body(body)
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Linear ---

@api_bp.route('/integrations/linear/webhook', methods=['POST'])
@require_linear_webhook
def linear_webhook():
    payload = request.get_json(silent=True) or {}
    text = linear_human_text(payload)
    if not should_extract(text, payload.get('labels')):
        return jsonify({'ok': True, 'skipped': True, 'reason': 'no decision trigger — add [decision] to issue/comment'})
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    try:
        extracted = llm.extract_decision_from_linear(payload)
        data = extracted.model_dump()
        issue_id = payload.get('issueId') or payload.get('data', {}).get('id', '')
        url = payload.get('url') or payload.get('data', {}).get('url', '')
        sk = f'linear:{issue_id}' if issue_id else None
        sources = [{'sourceType': 'linear', 'externalRef': issue_id or payload.get('title', ''),
                    'url': url, 'excerpt': json.dumps(payload)[:500]}]
        d = persist_extracted(data, 'linear', sources, source_key=sk,
                              workspace_id=webhook_workspace_id(payload))
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Salesforce (scoped) ---

@api_bp.route('/integrations/salesforce/webhook', methods=['POST'])
@require_salesforce_webhook
def salesforce_webhook():
    payload = request.get_json(silent=True) or {}
    text = ' '.join(str(payload.get(k, '')) for k in ('Subject', 'Description', 'Body', 'summary', 'note') if payload.get(k))
    if not should_extract(text):
        return jsonify({'ok': True, 'skipped': True, 'reason': 'no decision trigger'})
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    try:
        extracted = llm.extract_decision_from_salesforce(payload)
        data = extracted.model_dump()
        ref = payload.get('Id') or payload.get('id') or payload.get('recordId', '')
        sk = f'salesforce:{ref}' if ref else None
        sources = [{'sourceType': 'salesforce', 'externalRef': ref,
                    'url': payload.get('url', ''), 'excerpt': json.dumps(payload)[:500]}]
        d = persist_extracted(data, 'salesforce', sources, source_key=sk,
                              workspace_id=webhook_workspace_id(payload))
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Slack /whyline slash command ---

@api_bp.route('/integrations/slack/commands', methods=['POST'])
def slack_commands():
    if not Config.SLACK_SIGNING_SECRET:
        return jsonify({'error': 'SLACK_SIGNING_SECRET not configured'}), 503
    body_raw = request.get_data()
    sig = request.headers.get('X-Slack-Signature', '')
    ts = request.headers.get('X-Slack-Request-Timestamp', '')
    if not verify_slack_signature(Config.SLACK_SIGNING_SECRET, ts, body_raw, sig):
        return jsonify({'error': 'invalid signature'}), 403

    text = (request.form.get('text') or '').strip()
    user = request.form.get('user_name', 'slack')

    if not Config.LLM_API_KEY:
        return jsonify({'response_type': 'ephemeral', 'text': 'LLM_API_KEY not configured on Whyline server.'})

    response_url = request.form.get('response_url', '')
    enqueue_slack_slash(text, user, response_url)
    return jsonify({'response_type': 'ephemeral', 'text': 'Capturing decision…'})


# --- Search (retrieval without LLM) ---

@api_bp.route('/ai/search', methods=['POST'])
@require_workspace('read')
def ai_search():
    q = (request.get_json(silent=True) or {}).get('query', '').strip()
    if not q:
        return jsonify({'error': 'query required'}), 400
    top_k = int((request.get_json(silent=True) or {}).get('top_k') or Config.RETRIEVAL_TOP_K)
    active = store.all_active_text_blob(_ws())
    top = score_decisions(q, active, top_k=top_k)
    return jsonify({'ok': True, 'decisions': top, 'count': len(top)})