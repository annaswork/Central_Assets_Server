import copy
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.constants import (
    ALLOWED_AUDIO_EXTENSIONS,
    DEFAULT_AUDIO_THUMBNAIL_URL,
)
from config.paths import (
    CENTRAL_DATA_DIR,
    get_asset_dir,
    get_subcategory_dir,
)
from controller.base_controller import format_page_response, serialize_mongo_doc
from database.collections import (
    APP_INSTANCES,
    ASSETS,
    CATEGORIES,
    INSTANCE_ASSETS,
    SUBCATEGORIES,
)
from database.models.asset import AssetCreate, AssetUpdate
from database.repository import CentralRepository
from utils.datetimes import utc_now
from utils.errors import ConflictError, NotFoundError, ValidationError
from utils.ids import to_object_id
from utils.media_prober import (
    probe_audio_metadata,
    probe_image_metadata,
    probe_video_metadata,
)
from utils.responses import bulk_item_result, bulk_response
from utils.sequencing import compute_next_sequence
from utils.slugify import filename_to_title, slugify


def build_asset_type_filter(asset_type: str | None) -> dict[str, Any] | None:
    """Build a MongoDB query condition to filter assets that contain the specified polymorphic object type.

    Supported types:
      - 'images' (or 'image'): checks for image blocks/items/mime/extensions
      - 'videos' (or 'video'): checks for video blocks/items/mime/extensions
      - 'audios' (or 'audio'): checks for audio blocks/items/mime/extensions
      - 'json' (or 'json_data'): checks for json blocks/items/data
      - 'frames' (or 'frame'): checks for frames blocks/placeholders
    """
    if not asset_type:
        return None

    dt = asset_type.lower().strip()
    if dt in ("image", "images"):
        key_re = "image|img|photo|pic"
        ext_re = r"\.(png|jpe?g|webp|gif|svg|bmp|ico|tiff|avif|apng|heic)(\?|$)"
        mime_re = r"^image/"
        excluded_types = ["frames", "video", "video_list", "audio", "audio_list", "json", "json_data"]
    elif dt in ("video", "videos"):
        key_re = "video|vid|movie"
        ext_re = r"\.(mp4|webm|mov|mkv|avi|flv|wmv|m4v)(\?|$)"
        mime_re = r"^video/"
        excluded_types = ["frames", "image", "image_list", "audio", "audio_list", "json", "json_data"]
    elif dt in ("audio", "audios", "sound"):
        key_re = "audio|sound|voice|music"
        ext_re = r"\.(mp3|wav|aac|m4a|ogg|flac|opus|wma)(\?|$)"
        mime_re = r"^audio/"
        excluded_types = ["frames", "image", "image_list", "video", "video_list", "json", "json_data"]
    elif dt in ("json", "json_data"):
        key_re = "json"
        ext_re = r"\.json(\?|$)"
        mime_re = r"application/json"
        excluded_types = ["frames", "image", "image_list", "video", "video_list", "audio", "audio_list"]
    elif dt in ("frame", "frames"):
        key_re = "frame"
        ext_re = r"frame"
        mime_re = r"frame"
        excluded_types = ["image", "image_list", "video", "video_list", "audio", "audio_list", "json", "json_data"]
    else:
        return None

    type_expr = {
        "$expr": {
            "$anyElementTrue": {
                "$map": {
                    "input": {"$objectToArray": {"$ifNull": ["$more_fields", {}]}},
                    "as": "item",
                    "in": {
                        "$or": [
                            # 1. Block key name matches
                            {"$regexMatch": {"input": "$$item.k", "regex": key_re, "options": "i"}},
                            # 2. Block value is a dict/object
                            {
                                "$cond": {
                                    "if": {"$eq": [{"$type": "$$item.v"}, "object"]},
                                    "then": {
                                        "$or": [
                                            {"$regexMatch": {"input": {"$ifNull": ["$$item.v.type", ""]}, "regex": key_re, "options": "i"}},
                                            (
                                                {
                                                    "$or": [
                                                        {"$gt": [{"$size": {"$ifNull": ["$$item.v.coordinates", []]}}, 0]},
                                                        {"$gt": [{"$size": {"$ifNull": ["$$item.v.placeholders", []]}}, 0]},
                                                    ]
                                                }
                                                if dt in ("frame", "frames")
                                                else False
                                            ),
                                            ({"$eq": [{"$type": "$$item.v.data"}, "object"]} if dt in ("json", "json_data") else False),
                                            {
                                                "$and": [
                                                    {"$not": [{"$in": [{"$ifNull": ["$$item.v.type", ""]}, excluded_types]}]},
                                                    {
                                                        "$or": [
                                                            {"$regexMatch": {"input": {"$ifNull": ["$$item.v.mime", ""]}, "regex": mime_re, "options": "i"}},
                                                            {"$regexMatch": {"input": {"$ifNull": ["$$item.v.url", ""]}, "regex": ext_re, "options": "i"}},
                                                        ]
                                                    },
                                                ]
                                            },
                                            # Check items inside dict
                                            {
                                                "$cond": {
                                                    "if": {"$eq": [{"$type": "$$item.v.items"}, "array"]},
                                                    "then": {
                                                        "$anyElementTrue": {
                                                            "$map": {
                                                                "input": "$$item.v.items",
                                                                "as": "subitem",
                                                                "in": {
                                                                    "$cond": {
                                                                        "if": {"$eq": [{"$type": "$$subitem"}, "object"]},
                                                                        "then": {
                                                                            "$or": [
                                                                                {"$regexMatch": {"input": {"$ifNull": ["$$subitem.mime", ""]}, "regex": mime_re, "options": "i"}},
                                                                                {"$regexMatch": {"input": {"$ifNull": ["$$subitem.url", ""]}, "regex": ext_re, "options": "i"}},
                                                                            ]
                                                                        },
                                                                        "else": False,
                                                                    }
                                                                },
                                                            }
                                                        }
                                                    },
                                                    "else": False,
                                                }
                                            },
                                        ]
                                    },
                                    "else": False,
                                }
                            },
                            # 3. Block value is an array of items
                            {
                                "$cond": {
                                    "if": {"$eq": [{"$type": "$$item.v"}, "array"]},
                                    "then": {
                                        "$anyElementTrue": {
                                            "$map": {
                                                "input": "$$item.v",
                                                "as": "subitem",
                                                "in": {
                                                    "$cond": {
                                                        "if": {"$eq": [{"$type": "$$subitem"}, "object"]},
                                                        "then": {
                                                            "$or": [
                                                                {"$regexMatch": {"input": {"$ifNull": ["$$subitem.mime", ""]}, "regex": mime_re, "options": "i"}},
                                                                {"$regexMatch": {"input": {"$ifNull": ["$$subitem.url", ""]}, "regex": ext_re, "options": "i"}},
                                                            ]
                                                        },
                                                        "else": False,
                                                    }
                                                },
                                            }
                                        }
                                    },
                                    "else": False,
                                }
                            },
                        ]
                    }
                }
            }
        }
    }

    if dt in ("audio", "audios", "sound"):
        return {
            "$or": [
                type_expr,
                {"thumbnail_url": {"$regex": ext_re, "$options": "i"}},
            ]
        }

    return type_expr


