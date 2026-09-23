"""TOTP (Time-based One-Time Password) utilities for Google Authenticator 2FA."""

import base64
import hashlib
import io
import secrets
from typing import Any

import pyotp
import qrcode
from qrcode.image.pil import PilImage

from config.settings import settings


def generate_totp_secret() -> str:
    """Generate a random base32 TOTP secret key."""
    return pyotp.random_base32()


def generate_provisioning_uri(username: str, secret: str, issuer_name: str | None = None) -> str:
    """Generate standard otpauth:// provisioning URI for authenticator apps."""
    issuer = issuer_name or settings.app_name
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def generate_qr_code_base64(provisioning_uri: str) -> str:
    """Render a provisioning URI into a base64-encoded PNG data URL."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=7,
        border=2,
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img: PilImage = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_bytes = buffered.getvalue()
    encoded = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def verify_totp_code(secret: str, code: str, valid_window: int = 1) -> bool:
    """Verify a 6-digit TOTP code against a base32 secret with drift tolerance."""
    if not secret or not code:
        return False
    clean_code = str(code).strip().replace(" ", "").replace("-", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False

    totp = pyotp.TOTP(secret)
    return bool(totp.verify(clean_code, valid_window=valid_window))


def _hash_code(code: str) -> str:
    """Generate SHA-256 digest of normalized backup code."""
    normalized = str(code).strip().upper().replace(" ", "").replace("-", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generate a list of random formatted backup recovery codes (e.g. 'A1B2-C3D4')."""
    codes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()
        formatted = f"{raw[:4]}-{raw[4:]}"
        codes.append(formatted)
    return codes


def hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash a list of cleartext backup codes for secure database storage."""
    return [_hash_code(c) for c in codes]


def verify_and_consume_backup_code(
    stored_hashed_codes: list[str], submitted_code: str
) -> tuple[bool, list[str]]:
    """Check if submitted code matches any stored backup code.
    
    If found, returns (True, updated_list_without_used_code).
    Otherwise returns (False, stored_hashed_codes).
    """
    if not stored_hashed_codes or not submitted_code:
        return False, stored_hashed_codes

    target_hash = _hash_code(submitted_code)
    for idx, h in enumerate(stored_hashed_codes):
        if secrets.compare_digest(h, target_hash):
            remaining = stored_hashed_codes[:idx] + stored_hashed_codes[idx + 1 :]
            return True, remaining

    return False, stored_hashed_codes
