"""Resolve target workspace for integration webhooks — Phase 2 routing."""

from flask import request

from ..store import store


def webhook_workspace_id(payload: dict | None = None) -> str:
    """Header X-Whyline-Workspace or body workspace_id, else default."""
    hdr = request.headers.get('X-Whyline-Workspace', '').strip()
    if hdr and store.get_workspace(hdr):
        return hdr
    body = payload if payload is not None else (request.get_json(silent=True) or {})
    if isinstance(body, dict):
        wid = (body.get('workspace_id') or body.get('workspaceId') or '').strip()
        if wid and store.get_workspace(wid):
            return wid
    return store.get_default_workspace_id()