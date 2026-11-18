"""Frame placeholder detection using alpha-channel contour analysis.

Locates transparent cutout slots in frame images, generating proposed rotated bounding boxes.
This module is CPU-bound and synchronous; callers in async controllers should wrap it with
anyio.to_thread.run_sync.
"""

import io
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def detect_frame_placeholders(
    image_bytes: bytes,
    alpha_threshold: int = 64,
    min_area_fraction: float = 0.002,  # Ignore regions smaller than 0.2% of image area
) -> dict[str, Any]:
    """Detect transparent placeholder slots in a frame image.

    Returns:
        dict with keys:
            - 'width': int (source image width)
            - 'height': int (source image height)
            - 'placeholders': list[dict] with x, y, width, height, rotation, elevation, index
    """
    with Image.open(io.BytesIO(image_bytes)) as pil_img:
        img_width, img_height = pil_img.width, pil_img.height
        total_area = img_width * img_height

        # Check if the image has transparency
        if pil_img.mode not in ("RGBA", "LA") and not (
            pil_img.mode == "P" and "transparency" in pil_img.info
        ):
            return {
                "width": img_width,
                "height": img_height,
                "placeholders": [],
            }

        rgba = pil_img.convert("RGBA")
        np_img = np.array(rgba)
        alpha_channel = np_img[:, :, 3]

    # Binary mask: 255 where transparent (placeholder), 0 where opaque (frame graphics)
    mask = (alpha_channel <= alpha_threshold).astype(np.uint8) * 255

    # Apply morphological opening to eliminate single-pixel noise and artifacts
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # Find contours of transparent cutout regions
    contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = total_area * min_area_fraction
    raw_placeholders: list[dict[str, Any]] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue

        rect = cv2.minAreaRect(contour)
        (cx, cy), (box_w, box_h), angle = rect

        # Check if the cutout is axis-aligned (rectangle/square)
        bx, by, bw, bh = cv2.boundingRect(contour)
        bounding_area = float(bw * bh)
        if bounding_area > 0 and (area / bounding_area) >= 0.92:
            top_left_x = float(bx)
            top_left_y = float(by)
            width = float(bw)
            height = float(bh)
            rot = 0.0
        else:
            # Rotated bounding box from minAreaRect
            rot = float(angle)
            width = float(box_w)
            height = float(box_h)

            # Normalize rotation to range [-45.0, 45.0]
            while rot > 45.0:
                rot -= 90.0
                width, height = height, width
            while rot < -45.0:
                rot += 90.0
                width, height = height, width

            rot = round(max(-45.0, min(45.0, rot)), 2)
            top_left_x = cx - (width / 2.0)
            top_left_y = cy - (height / 2.0)

        raw_placeholders.append(
            {
                "x": int(round(max(0.0, top_left_x))),
                "y": int(round(max(0.0, top_left_y))),
                "height": int(round(height)),
                "width": int(round(width)),
                "rotation": float(rot),
                "elevation": 0,
                "_sort_y": cy,
                "_sort_x": cx,
            }
        )

    # Sort placeholders top-to-bottom, then left-to-right
    raw_placeholders.sort(key=lambda p: (round(p["_sort_y"] / 50.0), p["_sort_x"]))

    # Assign sequential elevation / zero-based index
    coordinates: list[dict[str, Any]] = []
    for idx, p in enumerate(raw_placeholders):
        coordinates.append(
            {
                "x": int(p["x"]),
                "y": int(p["y"]),
                "height": int(p["height"]),
                "width": int(p["width"]),
                "rotation": float(p["rotation"]),
                "elevation": idx,
            }
        )

    return {
        "width": int(img_width),
        "height": int(img_height),
        "coordinates": coordinates,
        "placeholders": coordinates,
    }


def detect_frame_placeholders_from_file_or_url(
    image_source: str | bytes,
) -> dict[str, Any]:
    """Detect frame placeholders from image bytes, local file path, or central_data static URL."""
    if isinstance(image_source, bytes):
        return detect_frame_placeholders(image_source)

    path_or_url = str(image_source).strip()
    p = Path(path_or_url)
    if p.exists() and p.is_file():
        return detect_frame_placeholders(p.read_bytes())

    from config.paths import CENTRAL_DATA_DIR

    rel_path = None
    if "/static/central_data/" in path_or_url:
        rel_path = path_or_url.split("/static/central_data/")[-1].split("?")[0].strip("/\\ ")
    elif "central_data/" in path_or_url:
        rel_path = path_or_url.split("central_data/")[-1].split("?")[0].strip("/\\ ")

    if rel_path:
        local_p = CENTRAL_DATA_DIR / rel_path
        if local_p.exists() and local_p.is_file():
            return detect_frame_placeholders(local_p.read_bytes())

    candidate = CENTRAL_DATA_DIR / path_or_url.lstrip("/\\")
    if candidate.exists() and candidate.is_file():
        return detect_frame_placeholders(candidate.read_bytes())

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        try:
            import httpx
            resp = httpx.get(path_or_url, timeout=10.0)
            if resp.is_success:
                return detect_frame_placeholders(resp.content)
        except Exception:
            pass

    raise ValueError(f"Unable to locate image file on disk for placeholder extraction: {image_source}")

