import json
import time
from collections import defaultdict

from flask import g, jsonify, request, session

from ..auth import ensure_api_key, require_atlassian_secret
from ..auth_identity import is_local_client, issue_csrf, require_csrf, require_workspace
from ..services.slack_async import enqueue_slack_thread_capture, slack_retry_num
from ..config import Config
from ..services import llm
from ..services.retrieval import score_decisions
from ..services.slack_ingest import persist_slack_thread
from ..services.triggers import should_extract

from ..services.slack_verify import verify_slack_signature
from ..services.webhook_workspace import webhook_workspace_id
from ..store import store
from . import api_bp

_auth_hits: dict[str, list[float]] = defaultdict(list)


def _rate_limit(key: str) -> bool:
    now = time.time()
    window = _auth_hits[key]
    _auth_hits[key] = [t for t in window if now - t < 60]
    from ..config import Config
    if len(_auth_hits[key]) >= Config.AUTH_RATE_LIMIT:
        return False
    _auth_hits[key].append(now)
    return True


def _ws():
    return getattr(g, 'workspace_id', None) or store.get_default_workspace_id()


def _role():
    actor = getattr(g, 'actor', None)
    return actor.role if actor else None


@api_bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'Whyline', 'apis': Config.status()})


@api_bp.route('/session', methods=['POST'])
def create_session():
    """Loopback-only session — checks remote_addr, never Host header."""
    if not is_local_client():
        return jsonify({'error': 'session only allowed from localhost'}), 403
    session['authed'] = True
    session.permanent = True
    return jsonify({'ok': True, 'csrf': issue_csrf()})


@api_bp.route('/auth/csrf', methods=['GET'])
def auth_csrf():
    return jsonify({'csrf': issue_csrf()})


@api_bp.route('/auth/login', methods=['POST'])
def auth_login():
    if not _rate_limit(request.remote_addr or 'unknown'):
        return jsonify({'error': 'rate limited'}), 429
    body = request.get_json(silent=True) or {}
    email, password = body.get('email', ''), body.get('password', '')
    if not email or not password:
        return jsonify({'error': 'email and password required'}), 400
    user = store.verify_login(email, password)
    if not user:
        return jsonify({'error': 'invalid credentials'}), 401
    session.clear()
    session['user_id'] = user['id']
    session.permanent = True
    return jsonify({'ok': True, 'user': user, 'csrf': issue_csrf()})


@api_bp.route('/auth/register', methods=['POST'])
def auth_register():
    if Config.AUTH_MODE != 'open':
        return jsonify({'error': 'registration disabled'}), 403
    if not _rate_limit(request.remote_addr or 'unknown'):
        return jsonify({'error': 'rate limited'}), 429
    body = request.get_json(silent=True) or {}
    email, password = body.get('email', ''), body.get('password', '')
    if not email or not password:
        return jsonify({'error': 'email and password required'}), 400
    if store.get_user_by_email(email):
        return jsonify({'error': 'email already registered'}), 409
    user = store.create_user(email, password)
    ws = store.create_workspace(f"{email.split('@')[0]}'s workspace")
    store.add_member(ws['id'], user['id'], 'owner')
    session.clear()
    session['user_id'] = user['id']
    session.permanent = True
    return jsonify({'ok': True, 'user': user, 'workspace_id': ws['id'], 'csrf': issue_csrf()})


@api_bp.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'ok': True})


@api_bp.route('/donation', methods=['GET'])
def donation():
    addr = Config.SOL_DONATION_ADDRESS
    if not addr:
        return jsonify({'enabled': False, 'note': 'Donations not configured for this deployment.'})
    return jsonify({
        'enabled': True, 'chain': 'solana', 'token': 'SOL', 'address': addr,
        'uri': f'solana:{addr}', 'note': 'Voluntary SOL on Solana chain only.',
    })


# --- Decisions CRUD (server-side SQLite) ---

@api_bp.route('/decisions', methods=['GET'])
@require_workspace('read')
def list_decisions():
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    return jsonify({'ok': True, 'decisions': store.list_decisions(
        workspace_id=_ws(), search=search, status=status, actor_role=_role())})


