"""Acceptance spec for multi-tenant isolation — merge gate for workspace scoping."""

import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(ROOT, 'backend')
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _purge():
    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            del sys.modules[name]


@pytest.fixture()
def isolated_env(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_API_KEY', 'iso-test-key')
    _purge()
    from app.store.migration_001 import migrate as migrate_001
    from app.store.migration_002 import migrate as migrate_002
    from app.store.migration_003 import migrate as migrate_003
    from app.store.sqlite import Store
    s = Store(path=db_path)
    migrate_001(s)
    migrate_002(s)
    migrate_003(s)
    yield s, db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture()
def store(isolated_env):
    return isolated_env[0]


@pytest.fixture()
def two_workspaces(store):
    a = store.create_workspace('Acme')
    b = store.create_workspace('Beta')
    da = store.upsert_decision(
        {'title': 'Acme: no annual billing in Germany', 'summary': 'VAT', 'reasoning': 'legal'},
        sources=[{'sourceType': 'meeting', 'excerpt': 'acme secret'}],
        workspace_id=a['id'],
    )
    db_ = store.upsert_decision(
        {'title': 'Beta: rejected vendor Foo', 'summary': 'cost', 'reasoning': 'compliance'},
        sources=[{'sourceType': 'slack', 'excerpt': 'beta secret'}],
        workspace_id=b['id'],
    )
    return {'a': a, 'b': b, 'da': da, 'db': db_}


@pytest.fixture()
def app_client_factory(isolated_env, monkeypatch):
    store, db_path = isolated_env
    _purge()
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_API_KEY', 'iso-test-key')
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True

    def factory(workspace_id=None, role='member', anonymous=False):
        client = app.test_client()
        token = None
        if not anonymous and workspace_id and role:
            token, _ = store.create_service_token(workspace_id, role=role, name='test')
        return client, token

    return factory


def test_list_is_scoped_to_workspace(store, two_workspaces):
    a, b = two_workspaces['a'], two_workspaces['b']
    a_ids = {d['id'] for d in store.list_decisions(workspace_id=a['id'])}
    b_ids = {d['id'] for d in store.list_decisions(workspace_id=b['id'])}
    assert two_workspaces['da']['id'] in a_ids
    assert two_workspaces['db']['id'] not in a_ids
    assert a_ids.isdisjoint(b_ids)


def test_get_across_workspace_returns_none(store, two_workspaces):
    a, db_ = two_workspaces['a'], two_workspaces['db']
    assert store.get_decision(db_['id'], workspace_id=a['id']) is None


def test_search_does_not_cross_tenants(store, two_workspaces):
    a = two_workspaces['a']
    hits = store.list_decisions(workspace_id=a['id'], search='vendor Foo')
    assert hits == []


def test_retrieval_only_scores_caller_workspace(store, two_workspaces):
    from app.services.retrieval import score_decisions
    a = two_workspaces['a']
    corpus = store.list_decisions(workspace_id=a['id'], status='active')
    top = score_decisions('vendor Foo compliance', corpus, top_k=8)
    assert all(d['id'] != two_workspaces['db']['id'] for d in top)


def test_ask_answer_and_receipts_stay_in_workspace(app_client_factory, two_workspaces):
    client, token_a = app_client_factory(workspace_id=two_workspaces['a']['id'], role='member')
    r = client.post('/api/ai/ask', json={'question': 'why did we reject vendor Foo?'},
                    headers={'X-Whyline-Key': token_a})
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        result = r.get_json()['result']
        leaked = [rc for rc in result.get('receipts', [])
                  if rc.get('decisionId') == two_workspaces['db']['id']]
        assert leaked == []


def test_token_cannot_read_other_workspace(app_client_factory, two_workspaces):
    client, token_a = app_client_factory(workspace_id=two_workspaces['a']['id'], role='member')
    r = client.get(f"/api/decisions/{two_workspaces['db']['id']}",
                   headers={'X-Whyline-Key': token_a})
    assert r.status_code in (403, 404)
    assert 'beta secret' not in r.get_data(as_text=True)


def test_token_cannot_mutate_other_workspace(app_client_factory, two_workspaces):
    client, token_a = app_client_factory(workspace_id=two_workspaces['a']['id'], role='admin')
    r = client.delete(f"/api/decisions/{two_workspaces['db']['id']}",
                      headers={'X-Whyline-Key': token_a})
    assert r.status_code in (403, 404)


@pytest.mark.parametrize('role,action,allowed', [
    ('viewer', 'read', True),
    ('viewer', 'create', False),
    ('viewer', 'manage', False),
    ('member', 'read', True),
    ('member', 'create', True),
    ('member', 'manage', False),
    ('admin', 'create', True),
    ('admin', 'manage', True),
    ('admin', 'admin', False),
    ('owner', 'admin', True),
])
def test_role_permission_matrix(store, role, action, allowed):
    ws = store.create_workspace('RBAC')
    u = store.create_user(f'{role}@example.com', password='test-pass-123')
    store.add_member(ws['id'], u['id'], role)
    assert store.can(u['id'], ws['id'], action) is allowed


def test_public_read_workspace_allows_anonymous_ask(app_client_factory, store):
    ws = store.create_workspace('Open KB', public_read=True)
    store.upsert_decision({'title': 'public decision', 'summary': 's', 'reasoning': 'r'},
                          workspace_id=ws['id'])
    client, _ = app_client_factory(workspace_id=ws['id'], role=None, anonymous=True)
    assert client.get(f"/api/decisions?workspace={ws['id']}").status_code == 200
    assert client.post('/api/decisions', json={'title': 'x'}).status_code in (401, 403)


def test_migration_from_legacy_single_key(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'solo')
    monkeypatch.setenv('WHYLINE_API_KEY', 'legacy-god-key')
    _purge()
    from app.store.sqlite import Store

    s = Store(path=db_path, migrate=False)
    s.upsert_decision({'title': 'legacy', 'summary': 'x', 'reasoning': 'y', 'sourceType': 'manual'},
                      sources=[{'sourceType': 'manual', 'excerpt': 'e'}])

    from app.store.migration_001 import migrate
    r1 = migrate(s)
    from app.store.migration_002 import migrate as migrate_002
    from app.store.migration_003 import migrate as migrate_003
    migrate_002(s)
    migrate_003(s)
    assert r1['created_default_ws'] is True
    assert r1['backfilled']['decisions'] >= 1
    assert r1['god_key_migrated'] is True

    r2 = migrate(s)
    migrate_002(s)
    migrate_003(s)
    assert r2['created_default_ws'] is False
    assert r2['backfilled']['decisions'] == 0
    assert r2['god_key_migrated'] is False

    for d in s.list_decisions(limit=1000):
        assert d.get('workspace_id')

    try:
        os.unlink(db_path)
    except OSError:
        pass