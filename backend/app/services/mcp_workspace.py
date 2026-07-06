"""MCP workspace binding — one workspace per MCP process."""

import os

from ..auth import ensure_api_key
from ..config import Config
from ..store import store


def resolve_mcp_workspace_id() -> str:
    wid = os.environ.get('MCP_WORKSPACE_ID', '').strip()
    if wid:
        if not store.get_workspace(wid):
            raise RuntimeError(f'MCP_WORKSPACE_ID not found: {wid}')
        return wid
    ensure_api_key()
    tok = store.verify_service_token(Config.WHYLINE_API_KEY)
    if tok:
        return tok['workspace_id']
    if Config.AUTH_MODE == 'solo':
        ws = store.get_default_workspace_id()
        if ws:
            return ws
    raise RuntimeError(
        'MCP requires MCP_WORKSPACE_ID or a workspace-scoped WHYLINE_API_KEY (service token)'
    )