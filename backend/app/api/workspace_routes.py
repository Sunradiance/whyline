"""Workspace management — multi-tenant Phase 2."""

from flask import g, jsonify, request, session

from ..auth_identity import require_csrf, require_workspace, resolve_actor
from ..config import Config
from ..store import store
from ..store.identity_mixin import _ROLE_LEVEL
from . import api_bp

_VALID_ROLES = frozenset(_ROLE_LEVEL)


def _actor_role():
    return getattr(g, 'actor', None) and g.actor.role


def _parse_role(raw, default: str = 'member') -> tuple[str | None, tuple | None]:
    role = (raw or default).strip()
    if role not in _VALID_ROLES:
        return None, (jsonify({'error': f'invalid role: {role}'}), 400)
    return role, None


def _role_rank(role: str) -> int:
    return _ROLE_LEVEL.get(role, 0)


def _guard_role_assignment(role: str, actor_role: str) -> tuple | None:
    if role == 'owner' and actor_role != 'owner':
        return jsonify({'error': 'only owners can assign or mint the owner role'}), 403
    if _role_rank(role) > _role_rank(actor_role):
        return jsonify({'error': 'cannot assign a role above your own'}), 403
    return None


def _guard_target_rank(actor_role: str, target_current_role: str | None, verb: str = 'modify') -> tuple | None:
    if target_current_role is None:
        return jsonify({'error': 'not found'}), 404
    if _role_rank(target_current_role) >= _role_rank(actor_role):
        return jsonify({'error': f'cannot {verb} a member at or above your role'}), 403
    return None


def _guard_membership_change(actor_role: str, target_current_role: str | None, new_role: str) -> tuple | None:
    blocked = _guard_role_assignment(new_role, actor_role)
    if blocked:
        return blocked
    if target_current_role is not None:
        blocked = _guard_target_rank(actor_role, target_current_role, 'modify')
        if blocked:
            return blocked
    return None


def _guard_member_removal(actor_role: str, target_current_role: str | None, workspace_id: str) -> tuple | None:
    blocked = _guard_target_rank(actor_role, target_current_role, 'remove')
    if blocked:
        return blocked
    if target_current_role == 'owner' and store.count_members_by_role(workspace_id, 'owner') <= 1:
        return jsonify({'error': 'cannot remove the last owner'}), 403
    return None


def _guard_token_revocation(actor_role: str, token_role: str, actor_token_id: str | None, target_token_id: str) -> tuple | None:
    if _role_rank(token_role) >= _role_rank(actor_role):
        return jsonify({'error': 'cannot revoke a token at or above your role'}), 403
    if actor_token_id and actor_token_id == target_token_id:
        return jsonify({'error': 'cannot revoke the token you are currently using'}), 403
    return None


def _actor_token_id():
    actor = getattr(g, 'actor', None)
    return actor.id if actor and actor.kind == 'service' else None


@api_bp.route('/workspaces', methods=['GET'])
def list_workspaces():
    actor = resolve_actor()
    if not actor:
        return jsonify({'error': 'unauthorized'}), 401
    if actor.kind in ('solo', 'service') and actor.workspace_id:
        ws = store.get_workspace(actor.workspace_id)
        return jsonify({'ok': True, 'workspaces': [{**ws, 'role': actor.role}] if ws else []})
    if actor.kind == 'user' and session.get('user_id'):
        return jsonify({'ok': True, 'workspaces': store.list_user_workspaces(session['user_id'])})
    return jsonify({'ok': True, 'workspaces': []})


@api_bp.route('/workspaces', methods=['POST'])
@require_csrf
def create_workspace():
    actor = resolve_actor()
    if actor is None:
        return jsonify({'error': 'unauthorized'}), 401
    if actor.kind == 'service':
        return jsonify({'error': 'workspace creation requires a user session'}), 403
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or 'New workspace').strip()
    ws = store.create_workspace(name, public_read=bool(body.get('public_read')))
    uid = session.get('user_id')
    if uid:
        store.add_member(ws['id'], uid, 'owner')
    elif actor.kind == 'solo':
        pass  # solo uses default workspace; extra workspaces for org mode
    store.audit(ws['id'], actor.kind, actor.id, 'workspace.create', 'workspace', ws['id'])
    return jsonify({'ok': True, 'workspace': ws})


@api_bp.route('/workspaces/<workspace_id>', methods=['GET'])
@require_workspace('read')
def get_workspace(workspace_id):
    ws = store.get_workspace(g.workspace_id)
    if not ws:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'ok': True, 'workspace': ws})


