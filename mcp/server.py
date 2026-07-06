#!/usr/bin/env python3
"""Whyline MCP server — workspace-scoped ask, extract, search."""
import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(ROOT, 'backend')
sys.path.insert(0, BACKEND)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from app.auth import ensure_api_key
from app.config import Config
from app.services import llm
from app.services.ingest import persist_extracted
from app.services.mcp_workspace import resolve_mcp_workspace_id
from app.services.retrieval import score_decisions
from app.store import store

server = Server('whyline')


def _ask(question: str) -> dict:
    ws = resolve_mcp_workspace_id()
    active = store.all_active_text_blob(workspace_id=ws)
    top = score_decisions(question, active, top_k=Config.RETRIEVAL_TOP_K)
    if not top:
        return {'result': {'answer': 'No matching decisions.', 'confidence': 'none', 'decisionIds': [], 'receipts': []}, 'retrieved': 0}
    if not Config.LLM_API_KEY:
        return {'error': 'LLM_API_KEY not configured', 'retrieved': [d['id'] for d in top]}
    result = llm.ask_why(question, top)
    corpus_ids = {d['id'] for d in top}
    result.decisionIds = [i for i in result.decisionIds if i in corpus_ids]
    out = result.model_dump()
    by_id = {d['id']: d for d in top}
    receipts = []
    for did in out.get('decisionIds', []):
        d = by_id.get(did)
        if not d:
            continue
        for s in d.get('sources', []):
            receipts.append({'decisionId': did, 'title': d.get('title'), 'url': s.get('url'),
                             'sourceType': s.get('sourceType')})
    out['receipts'] = receipts
    return {'result': out, 'retrieved': len(top), 'workspace_id': ws}


def _extract(text: str, source_type: str = 'mcp', url: str = '') -> dict:
    if not Config.LLM_API_KEY:
        return {'error': 'LLM_API_KEY not configured'}
    ws = resolve_mcp_workspace_id()
    extracted = llm.extract_decision_from_thread([{'text': text}], source_hint=source_type)
    data = extracted.model_dump()
    d = persist_extracted(
        data, source_type,
        [{'sourceType': source_type, 'url': url, 'excerpt': text[:500]}],
        workspace_id=ws,
    )
    return {'decision': d, 'workspace_id': ws}


def _search(query: str, top_k: int = 8) -> dict:
    ws = resolve_mcp_workspace_id()
    active = store.all_active_text_blob(workspace_id=ws)
    top = score_decisions(query, active, top_k=top_k)
    return {
        'decisions': [{'id': d['id'], 'title': d['title'], 'summary': d.get('summary'),
                       'status': d.get('status')} for d in top],
        'count': len(top),
        'workspace_id': ws,
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name='whyline_ask',
            description='Ask Whyline why the company decided something. Returns answer with decision IDs and receipt links.',
            inputSchema={
                'type': 'object',
                'properties': {'question': {'type': 'string', 'description': 'Natural language why question'}},
                'required': ['question'],
            },
        ),
        Tool(
            name='whyline_extract',
            description='Extract and persist a company decision from text (email, notes, transcript snippet).',
            inputSchema={
                'type': 'object',
                'properties': {
                    'text': {'type': 'string'},
                    'source_type': {'type': 'string', 'default': 'mcp'},
                    'url': {'type': 'string', 'default': ''},
                },
                'required': ['text'],
            },
        ),
        Tool(
            name='whyline_search',
            description='BM25 search over active decisions — no LLM call.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'top_k': {'type': 'integer', 'default': 8},
                },
                'required': ['query'],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ensure_api_key()
    try:
        if name == 'whyline_ask':
            out = _ask(arguments.get('question', ''))
        elif name == 'whyline_extract':
            out = _extract(arguments.get('text', ''), arguments.get('source_type', 'mcp'), arguments.get('url', ''))
        elif name == 'whyline_search':
            out = _search(arguments.get('query', ''), int(arguments.get('top_k', 8)))
        else:
            out = {'error': f'unknown tool: {name}'}
        return [TextContent(type='text', text=json.dumps(out, ensure_ascii=False, indent=2))]
    except Exception as e:
        return [TextContent(type='text', text=json.dumps({'error': str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())