def asset_has_type(
    more_fields: dict[str, Any] | None,
    asset_type: str,
    thumbnail_url: str | None = None,
) -> bool:
    """Check whether an asset dictionary or more_fields contains the specified polymorphic object type."""
    if not asset_type:
        return True

    dt = asset_type.lower().strip()
    more_fields = more_fields or {}
    if not isinstance(more_fields, dict):
        more_fields = {}

    if dt in ("image", "images"):
        key_pattern = re.compile(r"image|img|photo|pic", re.I)
        exts = {"png", "jpg", "jpeg", "webp", "gif", "svg", "bmp", "ico", "tiff", "avif", "apng", "heic"}
        mime_prefix = "image/"
        excluded_types = {"frames", "video", "video_list", "audio", "audio_list", "json", "json_data"}
    elif dt in ("video", "videos"):
        key_pattern = re.compile(r"video|vid|movie", re.I)
        exts = {"mp4", "webm", "mov", "mkv", "avi", "flv", "wmv", "m4v"}
        mime_prefix = "video/"
        excluded_types = {"frames", "image", "image_list", "audio", "audio_list", "json", "json_data"}
    elif dt in ("audio", "audios", "sound"):
        key_pattern = re.compile(r"audio|sound|voice|music", re.I)
        exts = set(ALLOWED_AUDIO_EXTENSIONS)
        mime_prefix = "audio/"
        excluded_types = {"frames", "image", "image_list", "video", "video_list", "json", "json_data"}
        if thumbnail_url:
            t_ext = Path(thumbnail_url.split("?")[0]).suffix.lower().lstrip(".")
            if t_ext in exts:
                return True
    elif dt in ("json", "json_data"):
        key_pattern = re.compile(r"json", re.I)
        exts = {"json"}
        mime_prefix = "application/json"
        excluded_types = {"frames", "image", "image_list", "video", "video_list", "audio", "audio_list"}
    elif dt in ("frame", "frames"):
        key_pattern = re.compile(r"frame", re.I)
        exts = set()
        mime_prefix = ""
        excluded_types = {"image", "image_list", "video", "video_list", "audio", "audio_list", "json", "json_data"}
    else:
        return False

    def check_item(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        mime = str(item.get("mime") or "").lower()
        if mime_prefix and mime.startswith(mime_prefix):
            return True
        url = str(item.get("url") or "")
        ext = Path(url.split("?")[0]).suffix.lower().lstrip(".")
        if ext and ext in exts:
            return True
        return False

    for block_key, block_val in more_fields.items():
        if key_pattern.search(str(block_key)):
            return True
        if isinstance(block_val, dict):
            b_type = str(block_val.get("type") or "").lower()
            if key_pattern.search(b_type):
                return True
            if dt in ("frame", "frames") and (
                block_val.get("coordinates") or block_val.get("placeholders") or b_type == "frames"
            ):
                return True
            if dt in ("json", "json_data") and (b_type in ("json", "json_data") or "data" in block_val):
                return True
            if b_type not in excluded_types and check_item(block_val):
                return True
            for it in block_val.get("items") or []:
                if check_item(it):
                    return True
        elif isinstance(block_val, list):
            for it in block_val:
                if check_item(it):
                    return True

    return False


async def list_assets(
    db: AsyncIOMotorDatabase,
    category_id: str | None = None,
    sub_category_id: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "sequence",
    sort_order: str = "asc",
    asset_type: str | None = None,
) -> dict[str, Any]:
    """List central creative assets with category/subcategory filters, search, type filter, and sorting."""
    repo = CentralRepository(db, ASSETS)
    query: dict[str, Any] = {}
    if category_id:
        query["category_id"] = to_object_id(category_id)
    if sub_category_id:
        query["sub_category_id"] = to_object_id(sub_category_id)
    if search and search.strip():
        query["name"] = {"$regex": search.strip(), "$options": "i"}

    if asset_type:
        type_filter = build_asset_type_filter(asset_type)
        if type_filter:
            if "$or" in type_filter or "$expr" in query or "$and" in query:
                if "$and" not in query:
                    query["$and"] = []
                query["$and"].append(type_filter)
            else:
                query.update(type_filter)

    # Determine sort field and direction
    valid_sort_fields = {
        "created_at": "created_at",
        "created": "created_at",
        "newest": "created_at",
        "oldest": "created_at",
        "views": "views",
        "most_viewed": "views",
        "downloads": "downloads",
        "most_downloaded": "downloads",
        "name": "name",
        "sequence": "sequence",
        "order": "sequence",
        "custom": "sequence",
    }
    s_lower = (sort_by or "sequence").lower()
    mongo_sort_field = valid_sort_fields.get(s_lower, "sequence")

    if s_lower == "oldest":
        direction = 1
    elif s_lower in ("newest", "most_viewed", "most_downloaded"):
        direction = -1
    elif s_lower in ("sequence", "order", "custom"):
        direction = 1 if (sort_order or "asc").lower() in ("asc", "1") else -1
    else:
        direction = 1 if (sort_order or "asc").lower() in ("asc", "1") else -1

    sort = [(mongo_sort_field, direction)]
    if mongo_sort_field != "created_at":
        sort.append(("created_at", direction))
    sort.append(("_id", direction))

    skip = (page - 1) * page_size
    total = await repo.count(query)
    items = await repo.find_many(query=query, skip=skip, limit=page_size, sort=sort)

    # Ensure items have views and downloads defaulted, and audio assets have default thumbnail
    for item in items:
        if "views" not in item or item["views"] is None:
            item["views"] = 0
        if "downloads" not in item or item["downloads"] is None:
            item["downloads"] = 0
        if is_audio_asset(item.get("thumbnail_url"), item.get("more_fields") or {}):
            thumb = item.get("thumbnail_url")
            if not thumb or Path(thumb.split("?")[0]).suffix.lower().lstrip(".") in ALLOWED_AUDIO_EXTENSIONS:
                item["thumbnail_url"] = DEFAULT_AUDIO_THUMBNAIL_URL

    return format_page_response(items, total, page, page_size)


def is_audio_asset(thumbnail_url: str | None, more_fields: dict[str, Any]) -> bool:
    """Check if an asset is primarily an audio asset."""
    if thumbnail_url and isinstance(thumbnail_url, str):
        ext = Path(thumbnail_url.split("?")[0]).suffix.lower().lstrip(".")
        if ext in ALLOWED_AUDIO_EXTENSIONS:
            return True

    if not isinstance(more_fields, dict):
        return False

    has_audio = False
    has_visual = False

    for block_key, block_val in more_fields.items():
        b_key_lower = str(block_key).lower()
        if "audio" in b_key_lower:
            has_audio = True

        if isinstance(block_val, dict):
            b_type = str(block_val.get("type", "")).lower()
            if "audio" in b_type:
                has_audio = True
            elif b_type in ("image", "video", "frames", "gif"):
                has_visual = True

            for item in block_val.get("items") or []:
                if isinstance(item, dict):
                    m = str(item.get("mime", "")).lower()
                    u = str(item.get("url", ""))
                    e = Path(u.split("?")[0]).suffix.lower().lstrip(".")
                    if m.startswith("audio/") or e in ALLOWED_AUDIO_EXTENSIONS:
                        has_audio = True
                    elif m.startswith("image/") or m.startswith("video/") or e in ("png", "jpg", "jpeg", "webp", "gif", "mp4"):
                        has_visual = True

            u = str(block_val.get("url", ""))
            if u:
                e = Path(u.split("?")[0]).suffix.lower().lstrip(".")
                if e in ALLOWED_AUDIO_EXTENSIONS:
                    has_audio = True
                elif e in ("png", "jpg", "jpeg", "webp", "gif", "mp4"):
                    has_visual = True

        elif isinstance(block_val, list):
            for item in block_val:
                if isinstance(item, dict):
                    m = str(item.get("mime", "")).lower()
                    u = str(item.get("url", ""))
                    e = Path(u.split("?")[0]).suffix.lower().lstrip(".")
                    if m.startswith("audio/") or e in ALLOWED_AUDIO_EXTENSIONS:
                        has_audio = True
                    elif m.startswith("image/") or m.startswith("video/") or e in ("png", "jpg", "jpeg", "webp", "gif", "mp4"):
                        has_visual = True

    if has_audio and not has_visual:
        return True
    return has_audio


async def get_asset(db: AsyncIOMotorDatabase, asset_id: str) -> dict[str, Any]:
    """Retrieve single central asset by ID."""
    repo = CentralRepository(db, ASSETS)
    doc = await repo.find_by_id(asset_id)
    if not doc:
        raise NotFoundError("Asset not found")
    res = serialize_mongo_doc(doc)
    if "views" not in res or res["views"] is None:
        res["views"] = 0
    if "downloads" not in res or res["downloads"] is None:
        res["downloads"] = 0
    if is_audio_asset(res.get("thumbnail_url"), res.get("more_fields") or {}):
        thumb = res.get("thumbnail_url")
        if not thumb or Path(thumb.split("?")[0]).suffix.lower().lstrip(".") in ALLOWED_AUDIO_EXTENSIONS:
            res["thumbnail_url"] = DEFAULT_AUDIO_THUMBNAIL_URL
    return res  # type: ignore


def derive_asset_name(thumbnail_url: str | None, more_fields: dict[str, Any]) -> str:
    """Derive a clean human title from the thumbnail or the very first file uploaded in more_fields."""
    if thumbnail_url and thumbnail_url.strip():
        stem = Path(urlparse(thumbnail_url).path).stem
        # Do not derive "Thumbnail Default" from the default thumbnail
        if "thumbnail_default" not in stem.lower() and stem.lower() not in ("default", "thumbnail"):
            title = filename_to_title(stem)
            if title:
                return title
    if isinstance(more_fields, dict):
        for block in more_fields.values():
            if isinstance(block, list) and len(block) > 0:
                first_item = block[0]
                if isinstance(first_item, dict):
                    fn = first_item.get("filename") or first_item.get("url")
                    if fn and isinstance(fn, str):
                        stem = Path(urlparse(fn).path).stem
                        title = filename_to_title(stem)
                        if title:
                            return title
                elif isinstance(first_item, str):
                    stem = Path(urlparse(first_item).path).stem
                    title = filename_to_title(stem)
                    if title:
                        return title
            elif isinstance(block, dict):
                # Check items
                items = block.get("items")
                if isinstance(items, list) and len(items) > 0:
                    first_item = items[0]
                    if isinstance(first_item, dict):
                        fn = first_item.get("filename") or first_item.get("url")
                        if fn and isinstance(fn, str):
                            stem = Path(urlparse(fn).path).stem
                            title = filename_to_title(stem)
                            if title:
                                return title
                    elif isinstance(first_item, str) and first_item.strip():
                        stem = Path(urlparse(first_item).path).stem
                        title = filename_to_title(stem) or first_item.strip().capitalize()
                        if title:
                            return title
                # Check urls
                urls = block.get("urls")
                if isinstance(urls, list) and len(urls) > 0 and isinstance(urls[0], str):
                    stem = Path(urlparse(urls[0]).path).stem
                    title = filename_to_title(stem)
                    if title:
                        return title
                # Check direct filename or url
                fn = block.get("filename") or block.get("url")
                if fn and isinstance(fn, str):
                    stem = Path(urlparse(fn).path).stem
                    title = filename_to_title(stem)
                    if title:
                        return title
    return "Asset"


def relocate_asset_files_to_asset_dir(
    cat_folder: str,
    sub_folder: str,
    asset_folder: str,
    thumbnail_url: str | None,
    more_fields_dict: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """Ensure all central storage files for this asset are located inside its dedicated asset directory."""
    asset_dir = get_asset_dir(cat_folder, sub_folder, asset_folder)
    asset_dir.mkdir(parents=True, exist_ok=True)
    sub_dir = get_subcategory_dir(cat_folder, sub_folder)

    old_prefix = f"/static/central_data/{cat_folder}/{sub_folder}/"
    new_prefix = f"/static/central_data/{cat_folder}/{sub_folder}/{asset_folder}/"

    def _relocate_url(url: str | None) -> str | None:
        if not url or not isinstance(url, str):
            return url
        if new_prefix in url:
            return url
        if old_prefix in url:
            tail = url.split(old_prefix)[-1].split("?")[0].strip("/\\ ")
            if "/" not in tail:
                old_file = sub_dir / tail
                new_file = asset_dir / tail
                if old_file.exists() and old_file.is_file():
                    try:
                        shutil.move(str(old_file), str(new_file))
                    except Exception:
                        pass
                return url.replace(f"{old_prefix}{tail}", f"{new_prefix}{tail}")
        return url

    new_thumb = _relocate_url(thumbnail_url)

    for block in more_fields_dict.values():
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict) and "url" in item:
                    item["url"] = _relocate_url(item["url"])
                elif isinstance(item, str):
                    _relocate_url(item)
        elif isinstance(block, dict):
            if "url" in block and isinstance(block["url"], str):
                block["url"] = _relocate_url(block["url"])
            if "imageUrl" in block and isinstance(block["imageUrl"], str):
                block["imageUrl"] = _relocate_url(block["imageUrl"])
            if "image_url" in block and isinstance(block["image_url"], str):
                block["image_url"] = _relocate_url(block["image_url"])
            if "urls" in block and isinstance(block["urls"], list):
                block["urls"] = [_relocate_url(u) for u in block["urls"]]
            if "items" in block and isinstance(block["items"], list):
                for item in block["items"]:
                    if isinstance(item, dict) and "url" in item:
                        item["url"] = _relocate_url(item["url"])

    return new_thumb, more_fields_dict


def _enrich_single_item_metadata(item: dict[str, Any], block_type: str = "") -> None:
    """Ensure a single media item dict has filesize, size_bytes, duration, dimensions (never dimensions for audio)."""
    if not isinstance(item, dict):
        return

    # 0. Auto-populate filename and mime from URL if missing
    raw_url = item.get("url") or item.get("imageUrl") or item.get("image_url") or ""
    if raw_url and isinstance(raw_url, str):
        if not item.get("filename"):
            url_name = Path(raw_url.split("?")[0]).name
            if url_name:
                item["filename"] = url_name
        if not item.get("mime"):
            ext = Path(raw_url.split("?")[0]).suffix.lower().lstrip(".")
            mime_map = {
                "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
                "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
                "m4a": "audio/mp4", "aac": "audio/aac", "flac": "audio/flac",
                "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
                "avi": "video/x-msvideo", "mkv": "video/x-matroska",
            }
            if ext in mime_map:
                item["mime"] = mime_map[ext]

    # 1. Sync existing filesize <-> size_bytes
    if item.get("filesize") is not None and item.get("size_bytes") is None:
        item["size_bytes"] = item["filesize"]
    elif item.get("size_bytes") is not None and item.get("filesize") is None:
        item["filesize"] = item["size_bytes"]

    # 2. Sync duration <-> duration_ms
    if item.get("duration_ms") is not None and item.get("duration") is None:
        item["duration"] = round(item["duration_ms"] / 1000.0, 3)
    elif item.get("duration") is not None and item.get("duration_ms") is None:
        try:
            item["duration_ms"] = int(float(item["duration"]) * 1000)
        except (ValueError, TypeError):
            pass

    # 3. Sync width & height -> dimensions
    w = item.get("width")
    h = item.get("height")
    if w is not None and h is not None and not item.get("dimensions"):
        try:
            item["dimensions"] = f"{int(w)}x{int(h)}"
        except (ValueError, TypeError):
            pass

    # Determine media category from block_type or filename/url
    filename = item.get("filename") or (
        raw_url.split("/")[-1] if isinstance(raw_url, str) and raw_url else ""
    )
    ext = Path(filename.split("?")[0]).suffix.lower().lstrip(".")
    b_lower = (block_type or "").lower()
    is_audio = "audio" in b_lower or ext in ("mp3", "wav", "ogg", "m4a", "aac", "flac")
    is_video = "video" in b_lower or ext in ("mp4", "webm", "mov", "avi", "mkv")
    is_image = "image" in b_lower or ext in ("png", "jpg", "jpeg", "webp", "gif", "svg")

    # STRICT REQUIREMENT: Audio files never have dimensions!
    if is_audio:
        item.pop("width", None)
        item.pop("height", None)
        item.pop("dimensions", None)

    # 4. If referencing a static file under CENTRAL_DATA_DIR, probe missing properties
    if raw_url and isinstance(raw_url, str):
        rel_path = None
        if "/static/central_data/" in raw_url:
            rel_path = raw_url.split("/static/central_data/")[-1].split("?")[0].strip("/\\ ")
        elif "central_data/" in raw_url:
            rel_path = raw_url.split("central_data/")[-1].split("?")[0].strip("/\\ ")

        if rel_path:
            disk_path = CENTRAL_DATA_DIR / rel_path
            if disk_path.exists() and disk_path.is_file():
                try:
                    sz = disk_path.stat().st_size
                    if item.get("filesize") is None or item.get("size_bytes") is None:
                        item["filesize"] = sz
                        item["size_bytes"] = sz

                    if is_audio and item.get("duration_ms") is None:
                        a_meta = probe_audio_metadata(disk_path.read_bytes(), disk_path.name)
                        if a_meta.get("duration_ms"):
                            item["duration_ms"] = a_meta["duration_ms"]
                            item["duration"] = a_meta.get("duration")
                    elif is_video and (
                        item.get("width") is None or item.get("duration_ms") is None
                    ):
                        v_meta = probe_video_metadata(disk_path.read_bytes(), disk_path.name)
                        if v_meta.get("width") and v_meta.get("height"):
                            item["width"] = v_meta["width"]
                            item["height"] = v_meta["height"]
                            item["dimensions"] = v_meta["dimensions"]
                        if v_meta.get("duration_ms"):
                            item["duration_ms"] = v_meta["duration_ms"]
                            item["duration"] = v_meta.get("duration")
                    elif is_image and (item.get("width") is None or item.get("height") is None):
                        i_meta = probe_image_metadata(disk_path.read_bytes())
                        if i_meta.get("width") and i_meta.get("height"):
                            item["width"] = i_meta["width"]
                            item["height"] = i_meta["height"]
                            item["dimensions"] = i_meta["dimensions"]
                except Exception:
                    pass


def _clean_frame_coordinate(raw_c: dict[str, Any], idx: int) -> dict[str, Any]:
    """Normalize a single frame placeholder coordinate with integer dimensions and [-45, 45] rotation."""
    rot = float(raw_c.get("rotation", 0.0) or 0.0)
    w = float(raw_c.get("width", 0) or 0)
    h = float(raw_c.get("height", 0) or 0)
    while rot > 45.0:
        rot -= 90.0
        w, h = h, w
    while rot < -45.0:
        rot += 90.0
        w, h = h, w
    rot = round(max(-45.0, min(45.0, rot)), 2)

    elevation = raw_c.get("elevation")
    if elevation is None:
        elevation = idx
    else:
        try:
            elevation = int(elevation)
        except Exception:
            elevation = idx

    return {
        "x": int(round(float(raw_c.get("x", 0) or 0))),
        "y": int(round(float(raw_c.get("y", 0) or 0))),
        "height": int(round(h)),
        "width": int(round(w)),
        "rotation": rot,
        "elevation": elevation,
    }


def _enrich_frames_block(block_val: dict[str, Any]) -> None:
    """Enrich and normalize a frames block using extract-frame-placeholders if needed."""
    if not isinstance(block_val, dict):
        return

    img_url = block_val.get("image_url") or block_val.get("url") or block_val.get("imageUrl") or ""
    if img_url:
        block_val["image_url"] = str(img_url)

    raw_coords = block_val.get("coordinates")
    if raw_coords is None:
        raw_coords = block_val.get("placeholders")

    clean_coords: list[dict[str, Any]] = []
    if isinstance(raw_coords, list) and raw_coords:
        clean_coords = [
            _clean_frame_coordinate(c, i)
            for i, c in enumerate(raw_coords)
            if isinstance(c, dict)
        ]

    # If coordinates are missing or empty, auto-detect from image
    if not clean_coords and img_url:
        try:
            from utils.frame_detector import detect_frame_placeholders_from_file_or_url

            detection = detect_frame_placeholders_from_file_or_url(img_url)
            detected = detection.get("coordinates") or []
            clean_coords = [
                _clean_frame_coordinate(c, i)
                for i, c in enumerate(detected)
                if isinstance(c, dict)
            ]
            if block_val.get("width") is None and detection.get("width"):
                block_val["width"] = int(detection["width"])
            if block_val.get("height") is None and detection.get("height"):
                block_val["height"] = int(detection["height"])
        except Exception:
            pass

    block_val["coordinates"] = clean_coords
    # Ensure there is only 'coordinates' variable containing list of objects (no placeholders)
    block_val.pop("placeholders", None)


def enrich_more_fields_metadata(more_fields: dict[str, Any]) -> dict[str, Any]:
    """Ensure all media blocks and items have duration, filesize, and dimensions (never for audio)."""
    if not isinstance(more_fields, dict):
        return more_fields

    for block_key, block_val in more_fields.items():
        if isinstance(block_val, list):
            for item in block_val:
                if isinstance(item, dict):
                    _enrich_single_item_metadata(item, block_type=block_key)
        elif isinstance(block_val, dict):
            block_type = (block_val.get("type") or block_key).lower()
            if "frame" in block_type or "frame" in str(block_key).lower():
                _enrich_frames_block(block_val)
            if isinstance(block_val.get("items"), list):
                for item in block_val["items"]:
                    if isinstance(item, dict):
                        _enrich_single_item_metadata(item, block_type=block_type)
                # Sync first item's metadata up to the block level
                if block_val["items"] and isinstance(block_val["items"][0], dict):
                    first = block_val["items"][0]
                    for k in (
                        "width",
                        "height",
                        "dimensions",
                        "duration",
                        "duration_ms",
                        "filesize",
                        "size_bytes",
                    ):
                        if first.get(k) is not None and block_val.get(k) is None:
                            block_val[k] = first[k]
                    if "audio" in block_type:
                        block_val.pop("width", None)
                        block_val.pop("height", None)
                        block_val.pop("dimensions", None)
            else:
                _enrich_single_item_metadata(block_val, block_type=block_type)
                if "audio" in block_type:
                    block_val.pop("width", None)
                    block_val.pop("height", None)
                    block_val.pop("dimensions", None)

    return more_fields


async def check_asset_name_availability(
    db: AsyncIOMotorDatabase,
    name: str,
    sub_category_id: str | None = None,
    category_id: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any]:
    """Verify in real-time whether an asset name is available or already used in the database."""
    clean_name = name.strip() if name else ""
    if not clean_name:
        return {
            "available": False,
            "name": "",
            "message": "Asset name cannot be empty.",
        }

    repo = CentralRepository(db, ASSETS)
    query: dict[str, Any] = {
        "name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"},
        "deleted_at": None,
    }
    if asset_id:
        query["_id"] = {"$ne": to_object_id(asset_id)}

    if sub_category_id:
        query["sub_category_id"] = to_object_id(sub_category_id)
        clashing = await repo.find_one(query)
        if clashing:
            return {
                "available": False,
                "name": clean_name,
                "message": f"Asset name '{clean_name}' is already used in this subcategory. Please choose a different name.",
            }
        return {
            "available": True,
            "name": clean_name,
            "message": "Available",
        }
    else:
        clashing = await repo.find_one(query)
        if clashing:
            return {
                "available": False,
                "name": clean_name,
                "message": f"Asset name '{clean_name}' is already used in database. Please choose a different name.",
            }
        return {
            "available": True,
            "name": clean_name,
            "message": "Available",
        }


