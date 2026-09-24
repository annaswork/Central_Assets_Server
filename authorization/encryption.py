"""Isolated cryptographic primitives for the platform.

Owns all calls to hashlib, hmac, secrets, bcrypt, and itsdangerous.
Nothing outside this module should call cryptographic functions directly.
"""

import hashlib
import hmac
import secrets
import string
from typing import Any

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config.settings import settings

BASE62_ALPHABET = string.ascii_letters + string.digits


def _generate_base62_string(length: int) -> str:
    """Generate cryptographically secure random base62 string."""
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))


def generate_key_pair() -> tuple[str, str, str]:
    """Generate API key components.

    Format: ak_<env>_<22-char id>_<32-char secret>

    Returns:
        tuple of (full_key, key_prefix, secret_hash)
    """
    env_str = settings.ENV.lower()[:4]
    key_id = _generate_base62_string(22)
    secret = _generate_base62_string(32)

    key_prefix = f"ak_{env_str}_{key_id}"
    full_key = f"{key_prefix}_{secret}"
    secret_hash = hash_secret(secret)

    return full_key, key_prefix, secret_hash


def hash_secret(secret: str) -> str:
    """Compute SHA-256 hex digest of secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Verify secret against stored SHA-256 hash using constant-time comparison."""
    computed_hash = hash_secret(secret)
    return hmac.compare_digest(computed_hash, stored_hash)


def hash_password(password: str) -> str:
    """Hash operator password using bcrypt with standard salt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify operator password against stored bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_session_serializer() -> URLSafeTimedSerializer:
    """Return serializer for admin operator session cookies."""
    return URLSafeTimedSerializer(settings.ADMIN_SESSION_SECRET, salt="admin-cookie-session")


def sign_session(payload: dict[str, Any]) -> str:
    """Sign admin session payload into an encrypted/signed token."""
    serializer = get_session_serializer()
    return serializer.dumps(payload)


def read_session(token: str, max_age_seconds: int | None = None) -> dict[str, Any] | None:
    """Read and verify signed session token, returning payload or None if invalid/expired."""
    serializer = get_session_serializer()
    max_age = max_age_seconds or settings.ADMIN_SESSION_MAX_AGE_SECONDS
    try:
        return serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def get_fernet_cipher():
    """Return Fernet AES-128-CBC cipher derived deterministically from ADMIN_SESSION_SECRET."""
    import base64
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.ADMIN_SESSION_SECRET.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_password(password: str) -> str:
    """Symmetrically encrypt manager password for authorized admin 2FA recovery."""
    cipher = get_fernet_cipher()
    return cipher.encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    """Decrypt encrypted password with master cipher."""
    cipher = get_fernet_cipher()
    return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
