"""Migration 003 — tenant-scoped dedup: content_hash index + ingest_log."""

SCHEMA_VERSION = 3


def _get_meta(c, key: str):
    row = c.execute('SELECT value FROM schema_meta WHERE key = ?', (key,)).fetchone()
    return row[0] if row else None


def migrate(store) -> dict:
    report = {'hash_index': False, 'ingest_log': False, 'to_version': SCHEMA_VERSION}

    with store._conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS schema_meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        global_idx = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_decisions_hash'"
        ).fetchone()
        if global_idx:
            c.execute('DROP INDEX idx_decisions_hash')
            report['hash_index'] = True
        c.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_decisions_hash_ws '
            'ON decisions(workspace_id, content_hash)'
        )

        cols = {r[1] for r in c.execute('PRAGMA table_info(ingest_log)').fetchall()}
        if cols and 'workspace_id' not in cols:
            default_ws = _get_meta(c, 'default_workspace_id') or ''
            c.executescript('''
                CREATE TABLE ingest_log_new (
                    workspace_id TEXT NOT NULL,
                    source_key   TEXT NOT NULL,
                    decision_id  TEXT NOT NULL,
                    created_at   TEXT,
                    PRIMARY KEY (workspace_id, source_key)
                );
            ''')
            c.execute('''
                INSERT INTO ingest_log_new (workspace_id, source_key, decision_id, created_at)
                SELECT COALESCE(d.workspace_id, ?), il.source_key, il.decision_id, il.created_at
                FROM ingest_log il
                LEFT JOIN decisions d ON d.id = il.decision_id
            ''', (default_ws,))
            c.execute('DROP TABLE ingest_log')
            c.execute('ALTER TABLE ingest_log_new RENAME TO ingest_log')
            report['ingest_log'] = True
        elif not cols:
            c.execute('''
                CREATE TABLE IF NOT EXISTS ingest_log (
                    workspace_id TEXT NOT NULL,
                    source_key   TEXT NOT NULL,
                    decision_id  TEXT NOT NULL,
                    created_at   TEXT,
                    PRIMARY KEY (workspace_id, source_key)
                )
            ''')

        c.execute(
            'INSERT INTO schema_meta (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            ('schema_version', str(SCHEMA_VERSION)),
        )

    return report