@api_bp.route('/decisions/<decision_id>', methods=['GET'])
@require_workspace('read')
def get_decision(decision_id):
    d = store.get_decision(decision_id, workspace_id=_ws(), actor_role=_role())
    if not d:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'ok': True, 'decision': d})


@api_bp.route('/decisions', methods=['POST'])
@require_workspace('create')
@require_csrf
def create_decision():
    body = request.get_json(silent=True) or {}
    sources = body.pop('sources', None)
    d = store.upsert_decision(body, sources=sources, workspace_id=_ws())
    store.audit(_ws(), g.actor.kind, g.actor.id, 'decision.create', 'decision', d['id'])
    return jsonify({'ok': True, 'decision': d})


@api_bp.route('/decisions/<decision_id>', methods=['PATCH'])
@require_workspace('manage')
@require_csrf
def patch_decision(decision_id):
    body = request.get_json(silent=True) or {}
    d = store.update_decision(decision_id, body, workspace_id=_ws())
    if not d:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'ok': True, 'decision': d})


@api_bp.route('/decisions/<decision_id>/supersede', methods=['POST'])
@require_workspace('manage')
@require_csrf
def supersede_decision(decision_id):
    body = request.get_json(silent=True) or {}
    if not store.get_decision(decision_id, workspace_id=_ws()):
        return jsonify({'error': 'not found'}), 404
    new_d = store.upsert_decision(body, workspace_id=_ws())
    old = store.supersede(decision_id, new_d['id'], workspace_id=_ws())
    if not old:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'ok': True, 'superseded': decision_id, 'replacement': new_d})


@api_bp.route('/decisions/<decision_id>', methods=['DELETE'])
@require_workspace('manage')
@require_csrf
def delete_decision(decision_id):
    if not store.delete_decision(decision_id, workspace_id=_ws()):
        return jsonify({'error': 'not found'}), 404
    return jsonify({'ok': True})


@api_bp.route('/decisions/export', methods=['GET'])
@require_workspace('read')
def export_decisions():
    return jsonify({'ok': True, **store.export_all(workspace_id=_ws())})


@api_bp.route('/decisions/import', methods=['POST'])
@require_workspace('manage')
@require_csrf
def import_decisions():
    body = request.get_json(silent=True) or {}
    if not body.get('decisions'):
        return jsonify({'error': 'decisions array required'}), 400
    result = store.import_decisions(body, workspace_id=_ws())
    return jsonify({'ok': True, **result})


# --- AI ---

def _validate_answer_ids(result: llm.AskResult, corpus_ids: set) -> llm.AskResult:
    result.decisionIds = [i for i in result.decisionIds if i in corpus_ids]
    return result


def _attach_provenance(result: llm.AskResult, decisions: list) -> dict:
    out = result.model_dump()
    by_id = {d['id']: d for d in decisions}
    receipts = []
    for did in out.get('decisionIds', []):
        d = by_id.get(did)
        if not d:
            continue
        for s in d.get('sources', []):
            receipts.append({
                'decisionId': did,
                'title': d.get('title'),
                'url': s.get('url'),
                'sourceType': s.get('sourceType'),
                'externalRef': s.get('externalRef'),
                'excerpt': s.get('excerpt'),
            })
        if not d.get('sources'):
            receipts.append({'decisionId': did, 'title': d.get('title'), 'url': '', 'sourceType': d.get('sourceType')})
    out['receipts'] = receipts
    return out


