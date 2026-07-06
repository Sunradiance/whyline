def test_session_rejects_non_loopback_remote_addr(app_client):
    r = app_client.post('/api/session', environ_overrides={'REMOTE_ADDR': '192.168.1.50'},
                        headers={'Host': 'localhost'})
    assert r.status_code == 403


def test_session_allows_loopback(app_client):
    r = app_client.post('/api/session', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200


def test_api_key_auth_without_session():
    import os
    import sys
    import tempfile

    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.environ['WHYLINE_DB_PATH'] = db_path
    os.environ['WHYLINE_API_KEY'] = 'team-key-123'
    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            del sys.modules[name]
    from app import create_app
    app = create_app()
    with app.test_client() as client:
        r = client.get('/api/decisions', headers={'X-Whyline-Key': 'team-key-123'},
                       environ_overrides={'REMOTE_ADDR': '10.0.0.5'})
        assert r.status_code == 200
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_retrieval_no_fallback_on_zero_overlap():
    from app.services.retrieval import score_decisions

    corpus = [{'id': '1', 'title': 'Germany billing monthly', 'summary': 'DACH VAT', 'reasoning': 'legal',
               'decidedBy': '', 'alternativesConsidered': []}]
    top = score_decisions('quantum physics rocket', corpus, top_k=3)
    assert top == []


def test_github_webhook_skips_without_trigger(monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.setenv('GITHUB_WEBHOOK_SECRET', 'gh-secret')
    import sys
    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            del sys.modules[name]
    from app import create_app
    import hashlib
    import hmac
    import json
    app = create_app()
    body = json.dumps({
        'action': 'created',
        'repository': {'full_name': 'org/repo'},
        'issue': {'number': 1, 'title': 'Test', 'labels': []},
        'comment': {'body': 'lgtm 🚀', 'id': 99, 'html_url': 'http://x', 'user': {'login': 'dev'}},
    }).encode()
    sig = 'sha256=' + hmac.new(b'gh-secret', body, hashlib.sha256).hexdigest()
    with app.test_client() as client:
        r = client.post('/api/integrations/github/webhook', data=body,
                        headers={'X-Hub-Signature-256': sig, 'X-GitHub-Event': 'issue_comment',
                                 'Content-Type': 'application/json'})
        assert r.status_code == 200
        assert r.get_json().get('skipped') is True


def test_parse_thread_ref_query_param():
    from app.services.slack_client import parse_thread_ref
    url = 'https://x.slack.com/archives/C99/p1234567890?thread_ts=9876543210.123456'
    ch, ts = parse_thread_ref(url)
    assert ch == 'C99'
    assert ts == '9876543210.123456'


def test_near_dup_appends_source(store, monkeypatch):
    from app.config import Config
    from app.services.ingest import persist_extracted
    monkeypatch.setattr(Config, 'NEAR_DUP_SCORE_THRESHOLD', 2.0)
    base = {'title': 'No annual billing in Germany DACH', 'summary': 'monthly only billing', 'reasoning': 'German VAT invoicing risk'}
    a = persist_extracted(base, 'slack', [{'sourceType': 'slack', 'url': 'https://slack/1', 'externalRef': 't1'}])
    b = persist_extracted(
        {**base, 'summary': 'monthly only billing in DACH region'},
        'jira', [{'sourceType': 'jira', 'url': 'https://jira/PROJ-1', 'externalRef': 'PROJ-1'}],
    )
    assert a['id'] == b['id']
    assert len(b.get('sources', [])) >= 2


def test_triggers():
    from app.services.triggers import should_extract
    assert should_extract('We decided [decision] to kill feature X')
    assert not should_extract('lgtm ship it')
    assert should_extract('', labels=['decision-recorded'])


def test_linear_human_text_not_json():
    from app.services.triggers import linear_human_text, should_extract
    payload = {'data': {'title': 'Bug', 'description': 'normal text'}}
    assert not should_extract(linear_human_text(payload))
    payload['data']['description'] = 'We decided [decision] to ship'
    assert should_extract(linear_human_text(payload))