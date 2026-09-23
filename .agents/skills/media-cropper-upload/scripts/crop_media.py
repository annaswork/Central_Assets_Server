#!/usr/bin/env python3
"""
crop_media.py - Production-ready Media Cropper with Transparency Preservation

Capabilities:
1. Static Images (PNG, WebP, JPEG):
   - Strict transparency preservation: Never converts transparent RGBA/LA/P to RGB/JPEG.
   - Saves transparent outputs to PNG or WebP with lossless alpha.
2. Animated GIFs:
   - Preserves multi-frame animation, loop count, frame durations, disposal methods,
     and transparent palette color index.
3. Videos (MP4, WebM, MOV, AVI):
   - Calculates aspect-ratio bounding boxes or custom coordinate crops.
   - Enforces even-dimension alignment (w % 2 == 0, h % 2 == 0) for H.264/H.265.
   - Preserves audio tracks when present, or applies -an when silent.
   - Injects -movflags +faststart for immediate web streaming.
"""

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Dict, Optional, Tuple

from PIL import Image, ImageSequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("media_cropper")


# ==============================================================================
# Helper Functions: Transparency & Dimension Detection
# ==============================================================================

def has_alpha_transparency(img: Image.Image) -> bool:
    """
    Checks if a PIL Image contains transparency (alpha channel or transparent palette).
    """
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        # getextrema returns (min, max) alpha value (0-255)
        extrema = alpha.getextrema()
        return extrema[0] < 255
    elif img.mode == "P":
        return "transparency" in img.info
    return False


