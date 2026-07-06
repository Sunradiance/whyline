"""Workspace-scoped authorization — replaces god-key with per-workspace tokens."""

import hmac
import secrets
from functools import wraps

from flask import g, jsonify, request, session

from .config import Config
from .store import store

_ACTION_LEVEL = {'read': 1, 'create': 2, 'manage': 3, 'admin': 4}
_ROLE_LEVEL = {'viewer': 1, 'member': 2, 'admin': 3, 'owner': 4}


def _role_allows(role: str, action: str) -> bool:
    return _ROLE_LEVEL.get(role, 0) >= _ACTION_LEVEL.get(action, 99)


def is_local_client() -> bool:
    addr = (request.remote_addr or '').strip()
    return addr in ('127.0.0.1', '::1') or addr.startswith('127.')


def _requested_workspace() -> str | None:
    if request.view_args and request.view_args.get('workspace_id'):
        return request.view_args['workspace_id']
    q = request.args.get('workspace')
    if q:
        return q
    if request.is_json:
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict) and body.get('workspace_id'):
            return body['workspace_id']
    return None


class Actor:
    __slots__ = ('kind', 'id', 'workspace_id', 'role')

    def __init__(self, kind, id, workspace_id, role):
        self.kind = kind
        self.id = id
        self.workspace_id = workspace_id
        self.role = role


def resolve_actor():
    key = request.headers.get('X-Whyline-Key', '')
    if key:
        tok = store.verify_service_token(key)
        if tok:
            return Actor('service', tok['token_id'], tok['workspace_id'], tok['role'])
        from .auth import ensure_api_key
        ensure_api_key()
        if (
            Config.AUTH_MODE == 'solo'
            and Config.WHYLINE_API_KEY
            and hmac.compare_digest(key, Config.WHYLINE_API_KEY)
        ):
            return Actor('service', 'legacy', store.get_default_workspace_id(), 'admin')
        return None

    uid = session.get('user_id')
    if uid:
        target = _requested_workspace() or store.get_default_workspace_id()
        role = store.get_role(uid, target) if target else None
        return Actor('user', uid, target, role)

    if Config.AUTH_MODE == 'solo' and session.get('authed') and is_local_client():
        return Actor('solo', 'local', store.get_default_workspace_id(), 'owner')

    return None


def require_workspace(action: str = 'read'):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            actor = resolve_actor()

            if actor is None and action == 'read':
                target = _requested_workspace()
                if target and store.workspace_is_public(target):
                    g.actor = Actor('anonymous', None, target, 'viewer')
                    g.workspace_id = target
                    return f(*args, **kwargs)

            if actor is None:
                return jsonify({'error': 'unauthorized'}), 401

            if not actor.workspace_id:
                return jsonify({'error': 'workspace required (?workspace=<id> or body.workspace_id)'}), 400

            requested = _requested_workspace()
            if requested and requested != actor.workspace_id:
                return jsonify({'error': 'not found'}), 404

            if not _role_allows(actor.role or '', action):
                return jsonify({'error': 'forbidden — insufficient role'}), 403

            g.actor = actor
            g.workspace_id = actor.workspace_id
            return f(*args, **kwargs)
        return wrapped
    return decorator


def issue_csrf() -> str:
    tok = session.get('csrf')
    if not tok:
        tok = secrets.token_urlsafe(32)
        session['csrf'] = tok
    return tok


def require_csrf(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if request.headers.get('X-Whyline-Key'):
            return f(*args, **kwargs)
        if Config.AUTH_MODE == 'solo' and is_local_client() and session.get('authed'):
            return f(*args, **kwargs)
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            sent = request.headers.get('X-CSRF-Token', '')
            if not sent or not secrets.compare_digest(sent, session.get('csrf', '')):
                return jsonify({'error': 'invalid csrf token'}), 403
        return f(*args, **kwargs)
    return wrapped