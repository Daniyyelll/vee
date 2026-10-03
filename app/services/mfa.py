"""TOTP helpers for privileged accounts.

Secrets are encrypted at rest. A successfully used time-step is persisted so the
same code cannot be replayed during its 30-second validity window.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6


def _fernet() -> Fernet:
    source = settings.mfa_encryption_key or settings.secret_jwt_key
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode()).digest())
    return Fernet(key)


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def decrypt_secret(sealed: bytes) -> str | None:
    try:
        return _fernet().decrypt(sealed).decode()
    except (InvalidToken, ValueError):
        return None


def provisioning_uri(secret: str, email: str) -> str:
    label = quote(f"{settings.project_name}:{email}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": settings.project_name,
            "algorithm": "SHA1",
            "digits": TOTP_DIGITS,
            "period": TOTP_PERIOD_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def _code(secret: str, counter: int) -> str:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_code(
    secret: str,
    supplied_code: str,
    *,
    last_counter: int | None = None,
    now: int | None = None,
) -> int | None:
    if not supplied_code.isdigit() or len(supplied_code) != TOTP_DIGITS:
        return None
    current = (now if now is not None else int(time.time())) // TOTP_PERIOD_SECONDS
    for counter in range(current - 1, current + 2):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(_code(secret, counter), supplied_code):
            return counter
    return None
