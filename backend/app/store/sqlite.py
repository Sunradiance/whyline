import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import Config
from .identity_mixin import StoreIdentityMixin


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _hash_decision(title: str, summary: str, reasoning: str) -> str:
    blob = f'{title}|{summary}|{reasoning}'.strip().lower()
    return hashlib.sha256(blob.encode()).hexdigest()


class Store(StoreIdentityMixin):
    def __init__(self, path: Optional[str] = None, *, migrate: bool = True):
        self.path = path or Config.DB_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_db()
        if migrate:
            self._run_migrations()

    def _run_migrations(self):
        """Every Store() path must migrate — MCP singleton, scripts, tests, Flask."""
        try:
            from ..auth import ensure_api_key
            ensure_api_key()
        except Exception:
            pass
        from .migration_001 import migrate as migrate_001
        from .migration_002 import migrate as migrate_002
        from .migration_003 import migrate as migrate_003
        migrate_001(self)
        migrate_002(self)
        migrate_003(self)

    def _now(self) -> str:
        return _now()

    def _uid(self) -> str:
        return _uid()

    def _has_workspace_column(self) -> bool:
        with self._conn() as c:
            cols = {r[1] for r in c.execute('PRAGMA table_info(decisions)').fetchall()}
        return 'workspace_id' in cols

    def _has_sensitive_column(self) -> bool:
        with self._conn() as c:
            cols = {r[1] for r in c.execute('PRAGMA table_info(decisions)').fetchall()}
        return 'sensitive' in cols

    def _has_scoped_ingest_log(self) -> bool:
        with self._conn() as c:
            cols = {r[1] for r in c.execute('PRAGMA table_info(ingest_log)').fetchall()}
        return 'workspace_id' in cols

    def _resolve_workspace_id(self, workspace_id: str | None) -> str | None:
        if workspace_id:
            return workspace_id
        if Config.AUTH_MODE == 'solo':
            return self.get_default_workspace_id()
        return None

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA busy_timeout = 5000')
        return conn

    def _init_db(self):
        with self._conn() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT,
                    reasoning TEXT,
                    alternatives TEXT,
                    decided_by TEXT,
                    decided_at TEXT,
                    status TEXT DEFAULT 'active',
                    superseded_by TEXT,
                    superseded_at TEXT,
                    topic_ids TEXT,
                    confidence INTEGER,
                    source_type TEXT,
                    content_hash TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    source_type TEXT,
                    external_ref TEXT,
                    url TEXT,
                    excerpt TEXT,
                    captured_at TEXT,
                    FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS people (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    role TEXT,
                    department TEXT
                );
                CREATE TABLE IF NOT EXISTS ingest_log (
                    source_key TEXT PRIMARY KEY,
                    decision_id TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS pending_captures (
                    id TEXT PRIMARY KEY,
                    event_id TEXT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_capture_event ON pending_captures(event_id)
                    WHERE event_id IS NOT NULL AND event_id != '';
            ''')
            self._migrate_pending_captures(c)

    def _migrate_pending_captures(self, c):
        cols = {r[1] for r in c.execute('PRAGMA table_info(pending_captures)').fetchall()}
        if 'retry_count' not in cols:
            c.execute('ALTER TABLE pending_captures ADD COLUMN retry_count INTEGER DEFAULT 0')

    def _row_to_decision(self, row, sources=None) -> dict:
        d = dict(row)
        if 'workspace_id' in d:
            d['workspaceId'] = d['workspace_id']
            d['workspace_id'] = d['workspaceId']
        if 'sensitive' in d:
            d['sensitive'] = bool(d['sensitive'])
        d['alternativesConsidered'] = json.loads(d.pop('alternatives') or '[]')
        d['topicIds'] = json.loads(d.pop('topic_ids') or '[]')
        d['decidedBy'] = d.pop('decided_by')
        d['decidedAt'] = d.pop('decided_at')
        d['supersededBy'] = d.pop('superseded_by')
        d['supersededAt'] = d.pop('superseded_at')
        d['sourceType'] = d.pop('source_type')
        d['contentHash'] = d.pop('content_hash')
        d['createdAt'] = d.pop('created_at')
        d['updatedAt'] = d.pop('updated_at')
        d['sources'] = sources or self.list_sources(d['id'])
        return d

    def list_sources(self, decision_id: str) -> list:
        with self._conn() as c:
            rows = c.execute('SELECT * FROM sources WHERE decision_id = ?', (decision_id,)).fetchall()
        out = []
        for r in rows:
            s = dict(r)
            s['sourceType'] = s.pop('source_type')
            s['externalRef'] = s.pop('external_ref')
            s['decisionId'] = s.pop('decision_id')
            s['capturedAt'] = s.pop('captured_at')
            out.append(s)
        return out

    def _batch_sources(self, decision_ids: list[str]) -> dict[str, list]:
        if not decision_ids:
            return {}
        placeholders = ','.join('?' * len(decision_ids))
        with self._conn() as c:
            rows = c.execute(
                f'SELECT * FROM sources WHERE decision_id IN ({placeholders}) ORDER BY captured_at',
                decision_ids,
            ).fetchall()
        out: dict[str, list] = {}
        for r in rows:
            s = dict(r)
            s['sourceType'] = s.pop('source_type')
            s['externalRef'] = s.pop('external_ref')
            s['decisionId'] = s.pop('decision_id')
            s['capturedAt'] = s.pop('captured_at')
            out.setdefault(s['decisionId'], []).append(s)
        return out

    def _role_can_see_sensitive(self, role: str | None) -> bool:
        from .identity_mixin import _ROLE_LEVEL
        return _ROLE_LEVEL.get(role or '', 0) >= _ROLE_LEVEL.get('admin', 3)

    def list_decisions(self, workspace_id: str = None, search: str = '', status: str = '', limit: int = 200,
                       include_sources: bool = True, actor_role: str = None) -> list:
        ws = self._resolve_workspace_id(workspace_id)
        if not ws:
            return []
        q = 'SELECT * FROM decisions WHERE 1=1'
        params = []
        q += ' AND workspace_id = ?'
        params.append(ws)
        if actor_role is not None and self._has_sensitive_column() and not self._role_can_see_sensitive(actor_role):
            q += ' AND (sensitive = 0 OR sensitive IS NULL)'
        if status:
            q += ' AND status = ?'
            params.append(status)
        if search:
            q += ' AND (title LIKE ? OR summary LIKE ? OR reasoning LIKE ? OR decided_by LIKE ?)'
            pat = f'%{search}%'
            params.extend([pat, pat, pat, pat])
        q += ' ORDER BY decided_at DESC, created_at DESC LIMIT ?'
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        if not include_sources:
            return [self._row_to_decision(r, sources=[]) for r in rows]
        ids = [dict(r)['id'] for r in rows]
        src_map = self._batch_sources(ids)
        return [self._row_to_decision(r, sources=src_map.get(dict(r)['id'], [])) for r in rows]

    def get_decision(self, decision_id: str, workspace_id: str = None, actor_role: str = None) -> Optional[dict]:
        with self._conn() as c:
            if workspace_id:
                row = c.execute(
                    'SELECT * FROM decisions WHERE id = ? AND workspace_id = ?',
                    (decision_id, workspace_id),
                ).fetchone()
            else:
                row = c.execute('SELECT * FROM decisions WHERE id = ?', (decision_id,)).fetchone()
        if not row:
            return None
        if actor_role is not None and self._has_sensitive_column() and row['sensitive'] and not self._role_can_see_sensitive(actor_role):
            return None
        return self._row_to_decision(row)

    def get_decisions_by_ids(self, ids: list, workspace_id: str = None) -> list:
        if not ids:
            return []
        placeholders = ','.join('?' * len(ids))
        params = list(ids)
        q = f'SELECT * FROM decisions WHERE id IN ({placeholders})'
        if workspace_id:
            q += ' AND workspace_id = ?'
            params.append(workspace_id)
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def all_active_text_blob(self, workspace_id: str = None, actor_role: str = None) -> list[dict]:
        ws = self._resolve_workspace_id(workspace_id)
        if not ws:
            return []
        return self.list_decisions(workspace_id=ws, status='active', limit=5000, actor_role=actor_role)

    def upsert_decision(self, data: dict, sources: Optional[list] = None, source_key: Optional[str] = None,
                        workspace_id: str = None) -> dict:
        ws = workspace_id or data.get('workspaceId') or data.get('workspace_id') or self.get_default_workspace_id()
        title = (data.get('title') or 'Untitled').strip()
        summary = data.get('summary') or ''
        reasoning = data.get('reasoning') or ''
        ch = _hash_decision(title, summary, reasoning)

        if source_key and ws:
            with self._conn() as c:
                if self._has_scoped_ingest_log():
                    existing = c.execute(
                        'SELECT decision_id FROM ingest_log WHERE workspace_id = ? AND source_key = ?',
                        (ws, source_key),
                    ).fetchone()
                else:
                    existing = c.execute(
                        'SELECT decision_id FROM ingest_log WHERE source_key = ?', (source_key,)
                    ).fetchone()
                if existing:
                    return self.get_decision(existing['decision_id'], workspace_id=ws)

        with self._conn() as c:
            if self._has_workspace_column() and ws:
                dup = c.execute(
                    'SELECT id FROM decisions WHERE content_hash = ? AND workspace_id = ?',
                    (ch, ws),
                ).fetchone()
            else:
                dup = c.execute('SELECT id FROM decisions WHERE content_hash = ?', (ch,)).fetchone()
            if dup:
                return self.get_decision(dup['id'], workspace_id=ws if self._has_workspace_column() else None)

        did = data.get('id') or _uid()
        now = _now()
        row = {
            'id': did,
            'title': title,
            'summary': summary,
            'reasoning': reasoning,
            'alternatives': json.dumps(data.get('alternativesConsidered') or []),
            'decided_by': data.get('decidedBy') or '',
            'decided_at': data.get('decidedAt') or now[:10],
            'status': data.get('status') or 'active',
            'superseded_by': data.get('supersededBy'),
            'superseded_at': data.get('supersededAt'),
            'topic_ids': json.dumps(data.get('topicIds') or data.get('topics') or []),
            'confidence': data.get('confidence') or 3,
            'source_type': data.get('sourceType') or 'manual',
            'content_hash': ch,
            'workspace_id': ws,
            'sensitive': 1 if data.get('sensitive') else 0,
            'created_at': data.get('createdAt') or now,
            'updated_at': now,
        }
        with self._conn() as c:
            if self._has_workspace_column() and self._has_sensitive_column():
                c.execute('''
                    INSERT INTO decisions (id, title, summary, reasoning, alternatives, decided_by, decided_at,
                        status, superseded_by, superseded_at, topic_ids, confidence, source_type, content_hash,
                        workspace_id, sensitive, created_at, updated_at)
                    VALUES (:id, :title, :summary, :reasoning, :alternatives, :decided_by, :decided_at,
                        :status, :superseded_by, :superseded_at, :topic_ids, :confidence, :source_type, :content_hash,
                        :workspace_id, :sensitive, :created_at, :updated_at)
                ''', row)
            elif self._has_workspace_column():
                row.pop('sensitive', None)
                c.execute('''
                    INSERT INTO decisions (id, title, summary, reasoning, alternatives, decided_by, decided_at,
                        status, superseded_by, superseded_at, topic_ids, confidence, source_type, content_hash,
                        workspace_id, created_at, updated_at)
                    VALUES (:id, :title, :summary, :reasoning, :alternatives, :decided_by, :decided_at,
                        :status, :superseded_by, :superseded_at, :topic_ids, :confidence, :source_type, :content_hash,
                        :workspace_id, :created_at, :updated_at)
                ''', row)
            else:
                row.pop('workspace_id', None)
                c.execute('''
                    INSERT INTO decisions (id, title, summary, reasoning, alternatives, decided_by, decided_at,
                        status, superseded_by, superseded_at, topic_ids, confidence, source_type, content_hash,
                        created_at, updated_at)
                    VALUES (:id, :title, :summary, :reasoning, :alternatives, :decided_by, :decided_at,
                        :status, :superseded_by, :superseded_at, :topic_ids, :confidence, :source_type, :content_hash,
                        :created_at, :updated_at)
                ''', row)
            if sources:
                for s in sources:
                    if self._has_workspace_column():
                        c.execute('''
                            INSERT INTO sources (id, decision_id, source_type, external_ref, url, excerpt, captured_at, workspace_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            s.get('id') or _uid(), did,
                            s.get('sourceType') or s.get('source_type', 'manual'),
                            s.get('externalRef') or s.get('external_ref', ''),
                            s.get('url', ''),
                            s.get('excerpt', ''),
                            s.get('capturedAt') or now,
                            ws,
                        ))
                    else:
                        c.execute('''
                            INSERT INTO sources (id, decision_id, source_type, external_ref, url, excerpt, captured_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            s.get('id') or _uid(), did,
                            s.get('sourceType') or s.get('source_type', 'manual'),
                            s.get('externalRef') or s.get('external_ref', ''),
                            s.get('url', ''),
                            s.get('excerpt', ''),
                            s.get('capturedAt') or now,
                        ))
            if source_key and ws:
                if self._has_scoped_ingest_log():
                    c.execute(
                        'INSERT INTO ingest_log (workspace_id, source_key, decision_id, created_at) VALUES (?, ?, ?, ?)',
                        (ws, source_key, did, now),
                    )
                else:
                    c.execute(
                        'INSERT INTO ingest_log (source_key, decision_id, created_at) VALUES (?, ?, ?)',
                        (source_key, did, now),
                    )
        return self.get_decision(did, workspace_id=ws)

    def update_decision(self, decision_id: str, patch: dict, workspace_id: str = None) -> Optional[dict]:
        existing = self.get_decision(decision_id, workspace_id=workspace_id)
        if not existing:
            return None
        for k, v in patch.items():
            if v is not None:
                existing[k] = v
        existing['updatedAt'] = _now()
        with self._conn() as c:
            c.execute('''
                UPDATE decisions SET title=?, summary=?, reasoning=?, alternatives=?, decided_by=?, decided_at=?,
                    status=?, superseded_by=?, superseded_at=?, topic_ids=?, confidence=?, source_type=?, updated_at=?
                WHERE id=?
            ''', (
                existing['title'], existing['summary'], existing['reasoning'],
                json.dumps(existing.get('alternativesConsidered') or []),
                existing.get('decidedBy'), existing.get('decidedAt'),
                existing.get('status', 'active'),
                existing.get('supersededBy'), existing.get('supersededAt'),
                json.dumps(existing.get('topicIds') or []),
                existing.get('confidence', 3),
                existing.get('sourceType', 'manual'),
                existing['updatedAt'], decision_id,
            ))
            if self._has_sensitive_column() and patch.get('sensitive') is not None:
                c.execute('UPDATE decisions SET sensitive = ? WHERE id = ?',
                          (1 if patch.get('sensitive') else 0, decision_id))
        return self.get_decision(decision_id, workspace_id=workspace_id)

    def supersede(self, old_id: str, new_id: str) -> Optional[dict]:
        now = _now()
        with self._conn() as c:
            c.execute("UPDATE decisions SET status='superseded', superseded_by=?, superseded_at=?, updated_at=? WHERE id=?",
                      (new_id, now, now, old_id))
        return self.get_decision(old_id)

    def add_sources(self, decision_id: str, sources: list, workspace_id: str = None) -> None:
        now = _now()
        ws = workspace_id or self.get_default_workspace_id()
        with self._conn() as c:
            if not workspace_id:
                row = c.execute('SELECT workspace_id FROM decisions WHERE id = ?', (decision_id,)).fetchone()
                if row and row['workspace_id']:
                    ws = row['workspace_id']
            for s in sources:
                c.execute('''
                    INSERT INTO sources (id, decision_id, source_type, external_ref, url, excerpt, captured_at, workspace_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    s.get('id') or _uid(), decision_id,
                    s.get('sourceType') or s.get('source_type', 'manual'),
                    s.get('externalRef') or s.get('external_ref', ''),
                    s.get('url', ''),
                    s.get('excerpt', ''),
                    s.get('capturedAt') or now,
                    ws,
                ))

    def enqueue_capture(self, kind: str, payload: dict, event_id: str = '', workspace_id: str = None) -> str:
        ws = workspace_id or self.get_default_workspace_id()
        now = _now()
        if event_id:
            with self._conn() as c:
                row = c.execute(
                    'SELECT id, status FROM pending_captures WHERE event_id = ?',
                    (event_id,),
                ).fetchone()
                if row:
                    if row['status'] == 'done':
                        return row['id']
                    if row['status'] in ('pending', 'processing'):
                        return row['id']
                    if row['status'] == 'failed':
                        return row['id']
        jid = _uid()
        with self._conn() as c:
            c.execute('''
                INSERT INTO pending_captures (id, event_id, kind, payload, status, retry_count, workspace_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            ''', (jid, event_id or None, kind, json.dumps(payload), ws, now, now))
        return jid

    def get_capture(self, job_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute('SELECT * FROM pending_captures WHERE id = ?', (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d['payload'] = json.loads(d['payload'])
        return d

    def list_pending_capture_ids(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT id FROM pending_captures WHERE status = 'pending'").fetchall()
        return [r['id'] for r in rows]

    def claim_capture(self, job_id: str) -> dict | None:
        now = _now()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE pending_captures SET status='processing', updated_at=? WHERE id=? AND status='pending'",
                (now, job_id),
            )
            if cur.rowcount != 1:
                return None
            row = c.execute('SELECT * FROM pending_captures WHERE id = ?', (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d['payload'] = json.loads(d['payload'])
        return d

    def complete_capture(self, job_id: str):
        now = _now()
        with self._conn() as c:
            c.execute("UPDATE pending_captures SET status='done', updated_at=? WHERE id=?", (now, job_id))

    def fail_capture(self, job_id: str, max_retries: int = 3):
        now = _now()
        with self._conn() as c:
            row = c.execute('SELECT retry_count FROM pending_captures WHERE id = ?', (job_id,)).fetchone()
            if not row:
                return
            retries = (row['retry_count'] or 0) + 1
            if retries < max_retries:
                c.execute(
                    "UPDATE pending_captures SET status='pending', retry_count=?, updated_at=? WHERE id=?",
                    (retries, now, job_id),
                )
            else:
                c.execute(
                    "UPDATE pending_captures SET status='failed', retry_count=?, updated_at=? WHERE id=?",
                    (retries, now, job_id),
                )

    def prune_captures(self, keep_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM pending_captures WHERE status IN ('done', 'failed') AND updated_at < ?",
                (cutoff,),
            )
            return cur.rowcount

    def capture_event_done(self, event_id: str) -> bool:
        if not event_id:
            return False
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM pending_captures WHERE event_id = ? AND status = 'done'",
                (event_id,),
            ).fetchone()
        return row is not None

    def import_decisions(self, data: dict, workspace_id: str = None) -> dict:
        imported = 0
        ws = workspace_id or self.get_default_workspace_id()
        for raw in data.get('decisions', []):
            d = {k: v for k, v in raw.items() if k != 'sources'}
            self.upsert_decision(d, sources=raw.get('sources'), workspace_id=ws)
            imported += 1
        return {'imported': imported}

    def export_all(self, workspace_id: str = None) -> dict:
        ws = self._resolve_workspace_id(workspace_id)
        if not ws:
            return {'exportedAt': _now(), 'count': 0, 'decisions': []}
        decisions = self.list_decisions(workspace_id=ws, limit=10000)
        return {'exportedAt': _now(), 'count': len(decisions), 'decisions': decisions}

    def delete_decision(self, decision_id: str, workspace_id: str = None) -> bool:
        with self._conn() as c:
            if workspace_id:
                row = c.execute(
                    'SELECT id FROM decisions WHERE id = ? AND workspace_id = ?',
                    (decision_id, workspace_id),
                ).fetchone()
                if not row:
                    return False
            c.execute('DELETE FROM sources WHERE decision_id = ?', (decision_id,))
            if workspace_id:
                cur = c.execute('DELETE FROM decisions WHERE id = ? AND workspace_id = ?', (decision_id, workspace_id))
            else:
                cur = c.execute('DELETE FROM decisions WHERE id = ?', (decision_id,))
            return cur.rowcount > 0

    def seed_if_empty(self):
        ws = self.get_default_workspace_id()
        if self.list_decisions(workspace_id=ws):
            return
        samples = [
            {
                'title': 'No annual billing in Germany (DACH)',
                'summary': 'We sell monthly-only in DE/AT/CH despite enterprise requests.',
                'reasoning': 'German VAT invoicing + billing system lacks annual proration. Legal flagged risk until Q3 compliance.',
                'alternativesConsidered': [
                    {'option': 'Enable annual with manual invoicing', 'whyRejected': 'Ops cost 4h/deal'},
                    {'option': 'Stripe Tax for DE', 'whyRejected': 'Missing B2B reverse-charge edge cases'},
                ],
                'decidedBy': 'CFO + Legal', 'decidedAt': '2025-03-14', 'sourceType': 'meeting', 'confidence': 5,
            },
            {
                'title': 'Rejected vendor Acme CDN',
                'summary': 'Stayed on current edge provider despite 20% lower Acme quote.',
                'reasoning': 'Acme lacked EU-only data path verification for sovereign customers.',
                'alternativesConsidered': [
                    {'option': 'Switch to Acme', 'whyRejected': 'No auditable EU-only routing'},
                ],
                'decidedBy': 'CTO', 'decidedAt': '2025-11-02', 'sourceType': 'slack', 'confidence': 4,
            },
            {
                'title': 'Killed "Teams" social feature',
                'summary': 'Deprioritized in-product community feed after beta.',
                'reasoning': 'DAU/MAU 4%. Support tickets +30%. Reallocating 2 engineers to onboarding.',
                'alternativesConsidered': [
                    {'option': 'Ship to all users', 'whyRejected': 'No retention movement'},
                ],
                'decidedBy': 'Product + CEO', 'decidedAt': '2025-10-18', 'sourceType': 'jira', 'confidence': 5,
            },
        ]
        for s in samples:
            self.upsert_decision(s, sources=[{
                'sourceType': s['sourceType'], 'externalRef': 'seed', 'url': '', 'excerpt': s['summary'][:200],
            }], workspace_id=ws)