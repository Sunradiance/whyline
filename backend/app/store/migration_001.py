"""Migration 001 — multi-tenant / access control. Idempotent; safe on every boot."""

import hashlib
import os
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DEFAULT_WS_NAME = 'Default workspace'


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(c, table: str) -> set:
    return {r[1] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_column_if_missing(c, table: str, column: str, ddl: str):
    if column not in _columns(c, table):
        c.execute(f'ALTER TABLE {table} ADD COLUMN {ddl}')


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_meta(c, key: str):
    row = c.execute('SELECT value FROM schema_meta WHERE key = ?', (key,)).fetchone()
    return row[0] if row else None


def _set_meta(c, key: str, value: str):
    c.execute(
        'INSERT INTO schema_meta (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, value),
    )


def migrate(store) -> dict:
    report = {
        'created_default_ws': False,
        'backfilled': {},
        'god_key_migrated': False,
        'from_version': None,
        'to_version': SCHEMA_VERSION,
    }

    with store._conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS schema_meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        report['from_version'] = _get_meta(c, 'schema_version')

        c.executescript('''
            CREATE TABLE IF NOT EXISTS workspaces (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                slug        TEXT UNIQUE,
                public_read INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                status        TEXT NOT NULL DEFAULT 'active',
                created_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS memberships (
                id           TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id      TEXT NOT NULL,
                role         TEXT NOT NULL DEFAULT 'member',
                created_at   TEXT,
                UNIQUE (workspace_id, user_id),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id)      REFERENCES users(id)      ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS service_tokens (
                id           TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                token_hash   TEXT UNIQUE NOT NULL,
                name         TEXT,
                role         TEXT NOT NULL DEFAULT 'member',
                created_at   TEXT,
                last_used_at TEXT,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id           TEXT PRIMARY KEY,
                workspace_id TEXT,
                actor_type   TEXT,
                actor_id     TEXT,
                action       TEXT,
                target_type  TEXT,
                target_id    TEXT,
                detail       TEXT,
                created_at   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_membership_user ON memberships(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_ws ON audit_log(workspace_id, created_at);
        ''')

        _add_column_if_missing(c, 'decisions', 'workspace_id', 'workspace_id TEXT')
        _add_column_if_missing(c, 'sources', 'workspace_id', 'workspace_id TEXT')
        _add_column_if_missing(c, 'pending_captures', 'workspace_id', 'workspace_id TEXT')

        c.execute('CREATE INDEX IF NOT EXISTS idx_decisions_ws ON decisions(workspace_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_sources_ws ON sources(workspace_id)')

        default_ws_id = _get_meta(c, 'default_workspace_id')
        if not default_ws_id:
            default_ws_id = _uid()
            c.execute(
                'INSERT INTO workspaces (id, name, slug, public_read, created_at) VALUES (?, ?, ?, 0, ?)',
                (default_ws_id, DEFAULT_WS_NAME, 'default', _now()),
            )
            _set_meta(c, 'default_workspace_id', default_ws_id)
            report['created_default_ws'] = True

        for table in ('decisions', 'sources', 'pending_captures'):
            cur = c.execute(
                f'UPDATE {table} SET workspace_id = ? WHERE workspace_id IS NULL',
                (default_ws_id,),
            )
            report['backfilled'][table] = cur.rowcount

        legacy_key = os.environ.get('WHYLINE_API_KEY', '').strip()
        if not legacy_key:
            key_path = os.path.join(os.path.dirname(store.path), '.api_key')
            if os.path.exists(key_path):
                with open(key_path) as f:
                    legacy_key = f.read().strip()
        # Solo-only: never mint admin from WHYLINE_API_KEY in team/open deployments.
        auth_mode = os.environ.get('WHYLINE_AUTH_MODE', 'solo').strip().lower()
        if legacy_key and auth_mode == 'solo' and _get_meta(c, 'god_key_migrated') != '1':
            th = _token_hash(legacy_key)
            exists = c.execute('SELECT 1 FROM service_tokens WHERE token_hash = ?', (th,)).fetchone()
            if not exists:
                c.execute(
                    'INSERT INTO service_tokens (id, workspace_id, token_hash, name, role, created_at) '
                    "VALUES (?, ?, ?, ?, 'admin', ?)",
                    (_uid(), default_ws_id, th, 'legacy-god-key', _now()),
                )
            _set_meta(c, 'god_key_migrated', '1')
            report['god_key_migrated'] = True

        _set_meta(c, 'schema_version', str(SCHEMA_VERSION))

    return report