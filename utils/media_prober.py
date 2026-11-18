"""Media metadata probing utilities for images, audio, and video files.

Extracts duration, filesize, and dimensions (width x height) from file bytes
and merges client-probed metadata when hardware decoding is available in the browser.
Audio files never have dimensions.
"""

import io
import os
import tempfile
import wave
from typing import Any

from PIL import Image

try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None


def probe_image_metadata(file_bytes: bytes) -> dict[str, Any]:
    """Extract width, height, and dimensions string for an image."""
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            w, h = img.width, img.height
            return {
                "width": int(w),
                "height": int(h),
                "dimensions": f"{int(w)}x{int(h)}",
            }
    except Exception:
        return {}


def probe_video_metadata(file_bytes: bytes, filename: str = "") -> dict[str, Any]:
    """Extract dimensions and duration for a video using OpenCV VideoCapture."""
    if not cv2:
        return {}

    suffix = ""
    if filename and "." in filename:
        suffix = f".{filename.split('.')[-1].lower()}"
    if not suffix:
        suffix = ".mp4"

    meta: dict[str, Any] = {}
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()

            if w > 0 and h > 0:
                meta["width"] = w
                meta["height"] = h
                meta["dimensions"] = f"{w}x{h}"

            if fps > 0 and count > 0:
                duration_sec = count / fps
                duration_ms = int(duration_sec * 1000)
                meta["duration_ms"] = duration_ms
                meta["duration"] = round(duration_sec, 3)
    except Exception:
        pass
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return meta


def probe_audio_metadata(file_bytes: bytes, filename: str = "") -> dict[str, Any]:
    """Extract duration for audio. Strictly omits width, height, and dimensions."""
    meta: dict[str, Any] = {}
    # 1. Try standard library wave module for WAV files
    try:
        with wave.open(io.BytesIO(file_bytes), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate > 0:
                duration_sec = frames / float(rate)
                duration_ms = int(duration_sec * 1000)
                meta["duration_ms"] = duration_ms
                meta["duration"] = round(duration_sec, 3)
                return meta
    except Exception:
        pass

    return meta


def probe_file_metadata(
    file_bytes: bytes,
    filename: str,
    mime_type: str | None = None,
    client_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract full media metadata combining server decoders and client-passed hints.

    Audio files will never have dimensions (width, height, dimensions).
    """
    hints = client_hints or {}
    filesize = len(file_bytes)
    result: dict[str, Any] = {
        "filesize": filesize,
        "size_bytes": filesize,
    }

    mime = (mime_type or "").lower()
    ext = os.path.splitext(filename)[1].lower().lstrip(".")

    is_audio = mime.startswith("audio/") or ext in ("mp3", "wav", "ogg", "m4a", "aac", "flac")
    is_video = mime.startswith("video/") or ext in ("mp4", "webm", "mov", "avi", "mkv")
    is_image = mime.startswith("image/") or ext in ("png", "jpg", "jpeg", "webp", "gif", "svg")

    if is_audio:
        # Audio metadata: duration only, never dimensions
        audio_meta = probe_audio_metadata(file_bytes, filename)
        duration_ms = audio_meta.get("duration_ms")
        duration = audio_meta.get("duration")

        if duration_ms is None and hints.get("duration_ms") is not None:
            try:
                duration_ms = int(hints["duration_ms"])
            except (ValueError, TypeError):
                pass
        if duration is None and hints.get("duration") is not None:
            try:
                duration = float(hints["duration"])
            except (ValueError, TypeError):
                pass

        if duration_ms is not None and duration is None:
            duration = round(duration_ms / 1000.0, 3)
        elif duration is not None and duration_ms is None:
            duration_ms = int(duration * 1000)

        if duration_ms is not None:
            result["duration_ms"] = duration_ms
        if duration is not None:
            result["duration"] = duration

    elif is_video:
        # Video metadata: width, height, dimensions, duration
        vid_meta = probe_video_metadata(file_bytes, filename)
        w = vid_meta.get("width") or hints.get("width")
        h = vid_meta.get("height") or hints.get("height")
        if w is not None and h is not None:
            try:
                w_int = int(w)
                h_int = int(h)
                result["width"] = w_int
                result["height"] = h_int
                result["dimensions"] = f"{w_int}x{h_int}"
            except (ValueError, TypeError):
                pass

        duration_ms = vid_meta.get("duration_ms") or hints.get("duration_ms")
        duration = vid_meta.get("duration") or hints.get("duration")
        if duration_ms is not None and duration is None:
            try:
                duration = round(int(duration_ms) / 1000.0, 3)
            except (ValueError, TypeError):
                pass
        elif duration is not None and duration_ms is None:
            try:
                duration_ms = int(float(duration) * 1000)
            except (ValueError, TypeError):
                pass

        if duration_ms is not None:
            try:
                result["duration_ms"] = int(duration_ms)
            except (ValueError, TypeError):
                pass
        if duration is not None:
            try:
                result["duration"] = float(duration)
            except (ValueError, TypeError):
                pass

    elif is_image:
        # Image metadata: width, height, dimensions
        img_meta = probe_image_metadata(file_bytes)
        w = img_meta.get("width") or hints.get("width")
        h = img_meta.get("height") or hints.get("height")
        if w is not None and h is not None:
            try:
                w_int = int(w)
                h_int = int(h)
                result["width"] = w_int
                result["height"] = h_int
                result["dimensions"] = f"{w_int}x{h_int}"
            except (ValueError, TypeError):
                pass

    return result