async def create_asset(db: AsyncIOMotorDatabase, data: AssetCreate) -> dict[str, Any]:
    """Create a new central asset, validating strict hierarchy parentage."""
    cat_oid = to_object_id(data.category_id)
    sub_oid = to_object_id(data.sub_category_id)

    # 1. Verify Category exists
    cat_repo = CentralRepository(db, CATEGORIES)
    category = await cat_repo.find_by_id(cat_oid)
    if not category:
        raise NotFoundError(f"Category '{data.category_id}' does not exist")

    # 2. Verify Subcategory exists and belongs to Category
    sub_repo = CentralRepository(db, SUBCATEGORIES)
    subcategory = await sub_repo.find_by_id(sub_oid)
    if not subcategory:
        raise NotFoundError(f"Subcategory '{data.sub_category_id}' does not exist")

    if subcategory["category_id"] != cat_oid:
        raise ValidationError(
            f"Subcategory '{subcategory['name']}' does not belong to Category '{category['name']}'"
        )

    # Convert more_fields typed blocks to dictionaries for MongoDB storage
    more_fields_dict = {}
    for block_key, block_val in data.more_fields.items():
        if hasattr(block_val, "model_dump"):
            more_fields_dict[block_key] = block_val.model_dump(mode="json")
        elif isinstance(block_val, list):
            more_fields_dict[block_key] = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in block_val
            ]
        elif isinstance(block_val, dict):
            more_fields_dict[block_key] = block_val
        else:
            more_fields_dict[block_key] = block_val

    more_fields_dict = enrich_more_fields_metadata(more_fields_dict)

    # If no name is provided, pick the name of the very first file that is uploaded
    clean_name = data.name.strip() if data.name and data.name.strip() else ""
    if not clean_name:
        clean_name = derive_asset_name(data.thumbnail_url, more_fields_dict)

    repo = CentralRepository(db, ASSETS)
    clashing = await repo.find_one(
        {
            "sub_category_id": sub_oid,
            "name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"},
        }
    )
    if clashing:
        raise ConflictError(
            f"Asset with name '{clean_name}' already exists in this subcategory. Please rename the new asset."
        )

    # Create folder according to asset's name under its category/subcategory
    cat_folder = category.get("folder_name") or slugify(category.get("name", "")) or "category"
    sub_folder = (
        subcategory.get("folder_name") or slugify(subcategory.get("name", "")) or "subcategory"
    )
    asset_folder = slugify(clean_name) or "asset"

    asset_dir = get_asset_dir(cat_folder, sub_folder, asset_folder)
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Assign sequence within subcategory
    assigned_seq = data.sequence
    if assigned_seq is None:
        max_docs = await repo.find_many(
            query={"sub_category_id": sub_oid, "deleted_at": None},
            sort=[("sequence", -1)],
            limit=1,
        )
        assigned_seq = compute_next_sequence(
            max_docs[0].get("sequence") if max_docs else None
        )

    # Resolve thumbnail: if audio asset, default to /static/thumbnail_default.png
    final_thumb_url = data.thumbnail_url.strip() if data.thumbnail_url and data.thumbnail_url.strip() else None
    if final_thumb_url:
        thumb_ext = Path(final_thumb_url.split("?")[0]).suffix.lower().lstrip(".")
        if thumb_ext in ALLOWED_AUDIO_EXTENSIONS:
            final_thumb_url = DEFAULT_AUDIO_THUMBNAIL_URL
    if not final_thumb_url and is_audio_asset(final_thumb_url, more_fields_dict):
        final_thumb_url = DEFAULT_AUDIO_THUMBNAIL_URL

    now = utc_now()
    doc = {
        "name": clean_name,
        "folder_name": asset_folder,
        "description": data.description.strip(),
        "category_id": cat_oid,
        "sub_category_id": sub_oid,
        "thumbnail_url": final_thumb_url,
        "is_enabled": data.is_enabled,
        "is_premium": data.is_premium,
        "sequence": assigned_seq,
        "views": 0,
        "downloads": 0,
        "more_fields": more_fields_dict,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }

    inserted_id = await repo.insert_one(doc)
    doc["_id"] = inserted_id
    return serialize_mongo_doc(doc)  # type: ignore


