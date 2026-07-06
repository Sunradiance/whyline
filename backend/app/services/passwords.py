"""Password + token hashing — no Flask/store deps (avoids circular imports)."""

import hashlib
import hmac
import secrets

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError
    _ph = PasswordHasher()
    _ARGON2 = True
except Exception:  # pragma: no cover
    _ph = None
    _ARGON2 = False


def hash_password(raw: str) -> str:
    if not _ARGON2:
        raise RuntimeError('argon2-cffi not installed — add it to requirements.txt')
    return _ph.hash(raw)


def verify_password(stored_hash: str, raw: str) -> bool:
    if not _ARGON2 or not stored_hash:
        return False
    try:
        return _ph.verify(stored_hash, raw)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(stored_hash: str) -> bool:
    if not _ARGON2 or not stored_hash:
        return False
    try:
        return _ph.check_needs_rehash(stored_hash)
    except Exception:
        return False


def new_service_token() -> str:
    return 'wl_' + secrets.token_urlsafe(32)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def token_matches(raw: str, stored_hash: str) -> bool:
    if not raw or not stored_hash:
        return False
    return hmac.compare_digest(token_hash(raw), stored_hash)