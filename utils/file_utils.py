"""File utilities for magic-byte sniffing, content hashing, and path sanitization."""

import hashlib
import json
import re
from pathlib import Path


def compute_sha256(content: bytes) -> str:
    """Compute SHA-256 hex digest of file contents for deduplication."""
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(filename: str) -> str:
    """Strip dangerous characters and ensure safe alphanumeric filename."""
    name = Path(filename).name
    # Keep only alphanumeric, dots, underscores, and dashes
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return sanitized.strip("._") or "file"


def sniff_mime_type(content: bytes, filename: str = "") -> str:
    """Sniff MIME type from initial magic bytes, falling back to extension."""
    if len(content) >= 8:
        # PNG: \x89PNG\r\n\x1a\n
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        # JPEG: \xff\xd8\xff
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        # GIF: GIF87a or GIF89a
        if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
            return "image/gif"
        # WEBP: RIFF....WEBP
        if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
            return "image/webp"
        # MP3: ID3 or sync frame 0xFF\xFB / 0xFF\xF3 / 0xFF\xF2
        if content.startswith(b"ID3") or (content[0] == 0xFF and (content[1] & 0xE0) == 0xE0):
            return "audio/mpeg"
        # WAV: RIFF....WAVE
        if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WAVE":
            return "audio/wav"
        # OGG: OggS
        if content.startswith(b"OggS"):
            return "audio/ogg"
        # MP4 / MOV: ....ftyp
        if len(content) >= 12 and content[4:8] == b"ftyp":
            brand = content[8:12]
            if brand in (b"qt  ", b"moov"):
                return "video/quicktime"
            return "video/mp4"
        # WebM / Matroska: \x1a\x45\xdf\xa3
        if content.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"

    # Attempt JSON parsing
    try:
        decoded = content.decode("utf-8")
        json.loads(decoded)
        return "application/json"
    except Exception:
        pass

    # Fallback to extension matching
    ext = Path(filename).suffix.lower().lstrip(".")
    extension_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "aac": "audio/aac",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "json": "application/json",
    }
    return extension_map.get(ext, "application/octet-stream")