async def update_asset(
    db: AsyncIOMotorDatabase, asset_id: str, data: AssetUpdate
) -> dict[str, Any]:
    """Update central asset attributes or more_fields."""
    repo = CentralRepository(db, ASSETS)
    oid = to_object_id(asset_id)
    existing = await repo.find_by_id(oid)
    if not existing:
        raise NotFoundError("Asset not found")

    update_fields: dict[str, Any] = {}
    old_asset_folder = existing.get("folder_name") or slugify(existing.get("name", "")) or "asset"
    new_asset_folder = None

    target_cat_oid = to_object_id(data.category_id) if data.category_id else existing.get("category_id")
    target_sub_oid = to_object_id(data.sub_category_id) if data.sub_category_id else existing.get("sub_category_id")

    if data.category_id is not None and target_cat_oid != existing.get("category_id"):
        update_fields["category_id"] = target_cat_oid
    if data.sub_category_id is not None and target_sub_oid != existing.get("sub_category_id"):
        update_fields["sub_category_id"] = target_sub_oid

    if data.name is not None and data.name.strip():
        clean_name = data.name.strip()
        clashing = await repo.find_one(
            {
                "_id": {"$ne": oid},
                "sub_category_id": target_sub_oid,
                "name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"},
            }
        )
        if clashing:
            raise ConflictError(
                f"Asset with name '{clean_name}' already exists in this subcategory. Please rename it."
            )
        update_fields["name"] = clean_name
        new_asset_folder = slugify(clean_name) or "asset"
        if new_asset_folder != old_asset_folder or target_cat_oid != existing.get("category_id") or target_sub_oid != existing.get("sub_category_id"):
            update_fields["folder_name"] = new_asset_folder
            # Rename directory on disk if it exists
            old_cat_doc = await db[CATEGORIES].find_one({"_id": existing.get("category_id")})
            old_sub_doc = await db[SUBCATEGORIES].find_one({"_id": existing.get("sub_category_id")})
            new_cat_doc = await db[CATEGORIES].find_one({"_id": target_cat_oid})
            new_sub_doc = await db[SUBCATEGORIES].find_one({"_id": target_sub_oid})
            old_cat_folder = (
                (old_cat_doc.get("folder_name") or slugify(old_cat_doc.get("name", "")))
                if old_cat_doc
                else "category"
            )
            old_sub_folder = (
                (old_sub_doc.get("folder_name") or slugify(old_sub_doc.get("name", "")))
                if old_sub_doc
                else "subcategory"
            )
            new_cat_folder = (
                (new_cat_doc.get("folder_name") or slugify(new_cat_doc.get("name", "")))
                if new_cat_doc
                else "category"
            )
            new_sub_folder = (
                (new_sub_doc.get("folder_name") or slugify(new_sub_doc.get("name", "")))
                if new_sub_doc
                else "subcategory"
            )
            old_dir = get_asset_dir(old_cat_folder, old_sub_folder, old_asset_folder)
            new_dir = get_asset_dir(new_cat_folder, new_sub_folder, new_asset_folder)
            if old_dir.exists() and old_dir.is_dir() and old_dir != new_dir:
                try:
                    new_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_dir), str(new_dir))
                except Exception:
                    pass

            old_frag = f"/{old_asset_folder}/"
            new_frag = f"/{new_asset_folder}/"
            current_thumb = (
                data.thumbnail_url
                if data.thumbnail_url is not None
                else existing.get("thumbnail_url")
            )
            if current_thumb and old_frag in current_thumb:
                update_fields["thumbnail_url"] = current_thumb.replace(old_frag, new_frag)

    if data.description is not None:
        update_fields["description"] = data.description.strip()
    if data.is_enabled is not None:
        update_fields["is_enabled"] = data.is_enabled
    if data.is_premium is not None:
        update_fields["is_premium"] = data.is_premium
    if "thumbnail_url" in data.model_fields_set or data.thumbnail_url is not None:
        thumb_val = data.thumbnail_url.strip() if data.thumbnail_url and data.thumbnail_url.strip() else None
        if thumb_val:
            thumb_ext = Path(thumb_val.split("?")[0]).suffix.lower().lstrip(".")
            if thumb_ext in ALLOWED_AUDIO_EXTENSIONS:
                thumb_val = DEFAULT_AUDIO_THUMBNAIL_URL
        if not thumb_val and is_audio_asset(thumb_val, data.more_fields if isinstance(data.more_fields, dict) else (existing.get("more_fields") or {})):
            thumb_val = DEFAULT_AUDIO_THUMBNAIL_URL
        update_fields["thumbnail_url"] = thumb_val
    if data.more_fields is not None:
        # Convert models to dicts
        more_fields_dict = {}
        for block_key, block_val in data.more_fields.items():
            if hasattr(block_val, "model_dump"):
                more_fields_dict[block_key] = block_val.model_dump(mode="json")
            elif isinstance(block_val, list):
                more_fields_dict[block_key] = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in block_val
                ]
            elif isinstance(block_val, dict):
                more_fields_dict[block_key] = block_val
            else:
                more_fields_dict[block_key] = block_val
        if new_asset_folder and new_asset_folder != old_asset_folder:
            old_frag = f"/{old_asset_folder}/"
            new_frag = f"/{new_asset_folder}/"
            for block in more_fields_dict.values():
                if isinstance(block, list):
                    for item in block:
                        if (
                            isinstance(item, dict)
                            and "url" in item
                            and isinstance(item["url"], str)
                        ):
                            item["url"] = item["url"].replace(old_frag, new_frag)
                elif isinstance(block, dict):
                    if "url" in block and isinstance(block["url"], str):
                        block["url"] = block["url"].replace(old_frag, new_frag)
                    if "imageUrl" in block and isinstance(block["imageUrl"], str):
                        block["imageUrl"] = block["imageUrl"].replace(old_frag, new_frag)
                    if "image_url" in block and isinstance(block["image_url"], str):
                        block["image_url"] = block["image_url"].replace(old_frag, new_frag)
                    if "urls" in block and isinstance(block["urls"], list):
                        block["urls"] = [
                            u.replace(old_frag, new_frag) if isinstance(u, str) else u
                            for u in block["urls"]
                        ]
                    if "items" in block and isinstance(block["items"], list):
                        for item in block["items"]:
                            if (
                                isinstance(item, dict)
                                and "url" in item
                                and isinstance(item["url"], str)
                            ):
                                item["url"] = item["url"].replace(old_frag, new_frag)

        more_fields_dict = enrich_more_fields_metadata(more_fields_dict)
        update_fields["more_fields"] = more_fields_dict

        # Auto-sync thumbnail if current thumbnail was pointing to a file in more_fields that was deleted
        current_thumb = update_fields.get("thumbnail_url") if "thumbnail_url" in update_fields else existing.get("thumbnail_url")
        if current_thumb:
            old_more_urls = extract_asset_file_urls({"more_fields": existing.get("more_fields")})
            new_more_urls = extract_asset_file_urls({"more_fields": more_fields_dict})
            if current_thumb in old_more_urls and current_thumb not in new_more_urls:
                first_img_url: str | None = None
                for blk in more_fields_dict.values():
                    if isinstance(blk, list):
                        for it in blk:
                            if isinstance(it, dict) and it.get("url"):
                                mime_s = str(it.get("mime") or "")
                                if mime_s.startswith("image/") or it.get("width") or not mime_s.startswith("audio/"):
                                    first_img_url = it["url"]
                                    break
                    elif isinstance(blk, dict):
                        if isinstance(blk.get("items"), list):
                            for it in blk["items"]:
                                if isinstance(it, dict) and it.get("url"):
                                    mime_s = str(it.get("mime") or "")
                                    if mime_s.startswith("image/") or it.get("width") or not mime_s.startswith("audio/"):
                                        first_img_url = it["url"]
                                        break
                        elif blk.get("url"):
                            mime_s = str(blk.get("mime") or "")
                            if mime_s.startswith("image/") or blk.get("width") or not mime_s.startswith("audio/"):
                                first_img_url = blk["url"]
                    if first_img_url:
                        break
                update_fields["thumbnail_url"] = first_img_url

    if data.sequence is not None:
        update_fields["sequence"] = data.sequence

    old_file_urls = extract_asset_file_urls(existing)

    if update_fields:
        await repo.update_one({"_id": oid}, {"$set": update_fields})

        # Synchronize central folder changes to all linked instance assets
        inst_asset_update: dict[str, Any] = {"updated_at": utc_now()}
        if "category_id" in update_fields:
            inst_asset_update["category_id"] = update_fields["category_id"]
        if "sub_category_id" in update_fields:
            inst_asset_update["sub_category_id"] = update_fields["sub_category_id"]

        await db[INSTANCE_ASSETS].update_many(
            {"source_id": oid},
            {"$set": inst_asset_update},
        )

    updated = await repo.find_by_id(oid)

    # When an item is deleted from inside the asset, delete it from that asset's folder on disk
    new_file_urls = extract_asset_file_urls(updated)
    old_folder_for_diff = old_asset_folder
    new_folder_for_diff = update_fields.get("folder_name") or old_asset_folder

    if new_folder_for_diff != old_folder_for_diff and old_folder_for_diff:
        normalized_old_urls = {
            u.replace(f"/{old_folder_for_diff}/", f"/{new_folder_for_diff}/") for u in old_file_urls
        }
    else:
        normalized_old_urls = old_file_urls

    removed_urls = normalized_old_urls - new_file_urls
    for removed_url in removed_urls:
        delete_file_url_from_disk(
            removed_url,
            old_folder=old_folder_for_diff,
            new_folder=new_folder_for_diff,
        )

    # Also clean up any orphaned physical files in the asset's dedicated directory on disk
    try:
        cat_doc = await db[CATEGORIES].find_one({"_id": existing.get("category_id")})
        sub_doc = await db[SUBCATEGORIES].find_one({"_id": existing.get("sub_category_id")})
        if cat_doc and sub_doc and new_folder_for_diff:
            cat_f = cat_doc.get("folder_name") or slugify(cat_doc.get("name", "")) or "category"
            sub_f = sub_doc.get("folder_name") or slugify(sub_doc.get("name", "")) or "subcategory"
            asset_disk_dir = get_asset_dir(cat_f, sub_f, new_folder_for_diff)
            if asset_disk_dir.exists() and asset_disk_dir.is_dir():
                active_filenames = set()
                for u in new_file_urls:
                    if f"/{new_folder_for_diff}/" in u:
                        fname = u.split(f"/{new_folder_for_diff}/")[-1].split("?")[0].strip("/\\ ")
                        if fname and "/" not in fname:
                            active_filenames.add(fname.lower())
                for disk_file in asset_disk_dir.iterdir():
                    if disk_file.is_file() and not disk_file.name.startswith("."):
                        if disk_file.name.lower() not in active_filenames:
                            try:
                                disk_file.unlink(missing_ok=True)
                            except Exception:
                                pass
    except Exception:
        pass

    return serialize_mongo_doc(updated)  # type: ignore


