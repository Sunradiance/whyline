import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(ROOT, 'backend')
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _purge_app_modules():
    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)


@pytest.fixture()
def app_client(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_API_KEY', 'test-api-key-fixed')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    _purge_app_modules()

    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['authed'] = True
        yield client
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture()
def store(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    _purge_app_modules()
    from app.store.migration_001 import migrate as migrate_001
    from app.store.migration_002 import migrate as migrate_002
    from app.store.migration_003 import migrate as migrate_003
    from app.store.sqlite import Store
    s = Store(path=db_path)
    migrate_001(s)
    migrate_002(s)
    migrate_003(s)
    yield s
    try:
        os.unlink(db_path)
    except OSError:
        pass