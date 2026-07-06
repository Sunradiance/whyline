import hashlib
import hmac
import json


def test_email_capture_requires_body(app_client):
    r = app_client.post('/api/integrations/email/capture', json={})
    assert r.status_code in (400, 500)


def test_email_webhook_rejects_without_secret(app_client):
    r = app_client.post('/api/integrations/email/ingest', json={'body': 'test'})
    assert r.status_code == 503


def test_transcript_requires_text(app_client):
    r = app_client.post('/api/integrations/transcript/ingest', json={})
    assert r.status_code == 400


def test_doc_requires_text(app_client):
    r = app_client.post('/api/integrations/doc/ingest', json={'title': 'RFC'})
    assert r.status_code == 400


def test_ai_search(app_client):
    app_client.post('/api/decisions', json={
        'title': 'Germany billing monthly only', 'summary': 'DACH', 'reasoning': 'VAT', 'sourceType': 'manual',
    })
    r = app_client.post('/api/ai/search', json={'query': 'Germany billing'})
    assert r.status_code == 200
    data = r.get_json()
    assert data['count'] >= 1


def test_github_rejects_without_secret(app_client):
    r = app_client.post('/api/integrations/github/webhook', json={'action': 'created'})
    assert r.status_code == 503


def test_parse_slack_thread_ref():
    from app.services.slack_client import parse_thread_ref
    ch, ts = parse_thread_ref('https://foo.slack.com/archives/C123ABC/p1234567890123456')
    assert ch == 'C123ABC'
    assert ts == '1234567890.123456'


def test_email_parse_mailgun():
    from app.services.email_parse import parse_email_payload
    p = parse_email_payload({'subject': 'Decision', 'body-plain': 'We chose X', 'From': 'a@b.com', 'Message-Id': 'm1'})
    assert 'We chose X' in p['body']
    assert p['message_id'] == 'm1'


def test_transcript_segments():
    from app.api.integration_routes import _transcript_segments
    segs = _transcript_segments({'text': 'Alice (00:12): We decided no annual billing.\nBob: Agreed.'})
    assert segs[0]['speaker'] == 'Alice'
    assert 'annual' in segs[0]['text']