def extract_asset_file_urls(doc: dict[str, Any]) -> set[str]:
    """Extract all static file URLs referenced in an asset document."""
    urls: set[str] = set()
    if not isinstance(doc, dict):
        return urls

    for k in ("thumbnail_url", "thumbnailUrl"):
        u = doc.get(k)
        if u and isinstance(u, str):
            urls.add(u)

    more_fields = doc.get("more_fields") or doc.get("moreFields") or {}
    if isinstance(more_fields, dict):
        for block in more_fields.values():
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, dict):
                        for sub_k in (
                            "url",
                            "imageUrl",
                            "image_url",
                            "thumbnail_url",
                            "thumbnailUrl",
                        ):
                            u = item.get(sub_k)
                            if u and isinstance(u, str):
                                urls.add(u)
                    elif isinstance(item, str) and item:
                        urls.add(item)
            elif isinstance(block, dict):
                for sub_k in (
                    "url",
                    "imageUrl",
                    "image_url",
                    "thumbnail_url",
                    "thumbnailUrl",
                ):
                    u = block.get(sub_k)
                    if u and isinstance(u, str):
                        urls.add(u)
                if isinstance(block.get("urls"), list):
                    for u in block["urls"]:
                        if u and isinstance(u, str):
                            urls.add(u)
                if isinstance(block.get("items"), list):
                    for item in block["items"]:
                        if isinstance(item, dict):
                            for sub_k in (
                                "url",
                                "imageUrl",
                                "image_url",
                                "thumbnail_url",
                                "thumbnailUrl",
                            ):
                                u = item.get(sub_k)
                                if u and isinstance(u, str):
                                    urls.add(u)
                        elif isinstance(item, str) and item:
                            urls.add(item)
    return urls


