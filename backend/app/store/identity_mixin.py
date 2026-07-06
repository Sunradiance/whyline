"""Identity, workspaces, membership, service tokens, and RBAC."""

from ..services.passwords import hash_password, new_service_token, token_hash, verify_password

_ACTION_LEVEL = {'read': 1, 'create': 2, 'manage': 3, 'admin': 4}
_ROLE_LEVEL = {'viewer': 1, 'member': 2, 'admin': 3, 'owner': 4}


def role_can(role: str, action: str) -> bool:
    return _ROLE_LEVEL.get(role, 0) >= _ACTION_LEVEL.get(action, 99)


class StoreIdentityMixin:
    def create_workspace(self, name: str, public_read: bool = False, slug: str = None) -> dict:
        wid = self._uid()
        now = self._now()
        with self._conn() as c:
            c.execute(
                'INSERT INTO workspaces (id, name, slug, public_read, created_at) VALUES (?,?,?,?,?)',
                (wid, name, slug, 1 if public_read else 0, now),
            )
        return self.get_workspace(wid)

    def get_workspace(self, workspace_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute('SELECT * FROM workspaces WHERE id = ?', (workspace_id,)).fetchone()
        return dict(row) if row else None

    def workspace_is_public(self, workspace_id: str) -> bool:
        ws = self.get_workspace(workspace_id)
        return bool(ws and ws.get('public_read'))

    def list_user_workspaces(self, user_id: str) -> list:
        with self._conn() as c:
            rows = c.execute('''
                SELECT w.id, w.name, w.slug, w.public_read, w.created_at, m.role
                FROM workspaces w
                JOIN memberships m ON m.workspace_id = w.id
                WHERE m.user_id = ?
                ORDER BY w.created_at
            ''', (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def update_workspace(self, workspace_id: str, *, name: str = None, public_read: bool = None) -> dict | None:
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        fields, params = [], []
        if name is not None:
            fields.append('name = ?')
            params.append(name)
        if public_read is not None:
            fields.append('public_read = ?')
            params.append(1 if public_read else 0)
        if not fields:
            return ws
        params.append(workspace_id)
        with self._conn() as c:
            c.execute(f"UPDATE workspaces SET {', '.join(fields)} WHERE id = ?", params)
        return self.get_workspace(workspace_id)

    def list_members(self, workspace_id: str) -> list:
        with self._conn() as c:
            rows = c.execute('''
                SELECT m.id, m.role, m.created_at, u.id AS user_id, u.email
                FROM memberships m
                JOIN users u ON u.id = m.user_id
                WHERE m.workspace_id = ?
                ORDER BY m.created_at
            ''', (workspace_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_audit_log(self, workspace_id: str, limit: int = 100) -> list:
        with self._conn() as c:
            rows = c.execute(
                'SELECT * FROM audit_log WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?',
                (workspace_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_default_workspace_id(self) -> str | None:
        import sqlite3
        with self._conn() as c:
            try:
                row = c.execute("SELECT value FROM schema_meta WHERE key = 'default_workspace_id'").fetchone()
            except sqlite3.OperationalError:
                return None
        return row[0] if row else None

    def create_user(self, email: str, password: str = None) -> dict:
        uid = self._uid()
        now = self._now()
        pw = hash_password(password) if password else None
        with self._conn() as c:
            c.execute(
                "INSERT INTO users (id, email, password_hash, status, created_at) VALUES (?,?,?, 'active', ?)",
                (uid, email.lower().strip(), pw, now),
            )
        return self.get_user(uid)

    def get_user(self, user_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute('SELECT id, email, status, created_at FROM users WHERE id = ?', (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict | None:
        with self._conn() as c:
            row = c.execute('SELECT * FROM users WHERE email = ?', (email.lower().strip(),)).fetchone()
        return dict(row) if row else None

    def verify_login(self, email: str, password: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE email = ? AND status = 'active'", (email.lower().strip(),)).fetchone()
        if not row or not verify_password(row['password_hash'], password):
            return None
        return {'id': row['id'], 'email': row['email']}

    def add_member(self, workspace_id: str, user_id: str, role: str = 'member') -> dict:
        if role not in _ROLE_LEVEL:
            raise ValueError(f'unknown role: {role}')
        mid = self._uid()
        now = self._now()
        with self._conn() as c:
            c.execute(
                'INSERT INTO memberships (id, workspace_id, user_id, role, created_at) VALUES (?,?,?,?,?) '
                'ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = excluded.role',
                (mid, workspace_id, user_id, role, now),
            )
            row = c.execute(
                'SELECT * FROM memberships WHERE workspace_id = ? AND user_id = ?',
                (workspace_id, user_id),
            ).fetchone()
        return dict(row)

    def get_role(self, user_id: str, workspace_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                'SELECT role FROM memberships WHERE user_id = ? AND workspace_id = ?',
                (user_id, workspace_id),
            ).fetchone()
        return row['role'] if row else None

    def count_members_by_role(self, workspace_id: str, role: str) -> int:
        with self._conn() as c:
            row = c.execute(
                'SELECT COUNT(*) AS n FROM memberships WHERE workspace_id = ? AND role = ?',
                (workspace_id, role),
            ).fetchone()
        return row['n'] if row else 0

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                'DELETE FROM memberships WHERE workspace_id = ? AND user_id = ?',
                (workspace_id, user_id),
            )
            return cur.rowcount == 1

    def list_service_tokens(self, workspace_id: str) -> list:
        with self._conn() as c:
            rows = c.execute(
                'SELECT id, workspace_id, name, role, created_at, last_used_at '
                'FROM service_tokens WHERE workspace_id = ? ORDER BY created_at',
                (workspace_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_service_token(self, token_id: str, workspace_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                'SELECT id, workspace_id, name, role, created_at, last_used_at '
                'FROM service_tokens WHERE id = ? AND workspace_id = ?',
                (token_id, workspace_id),
            ).fetchone()
        return dict(row) if row else None

    def revoke_service_token(self, token_id: str, workspace_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                'DELETE FROM service_tokens WHERE id = ? AND workspace_id = ?',
                (token_id, workspace_id),
            )
            return cur.rowcount == 1

    def can(self, user_id: str, workspace_id: str, action: str) -> bool:
        role = self.get_role(user_id, workspace_id)
        return role_can(role, action) if role else False

    def create_service_token(self, workspace_id: str, role: str = 'member', name: str = '') -> tuple[str, dict]:
        if role not in _ROLE_LEVEL:
            raise ValueError(f'unknown role: {role}')
        raw = new_service_token()
        tid = self._uid()
        now = self._now()
        with self._conn() as c:
            c.execute(
                'INSERT INTO service_tokens (id, workspace_id, token_hash, name, role, created_at) '
                'VALUES (?,?,?,?,?,?)',
                (tid, workspace_id, token_hash(raw), name, role, now),
            )
        return raw, {'id': tid, 'workspace_id': workspace_id, 'role': role, 'name': name}

    def verify_service_token(self, raw: str) -> dict | None:
        if not raw:
            return None
        th = token_hash(raw)
        now = self._now()
        with self._conn() as c:
            row = c.execute(
                'SELECT id, workspace_id, role FROM service_tokens WHERE token_hash = ?', (th,)
            ).fetchone()
            if not row:
                return None
            c.execute('UPDATE service_tokens SET last_used_at = ? WHERE id = ?', (now, row['id']))
        return {'token_id': row['id'], 'workspace_id': row['workspace_id'], 'role': row['role']}

    def audit(self, workspace_id, actor_type, actor_id, action, target_type='', target_id='', detail=''):
        with self._conn() as c:
            c.execute(
                'INSERT INTO audit_log (id, workspace_id, actor_type, actor_id, action, target_type, target_id, detail, created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (self._uid(), workspace_id, actor_type, actor_id, action, target_type, target_id, detail, self._now()),
            )