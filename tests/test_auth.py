import hashlib
import hmac
import time

from app.services.slack_verify import verify_slack_signature


def test_slack_signature_valid():
    secret = 'test-secret'
    body = b'{"type":"url_verification"}'
    ts = str(int(time.time()))
    base = f'v0:{ts}:'.encode() + body
    sig = 'v0=' + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    assert verify_slack_signature(secret, ts, body, sig)


def test_slack_signature_rejects_bad_timestamp():
    secret = 'test-secret'
    body = b'{}'
    assert not verify_slack_signature(secret, 'not-a-number', body, 'v0=abc')


def test_slack_events_rejects_without_secret(app_client):
    r = app_client.post('/api/integrations/slack/events', json={'type': 'url_verification'})
    assert r.status_code == 503


def test_jira_rejects_without_secret(app_client):
    r = app_client.post('/api/integrations/atlassian/jira', json={'issueKey': 'PROJ-1'})
    assert r.status_code == 503


def test_jira_rejects_wrong_secret(app_client, monkeypatch):
    monkeypatch.setenv('ATLASSIAN_WEBHOOK_SECRET', 'real-secret')
    for name in list(__import__('sys').modules):
        if name == 'app' or name.startswith('app.'):
            del __import__('sys').modules[name]
    from app import create_app
    app = create_app()
    with app.test_client() as client:
        r = client.post('/api/integrations/atlassian/jira',
                        json={'issueKey': 'PROJ-1'},
                        headers={'X-Whyline-Secret': 'wrong'})
        assert r.status_code == 403