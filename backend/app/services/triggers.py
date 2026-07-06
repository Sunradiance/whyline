"""Webhook ingest triggers — avoid poisoning memory with every comment."""
import re

from ..config import Config

_DEFAULT_MARKERS = (
    '[decision]', '#decision', 'decision:', 'adr:', 'whyline:', 'whyline capture',
)


def should_extract(
    text: str = '',
    labels: list | None = None,
    path: str = '',
    force: bool = False,
) -> bool:
    if force:
        return True
    blob = (text or '').lower()
    markers = Config.WEBHOOK_DECISION_MARKERS or _DEFAULT_MARKERS
    if any(m in blob for m in markers):
        return True
    if labels and any('decision' in str(l).lower() for l in labels):
        return True
    if path and re.search(r'(adr|decisions?)/', path, re.I):
        return True
    return False


def linear_human_text(payload: dict) -> str:
    """Extract human-readable fields only — not raw JSON."""
    data = payload.get('data', payload)
    parts = []
    for key in ('title', 'description', 'body', 'comment', 'text'):
        val = data.get(key) if isinstance(data, dict) else payload.get(key)
        if val and isinstance(val, str):
            parts.append(val)
    return ' '.join(parts)