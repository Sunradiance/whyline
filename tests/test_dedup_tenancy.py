"""Cross-tenant dedup — the blind spot Fable flagged."""

import os
import tempfile

import pytest


def test_identical_content_hash_in_two_workspaces(store):
    a = store.create_workspace('Tenant A')
    b = store.create_workspace('Tenant B')
    data = {'title': 'Migrate to Postgres', 'summary': 'standardize on PG', 'reasoning': 'ops consensus'}
    da = store.upsert_decision(data, workspace_id=a['id'])
    db = store.upsert_decision(data, workspace_id=b['id'])
    assert da is not None and db is not None
    assert da['id'] != db['id']


def test_ingest_log_scoped_per_workspace(store):
    a = store.create_workspace('Tenant A')
    b = store.create_workspace('Tenant B')
    d1 = store.upsert_decision(
        {'title': 'Jira decision A', 'summary': 'a', 'reasoning': 'a'},
        source_key='jira:PROJ-1',
        workspace_id=a['id'],
    )
    d2 = store.upsert_decision(
        {'title': 'Jira decision B', 'summary': 'b', 'reasoning': 'b'},
        source_key='jira:PROJ-1',
        workspace_id=b['id'],
    )
    assert d1['id'] != d2['id']


def test_list_decisions_fail_closed_in_team_mode(store, monkeypatch):
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'team')
    from app.config import Config
    Config.AUTH_MODE = 'team'
    assert store.list_decisions(workspace_id=None) == []


def test_mcp_resolves_default_workspace_in_solo(store, monkeypatch):
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'solo')
    monkeypatch.delenv('MCP_WORKSPACE_ID', raising=False)
    from app.config import Config
    Config.AUTH_MODE = 'solo'
    store.upsert_decision(
        {'title': 'MCP visible', 'summary': 's', 'reasoning': 'r'},
        workspace_id=store.get_default_workspace_id(),
    )
    from app.services.mcp_workspace import resolve_mcp_workspace_id
    from app.services.retrieval import score_decisions
    ws = resolve_mcp_workspace_id()
    assert ws == store.get_default_workspace_id()
    corpus = store.all_active_text_blob(workspace_id=ws)
    top = score_decisions('MCP visible', corpus, top_k=5)
    assert len(top) >= 1


def _decision_indexes(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='decisions'"
    ).fetchall()
    return [r[0] for r in rows]


def test_bare_store_never_resurrects_global_hash_index(monkeypatch):
    """Fable mythos repro: bare Store() on migrated DB must not recreate idx_decisions_hash."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_API_KEY', 'bare-store-key')
    for name in list(__import__('sys').modules):
        if name == 'app' or name.startswith('app.'):
            del __import__('sys').modules[name]
    from app.store.sqlite import Store

    s1 = Store(path=db_path)
    a = s1.create_workspace('A')
    b = s1.create_workspace('B')
    data = {'title': 'Migrate to Postgres', 'summary': 'pg', 'reasoning': 'ops'}
    s1.upsert_decision(data, workspace_id=a['id'])
    s1.upsert_decision(data, workspace_id=b['id'])
    with s1._conn() as c:
        idx1 = _decision_indexes(c)
    assert 'idx_decisions_hash_ws' in idx1
    assert 'idx_decisions_hash' not in idx1

    s2 = Store(path=db_path)
    with s2._conn() as c:
        idx2 = _decision_indexes(c)
    assert 'idx_decisions_hash' not in idx2

    c_ws = s2.create_workspace('C')
    d_ws = s2.create_workspace('D')
    dc = s2.upsert_decision(data, workspace_id=c_ws['id'])
    dd = s2.upsert_decision(data, workspace_id=d_ws['id'])
    assert dc['id'] != dd['id']
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_mcp_workspace_fails_closed_in_team_mode(monkeypatch):
    """Fresh DB + team mode: stray WHYLINE_API_KEY must not become admin token."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'team')
    monkeypatch.delenv('MCP_WORKSPACE_ID', raising=False)
    monkeypatch.setenv('WHYLINE_API_KEY', 'not-a-service-token')
    for name in list(__import__('sys').modules):
        if name == 'app' or name.startswith('app.'):
            del __import__('sys').modules[name]
    from app.config import Config
    from app.services.mcp_workspace import resolve_mcp_workspace_id
    from app.store.sqlite import Store

    Store(path=db_path)
    Config.AUTH_MODE = 'team'
    Config.WHYLINE_API_KEY = 'not-a-service-token'
    with pytest.raises(RuntimeError, match='MCP requires'):
        resolve_mcp_workspace_id()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_solo_to_team_revokes_legacy_god_key(monkeypatch):
    """Mainline upgrade path: solo trial key must not stay admin after team flip."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    solo_key = 'solo-trial-master-key'
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'solo')
    monkeypatch.setenv('WHYLINE_API_KEY', solo_key)
    for name in list(__import__('sys').modules):
        if name == 'app' or name.startswith('app.'):
            del __import__('sys').modules[name]
    from app.store.sqlite import Store

    s_solo = Store(path=db_path)
    tok = s_solo.verify_service_token(solo_key)
    assert tok is not None
    assert tok['role'] == 'admin'

    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'team')
    for name in list(__import__('sys').modules):
        if name == 'app' or name.startswith('app.'):
            del __import__('sys').modules[name]
    from app import create_app
    from app.config import Config
    from app.services.mcp_workspace import resolve_mcp_workspace_id

    assert Config.AUTH_MODE == 'team'
    s_team = Store(path=db_path)
    assert s_team.verify_service_token(solo_key) is None
    Config.WHYLINE_API_KEY = solo_key
    with pytest.raises(RuntimeError, match='MCP requires'):
        resolve_mcp_workspace_id()

    app = create_app()
    app.config['TESTING'] = True
    client = app.test_client()
    assert client.get('/api/decisions', headers={'X-Whyline-Key': solo_key}).status_code == 401
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_god_key_not_migrated_in_team_mode(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    monkeypatch.setenv('WHYLINE_DB_PATH', db_path)
    monkeypatch.setenv('WHYLINE_AUTH_MODE', 'team')
    monkeypatch.setenv('WHYLINE_API_KEY', 'legacy-god-key')
    for name in list(__import__('sys').modules):
        if name == 'app' or name.startswith('app.'):
            del __import__('sys').modules[name]
    from app.store.migration_001 import migrate as migrate_001
    from app.store.sqlite import Store

    s = Store(path=db_path, migrate=False)
    r = migrate_001(s)
    assert r['god_key_migrated'] is False
    assert s.verify_service_token('legacy-god-key') is None
    try:
        os.unlink(db_path)
    except OSError:
        pass