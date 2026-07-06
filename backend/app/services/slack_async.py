"""Async Slack capture — durable queue, ack first."""
from .capture_queue import enqueue


def slack_retry_num(headers) -> int:
    try:
        return int(headers.get('X-Slack-Retry-Num', '0') or '0')
    except (TypeError, ValueError):
        return 0


def enqueue_slack_thread_capture(channel: str, message_ts: str, *, label: str = 'event', event_id: str = '') -> None:
    enqueue('slack_thread', {'channel': channel, 'message_ts': message_ts, 'label': label}, event_id=event_id)


def enqueue_slack_slash(text: str, user: str, response_url: str) -> None:
    enqueue('slack_slash', {'text': text, 'user': user, 'response_url': response_url})