def get_video_stream_info(file_path: Path) -> Dict[str, any]:
    """
    Extracts video dimensions, duration, FPS, and audio presence via ffprobe.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=index,codec_name,codec_type,width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found. Please ensure ffmpeg is installed.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed to inspect {file_path}: {e.stderr}")

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    if not video_stream:
        raise ValueError(f"No video streams found in file: {file_path}")

    width = int(video_stream["width"])
    height = int(video_stream["height"])

    fps_parts = video_stream.get("r_frame_rate", "30/1").split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30.0

    return {
        "width": width,
        "height": height,
        "fps": fps,
        "duration": float(data.get("format", {}).get("duration", 0)),
        "codec": video_stream.get("codec_name"),
        "has_audio": has_audio,
    }


def parse_ratio_string(ratio_str: str) -> float:
    """
    Parses an aspect ratio string like '9:16', '16:9', '4:3', '1:1' into a float.
    """
    if ":" in ratio_str:
        w, h = ratio_str.split(":", 1)
        return float(w) / float(h)
    elif "/" in ratio_str:
        w, h = ratio_str.split("/", 1)
        return float(w) / float(h)
    return float(ratio_str)


def compute_crop_coordinates(
    source_w: int,
    source_h: int,
    target_ratio: float,
    position: str = "center",
    enforce_even: bool = False,
) -> Dict[str, int]:
    """
    Calculates crop bounding box (crop_w, crop_h, x, y) to match target_ratio.
    """
    current_ratio = source_w / source_h

    if current_ratio > target_ratio:
        # Wider than target -> crop width
        crop_h = source_h
        crop_w = round(source_h * target_ratio)
    else:
        # Taller than target -> crop height
        crop_w = source_w
        crop_h = round(source_w / target_ratio)

    if enforce_even:
        crop_w -= (crop_w % 2)
        crop_h -= (crop_h % 2)

    x = (source_w - crop_w) // 2
    if position == "top":
        y = 0
    elif position == "bottom":
        y = source_h - crop_h
    else:  # "center"
        y = (source_h - crop_h) // 2

    # Clamp bounds
    x = max(0, min(x, source_w - crop_w))
    y = max(0, min(y, source_h - crop_h))

    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "x": x,
        "y": y,
    }


# ==============================================================================
# Image Cropper (Alpha-Safe)
# ==============================================================================

def crop_image(
    input_path: Path,
    output_path: Path,
    target_ratio: Optional[float] = None,
    custom_crop: Optional[Tuple[int, int, int, int]] = None,
    position: str = "center",
) -> Path:
    """
    Crops a static image. Strictly preserves transparency:
    If the image has an alpha channel, it will NEVER be converted to RGB/JPEG,
    guaranteeing that the cropped output has no background.
    """
    with Image.open(input_path) as img:
        source_w, source_h = img.size
        has_alpha = has_alpha_transparency(img)

        if custom_crop:
            x, y, w, h = custom_crop
            crop_box = (x, y, x + w, y + h)
        elif target_ratio:
            coords = compute_crop_coordinates(source_w, source_h, target_ratio, position, enforce_even=False)
            crop_box = (coords["x"], coords["y"], coords["x"] + coords["crop_w"], coords["y"] + coords["crop_h"])
        else:
            raise ValueError("Either target_ratio or custom_crop must be provided")

        cropped = img.crop(crop_box)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if has_alpha or img.mode in ("RGBA", "LA"):
            logger.info("Alpha transparency detected; preserving transparency in output.")
            if cropped.mode != "RGBA":
                cropped = cropped.convert("RGBA")

            # Output must support alpha
            ext = output_path.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                output_path = output_path.with_suffix(".png")
                logger.warning("Target extension was JPEG but alpha was detected. Changed target to .png.")

            if output_path.suffix.lower() == ".webp":
                cropped.save(output_path, format="WEBP", lossless=True)
            else:
                cropped.save(output_path, format="PNG", optimize=True)
        else:
            # Safe to export as RGB/JPEG if source was opaque
            if cropped.mode in ("RGBA", "P"):
                cropped = cropped.convert("RGB")
            cropped.save(output_path, quality=95)

    logger.info(f"✓ Successfully cropped image to: {output_path}")
    return output_path


# ==============================================================================
# Animated GIF Cropper (Preserving Transparency & Multi-Frame Animation)
# ==============================================================================

def crop_animated_gif(
    input_path: Path,
    output_path: Path,
    target_ratio: Optional[float] = None,
    custom_crop: Optional[Tuple[int, int, int, int]] = None,
    position: str = "center",
) -> Path:
    """
    Crops an animated GIF while preserving frame sequence, durations, loop counts,
    and transparent backgrounds.
    """
    with Image.open(input_path) as im:
        source_w, source_h = im.size
        loop = im.info.get("loop", 0)

        if custom_crop:
            x, y, w, h = custom_crop
            crop_box = (x, y, x + w, y + h)
        elif target_ratio:
            coords = compute_crop_coordinates(source_w, source_h, target_ratio, position, enforce_even=False)
            crop_box = (coords["x"], coords["y"], coords["x"] + coords["crop_w"], coords["y"] + coords["crop_h"])
        else:
            raise ValueError("Either target_ratio or custom_crop must be provided")

        frames = []
        durations = []
        disposals = []

        for frame in ImageSequence.Iterator(im):
            # Convert frame to RGBA to preserve transparency mask during crop
            f_rgba = frame.convert("RGBA")
            cropped_frame = f_rgba.crop(crop_box)
            frames.append(cropped_frame)
            durations.append(frame.info.get("duration", 100))
            # disposal=2 restores background, essential for clean transparency between frames
            disposals.append(frame.info.get("disposal", 2))

        output_path.parent.mkdir(parents=True, exist_ok=True)

        save_kwargs = {
            "save_all": True,
            "append_images": frames[1:],
            "duration": durations,
            "loop": loop,
            "disposal": disposals,
            "optimize": False,
        }

        frames[0].save(output_path, format="GIF", **save_kwargs)

    logger.info(f"✓ Successfully cropped animated GIF to: {output_path}")
    return output_path


# ==============================================================================
# Video Cropper (MP4, WebM, MOV with Codec Alignment)
# ==============================================================================

def crop_video(
    input_path: Path,
    output_path: Path,
    target_ratio: Optional[float] = None,
    custom_crop: Optional[Tuple[int, int, int, int]] = None,
    position: str = "center",
    crf: int = 23,
    preset: str = "medium",
) -> Path:
    """
    Crops a video using FFmpeg.
    - Enforces even dimensions (w%2==0, h%2==0).
    - Preserves audio track if present.
    - Generates faststart MP4 output.
    """
    video_info = get_video_stream_info(input_path)
    source_w = video_info["width"]
    source_h = video_info["height"]

    if custom_crop:
        x, y, w, h = custom_crop
        # Enforce even dimensions
        w -= (w % 2)
        h -= (h % 2)
        x = max(0, min(x, source_w - w))
        y = max(0, min(y, source_h - h))
    elif target_ratio:
        coords = compute_crop_coordinates(source_w, source_h, target_ratio, position, enforce_even=True)
        w, h, x, y = coords["crop_w"], coords["crop_h"], coords["x"], coords["y"]
    else:
        raise ValueError("Either target_ratio or custom_crop must be provided")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_str = f"crop={w}:{h}:{x}:{y}"
    logger.info(f"Cropping video: {source_w}x{source_h} -> {w}x{h} at ({x}, {y}) using filter '{filter_str}'")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
    ]

    if video_info["has_audio"]:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.append("-an")

    if output_path.suffix.lower() == ".mp4":
        cmd.extend(["-movflags", "+faststart"])

    cmd.append(str(output_path))

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e.stderr}")
        raise RuntimeError(f"FFmpeg cropping failed: {e.stderr}")

    logger.info(f"✓ Successfully cropped video to: {output_path}")
    return output_path


# ==============================================================================
# Unified CLI Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Crop images, GIFs, and videos with automatic transparency and codec preservation."
    )
    parser.add_argument("input", type=Path, help="Path to input media file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to output media file")
    parser.add_argument("-r", "--ratio", type=str, help="Target aspect ratio (e.g. '9:16', '1:1', '4:3', '16:9')")
    parser.add_argument("-c", "--crop", type=str, help="Custom crop rect 'x,y,width,height' (e.g. '50,100,400,600')")
    parser.add_argument("-p", "--position", type=str, default="center", choices=["center", "top", "bottom"],
                        help="Crop alignment when ratio is used (default: center)")

    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    target_ratio = parse_ratio_string(args.ratio) if args.ratio else None
    custom_crop = tuple(map(int, args.crop.split(","))) if args.crop else None

    if not target_ratio and not custom_crop:
        logger.error("You must specify either --ratio or --crop.")
        sys.exit(1)

    suffix = args.input.suffix.lower()

    try:
        if suffix in (".png", ".webp", ".jpg", ".jpeg", ".bmp", ".tiff"):
            crop_image(args.input, args.output, target_ratio, custom_crop, args.position)
        elif suffix == ".gif":
            crop_animated_gif(args.input, args.output, target_ratio, custom_crop, args.position)
        elif suffix in (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"):
            crop_video(args.input, args.output, target_ratio, custom_crop, args.position)
        else:
            logger.error(f"Unsupported media format: {suffix}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
