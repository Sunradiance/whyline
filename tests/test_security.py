def test_env_not_served(app_client):
    r = app_client.get('/.env')
    assert r.status_code == 404


def test_backend_env_not_served(app_client):
    r = app_client.get('/backend/.env')
    assert r.status_code == 404


def test_data_api_key_not_served(app_client):
    r = app_client.get('/data/.api_key')
    assert r.status_code == 404


def test_allowed_static(app_client):
    r = app_client.get('/css/app.css')
    assert r.status_code == 200


def test_ai_requires_auth():
    import os
    import sys
    import tempfile

    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.environ['WHYLINE_DB_PATH'] = db_path
    os.environ['WHYLINE_API_KEY'] = 'secret-key'
    os.environ.pop('LLM_API_KEY', None)

    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            del sys.modules[name]

    from app import create_app
    app = create_app()
    with app.test_client() as client:
        r = client.post('/api/ai/ask', json={'question': 'why?'})
        assert r.status_code == 401
    try:
        os.unlink(db_path)
    except OSError:
        pass