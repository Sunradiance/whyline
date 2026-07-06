import re

import requests
from ..config import Config


def parse_thread_ref(text: str) -> tuple[str | None, str | None]:
    text = (text or '').strip()
    thread_q = re.search(r'[?&]thread_ts=([0-9]+\.[0-9]+)', text)
    m = re.search(r'archives/([A-Z0-9]+)/p(\d+)', text)
    if m:
        channel = m.group(1)
        if thread_q:
            return channel, thread_q.group(1)
        raw = m.group(2)
        thread_ts = f"{raw[:-6]}.{raw[-6:]}" if len(raw) > 6 else raw
        return channel, thread_ts
    parts = text.split()
    if len(parts) >= 2 and parts[0].startswith('C'):
        return parts[0], parts[1]
    return None, None


def fetch_thread_messages(channel: str, thread_ts: str) -> list[dict]:
    if not Config.SLACK_BOT_TOKEN:
        raise RuntimeError('SLACK_BOT_TOKEN not configured')
    resp = requests.get(
        'https://slack.com/api/conversations.replies',
        headers={'Authorization': f'Bearer {Config.SLACK_BOT_TOKEN}'},
        params={'channel': channel, 'ts': thread_ts, 'limit': 200},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('ok'):
        raise RuntimeError(data.get('error', 'slack api error'))
    return data.get('messages', [])


def resolve_thread_ts(channel: str, message_ts: str) -> str:
    """Map any message ts (parent or reply) to thread root via conversations.replies."""
    if not Config.SLACK_BOT_TOKEN:
        return message_ts
    resp = requests.get(
        'https://slack.com/api/conversations.replies',
        headers={'Authorization': f'Bearer {Config.SLACK_BOT_TOKEN}'},
        params={'channel': channel, 'ts': message_ts, 'limit': 1},
        timeout=15,
    )
    data = resp.json()
    if not data.get('ok') or not data.get('messages'):
        return message_ts
    root = data['messages'][0]
    return root.get('thread_ts') or root.get('ts') or message_ts


def get_permalink(channel: str, message_ts: str) -> str:
    if not Config.SLACK_BOT_TOKEN:
        return ''
    resp = requests.get(
        'https://slack.com/api/chat.getPermalink',
        headers={'Authorization': f'Bearer {Config.SLACK_BOT_TOKEN}'},
        params={'channel': channel, 'message_ts': message_ts},
        timeout=15,
    )
    data = resp.json()
    return data.get('permalink', '') if data.get('ok') else ''