def delete_file_url_from_disk(
    raw_url: str,
    old_folder: str | None = None,
    new_folder: str | None = None,
) -> str | None:
    """Unlink a single media file from the filesystem if located under CENTRAL_DATA_DIR."""
    if not raw_url or not isinstance(raw_url, str):
        return None

    rel_path: str | None = None
    if "/static/central_data/" in raw_url:
        rel_path = raw_url.split("/static/central_data/")[-1].split("?")[0].strip("/\\ ")
    elif "central_data/" in raw_url:
        rel_path = raw_url.split("central_data/")[-1].split("?")[0].strip("/\\ ")

    if not rel_path:
        return None

    target_path = CENTRAL_DATA_DIR / rel_path

    # If asset directory was renamed, check the renamed folder path if original is missing
    if (
        not target_path.exists()
        and old_folder
        and new_folder
        and old_folder != new_folder
        and f"/{old_folder}/" in raw_url
    ):
        rel_path = rel_path.replace(f"/{old_folder}/", f"/{new_folder}/")
        target_path = CENTRAL_DATA_DIR / rel_path

    if target_path.exists() and target_path.is_file():
        try:
            target_path.unlink(missing_ok=True)
            return str(target_path)
        except Exception:
            pass
    return None


def delete_asset_file_from_disk(existing: dict[str, Any]) -> list[str]:
    """Delete physical media files and dedicated directory associated with an asset."""
    deleted_paths: list[str] = []
    urls_to_check = extract_asset_file_urls(existing)
    folders_to_clean: set[Path] = set()

    for raw_url in urls_to_check:
        deleted = delete_file_url_from_disk(raw_url)
        if deleted:
            deleted_paths.append(deleted)
            rel_path = raw_url.split("/static/central_data/")[-1].split("?")[0].strip("/\\ ")
            rel_parts = Path(rel_path).parts
            if len(rel_parts) >= 4:
                folders_to_clean.add(CENTRAL_DATA_DIR / rel_parts[0] / rel_parts[1] / rel_parts[2])

    # Remove empty or abandoned asset directories
    for folder in folders_to_clean:
        if folder.exists() and folder.is_dir():
            try:
                if not any(folder.iterdir()):
                    folder.rmdir()
                else:
                    shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                pass

    return deleted_paths


