"""Shared persist logic for all integration ingest paths."""
from ..config import Config
from ..store import store
from .retrieval import best_match_score


def persist_extracted(
    data: dict,
    source_type: str,
    sources: list,
    source_key: str | None = None,
    *,
    check_near_dup: bool = True,
    workspace_id: str | None = None,
) -> dict:
    ws = workspace_id or store.get_default_workspace_id()
    if check_near_dup:
        q = f"{data.get('title', '')} {data.get('summary', '')} {data.get('reasoning', '')}"
        score, existing = best_match_score(
            q, store.list_decisions(workspace_id=ws, status='active', limit=500, include_sources=False),
        )
        if existing and score >= Config.NEAR_DUP_SCORE_THRESHOLD:
            if sources:
                store.add_sources(existing['id'], sources, workspace_id=ws)
            return store.get_decision(existing['id'], workspace_id=ws)
    return store.upsert_decision(
        {**data, 'sourceType': source_type, 'topicIds': data.get('topics', [])},
        sources=sources,
        source_key=source_key,
        workspace_id=ws,
    )