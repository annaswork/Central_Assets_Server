"""Frame placeholder detection controller, running contour calculations in a worker thread."""

from pathlib import Path
from typing import Any

import anyio
import httpx

from config.paths import CENTRAL_DATA_DIR
from utils.errors import ValidationError
from utils.frame_detector import detect_frame_placeholders


async def detect_placeholders(
    image_bytes: bytes | None = None,
    image_url: str | None = None,
    image_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run transparent region analysis asynchronously using anyio threadpool."""
    raw_bytes = image_bytes

    if not raw_bytes and image_path:
        p = Path(image_path)
        if p.exists() and p.is_file():
            raw_bytes = p.read_bytes()

    if not raw_bytes and image_url:
        from urllib.parse import unquote

        clean_url = unquote(str(image_url).strip())
        rel_path = None
        if "/static/central_data/" in clean_url:
            rel_path = clean_url.split("/static/central_data/")[-1].split("?")[0].strip("/\\ ")
        elif "central_data/" in clean_url:
            rel_path = clean_url.split("central_data/")[-1].split("?")[0].strip("/\\ ")
        elif "/static/" in clean_url:
            rel_path = clean_url.split("/static/")[-1].split("?")[0].strip("/\\ ")

        if rel_path:
            disk_p = CENTRAL_DATA_DIR / rel_path
            if disk_p.exists() and disk_p.is_file():
                raw_bytes = disk_p.read_bytes()

        if not raw_bytes:
            candidate = CENTRAL_DATA_DIR / clean_url.lstrip("/\\")
            if candidate.exists() and candidate.is_file():
                raw_bytes = candidate.read_bytes()

        if not raw_bytes and Path(clean_url).exists() and Path(clean_url).is_file():
            raw_bytes = Path(clean_url).read_bytes()
        elif not raw_bytes and (clean_url.startswith("http://") or clean_url.startswith("https://")):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(clean_url)
                    if resp.is_success:
                        raw_bytes = resp.content
            except Exception:
                pass

    if not raw_bytes:
        raise ValidationError("No image data provided or unable to locate image file")

    result = await anyio.to_thread.run_sync(detect_frame_placeholders, raw_bytes)
    result["image_url"] = image_url or (str(image_path) if image_path else "")
    return result
