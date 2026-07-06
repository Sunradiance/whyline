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
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'team')
    monkeypatch.setenv('WHYLINE_API_KEY', 'iso-test-key')
    _purge()
    from app.store.migration_001 import migrate as migrate_001
    from app.store.migration_002 import migrate as migrate_002
    from app.store.migration_003 import migrate as migrate_003
    from app.store.migration_004 import migrate as migrate_004
    from app.store.sqlite import Store
    s = Store(path=db_path)
    migrate_001(s)
    migrate_002(s)
    migrate_003(s)
    migrate_004(s)
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


def test_supersede_cannot_cross_workspaces(store, two_workspaces):
    a, db_ = two_workspaces['a'], two_workspaces['db']
    replacement = store.upsert_decision(
        {'title': 'Acme replacement', 'summary': 's', 'reasoning': 'r'},
        workspace_id=a['id'],
    )
    result = store.supersede(db_['id'], replacement['id'], workspace_id=a['id'])
    assert result is None
    still_active = store.get_decision(db_['id'], workspace_id=two_workspaces['b']['id'])
    assert still_active['status'] == 'active'


def test_invalid_token_role_returns_400(app_client_factory, store):
    ws = store.create_workspace('RoleVal')
    token, _ = store.create_service_token(ws['id'], role='owner', name='owner')
    client, _ = app_client_factory(workspace_id=ws['id'], role='owner')
    r = client.post(
        f"/api/workspaces/{ws['id']}/tokens",
        json={'role': 'superadmin'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 400
    assert 'invalid role' in r.get_json().get('error', '')


def test_admin_role_can_mint_token(app_client_factory, store):
    ws = store.create_workspace('AdminMint')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.post(
        f"/api/workspaces/{ws['id']}/tokens",
        json={'role': 'member', 'name': 'bot'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 200
    assert r.get_json().get('token')


def test_admin_cannot_patch_workspace_settings(app_client_factory, store):
    ws = store.create_workspace('AdminPatch')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.patch(
        f"/api/workspaces/{ws['id']}",
        json={'name': 'hijacked'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 403


def test_admin_cannot_demote_owner(app_client_factory, store):
    ws = store.create_workspace('Depose')
    boss = store.create_user('boss@co.com', 'pass-12345')
    admin_user = store.create_user('admin@co.com', 'pass-12345')
    store.add_member(ws['id'], boss['id'], 'owner')
    store.add_member(ws['id'], admin_user['id'], 'admin')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={'email': 'boss@co.com', 'role': 'viewer'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 403
    assert store.get_role(boss['id'], ws['id']) == 'owner'


def test_admin_cannot_modify_peer_admin(app_client_factory, store):
    ws = store.create_workspace('PeerAdmin')
    peer = store.create_user('peer@co.com', 'pass-12345')
    store.add_member(ws['id'], store.create_user('owner@co.com', 'pass-12345')['id'], 'owner')
    store.add_member(ws['id'], peer['id'], 'admin')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={'email': 'peer@co.com', 'role': 'member'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 403
    assert store.get_role(peer['id'], ws['id']) == 'admin'


def test_owner_can_demote_admin(app_client_factory, store):
    ws = store.create_workspace('OwnerDemote')
    sub = store.create_user('sub@co.com', 'pass-12345')
    store.add_member(ws['id'], store.create_user('owner@co.com', 'pass-12345')['id'], 'owner')
    store.add_member(ws['id'], sub['id'], 'admin')
    token, _ = store.create_service_token(ws['id'], role='owner', name='owner')
    client, _ = app_client_factory(workspace_id=ws['id'], role='owner')
    r = client.post(
        f"/api/workspaces/{ws['id']}/members",
        json={'email': 'sub@co.com', 'role': 'member'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 200
    assert store.get_role(sub['id'], ws['id']) == 'member'


def test_owner_can_remove_member_and_access_lost(app_client_factory, store):
    ws = store.create_workspace('Offboard')
    owner = store.create_user('owner@co.com', 'pass-12345')
    departing = store.create_user('depart@co.com', 'pass-12345')
    store.add_member(ws['id'], owner['id'], 'owner')
    store.add_member(ws['id'], departing['id'], 'member')
    owner_token, _ = store.create_service_token(ws['id'], role='owner', name='owner')
    client, _ = app_client_factory(workspace_id=ws['id'], role='owner')
    r = client.delete(
        f"/api/workspaces/{ws['id']}/members/{departing['id']}",
        headers={'X-Whyline-Key': owner_token},
    )
    assert r.status_code == 200
    assert store.get_role(departing['id'], ws['id']) is None

    with client.session_transaction() as sess:
        sess['user_id'] = departing['id']
    r2 = client.get(f'/api/decisions?workspace={ws["id"]}')
    assert r2.status_code in (401, 403)


def test_admin_cannot_remove_owner_member(app_client_factory, store):
    ws = store.create_workspace('NoRemoveOwner')
    boss = store.create_user('boss@co.com', 'pass-12345')
    store.add_member(ws['id'], boss['id'], 'owner')
    store.add_member(ws['id'], store.create_user('admin@co.com', 'pass-12345')['id'], 'admin')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.delete(
        f"/api/workspaces/{ws['id']}/members/{boss['id']}",
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 403
    assert store.get_role(boss['id'], ws['id']) == 'owner'


def test_admin_can_remove_viewer(app_client_factory, store):
    ws = store.create_workspace('RemoveViewer')
    viewer = store.create_user('view@co.com', 'pass-12345')
    store.add_member(ws['id'], store.create_user('owner@co.com', 'pass-12345')['id'], 'owner')
    store.add_member(ws['id'], viewer['id'], 'viewer')
    store.add_member(ws['id'], store.create_user('admin@co.com', 'pass-12345')['id'], 'admin')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.delete(
        f"/api/workspaces/{ws['id']}/members/{viewer['id']}",
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 200
    assert store.get_role(viewer['id'], ws['id']) is None


def test_revoked_token_loses_access(app_client_factory, store):
    ws = store.create_workspace('RevokeTok')
    store.add_member(ws['id'], store.create_user('owner@co.com', 'pass-12345')['id'], 'owner')
    leaked, leaked_row = store.create_service_token(ws['id'], role='member', name='leaked')
    owner_token, owner_row = store.create_service_token(ws['id'], role='owner', name='owner')
    client, _ = app_client_factory(workspace_id=ws['id'], role='owner')
    r = client.delete(
        f"/api/workspaces/{ws['id']}/tokens/{leaked_row['id']}",
        headers={'X-Whyline-Key': owner_token},
    )
    assert r.status_code == 200
    assert store.verify_service_token(leaked) is None
    r2 = client.get('/api/decisions', headers={'X-Whyline-Key': leaked})
    assert r2.status_code == 401


def test_admin_cannot_revoke_owner_token(app_client_factory, store):
    ws = store.create_workspace('NoRevokeOwnerTok')
    store.add_member(ws['id'], store.create_user('owner@co.com', 'pass-12345')['id'], 'owner')
    store.add_member(ws['id'], store.create_user('admin@co.com', 'pass-12345')['id'], 'admin')
    owner_tok_raw, owner_tok_row = store.create_service_token(ws['id'], role='owner', name='boss-key')
    admin_token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    r = client.delete(
        f"/api/workspaces/{ws['id']}/tokens/{owner_tok_row['id']}",
        headers={'X-Whyline-Key': admin_token},
    )
    assert r.status_code == 403
    assert store.verify_service_token(owner_tok_raw) is not None


def test_cannot_revoke_active_token(app_client_factory, store):
    ws = store.create_workspace('SelfRevoke')
    store.add_member(ws['id'], store.create_user('owner@co.com', 'pass-12345')['id'], 'owner')
    owner_token, owner_row = store.create_service_token(ws['id'], role='owner', name='active')
    client, _ = app_client_factory(workspace_id=ws['id'], role='owner')
    r = client.delete(
        f"/api/workspaces/{ws['id']}/tokens/{owner_row['id']}",
        headers={'X-Whyline-Key': owner_token},
    )
    assert r.status_code == 403
    assert store.verify_service_token(owner_token) is not None


def test_cannot_revoke_token_in_other_workspace(app_client_factory, store, two_workspaces):
    a = two_workspaces['a']
    b = two_workspaces['b']
    _, b_row = store.create_service_token(b['id'], role='member', name='b-token')
    a_token, _ = store.create_service_token(a['id'], role='owner', name='a-owner')
    client, _ = app_client_factory(workspace_id=a['id'], role='owner')
    r = client.delete(
        f"/api/workspaces/{a['id']}/tokens/{b_row['id']}",
        headers={'X-Whyline-Key': a_token},
    )
    assert r.status_code == 404


def test_service_token_cannot_create_workspace(app_client_factory, store):
    ws = store.create_workspace('NoOrphan')
    token, _ = store.create_service_token(ws['id'], role='admin', name='admin')
    client, _ = app_client_factory(workspace_id=ws['id'], role='admin')
    before = len(store.list_user_workspaces('nobody'))
    r = client.post(
        '/api/workspaces',
        json={'name': 'Orphan WS'},
        headers={'X-Whyline-Key': token},
    )
    assert r.status_code == 403
    assert before == len(store.list_user_workspaces('nobody'))


def test_token_cannot_supersede_other_workspace(store, app_client_factory, two_workspaces):
    client, token_a = app_client_factory(workspace_id=two_workspaces['a']['id'], role='admin')
    r = client.post(
        f"/api/decisions/{two_workspaces['db']['id']}/supersede",
        json={'title': 'hostile supersede', 'summary': 's', 'reasoning': 'r'},
        headers={'X-Whyline-Key': token_a},
    )
    assert r.status_code in (403, 404)
    still_active = store.get_decision(
        two_workspaces['db']['id'],
        workspace_id=two_workspaces['b']['id'],
    )
    assert still_active['status'] == 'active'


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
    from app.store.migration_004 import migrate as migrate_004
    migrate_002(s)
    migrate_003(s)
    migrate_004(s)
    assert r1['created_default_ws'] is True
    assert r1['backfilled']['decisions'] >= 1
    assert r1['god_key_migrated'] is True

    r2 = migrate(s)
    migrate_002(s)
    migrate_003(s)
    migrate_004(s)
    assert r2['created_default_ws'] is False
    assert r2['backfilled']['decisions'] == 0
    assert r2['god_key_migrated'] is False

    for d in s.list_decisions(limit=1000):
        assert d.get('workspace_id')

    try:
        os.unlink(db_path)
    except OSError:
        pass