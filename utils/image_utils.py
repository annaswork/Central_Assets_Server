"""Image utilities for dimensions extraction, alpha analysis, and WebP thumbnail generation."""

import io

from PIL import Image


def get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Extract width and height from image bytes without loading entire image into memory."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.width, img.height


def generate_thumbnail(
    image_bytes: bytes,
    max_size: tuple[int, int] = (320, 320),
    quality: int = 85,
) -> bytes:
    """Generate a high-quality WebP thumbnail preserving aspect ratio."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        # Convert RGBA or paletted images properly
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            converted = img.convert("RGBA")
        else:
            converted = img.convert("RGB")

        converted.thumbnail(max_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        converted.save(buffer, format="WEBP", quality=quality, method=6)
        return buffer.getvalue()


def has_alpha_channel(image_bytes: bytes) -> bool:
    """Determine if an image contains an alpha channel for transparency."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def generate_scaled_thumbnail(
    image_bytes: bytes,
    scale_factor: float = 1 / 3,
    output_format: str = "WEBP",
    quality: int = 85,
) -> tuple[bytes, str]:
    """Generate a thumbnail scaled down by scale_factor (e.g. 1/3rd of original width and height).

    Returns a tuple of (thumbnail_bytes, extension).
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        orig_w, orig_h = img.width, img.height
        new_w = max(1, round(orig_w * scale_factor))
        new_h = max(1, round(orig_h * scale_factor))

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            converted = img.convert("RGBA")
        else:
            converted = img.convert("RGB")

        resized = converted.resize((new_w, new_h), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        fmt = output_format.upper()
        if fmt not in ("WEBP", "PNG", "JPEG"):
            fmt = "WEBP"
        if fmt == "JPEG" and resized.mode == "RGBA":
            resized = resized.convert("RGB")

        save_kwargs = {"quality": quality}
        if fmt == "WEBP":
            save_kwargs["method"] = 6

        resized.save(buffer, format=fmt, **save_kwargs)
        ext = "webp" if fmt == "WEBP" else fmt.lower()
        return buffer.getvalue(), ext


def get_ffmpeg_executable() -> str:
    """Resolve available ffmpeg binary, checking system PATH or imageio_ffmpeg."""
    import os
    import shutil

    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return "ffmpeg"


def extract_first_frame_thumbnail(
    file_bytes: bytes,
    filename: str = "media",
    max_size: tuple[int, int] = (480, 480),
) -> tuple[bytes, str]:
    """Extract frame 0 / 1st frame thumbnail as .webp preserving alpha channel transparency.

    Supports videos (MP4, WebM, MOV), animated GIFs, Animated WebP, Lottie JSON, APNG, and static images.
    Always returns (thumbnail_bytes, "webp").
    """
    import os
    import shutil
    import subprocess
    import tempfile
    import json
    import base64
    from pathlib import Path

    ext_lower = Path(filename).suffix.lower().lstrip(".")
    is_video = ext_lower in ("mp4", "webm", "mov", "avi", "mkv")
    is_lottie = ext_lower in ("json", "lottie") or (file_bytes.strip().startswith(b"{") and b'"v"' in file_bytes[:300])

    # 1. Lottie JSON animation frame 0 extraction
    if is_lottie:
        try:
            lottie_data = json.loads(file_bytes.decode("utf-8", errors="ignore"))
            assets = lottie_data.get("assets", [])
            for asset in assets:
                p = asset.get("p", "")
                if p and "data:image" in p:
                    b64_str = p.split(",", 1)[-1]
                    raw_img = base64.b64decode(b64_str)
                    with Image.open(io.BytesIO(raw_img)) as img:
                        img.seek(0)
                        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
                        converted = img.convert("RGBA") if has_alpha else img.convert("RGB")
                        converted.thumbnail(max_size, Image.Resampling.LANCZOS)
                        buf = io.BytesIO()
                        converted.save(buf, format="WEBP", quality=90, method=6)
                        return buf.getvalue(), "webp"
        except Exception:
            pass

    # 2. Video 1st frame extraction via FFmpeg
    if is_video:
        sys_ffmpeg = get_ffmpeg_executable()
        with tempfile.NamedTemporaryFile(suffix=f".{ext_lower}", delete=False) as tmp_in:
            tmp_in.write(file_bytes)
            tmp_in_path = tmp_in.name
        tmp_out_path = tmp_in_path + "_frame0.png"
        try:
            cmd = [
                sys_ffmpeg, "-y", "-ss", "00:00:00", "-i", tmp_in_path,
                "-vframes", "1", "-f", "image2", "-vcodec", "png", tmp_out_path
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            if os.path.exists(tmp_out_path):
                out_bytes = Path(tmp_out_path).read_bytes()
                with Image.open(io.BytesIO(out_bytes)) as img:
                    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
                    converted = img.convert("RGBA") if has_alpha else img.convert("RGB")
                    converted.thumbnail(max_size, Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    converted.save(buf, format="WEBP", quality=90, method=6)
                    return buf.getvalue(), "webp"
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_in_path):
                try:
                    os.unlink(tmp_in_path)
                except Exception:
                    pass
            if os.path.exists(tmp_out_path):
                try:
                    os.unlink(tmp_out_path)
                except Exception:
                    pass

    # 3. Static images, animated GIFs, APNG, WebP
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img.seek(0)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            converted = img.convert("RGBA") if has_alpha else img.convert("RGB")
            converted.thumbnail(max_size, Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            converted.save(buf, format="WEBP", quality=90, method=6)
            return buf.getvalue(), "webp"
    except Exception:
        return generate_scaled_thumbnail(file_bytes, scale_factor=1 / 3, output_format="WEBP")


