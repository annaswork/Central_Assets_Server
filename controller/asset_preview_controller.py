"""Controller for asset preview screen popup, stats reset, and status toggle."""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.constants import ALLOWED_AUDIO_EXTENSIONS, DEFAULT_AUDIO_THUMBNAIL_URL
from controller.base_controller import serialize_mongo_doc
from database.collections import ASSETS, CATEGORIES, SUBCATEGORIES
from utils.datetimes import format_datetime_display, utc_now
from utils.errors import NotFoundError
from utils.ids import to_object_id


def format_bytes(size_bytes: int | float | None) -> str:
    """Format byte count into human-readable string like '7.62 KB'."""
    if size_bytes is None:
        return "—"
    try:
        val = float(size_bytes)
    except (ValueError, TypeError):
        return "—"
    if val <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} B"
    return f"{val:.2f} {units[unit_idx]}"


def format_duration(seconds: float | int | None) -> str:
    """Format duration into readable string like '12.4s' or '1m 20s'."""
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except (ValueError, TypeError):
        return "—"
    if s <= 0:
        return "0s"
    if s < 60:
        return f"{s:.1f}s" if s % 1 != 0 else f"{int(s)}s"
    m = int(s // 60)
    rem_s = int(s % 60)
    return f"{m}m {rem_s}s"


async def get_asset_preview_details(db: AsyncIOMotorDatabase, asset_id: str) -> dict[str, Any]:
    """Retrieve complete asset preview payload including category/subcategory names,

    formatted datetimes, stats, and normalized more_fields with per-file metadata.
    """
    oid = to_object_id(asset_id)
    doc = await db[ASSETS].find_one({"_id": oid, "deleted_at": None})
    if not doc:
        raise NotFoundError(f"Asset '{asset_id}' not found")

    asset = serialize_mongo_doc(doc)

    # 1. Resolve Category and Subcategory names
    category_name = ""
    subcategory_name = ""
    if doc.get("category_id"):
        try:
            cat_doc = await db[CATEGORIES].find_one(
                {"_id": to_object_id(doc["category_id"]), "deleted_at": None}
            )
            if cat_doc:
                category_name = cat_doc.get("name", "")
        except Exception:
            pass

    if doc.get("sub_category_id"):
        try:
            sub_doc = await db[SUBCATEGORIES].find_one(
                {"_id": to_object_id(doc["sub_category_id"]), "deleted_at": None}
            )
            if sub_doc:
                subcategory_name = sub_doc.get("name", "")
        except Exception:
            pass

    # 2. Formatted Datetimes
    created_at_dt = doc.get("created_at")
    updated_at_dt = doc.get("updated_at")
    created_formatted = format_datetime_display(created_at_dt) if created_at_dt else "—"
    updated_formatted = format_datetime_display(updated_at_dt) if updated_at_dt else "—"

    # 3. Process more_fields blocks and their metadata
    raw_more_fields = doc.get("more_fields") or {}
    processed_blocks: list[dict[str, Any]] = []

    for block_key, block_val in raw_more_fields.items():
        b_label = block_key.replace("_", " ").title()

        if isinstance(block_val, list):
            # Check if this list contains media objects (dicts with 'url' key)
            has_media_items = any(
                isinstance(x, dict) and ("url" in x or "filename" in x)
                for x in block_val
                if isinstance(x, dict)
            )

            if has_media_items:
                # Process as media items through the full pipeline
                processed_items: list[dict[str, Any]] = []
                for item in block_val:
                    if isinstance(item, str):
                        item = {"url": item}
                    elif not isinstance(item, dict):
                        continue

                    url = item.get("url") or ""
                    fn = item.get("filename")
                    if not fn and url:
                        fn = Path(urlparse(url).path).name

                    size_b = item.get("filesize") or item.get("size_bytes")
                    dur_s = item.get("duration")
                    if dur_s is None and item.get("duration_ms"):
                        dur_s = round(item["duration_ms"] / 1000.0, 2)

                    dims = item.get("dimensions")
                    if not dims and item.get("width") and item.get("height"):
                        dims = f"{item['width']} × {item['height']}"
                    elif dims and "x" in str(dims):
                        dims = str(dims).replace("x", " × ")

                    ext = (
                        Path(fn).suffix.lower()
                        if fn
                        else (Path(urlparse(url).path).suffix.lower() if url else "")
                    )
                    fmt = item.get("format") or item.get("mime")
                    if not fmt and ext:
                        fmt = ext.lstrip(".").upper()

                    is_gif = (
                        (fmt and str(fmt).upper() == "GIF")
                        or ext == ".gif"
                        or ".gif" in url.lower()
                    )
                    is_video = ext in (
                        ".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv",
                    ) or (fmt and str(fmt).upper() in ("MP4", "WEBM", "OGG", "MOV"))
                    is_audio = ext in (
                        ".mp3", ".wav", ".m4a", ".aac", ".flac", ".oga",
                    ) or (fmt and str(fmt).upper() in ("MP3", "WAV", "AAC", "FLAC", "M4A"))
                    is_animation = is_gif or (
                        (fmt and str(fmt).upper() in ("APNG", "LOTTIE", "ANIMATION"))
                        or ext in (".apng", ".lottie")
                    )

                    media_kind = (
                        "gif"
                        if is_gif
                        else ("video" if is_video else ("audio" if is_audio else "image"))
                    )

                    # Audio items must not have dimensions
                    final_dims = None if is_audio else dims

                    processed_items.append(
                        {
                            "url": url,
                            "filename": fn or "file",
                            "filesize": size_b,
                            "filesize_formatted": format_bytes(size_b),
                            "duration": dur_s,
                            "duration_formatted": format_duration(dur_s) if dur_s is not None else None,
                            "dimensions": final_dims,
                            "format": fmt,
                            "media_kind": media_kind,
                            "is_gif": is_gif,
                            "is_animation": is_animation,
                            "is_video": is_video,
                            "is_audio": is_audio,
                        }
                    )

                # Infer block type from the first item's media kind
                first_kind = processed_items[0]["media_kind"] if processed_items else "image"
                inferred_type = f"{first_kind}_list" if len(processed_items) != 1 else f"{first_kind}_single"

                processed_blocks.append(
                    {
                        "key": block_key,
                        "type": inferred_type,
                        "label": b_label,
                        "items": processed_items,
                        "count": len(processed_items),
                    }
                )
            else:
                # Plain string list
                str_items = [str(x) for x in block_val if str(x).strip()]
                processed_blocks.append(
                    {
                        "key": block_key,
                        "type": "string_list",
                        "label": b_label,
                        "items": str_items,
                        "count": len(str_items),
                    }
                )
            continue

        if not isinstance(block_val, dict):
            # Fallback for scalar values
            processed_blocks.append(
                {
                    "key": block_key,
                    "type": "custom",
                    "label": b_label,
                    "items": [],
                    "raw_data": block_val,
                }
            )
            continue

        b_type = (block_val.get("type") or "").lower()

        # Detect standardized frames block: plain object with 'coordinates' or 'placeholders' array (or type == 'frames')
        has_coords = "coordinates" in block_val and isinstance(block_val.get("coordinates"), list)
        has_ph = "placeholders" in block_val and isinstance(block_val.get("placeholders"), list)
        if (b_type == "frames" or b_type == "" or "frame" in block_key.lower()) and (
            has_coords or has_ph or b_type == "frames"
        ):
            frame_img = block_val.get("image_url") or block_val.get("imageUrl") or block_val.get("url") or ""
            coords = block_val.get("coordinates") if has_coords else block_val.get("placeholders", [])
            processed_blocks.append(
                {
                    "key": block_key,
                    "type": "frames",
                    "label": b_label,
                    "image_url": frame_img,
                    "width": block_val.get("width"),
                    "height": block_val.get("height"),
                    "coordinates": coords,
                    "count": len(coords),
                }
            )
            continue

        # Detect standardized JSON block: plain dict without a recognized block type
        if b_type == "" and "items" not in block_val and "url" not in block_val and "urls" not in block_val:
            processed_blocks.append(
                {
                    "key": block_key,
                    "type": "json_data",
                    "label": b_label,
                    "data": block_val,
                }
            )
            continue

        if b_type == "string_list":
            items_list = block_val.get("items") or []
            clean_items = [str(x) for x in items_list if str(x).strip()]
            processed_blocks.append(
                {
                    "key": block_key,
                    "type": "string_list",
                    "label": b_label,
                    "items": clean_items,
                    "count": len(clean_items),
                }
            )
        elif b_type in ("json_data", "json", "text", "number", "boolean"):
            processed_blocks.append(
                {
                    "key": block_key,
                    "type": b_type,
                    "label": b_label,
                    "data": block_val.get("data")
                    if "data" in block_val
                    else block_val.get("value"),
                }
            )
        elif (
            b_type
            in (
                "image_list",
                "image_single",
                "video_list",
                "video_single",
                "audio_list",
                "audio_single",
            )
            or "items" in block_val
            or "url" in block_val
        ):
            # Process media items
            raw_items = block_val.get("items")
            if raw_items is None and "url" in block_val:
                raw_items = [block_val]
            elif not isinstance(raw_items, list):
                raw_items = []

            processed_items: list[dict[str, Any]] = []
            for item in raw_items:
                if isinstance(item, str):
                    item = {"url": item}
                elif not isinstance(item, dict):
                    continue

                url = item.get("url") or ""
                fn = item.get("filename")
                if not fn and url:
                    fn = Path(urlparse(url).path).name

                size_b = item.get("filesize") or item.get("size_bytes")
                dur_s = item.get("duration")
                if dur_s is None and item.get("duration_ms"):
                    dur_s = round(item["duration_ms"] / 1000.0, 2)

                dims = item.get("dimensions")
                if (
                    not dims
                    and item.get("width")
                    and item.get("height")
                    and not b_type.startswith("audio")
                ):
                    dims = f"{item['width']} × {item['height']}"
                elif dims and "x" in str(dims):
                    dims = str(dims).replace("x", " × ")

                ext = (
                    Path(fn).suffix.lower()
                    if fn
                    else (Path(urlparse(url).path).suffix.lower() if url else "")
                )
                fmt = item.get("format")
                if not fmt and ext:
                    fmt = ext.lstrip(".").upper()
                if not fmt:
                    fmt = item.get("mime")

                is_gif = (
                    (fmt and str(fmt).upper() == "GIF") or ext == ".gif" or ".gif" in url.lower()
                )
                is_video = (
                    b_type.startswith("video")
                    or ext in (".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv")
                    or (fmt and str(fmt).upper() in ("MP4", "WEBM", "OGG", "MOV"))
                )
                is_audio = (
                    b_type.startswith("audio")
                    or ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".oga")
                    or (fmt and str(fmt).upper() in ("MP3", "WAV", "AAC", "FLAC", "M4A"))
                )
                is_animation = is_gif or (
                    (fmt and str(fmt).upper() in ("APNG", "LOTTIE", "ANIMATION", "WEBM", "MP4"))
                    or ext in (".apng", ".lottie")
                )

                media_kind = (
                    "gif"
                    if is_gif
                    else ("video" if is_video else ("audio" if is_audio else "image"))
                )

                # Strict guard: audio items must NEVER have dimensions
                final_dims = None if (is_audio or b_type.startswith("audio")) else dims

                processed_items.append(
                    {
                        "url": url,
                        "filename": fn or "file",
                        "filesize": size_b,
                        "filesize_formatted": format_bytes(size_b),
                        "duration": dur_s,
                        "duration_formatted": format_duration(dur_s) if dur_s is not None else None,
                        "dimensions": final_dims,
                        "format": fmt,
                        "media_kind": media_kind,
                        "is_gif": is_gif,
                        "is_animation": is_animation,
                        "is_video": is_video,
                        "is_audio": is_audio,
                    }
                )

            processed_blocks.append(
                {
                    "key": block_key,
                    "type": b_type if b_type else "media",
                    "label": b_label,
                    "items": processed_items,
                    "count": len(processed_items),
                }
            )
        else:
            # Generic dictionary block
            processed_blocks.append(
                {
                    "key": block_key,
                    "type": b_type or "custom",
                    "label": b_label,
                    "raw_data": block_val,
                }
            )


    return {
        "id": asset["id"],
        "name": asset.get("name", "Untitled Asset"),
        "description": asset.get("description", ""),
        "category_id": asset.get("category_id"),
        "category_name": category_name or "Category",
        "subcategory_id": asset.get("sub_category_id"),
        "subcategory_name": subcategory_name or "Subcategory",
        "thumbnail_url": (
            DEFAULT_AUDIO_THUMBNAIL_URL
            if (
                not (asset.get("thumbnail_url") or "")
                or Path((asset.get("thumbnail_url") or "").split("?")[0]).suffix.lower().lstrip(".")
                in ALLOWED_AUDIO_EXTENSIONS
            )
            and any("audio" in str(k).lower() for k in (asset.get("more_fields") or {}).keys())
            else (asset.get("thumbnail_url") or "")
        ),
        "views": int(asset.get("views") or 0),
        "downloads": int(asset.get("downloads") or 0),
        "is_enabled": bool(asset.get("is_enabled", True)),
        "is_premium": bool(asset.get("is_premium", False)),
        "sequence": asset.get("sequence", 1),
        "created_at_formatted": created_formatted,
        "updated_at_formatted": updated_formatted,
        "more_fields_blocks": processed_blocks,
    }