@api_bp.route('/ai/ask', methods=['POST'])
@require_workspace('read')
def ai_ask():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    q = (request.get_json(silent=True) or {}).get('question', '').strip()
    if not q:
        return jsonify({'error': 'question required'}), 400
    try:
        active = store.all_active_text_blob(_ws(), actor_role=_role())
        top = score_decisions(q, active, top_k=Config.RETRIEVAL_TOP_K)
        if not top:
            return jsonify({
                'ok': True,
                'retrieved': 0,
                'result': {
                    'answer': 'No matching decisions in the corpus for this question.',
                    'confidence': 'none',
                    'decisionIds': [],
                    'trail': [],
                    'gaps': ['No keyword overlap with active decisions — nothing retrieved.'],
                    'receipts': [],
                },
            })
        result = llm.ask_why(q, top)
        corpus_ids = {d['id'] for d in top}
        result = _validate_answer_ids(result, corpus_ids)
        return jsonify({'ok': True, 'result': _attach_provenance(result, top), 'retrieved': len(top)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/ai/extract', methods=['POST'])
@require_workspace('create')
@require_csrf
def ai_extract():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    text = body.get('text', '').strip()
    if not text:
        return jsonify({'error': 'text required'}), 400
    try:
        extracted = llm.extract_decision_from_thread([{'text': text}], body.get('source', 'manual'))
        data = extracted.model_dump()
        sources = body.get('sources') or [{'sourceType': 'manual', 'excerpt': text[:300], 'url': body.get('url', '')}]
        d = store.upsert_decision({**data, 'sourceType': body.get('source', 'manual'), 'topicIds': data.get('topics', [])},
                                  sources=sources, workspace_id=_ws())
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/ai/synthesize', methods=['POST'])
@require_workspace('create')
@require_csrf
def ai_synthesize():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    frags = (request.get_json(silent=True) or {}).get('fragments', [])
    if not frags:
        return jsonify({'error': 'fragments required'}), 400
    try:
        extracted = llm.synthesize_decision(frags)
        data = extracted.model_dump()
        d = store.upsert_decision({**data, 'sourceType': 'synthesis', 'topicIds': data.get('topics', [])},
                                  sources=[{'sourceType': 'synthesis', 'excerpt': '; '.join(frags)[:400]}],
                                  workspace_id=_ws())
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/ai/enhance-brief', methods=['POST'])
@require_workspace('read')
def enhance_brief():
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    body = request.get_json(silent=True) or {}
    try:
        ctx = {'decisions': store.list_decisions(workspace_id=_ws(), status='active', limit=100, actor_role=_role())}
        brief = llm.enhance_brief(body.get('brief', ''), ctx)
        return jsonify({'ok': True, 'brief': brief})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Integrations ---

@api_bp.route('/integrations/status', methods=['GET'])
@require_workspace('read')
def integrations_status():
    return jsonify({
        'slack': {'configured': bool(Config.SLACK_BOT_TOKEN and Config.SLACK_SIGNING_SECRET),
                  'slash': '/whyline', 'reaction': 'pushpin'},
        'email': {'configured': bool(Config.EMAIL_WEBHOOK_SECRET),
                  'endpoint': '/api/integrations/email/ingest', 'alias': 'decisions@yourco'},
        'transcript': {'configured': bool(Config.LLM_API_KEY), 'endpoint': '/api/integrations/transcript/ingest'},
        'doc': {'configured': bool(Config.LLM_API_KEY), 'types': ['notion', 'confluence', 'gdocs'],
                'endpoint': '/api/integrations/doc/ingest'},
        'github': {'configured': bool(Config.GITHUB_WEBHOOK_SECRET), 'endpoint': '/api/integrations/github/webhook'},
        'gitlab': {'configured': bool(Config.GITHUB_WEBHOOK_SECRET), 'endpoint': '/api/integrations/gitlab/webhook'},
        'teams': {'configured': bool(Config.TEAMS_WEBHOOK_SECRET), 'endpoint': '/api/integrations/teams/ingest'},
        'linear': {'configured': bool(Config.LINEAR_WEBHOOK_SECRET), 'endpoint': '/api/integrations/linear/webhook'},
        'salesforce': {'configured': bool(Config.SALESFORCE_WEBHOOK_SECRET),
                       'endpoint': '/api/integrations/salesforce/webhook'},
        'atlassian': {'configured': bool(Config.ATLASSIAN_WEBHOOK_SECRET)},
        'mcp': {'configured': True, 'tools': ['whyline_ask', 'whyline_extract', 'whyline_search']},
    })


@api_bp.route('/integrations/slack/events', methods=['POST'])
def slack_events():
    if not Config.SLACK_SIGNING_SECRET:
        return jsonify({'error': 'SLACK_SIGNING_SECRET not configured'}), 503
    body_raw = request.get_data()
    sig = request.headers.get('X-Slack-Signature', '')
    ts = request.headers.get('X-Slack-Request-Timestamp', '')
    if not verify_slack_signature(Config.SLACK_SIGNING_SECRET, ts, body_raw, sig):
        return jsonify({'error': 'invalid signature'}), 403

    payload = request.get_json(silent=True) or {}
    if payload.get('type') == 'url_verification':
        return jsonify({'challenge': payload.get('challenge')})

    if payload.get('type') == 'event_callback':
        event_id = payload.get('event_id', '')
        if slack_retry_num(request.headers) > 0 and store.capture_event_done(event_id):
            return jsonify({'ok': True})

        event = payload.get('event', {})
        etype = event.get('type')

        if etype == 'reaction_added':
            reaction = (event.get('reaction') or '').lower()
            if reaction in Config.SLACK_CAPTURE_REACTIONS:
                item = event.get('item', {})
                if item.get('type') == 'message':
                    channel, ts = item.get('channel'), item.get('ts')
                    if channel and ts:
                        enqueue_slack_thread_capture(channel, ts, label='reaction', event_id=event_id)
            return jsonify({'ok': True})

        if etype == 'app_mention':
            channel = event.get('channel')
            ts = event.get('thread_ts') or event.get('ts')
            text = event.get('text', '')
            if channel and ts and should_extract(text):
                enqueue_slack_thread_capture(channel, ts, label='mention', event_id=event_id)
            return jsonify({'ok': True})

    return jsonify({'ok': True})


@api_bp.route('/integrations/slack/capture', methods=['POST'])
@require_workspace('create')
@require_csrf
def slack_capture_manual():
    """Manual: POST {channel, thread_ts} to capture a thread."""
    if not Config.SLACK_BOT_TOKEN:
        return jsonify({'error': 'SLACK_BOT_TOKEN not configured'}), 400
    body = request.get_json(silent=True) or {}
    channel, thread_ts = body.get('channel'), body.get('thread_ts')
    if not channel or not thread_ts:
        return jsonify({'error': 'channel and thread_ts required'}), 400
    try:
        d = persist_slack_thread(channel, thread_ts)
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/integrations/slack/ingest', methods=['POST'])
@require_workspace('create')
@require_csrf
def slack_ingest():
    messages = (request.get_json(silent=True) or {}).get('messages', [])
    if not messages:
        return jsonify({'error': 'messages required'}), 400
    try:
        extracted = llm.extract_decision_from_thread(messages)
        data = extracted.model_dump()
        d = store.upsert_decision({**data, 'sourceType': 'slack', 'topicIds': data.get('topics', [])},
                                  sources=[{'sourceType': 'slack', 'excerpt': json.dumps(messages)[:400]}],
                                  workspace_id=_ws())
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/integrations/atlassian/jira', methods=['POST'])
@require_atlassian_secret
def atlassian_jira():
    payload = request.get_json(silent=True) or {}
    text = ' '.join(filter(None, [payload.get('summary'), payload.get('comment'), payload.get('description')]))
    if not should_extract(text, payload.get('labels')):
        return jsonify({'ok': True, 'skipped': True, 'reason': 'no decision trigger — add [decision] or decision: label'})
    if not Config.LLM_API_KEY:
        return jsonify({'error': 'LLM_API_KEY not configured'}), 400
    try:
        extracted = llm.ingest_jira_payload(payload)
        data = extracted.model_dump()
        jira_key = payload.get('issueKey') or payload.get('key', '')
        jira_url = payload.get('url') or (f"https://jira.example/browse/{jira_key}" if jira_key else '')
        source_key = f'jira:{jira_key}' if jira_key else None
        sources = [{'sourceType': 'jira', 'externalRef': jira_key, 'url': jira_url,
                    'excerpt': (payload.get('summary') or '')[:300]}]
        d = store.upsert_decision(
            {**data, 'sourceType': 'jira', 'topicIds': data.get('topics', [])},
            sources=sources, source_key=source_key,
            workspace_id=webhook_workspace_id(payload),
        )
        return jsonify({'ok': True, 'decision': d})
    except Exception as e:
        return jsonify({'error': str(e)}), 500