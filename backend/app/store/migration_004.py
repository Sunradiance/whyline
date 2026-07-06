"""Migration 004 — auth mode ratchet. Multi-tenant DBs cannot silently downgrade to solo."""

from __future__ import annotations

import os

SCHEMA_VERSION = 4

_MODE_RANK = {'solo': 0, 'team': 1, 'open': 1}


class AuthModeRatchetError(RuntimeError):
    """Configured AUTH_MODE is below the DB's ratcheted floor."""


def _get_meta(c, key: str):
    row = c.execute('SELECT value FROM schema_meta WHERE key = ?', (key,)).fetchone()
    return row[0] if row else None


def _set_meta(c, key: str, value: str):
    c.execute(
        'INSERT INTO schema_meta (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, value),
    )


def _normalize_mode(mode: str | None) -> str:
    m = (mode or 'solo').strip().lower()
    return m if m in _MODE_RANK else 'solo'


def _rank(mode: str) -> int:
    return _MODE_RANK.get(_normalize_mode(mode), 0)


def _db_signals_multi_tenant(c) -> bool:
    ws = c.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0]
    users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    memberships = c.execute('SELECT COUNT(*) FROM memberships').fetchone()[0]
    return ws > 1 or users > 0 or memberships > 0


def migrate(store) -> dict:
    from ..config import Config

    report = {
        'current_mode': _normalize_mode(Config.AUTH_MODE),
        'highest_mode': None,
        'floor_mode': None,
        'ratchet_enforced': False,
        'downgrade_blocked': False,
    }

    allow_downgrade = os.environ.get('WHYLINE_ALLOW_SOLO_DOWNGRADE', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )

    with store._conn() as c:
        current = _normalize_mode(Config.AUTH_MODE)
        highest = _normalize_mode(_get_meta(c, 'highest_auth_mode') or 'solo')
        floor_rank = max(_rank(highest), 1 if _db_signals_multi_tenant(c) else 0)
        floor_mode = 'team' if floor_rank >= 1 else 'solo'

        report['highest_mode'] = highest
        report['floor_mode'] = floor_mode

        if _rank(current) < floor_rank and not allow_downgrade:
            report['downgrade_blocked'] = True
            raise AuthModeRatchetError(
                f'AUTH_MODE={current!r} is below ratcheted floor {floor_mode!r} '
                f'(highest_auth_mode={highest!r}). '
                'Set WHYLINE_AUTH_MODE=team (or open), or pass WHYLINE_ALLOW_SOLO_DOWNGRADE=1 '
                'to explicitly downgrade — never silent.'
            )

        new_highest = highest
        if _rank(current) > _rank(highest):
            new_highest = current
        elif floor_rank >= 1 and _rank(highest) < 1:
            new_highest = 'team'

        if new_highest != highest:
            _set_meta(c, 'highest_auth_mode', new_highest)
            report['ratchet_enforced'] = True
            report['highest_mode'] = new_highest

        _set_meta(c, 'schema_version', str(SCHEMA_VERSION))

    return report