async def reset_asset_stats(db: AsyncIOMotorDatabase, asset_id: str) -> dict[str, Any]:
    """Reset the views and downloads counters of an asset to 0."""
    oid = to_object_id(asset_id)
    now = utc_now()
    res = await db[ASSETS].find_one_and_update(
        {"_id": oid, "deleted_at": None},
        {"$set": {"views": 0, "downloads": 0, "updated_at": now}},
        return_document=True,
    )
    if not res:
        raise NotFoundError(f"Asset '{asset_id}' not found")
    return {
        "id": asset_id,
        "views": 0,
        "downloads": 0,
        "updated_at": format_datetime_display(now),
        "message": "Asset views and downloads have been reset to 0.",
    }


async def toggle_asset_status(db: AsyncIOMotorDatabase, asset_id: str) -> dict[str, Any]:
    """Toggle is_enabled status of an asset."""
    oid = to_object_id(asset_id)
    doc = await db[ASSETS].find_one({"_id": oid, "deleted_at": None})
    if not doc:
        raise NotFoundError(f"Asset '{asset_id}' not found")

    new_status = not bool(doc.get("is_enabled", True))
    now = utc_now()
    await db[ASSETS].update_one(
        {"_id": oid}, {"$set": {"is_enabled": new_status, "updated_at": now}}
    )
    return {
        "id": asset_id,
        "is_enabled": new_status,
        "updated_at": format_datetime_display(now),
        "message": f"Asset is now {'enabled' if new_status else 'disabled'}.",
    }