@api_bp.route('/workspaces/<workspace_id>', methods=['PATCH'])
@require_workspace('admin')
@require_csrf
def patch_workspace(workspace_id):
    body = request.get_json(silent=True) or {}
    ws = store.update_workspace(
        g.workspace_id,
        name=body.get('name'),
        public_read=body.get('public_read') if 'public_read' in body else None,
    )
    if not ws:
        return jsonify({'error': 'not found'}), 404
    store.audit(g.workspace_id, g.actor.kind, g.actor.id, 'workspace.update', 'workspace', ws['id'])
    return jsonify({'ok': True, 'workspace': ws})


@api_bp.route('/workspaces/<workspace_id>/members', methods=['GET'])
@require_workspace('read')
def list_workspace_members(workspace_id):
    return jsonify({'ok': True, 'members': store.list_members(g.workspace_id)})


@api_bp.route('/workspaces/<workspace_id>/members', methods=['POST'])
@require_workspace('manage')
@require_csrf
def add_workspace_member(workspace_id):
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').strip().lower()
    role, err = _parse_role(body.get('role'), 'member')
    if err:
        return err
    if not email:
        return jsonify({'error': 'email required'}), 400
    user = store.get_user_by_email(email)
    if not user:
        if Config.AUTH_MODE == 'open':
            user = store.create_user(email, body.get('password') or None)
        else:
            return jsonify({'error': 'user not found — provision account first'}), 404
    target_current = store.get_role(user['id'], g.workspace_id)
    blocked = _guard_membership_change(_actor_role() or '', target_current, role)
    if blocked:
        return blocked
    m = store.add_member(g.workspace_id, user['id'], role)
    store.audit(g.workspace_id, g.actor.kind, g.actor.id, 'member.invite', 'user', user['id'], email)
    return jsonify({'ok': True, 'membership': m})


@api_bp.route('/workspaces/<workspace_id>/members/<user_id>', methods=['DELETE'])
@require_workspace('manage')
@require_csrf
def remove_workspace_member(workspace_id, user_id):
    target_current = store.get_role(user_id, g.workspace_id)
    blocked = _guard_member_removal(_actor_role() or '', target_current, g.workspace_id)
    if blocked:
        return blocked
    if not store.remove_member(g.workspace_id, user_id):
        return jsonify({'error': 'not found'}), 404
    store.audit(g.workspace_id, g.actor.kind, g.actor.id, 'member.remove', 'user', user_id)
    return jsonify({'ok': True, 'removed': user_id})


@api_bp.route('/workspaces/<workspace_id>/tokens', methods=['GET'])
@require_workspace('manage')
def list_workspace_tokens(workspace_id):
    return jsonify({'ok': True, 'tokens': store.list_service_tokens(g.workspace_id)})


@api_bp.route('/workspaces/<workspace_id>/tokens', methods=['POST'])
@require_workspace('manage')
@require_csrf
def create_workspace_token(workspace_id):
    body = request.get_json(silent=True) or {}
    role, err = _parse_role(body.get('role'), 'member')
    if err:
        return err
    blocked = _guard_role_assignment(role, _actor_role() or '')
    if blocked:
        return blocked
    raw, row = store.create_service_token(g.workspace_id, role=role, name=body.get('name', ''))
    store.audit(g.workspace_id, g.actor.kind, g.actor.id, 'token.create', 'service_token', row['id'])
    return jsonify({'ok': True, 'token': raw, 'meta': row, 'note': 'Shown once — store securely.'})


@api_bp.route('/workspaces/<workspace_id>/tokens/<token_id>', methods=['DELETE'])
@require_workspace('manage')
@require_csrf
def revoke_workspace_token(workspace_id, token_id):
    row = store.get_service_token(token_id, g.workspace_id)
    if not row:
        return jsonify({'error': 'not found'}), 404
    blocked = _guard_token_revocation(
        _actor_role() or '',
        row['role'],
        _actor_token_id(),
        token_id,
    )
    if blocked:
        return blocked
    if not store.revoke_service_token(token_id, g.workspace_id):
        return jsonify({'error': 'not found'}), 404
    store.audit(g.workspace_id, g.actor.kind, g.actor.id, 'token.revoke', 'service_token', token_id)
    return jsonify({'ok': True, 'revoked': token_id})


@api_bp.route('/workspaces/<workspace_id>/audit', methods=['GET'])
@require_workspace('admin')
def workspace_audit(workspace_id):
    limit = int(request.args.get('limit', 100))
    return jsonify({'ok': True, 'entries': store.list_audit_log(g.workspace_id, limit=limit)})