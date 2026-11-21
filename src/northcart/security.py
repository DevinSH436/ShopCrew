"""Password hashing (stdlib scrypt) and CSRF tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    """Hash ``password`` with a random salt. Format: ``scrypt$<salt>$<hash>``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a ``hash_password`` result."""
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(actual, expected)


def new_token() -> str:
    """Random URL-safe token (CSRF tokens, guest cart keys)."""
    return secrets.token_urlsafe(24)


def tokens_match(a: str | None, b: str | None) -> bool:
    """Constant-time comparison that treats missing values as a mismatch."""
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))