async def delete_asset_item(
    db: AsyncIOMotorDatabase,
    asset_id: str,
    block_key: str | None = None,
    item_index: int | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Delete a specific media item from inside an asset and delete its physical file from that asset's folder."""
    repo = CentralRepository(db, ASSETS)
    oid = to_object_id(asset_id)
    existing = await repo.find_by_id(oid)
    if not existing:
        raise NotFoundError("Asset not found")

    more_fields = copy.deepcopy(existing.get("more_fields") or {})
    working_thumb = existing.get("thumbnail_url")
    deleted_url: str | None = None

    # 1. Match specific block_key and item_index
    if block_key and block_key in more_fields:
        blk = more_fields[block_key]
        if isinstance(blk, list) and item_index is not None and 0 <= item_index < len(blk):
            item = blk[item_index]
            deleted_url = (
                item.get("url")
                if isinstance(item, dict)
                else (item if isinstance(item, str) else None)
            )
            blk.pop(item_index)
        elif isinstance(blk, dict):
            items_list = blk.get("items")
            if (
                isinstance(items_list, list)
                and item_index is not None
                and 0 <= item_index < len(items_list)
            ):
                item = items_list[item_index]
                deleted_url = (
                    item.get("url")
                    if isinstance(item, dict)
                    else (item if isinstance(item, str) else None)
                )
                items_list.pop(item_index)
                if isinstance(blk.get("urls"), list):
                    blk["urls"] = [
                        it.get("url") if isinstance(it, dict) else it for it in items_list if it
                    ]
                blk["url"] = (
                    (items_list[0].get("url") if isinstance(items_list[0], dict) else items_list[0])
                    if items_list
                    else ""
                )
            elif url and isinstance(items_list, list):
                new_items = []
                for it in items_list:
                    it_url = it.get("url") if isinstance(it, dict) else it
                    if it_url == url or (isinstance(it_url, str) and url.strip() in it_url):
                        deleted_url = it_url
                    else:
                        new_items.append(it)
                blk["items"] = new_items
                if isinstance(blk.get("urls"), list):
                    blk["urls"] = [
                        it.get("url") if isinstance(it, dict) else it for it in new_items if it
                    ]
                blk["url"] = (
                    (new_items[0].get("url") if isinstance(new_items[0], dict) else new_items[0])
                    if new_items
                    else ""
                )
    # 2. Match url across any block
    elif url:
        for b_key, blk in list(more_fields.items()):
            if isinstance(blk, list):
                new_items = []
                for it in blk:
                    it_url = it.get("url") if isinstance(it, dict) else it
                    if it_url == url or (isinstance(it_url, str) and url.strip() in it_url):
                        deleted_url = it_url
                    else:
                        new_items.append(it)
                more_fields[b_key] = new_items
            elif isinstance(blk, dict) and isinstance(blk.get("items"), list):
                new_items = []
                for it in blk["items"]:
                    it_url = it.get("url") if isinstance(it, dict) else it
                    if it_url == url or (isinstance(it_url, str) and url.strip() in it_url):
                        deleted_url = it_url
                    else:
                        new_items.append(it)
                blk["items"] = new_items
                if isinstance(blk.get("urls"), list):
                    blk["urls"] = [
                        it.get("url") if isinstance(it, dict) else it for it in new_items if it
                    ]
                blk["url"] = (
                    (new_items[0].get("url") if isinstance(new_items[0], dict) else new_items[0])
                    if new_items
                    else ""
                )
                more_fields[b_key] = blk

    # 3. Match thumbnail if url targeted thumbnail or not yet resolved
    if url and working_thumb and (url.strip() == working_thumb.strip() or url.strip() in working_thumb):
        if not deleted_url:
            deleted_url = working_thumb
        working_thumb = ""

    if not deleted_url and not url:
        raise ValidationError("Item to delete was not found in the asset")
    if not deleted_url:
        deleted_url = url

    # Guard: Check last item protection across more_fields
    total_remaining = 0
    for blk in more_fields.values():
        if isinstance(blk, list):
            total_remaining += len(blk)
        elif isinstance(blk, dict):
            if isinstance(blk.get("items"), list):
                total_remaining += len(blk["items"])
            elif blk.get("url") or blk.get("imageUrl") or blk.get("image_url"):
                total_remaining += 1
            elif blk.get("data") and isinstance(blk["data"], dict) and blk["data"]:
                total_remaining += 1

    if total_remaining == 0:
        raise ValidationError(
            "Cannot delete this item: An asset must contain at least one item in more fields."
        )

    # Delete physical file from that asset's folder on disk
    deleted_path = delete_file_url_from_disk(deleted_url)

    if deleted_url and working_thumb and (deleted_url.strip() == working_thumb.strip() or deleted_url.strip() in working_thumb):
        working_thumb = None

    if not working_thumb:
        for blk in more_fields.values():
            if isinstance(blk, list):
                for it in blk:
                    if isinstance(it, dict) and it.get("url"):
                        mime_s = str(it.get("mime") or "")
                        if mime_s.startswith("image/") or it.get("width") or not mime_s.startswith("audio/"):
                            working_thumb = it["url"]
                            break
            elif isinstance(blk, dict):
                if isinstance(blk.get("items"), list):
                    for it in blk["items"]:
                        if isinstance(it, dict) and it.get("url"):
                            mime_s = str(it.get("mime") or "")
                            if mime_s.startswith("image/") or it.get("width") or not mime_s.startswith("audio/"):
                                working_thumb = it["url"]
                                break
                elif blk.get("url"):
                    mime_s = str(blk.get("mime") or "")
                    if mime_s.startswith("image/") or blk.get("width") or not mime_s.startswith("audio/"):
                        working_thumb = blk["url"]
            if working_thumb:
                break

    update_payload: dict[str, Any] = {"more_fields": more_fields}
    if working_thumb != existing.get("thumbnail_url"):
        update_payload["thumbnail_url"] = working_thumb

    await repo.update_one({"_id": oid}, {"$set": update_payload})
    updated = await repo.find_by_id(oid)
    return {
        "success": True,
        "deleted_url": deleted_url,
        "deleted_file": deleted_path,
        "asset": serialize_mongo_doc(updated),
    }


async def delete_asset(db: AsyncIOMotorDatabase, asset_id: str) -> dict[str, Any]:
    """Soft delete a central asset, delete its physical file from storage, and report affected references."""
    repo = CentralRepository(db, ASSETS)
    oid = to_object_id(asset_id)
    existing = await repo.find_by_id(oid)
    if not existing:
        raise NotFoundError("Asset not found")

    # Delete physical file from filesystem
    deleted_files = delete_asset_file_from_disk(existing)

    # Clean up dedicated asset folder if it exists
    if existing.get("folder_name"):
        cat_doc = await db[CATEGORIES].find_one({"_id": existing.get("category_id")})
        sub_doc = await db[SUBCATEGORIES].find_one({"_id": existing.get("sub_category_id")})
        if cat_doc and sub_doc:
            cat_f = cat_doc.get("folder_name") or slugify(cat_doc.get("name", ""))
            sub_f = sub_doc.get("folder_name") or slugify(sub_doc.get("name", ""))
            asset_dir = get_asset_dir(cat_f, sub_f, existing["folder_name"])
            if asset_dir.exists() and asset_dir.is_dir():
                try:
                    shutil.rmtree(asset_dir, ignore_errors=True)
                except Exception:
                    pass

    # Count how many apps reference this asset
    inst_ref_count = await db[INSTANCE_ASSETS].count_documents(
        {
            "source_id": oid,
            "deleted_at": None,
        }
    )

    # Permanently delete from central assets collection and instance reference rows
    await repo.hard_delete({"_id": oid})
    await db[INSTANCE_ASSETS].delete_many({"source_id": oid})

    return {
        "success": True,
        "deleted_id": str(oid),
        "deleted_files": deleted_files,
        "unresolvable_instance_references": inst_ref_count,
    }


async def get_asset_references(db: AsyncIOMotorDatabase, asset_id: str) -> list[dict[str, Any]]:
    """Reverse lookup: Find all app instances currently referencing this central asset."""
    oid = to_object_id(asset_id)

    pipeline = [
        {"$match": {"source_id": oid, "deleted_at": None}},
        {
            "$lookup": {
                "from": APP_INSTANCES,
                "localField": "app_instance_id",
                "foreignField": "_id",
                "as": "app_info",
            }
        },
        {"$unwind": "$app_info"},
        {
            "$project": {
                "reference_id": {"$toString": "$_id"},
                "app_instance_id": {"$toString": "$app_instance_id"},
                "app_name": "$app_info.name",
                "package_name": "$app_info.package_name",
                "is_enabled": "$is_enabled",
                "is_premium": "$is_premium",
                "views": "$views",
                "downloads": "$downloads",
            }
        },
    ]

    cursor = db[INSTANCE_ASSETS].aggregate(pipeline)
    return await cursor.to_list(length=None)


async def bulk_create_assets(
    db: AsyncIOMotorDatabase,
    items: list[AssetCreate],
    atomic: bool = False,
) -> dict[str, Any]:
    """Bulk create single-file central assets with partial success support (HTTP 207)."""
    results: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        try:
            created = await create_asset(db, item)
            results.append(bulk_item_result(index=index, status="created", id=created["id"]))
        except (ConflictError, NotFoundError, ValidationError) as err:
            results.append(bulk_item_result(index=index, status="skipped", error=str(err)))
        except Exception as exc:
            results.append(bulk_item_result(index=index, status="failed", error=str(exc)))

    return bulk_response(results, atomic=atomic)
