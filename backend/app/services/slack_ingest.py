from . import llm
from .ingest import persist_extracted
from .slack_client import fetch_thread_messages, get_permalink


def persist_slack_thread(channel: str, thread_ts: str) -> dict:
    messages = fetch_thread_messages(channel, thread_ts)
    permalink = get_permalink(channel, thread_ts)
    extracted = llm.extract_decision_from_thread(messages)
    data = extracted.model_dump()
    source_key = f'slack:{channel}:{thread_ts}'
    sources = [{
        'sourceType': 'slack',
        'externalRef': f'{channel}/{thread_ts}',
        'url': permalink,
        'excerpt': '\n'.join(m.get('text', '') for m in messages[:5])[:500],
    }]
    return persist_extracted(data, 'slack', sources, source_key=source_key)