import hashlib
import hmac
import time


def verify_slack_signature(signing_secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    if not signing_secret or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > 60 * 5:
        return False
    base = f'v0:{timestamp}:'.encode() + body
    digest = 'v0=' + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)