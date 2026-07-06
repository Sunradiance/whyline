"""Migration 002 — sensitive decisions flag."""

SCHEMA_VERSION = 2


def _columns(c, table: str) -> set:
    return {r[1] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}


def migrate(store) -> dict:
    report = {'sensitive_column': False, 'to_version': SCHEMA_VERSION}
    with store._conn() as c:
        if 'sensitive' not in _columns(c, 'decisions'):
            c.execute('ALTER TABLE decisions ADD COLUMN sensitive INTEGER DEFAULT 0')
            report['sensitive_column'] = True
        c.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (str(SCHEMA_VERSION),),
        )
    return report