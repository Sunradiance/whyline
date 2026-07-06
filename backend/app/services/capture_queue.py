"""Durable capture queue — write to SQLite before ack; drain on boot."""
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from threading import Timer

from ..config import Config
from ..store import store

log = logging.getLogger('whyline.capture')
_executor = ThreadPoolExecutor(max_workers=Config.CAPTURE_MAX_CONCURRENT, thread_name_prefix='capture')
_enqueue_count = 0


def _retry_delay(retry_count: int) -> float:
    base = Config.CAPTURE_RETRY_BASE_SECONDS
    ceiling = Config.CAPTURE_RETRY_MAX_SECONDS
    exp = min(base * (2 ** max(0, retry_count - 1)), ceiling)
    return exp + random.uniform(0, exp * 0.25)


def _maybe_prune():
    global _enqueue_count
    _enqueue_count += 1
    if _enqueue_count % Config.CAPTURE_PRUNE_EVERY_N == 0:
        removed = store.prune_captures(Config.CAPTURE_PRUNE_DAYS)
        if removed:
            log.info('pruned %s terminal capture rows', removed)


def _schedule_retry(job_id: str, retry_count: int):
    delay = _retry_delay(retry_count)

    def run():
        job = store.get_capture(job_id)
        if job and job.get('status') == 'pending':
            _executor.submit(_process_job, job_id)

    Timer(delay, run).start()
    log.info('capture retry scheduled id=%s in %.1fs (attempt %s)', job_id, delay, retry_count)


def enqueue(kind: str, payload: dict, event_id: str = '') -> str:
    job_id = store.enqueue_capture(kind, payload, event_id=event_id)
    _maybe_prune()
    job = store.get_capture(job_id)
    if job and job.get('status') == 'pending':
        _executor.submit(_process_job, job_id)
    return job_id


def drain_pending():
    store.prune_captures(Config.CAPTURE_PRUNE_DAYS)
    for job_id in store.list_pending_capture_ids():
        _executor.submit(_process_job, job_id)


def _process_job(job_id: str):
    job = store.claim_capture(job_id)
    if not job:
        return
    try:
        kind, p = job['kind'], job['payload']
        if kind == 'slack_thread':
            from .slack_client import resolve_thread_ts
            from .slack_ingest import persist_slack_thread
            channel = p['channel']
            message_ts = p.get('message_ts') or p.get('thread_ts')
            thread_ts = resolve_thread_ts(channel, message_ts)
            persist_slack_thread(channel, thread_ts)
            log.info('slack_thread ok channel=%s ts=%s', channel, thread_ts)
        elif kind == 'slack_slash':
            _process_slash(p)
        else:
            log.warning('unknown capture kind %s', kind)
        store.complete_capture(job_id)
    except Exception:
        log.exception('capture failed id=%s', job_id)
        store.fail_capture(job_id, max_retries=Config.CAPTURE_MAX_RETRIES)
        job_after = store.get_capture(job_id)
        if job_after and job_after.get('status') == 'pending':
            _schedule_retry(job_id, job_after.get('retry_count') or 1)


def _process_slash(p: dict):
    import requests
    from ..config import Config
    from ..services import llm
    from .ingest import persist_extracted
    from .slack_client import parse_thread_ref
    from .slack_ingest import persist_slack_thread

    text, user, response_url = p.get('text', ''), p.get('user', ''), p.get('response_url', '')
    channel, thread_ts = parse_thread_ref(text)
    if channel and thread_ts and Config.SLACK_BOT_TOKEN:
        d = persist_slack_thread(channel, thread_ts)
        msg = f"✓ Captured from thread: *{d.get('title', 'Decision')}*"
    elif not text:
        msg = 'Usage: `/whyline <decision text>` or paste a Slack thread URL'
    else:
        extracted = llm.extract_decision_from_thread([{'user': user, 'text': text}], source_hint='slack-cmd')
        d = persist_extracted(extracted.model_dump(), 'slack',
                              [{'sourceType': 'slack', 'externalRef': f'cmd:{user}', 'excerpt': text[:500]}])
        msg = f"✓ Captured: *{d.get('title', 'Decision')}*"
    if response_url:
        requests.post(response_url, json={'response_type': 'ephemeral', 'text': msg}, timeout=10)