"""
Media Cropping and Cutting Controller.

Implements alpha-safe image cropping, multi-frame GIF cropping,
video cropping with even-dimension alignment and faststart streaming,
and accurate audio segment cutting.

Rules from .agents/skills/media-cropper-upload:
- Zero background loss guarantee: Never converts transparent RGBA/LA/P images to JPEG.
- Animated GIFs: Preserves transparency, disposal=2, frame durations, and loop count.
- Lottie animations: Vector animations; explicitly separated from raster crops.
- Videos: Enforces w%2==0 and h%2==0, preserves audio streams, applies faststart.
- Audio: Trims start_time to end_time with proper codec retention.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Tuple

from PIL import Image, ImageSequence

logger = logging.getLogger("crop_controller")


def get_ffmpeg_executable() -> str:
    """Resolve available ffmpeg binary, checking system PATH or imageio_ffmpeg."""
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


def get_ffprobe_executable() -> str | None:
    """Resolve available ffprobe binary if present."""
    sys_ffprobe = shutil.which("ffprobe")
    if sys_ffprobe:
        return sys_ffprobe
    return None


def has_alpha_transparency(img: Image.Image) -> bool:
    """Check if a PIL Image contains transparency (alpha channel or transparent palette)."""
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        extrema = alpha.getextrema()
        return extrema[0] < 255
    elif img.mode == "P":
        return "transparency" in img.info
    return False


def compute_crop_box(
    source_w: int,
    source_h: int,
    target_ratio: float | None = None,
    custom_box: Tuple[int, int, int, int] | None = None,
    enforce_even: bool = False,
) -> Tuple[int, int, int, int]:
    """
    Computes (x, y, w, h) bounding box.
    If target_ratio is specified and no custom_box, computes centered crop.
    """
    if custom_box:
        x, y, w, h = custom_box
        # Clamp to bounds
        x = max(0, min(x, source_w - 1))
        y = max(0, min(y, source_h - 1))
        w = max(1, min(w, source_w - x))
        h = max(1, min(h, source_h - y))
    elif target_ratio:
        current_ratio = source_w / source_h
        if current_ratio > target_ratio:
            crop_h = source_h
            crop_w = round(source_h * target_ratio)
        else:
            crop_w = source_w
            crop_h = round(source_w / target_ratio)
        crop_w = max(1, min(crop_w, source_w))
        crop_h = max(1, min(crop_h, source_h))
        x = (source_w - crop_w) // 2
        y = (source_h - crop_h) // 2
        w, h = crop_w, crop_h
    else:
        x, y, w, h = 0, 0, source_w, source_h

    if enforce_even:
        w -= w % 2
        h -= h % 2
        w = max(2, w)
        h = max(2, h)

    return (x, y, w, h)


def crop_image_bytes(
    image_bytes: bytes,
    filename: str,
    crop_box: Tuple[int, int, int, int] | None = None,
    target_ratio: float | None = None,
) -> Tuple[bytes, str, str, int, int]:
    """
    Crops a static image strictly preserving transparency.
    Returns: (output_bytes, output_filename, mime_type, width, height)
    """
    with Image.open(BytesIO(image_bytes)) as img:
        source_w, source_h = img.size
        has_alpha = has_alpha_transparency(img)

        x, y, w, h = compute_crop_box(
            source_w, source_h, target_ratio, crop_box, enforce_even=False
        )
        crop_rect = (x, y, x + w, y + h)
        cropped = img.crop(crop_rect)

        stem = Path(filename).stem
        ext = Path(filename).suffix.lower()

        out_buf = BytesIO()

        if has_alpha or img.mode in ("RGBA", "LA") or ext in (".png", ".webp", ".svg"):
            # Enforce RGBA mode to retain 100% transparency
            if cropped.mode != "RGBA":
                cropped = cropped.convert("RGBA")

            # Never export transparent image to JPEG
            if ext in (".jpg", ".jpeg", ""):
                ext = ".png"

            if ext == ".webp":
                cropped.save(out_buf, format="WEBP", lossless=True)
                mime = "image/webp"
            else:
                cropped.save(out_buf, format="PNG", optimize=True)
                mime = "image/png"
                ext = ".png"
        else:
            # Safe opaque image export
            if ext in (".jpg", ".jpeg"):
                if cropped.mode in ("RGBA", "P"):
                    cropped = cropped.convert("RGB")
                cropped.save(out_buf, format="JPEG", quality=95)
                mime = "image/jpeg"
            elif ext == ".webp":
                cropped.save(out_buf, format="WEBP", quality=95)
                mime = "image/webp"
            else:
                cropped.save(out_buf, format="PNG", optimize=True)
                mime = "image/png"

        out_bytes = out_buf.getvalue()
        final_filename = f"{stem}_cropped{ext}"
        return out_bytes, final_filename, mime, w, h


def clean_frame_dither(frame: Image.Image) -> Image.Image:
    """
    Suppresses GIF dithering noise and near-black artifacts.
    Preserves palette mode for 'P' images and zeros out near-black colors (<= 15).
    For RGBA/RGB, quantizes with FASTOCTREE and dither=NONE.
    """
    if frame.mode == "P":
        palette = frame.getpalette()
        if palette:
            new_palette = []
            for i in range(0, len(palette), 3):
                r, g, b = palette[i : i + 3]
                if r <= 15 and g <= 15 and b <= 15:
                    new_palette.extend([0, 0, 0])
                else:
                    new_palette.extend([r, g, b])
            frame.putpalette(new_palette)
        return frame
    elif frame.mode in ("RGBA", "RGB"):
        return frame.quantize(
            colors=256,
            method=Image.Quantize.FASTOCTREE,
            dither=Image.Dither.NONE,
        )
    return frame


def crop_gif_bytes(
    gif_bytes: bytes,
    filename: str,
    crop_box: Tuple[int, int, int, int] | None = None,
    target_ratio: float | None = None,
) -> Tuple[bytes, str, str, int, int]:
    """
    Crops an animated GIF while strictly preserving multi-frame animation,
    transparent backgrounds (disposal=2), loop count, frame durations, and
    suppressing dither noise according to media-cropper-upload skill.
    Note: Lottie JSON animations are vector formats and are not processed here.
    """
    with Image.open(BytesIO(gif_bytes)) as im:
        source_w, source_h = im.size
        loop = im.info.get("loop", 0)

        x, y, w, h = compute_crop_box(
            source_w, source_h, target_ratio, crop_box, enforce_even=False
        )
        crop_rect = (x, y, x + w, y + h)

        frames = []
        durations = []
        disposals = []

        for frame in ImageSequence.Iterator(im):
            f_copy = frame.copy()
            cropped_frame = f_copy.crop(crop_rect)
            cleaned_frame = clean_frame_dither(cropped_frame)
            frames.append(cleaned_frame)
            durations.append(frame.info.get("duration", 100))
            # disposal=2 restores background, preventing ghosting on transparent GIFs
            disposals.append(frame.info.get("disposal", 2))

        out_buf = BytesIO()
        if frames:
            save_kwargs = {
                "save_all": True,
                "append_images": frames[1:],
                "duration": durations,
                "loop": loop,
                "disposal": disposals,
                "optimize": False,
                "dither": Image.Dither.NONE,
            }
            frames[0].save(out_buf, format="GIF", **save_kwargs)
        else:
            out_buf.write(gif_bytes)

        out_bytes = out_buf.getvalue()
        stem = Path(filename).stem
        final_filename = f"{stem}_cropped.gif"
        return out_bytes, final_filename, "image/gif", w, h


def get_video_dimensions_fallback(file_path: Path) -> Tuple[int, int, float, bool]:
    """
    Extracts width, height, duration, and audio presence using OpenCV or ffprobe.
    """
    ffprobe = get_ffprobe_executable()
    if ffprobe:
        try:
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,width,height",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(file_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            duration = float(data.get("format", {}).get("duration", 0.0))
            if v_stream:
                return int(v_stream["width"]), int(v_stream["height"]), duration, has_audio
        except Exception as e:
            logger.debug(f"ffprobe fallback failed: {e}")

    # Fallback to OpenCV
    try:
        import cv2

        cap = cv2.VideoCapture(str(file_path))
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            duration = (count / fps) if fps > 0 else 0.0
            cap.release()
            return w, h, duration, True
    except Exception as e:
        logger.debug(f"OpenCV video probe failed: {e}")

    return 1920, 1080, 0.0, True


def crop_video_bytes(
    video_bytes: bytes,
    filename: str,
    crop_box: Tuple[int, int, int, int] | None = None,
    target_ratio: float | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> Tuple[bytes, str, str, int, int, float]:
    """
    Crops video spatially (aspect ratio or bounding box) and/or temporally (cutting start/end).
    Enforces even-dimension alignment (w%2==0, h%2==0) and web faststart streaming.
    """
    ffmpeg_cmd = get_ffmpeg_executable()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        in_file = tmp_path / f"input_{filename}"
        in_file.write_bytes(video_bytes)

        source_w, source_h, total_duration, has_audio = get_video_dimensions_fallback(in_file)

        x, y, w, h = compute_crop_box(source_w, source_h, target_ratio, crop_box, enforce_even=True)

        ext = Path(filename).suffix.lower()
        if ext not in (".mp4", ".webm", ".mov", ".m4v"):
            ext = ".mp4"
        out_file = tmp_path / f"output{ext}"

        cmd = [ffmpeg_cmd, "-y"]

        # Temporal cutting if requested
        if start_time is not None and start_time > 0:
            cmd.extend(["-ss", f"{start_time:.3f}"])
        if end_time is not None and end_time > (start_time or 0):
            duration = end_time - (start_time or 0)
            cmd.extend(["-t", f"{duration:.3f}"])

        cmd.extend(["-i", str(in_file)])

        # Spatial cropping filter
        filter_str = f"crop={w}:{h}:{x}:{y}"
        cmd.extend(
            [
                "-vf",
                filter_str,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
            ]
        )

        if has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.append("-an")

        if ext == ".mp4":
            cmd.extend(["-movflags", "+faststart"])

        cmd.append(str(out_file))

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg video crop failed: {res.stderr}")
            raise RuntimeError(
                f"Video crop failed: {res.stderr[-300:] if res.stderr else 'unknown error'}"
            )

        out_bytes = out_file.read_bytes()
        stem = Path(filename).stem
        final_filename = f"{stem}_cropped{ext}"
        mime = (
            "video/mp4"
            if ext == ".mp4"
            else ("video/webm" if ext == ".webm" else "video/quicktime")
        )
        effective_duration = (
            (end_time - (start_time or 0))
            if (end_time and end_time > (start_time or 0))
            else total_duration
        )

        return out_bytes, final_filename, mime, w, h, effective_duration


def cut_audio_bytes(
    audio_bytes: bytes,
    filename: str,
    start_time: float,
    end_time: float,
) -> Tuple[bytes, str, str, float]:
    """
    Cuts an audio file to the [start_time, end_time] interval.
    Uses ffmpeg with codec-specific parameters for MP3, WAV, AAC, M4A, OGG.
    """
    if end_time <= start_time:
        raise ValueError("Audio cut end_time must be strictly greater than start_time.")

    duration = end_time - start_time
    ffmpeg_cmd = get_ffmpeg_executable()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        in_file = tmp_path / f"input_{filename}"
        in_file.write_bytes(audio_bytes)

        ext = Path(filename).suffix.lower()
        if not ext:
            ext = ".mp3"
        out_file = tmp_path / f"output{ext}"

        cmd = [
            ffmpeg_cmd,
            "-y",
            "-ss",
            f"{start_time:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(in_file),
        ]

        if ext == ".mp3":
            cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
            mime = "audio/mpeg"
        elif ext in (".m4a", ".aac"):
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            mime = "audio/mp4" if ext == ".m4a" else "audio/aac"
        elif ext == ".ogg":
            cmd.extend(["-c:a", "libvorbis", "-q:a", "4"])
            mime = "audio/ogg"
        elif ext == ".wav":
            cmd.extend(["-c:a", "pcm_s16le"])
            mime = "audio/wav"
        else:
            cmd.extend(["-c", "copy"])
            mime = "audio/mpeg"

        cmd.append(str(out_file))

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg audio cut failed: {res.stderr}")
            # Try fallback with copy
            cmd_fallback = [
                ffmpeg_cmd,
                "-y",
                "-ss",
                f"{start_time:.3f}",
                "-t",
                f"{duration:.3f}",
                "-i",
                str(in_file),
                "-c",
                "copy",
                str(out_file),
            ]
            res_fb = subprocess.run(cmd_fallback, capture_output=True, text=True)
            if res_fb.returncode != 0:
                raise RuntimeError(
                    f"Audio cutting failed: {res.stderr[-300:] if res.stderr else 'unknown error'}"
                )

        out_bytes = out_file.read_bytes()
        stem = Path(filename).stem
        final_filename = f"{stem}_cut{ext}"
        return out_bytes, final_filename, mime, duration


def process_media_crop(
    file_bytes: bytes,
    filename: str,
    crop_type: str | None = None,
    crop_box: Tuple[int, int, int, int] | None = None,
    target_ratio: float | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict[str, Any]:
    """
    Unified entrypoint for cropping or cutting media.
    Detects media format and delegates to image, gif, video, or audio handlers.
    """
    ext = Path(filename).suffix.lower()

    # Determine type if not explicitly supplied
    c_type = (crop_type or "").lower()
    if not c_type:
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".tiff"):
            c_type = "image"
        elif ext == ".gif":
            c_type = "gif"
        elif ext in (".mp4", ".webm", ".mov", ".m4v", ".avi"):
            c_type = "video"
        elif ext in (".mp3", ".wav", ".ogg", ".aac", ".m4a", ".flac"):
            c_type = "audio"
        else:
            c_type = "image"

    if c_type == "audio":
        s_time = float(start_time) if start_time is not None else 0.0
        e_time = float(end_time) if end_time is not None else 10.0
        out_bytes, out_name, mime, duration = cut_audio_bytes(file_bytes, filename, s_time, e_time)
        return {
            "bytes": out_bytes,
            "filename": out_name,
            "mime": mime,
            "duration": duration,
            "duration_ms": int(duration * 1000),
            "size_bytes": len(out_bytes),
        }
    elif c_type == "gif":
        out_bytes, out_name, mime, w, h = crop_gif_bytes(
            file_bytes, filename, crop_box, target_ratio
        )
        return {
            "bytes": out_bytes,
            "filename": out_name,
            "mime": mime,
            "width": w,
            "height": h,
            "dimensions": f"{w}x{h}",
            "size_bytes": len(out_bytes),
        }
    elif c_type == "video":
        out_bytes, out_name, mime, w, h, duration = crop_video_bytes(
            file_bytes, filename, crop_box, target_ratio, start_time, end_time
        )
        return {
            "bytes": out_bytes,
            "filename": out_name,
            "mime": mime,
            "width": w,
            "height": h,
            "dimensions": f"{w}x{h}",
            "duration": duration,
            "duration_ms": int(duration * 1000) if duration else None,
            "size_bytes": len(out_bytes),
        }
    else:  # "image"
        out_bytes, out_name, mime, w, h = crop_image_bytes(
            file_bytes, filename, crop_box, target_ratio
        )
        return {
            "bytes": out_bytes,
            "filename": out_name,
            "mime": mime,
            "width": w,
            "height": h,
            "dimensions": f"{w}x{h}",
            "size_bytes": len(out_bytes),
        }
