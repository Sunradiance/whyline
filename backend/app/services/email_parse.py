"""Normalize email webhook payloads (Mailgun, SendGrid, generic JSON, raw forward)."""
import re
from email import policy
from email.parser import BytesParser


def _first(*vals: str) -> str:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return ''


def parse_email_payload(payload: dict, raw_body: bytes | None = None) -> dict:
    """Return {subject, body, from_addr, message_id, url}."""
    if raw_body and payload.get('content_type', '').startswith('message/'):
        msg = BytesParser(policy=policy.default).parsebytes(raw_body)
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain' and not part.get_filename():
                    body = part.get_content() or ''
                    break
        else:
            body = msg.get_content() or ''
        return {
            'subject': msg.get('subject', ''),
            'body': body.strip(),
            'from_addr': msg.get('from', ''),
            'message_id': msg.get('message-id', ''),
            'url': '',
        }

    # Mailgun-style
    body = _first(
        payload.get('body'),
        payload.get('text'),
        payload.get('body-plain'),
        payload.get('stripped-text'),
        payload.get('plain'),
    )
    if not body and payload.get('body-html'):
        body = re.sub(r'<[^>]+>', ' ', payload.get('body-html', ''))
        body = re.sub(r'\s+', ' ', body).strip()

    return {
        'subject': _first(payload.get('subject'), payload.get('Subject')),
        'body': body,
        'from_addr': _first(payload.get('from'), payload.get('sender'), payload.get('From')),
        'message_id': _first(payload.get('message_id'), payload.get('Message-Id'), payload.get('Message-ID')),
        'url': _first(payload.get('url')),
    }


def email_to_messages(parsed: dict) -> list[dict]:
    parts = []
    if parsed.get('subject'):
        parts.append(f"Subject: {parsed['subject']}")
    if parsed.get('from_addr'):
        parts.append(f"From: {parsed['from_addr']}")
    if parsed.get('body'):
        parts.append(parsed['body'])
    text = '\n\n'.join(parts)
    return [{'speaker': parsed.get('from_addr', 'email'), 'text': text}]