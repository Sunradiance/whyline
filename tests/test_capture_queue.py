def test_claim_is_atomic(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'})
    first = store.claim_capture(jid)
    second = store.claim_capture(jid)
    assert first is not None
    assert first['status'] == 'processing'
    assert second is None


def test_failed_capture_requeues_for_retry(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-retry')
    store.claim_capture(jid)
    store.fail_capture(jid, max_retries=3)
    job = store.get_capture(jid)
    assert job['status'] == 'pending'
    assert job['retry_count'] == 1
    assert jid in store.list_pending_capture_ids()


def test_failed_capture_permanent_after_max_retries(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-dead')
    for _ in range(3):
        store.claim_capture(jid)
        store.fail_capture(jid, max_retries=3)
    job = store.get_capture(jid)
    assert job['status'] == 'failed'
    assert job['retry_count'] == 3
    assert jid not in store.list_pending_capture_ids()


def test_enqueue_returns_existing_id_when_done(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-done')
    store.claim_capture(jid)
    store.complete_capture(jid)
    again = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-done')
    assert again == jid
    assert store.get_capture(jid)['status'] == 'done'


def test_enqueue_pending_retry_is_reprocessable(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-pend')
    store.claim_capture(jid)
    store.fail_capture(jid, max_retries=3)
    again = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-pend')
    assert again == jid
    reclaimed = store.claim_capture(jid)
    assert reclaimed is not None


def test_enqueue_permanent_failed_does_not_reprocess(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-fail')
    for _ in range(3):
        store.claim_capture(jid)
        store.fail_capture(jid, max_retries=3)
    again = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-fail')
    assert again == jid
    assert store.claim_capture(jid) is None


def test_prune_removes_old_terminal_rows(store):
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-old')
    store.claim_capture(jid)
    store.complete_capture(jid)
    with store._conn() as c:
        c.execute(
            "UPDATE pending_captures SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?",
            (jid,),
        )
    removed = store.prune_captures(keep_days=7)
    assert removed == 1
    assert store.get_capture(jid) is None


def test_retry_delay_grows_with_attempt(monkeypatch):
    from app.config import Config
    from app.services import capture_queue

    monkeypatch.setattr(Config, 'CAPTURE_RETRY_BASE_SECONDS', 2)
    monkeypatch.setattr(Config, 'CAPTURE_RETRY_MAX_SECONDS', 60)
    monkeypatch.setattr(capture_queue.random, 'uniform', lambda _a, _b: 0)
    assert capture_queue._retry_delay(1) == 2
    assert capture_queue._retry_delay(2) == 4
    assert capture_queue._retry_delay(3) == 8


def test_failure_schedules_backoff_retry(store, monkeypatch):
    from app.config import Config
    from app.services import capture_queue

    scheduled = []

    class FakeTimer:
        def __init__(self, delay, fn):
            scheduled.append(delay)
            self._fn = fn

        def start(self):
            pass

    monkeypatch.setattr(capture_queue, 'Timer', FakeTimer)
    monkeypatch.setattr(Config, 'CAPTURE_RETRY_BASE_SECONDS', 2)
    monkeypatch.setattr(capture_queue.random, 'uniform', lambda _a, _b: 0)

    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-backoff')
    store.claim_capture(jid)
    store.fail_capture(jid, max_retries=3)
    capture_queue._schedule_retry(jid, 1)
    assert len(scheduled) == 1
    assert scheduled[0] == 2


def test_enqueue_triggers_opportunistic_prune(monkeypatch):
    from app.config import Config
    from app.services import capture_queue

    monkeypatch.setattr(Config, 'CAPTURE_PRUNE_EVERY_N', 2)
    capture_queue._enqueue_count = 0
    pruned = []
    monkeypatch.setattr(capture_queue.store, 'enqueue_capture', lambda *a, **k: 'jid')
    monkeypatch.setattr(capture_queue.store, 'get_capture', lambda _jid: None)
    monkeypatch.setattr(capture_queue.store, 'prune_captures', lambda days: pruned.append(days) or 0)

    capture_queue.enqueue('slack_thread', {'channel': 'C1'}, event_id='Ev-p1')
    capture_queue.enqueue('slack_thread', {'channel': 'C2'}, event_id='Ev-p2')
    assert pruned == [Config.CAPTURE_PRUNE_DAYS]


def test_drain_pending_requeues_failed_jobs(store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.config import Config
    from app.services import capture_queue

    monkeypatch.setattr(Config, 'CAPTURE_MAX_RETRIES', 3)
    jid = store.enqueue_capture('slack_thread', {'channel': 'C1'}, event_id='Ev-drain')
    store.claim_capture(jid)
    store.fail_capture(jid, max_retries=3)

    calls = []

    def fake_process(job_id):
        calls.append(job_id)
        store.claim_capture(job_id)
        store.complete_capture(job_id)

    pool = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(capture_queue, '_process_job', fake_process)
    monkeypatch.setattr(capture_queue, '_executor', pool)
    capture_queue.drain_pending()
    pool.shutdown(wait=True)
    assert jid in calls
    assert store.get_capture(jid)['status'] == 'done'