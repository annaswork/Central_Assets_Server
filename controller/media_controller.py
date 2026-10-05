"""Media upload handler, content-addressable storage, and thumbnail generation."""

import logging
from pathlib import Path
from typing import Any

import anyio

from config.constants import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_EXTENSIONS,
    ALLOWED_HTML_EXTENSIONS,
    DEFAULT_AUDIO_THUMBNAIL_URL,
    DEFAULT_DOCUMENT_THUMBNAIL_URL,
    DEFAULT_HTML_THUMBNAIL_URL,
    MAX_UPLOAD_FILE_BYTES,
)
from config.paths import (
    CENTRAL_DATA_DIR,
    PROFILES_DIR,
    ROOT_DIR,
    STATIC_DIR,
    build_central_static_url,
    central_media_url,
    get_asset_dir,
    get_category_dir,
    get_subcategory_dir,
)
from utils.errors import ConflictError, ValidationError
from utils.file_utils import compute_sha256, sanitize_filename, sniff_mime_type
from utils.image_utils import extract_first_frame_thumbnail, generate_scaled_thumbnail
from utils.media_prober import probe_file_metadata

logger = logging.getLogger("media_controller")


async def handle_upload(
    file_bytes: bytes,
    filename: str,
    target_subdir: str = "misc",
    category_folder: str | None = None,
    subcategory_folder: str | None = None,
    asset_folder: str | None = None,
    base_url: str = "",
    client_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upload media file, calculating hash, MIME, dimensions, and saving in hierarchy."""
    if len(file_bytes) > MAX_UPLOAD_FILE_BYTES:
        raise ValidationError(
            f"File exceeds maximum allowable size of {MAX_UPLOAD_FILE_BYTES / (1024 * 1024):.0f} MB"
        )

    mime_type = sniff_mime_type(file_bytes, filename)
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"File extension '.{ext}' is not supported")

    sha256 = compute_sha256(file_bytes)
    safe_name = sanitize_filename(filename)

    is_thumbnail_upload = (
        target_subdir in ("thumbnails", "assets/thumbnails")
        or "thumbnail" in str(target_subdir).lower()
    )
    if is_thumbnail_upload and not safe_name.lower().startswith("thumb_"):
        safe_name = f"thumb_{safe_name}"

    if category_folder and subcategory_folder:
        clean_cat = category_folder.strip("/\\ ")
        clean_sub = subcategory_folder.strip("/\\ ")
        if asset_folder and asset_folder.strip("/\\ "):
            clean_asset = asset_folder.strip("/\\ ")
            dest_dir = get_asset_dir(clean_cat, clean_sub, clean_asset)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / safe_name
            if dest_path.exists() and not is_thumbnail_upload:
                raise ConflictError(
                    f"A file named '{safe_name}' already exists in '{clean_cat}/{clean_sub}/{clean_asset}'. "
                    f"Please rename the file or asset and try again."
                )
            async with await anyio.open_file(dest_path, "wb") as f:
                await f.write(file_bytes)

            public_url = build_central_static_url(
                base_url, clean_cat, clean_sub, safe_name, asset_folder=clean_asset
            )
        else:
            dest_dir = get_subcategory_dir(clean_cat, clean_sub)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / safe_name
            if dest_path.exists() and not is_thumbnail_upload:
                raise ConflictError(
                    f"A file named '{safe_name}' already exists in '{clean_cat}/{clean_sub}'. "
                    f"Please rename the file or asset and try again."
                )
            async with await anyio.open_file(dest_path, "wb") as f:
                await f.write(file_bytes)

            public_url = build_central_static_url(base_url, clean_cat, clean_sub, safe_name)
    elif target_subdir in ("profiles", "profiles/"):
        dest_dir = PROFILES_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        unique_filename = f"{sha256[:16]}_{safe_name}"
        dest_path = dest_dir / unique_filename

        # Write file asynchronously if not already stored
        if not dest_path.exists():
            async with await anyio.open_file(dest_path, "wb") as f:
                await f.write(file_bytes)

        relative_stored_path = f"profiles/{unique_filename}"
        path = f"/static/{relative_stored_path}"
        if base_url and base_url.strip():
            base = base_url.strip().rstrip("/")
            public_url = f"{base}{path}"
        else:
            public_url = path
    else:
        dest_dir = CENTRAL_DATA_DIR / target_subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        unique_filename = f"{sha256[:16]}_{safe_name}"
        dest_path = dest_dir / unique_filename

        # Write file asynchronously if not already stored
        if not dest_path.exists():
            async with await anyio.open_file(dest_path, "wb") as f:
                await f.write(file_bytes)

        relative_stored_path = f"{target_subdir}/{unique_filename}"
        public_url = central_media_url(relative_stored_path, base_url=base_url)

    probed = await anyio.to_thread.run_sync(
        probe_file_metadata, file_bytes, safe_name, mime_type, client_hints
    )

    is_audio = mime_type.startswith("audio/") or ext in ALLOWED_AUDIO_EXTENSIONS
    is_video = mime_type.startswith("video/") or ext in ("mp4", "webm", "mov", "avi", "mkv")
    is_gif = mime_type == "image/gif" or ext == "gif"
    is_lottie = ext in ("json", "lottie") or (mime_type == "application/json" and b'"v"' in file_bytes[:300])
    is_html = ext in ALLOWED_HTML_EXTENSIONS or mime_type == "text/html"
    is_document = ext in ALLOWED_DOCUMENT_EXTENSIONS or mime_type in (
        "application/xml",
        "text/xml",
        "application/pdf",
        "text/plain",
        "text/csv",
    )

    if is_audio:
        thumb_url = DEFAULT_AUDIO_THUMBNAIL_URL
    elif is_html:
        thumb_url = DEFAULT_HTML_THUMBNAIL_URL
    elif is_document:
        thumb_url = DEFAULT_DOCUMENT_THUMBNAIL_URL
    elif is_video or is_gif or is_lottie:
        try:
            thumb_bytes, thumb_ext = await anyio.to_thread.run_sync(
                extract_first_frame_thumbnail, file_bytes, safe_name, (480, 480)
            )
            stem = Path(safe_name).stem
            thumb_filename = f"thumb_{stem}.{thumb_ext}"
            thumb_dest_path = dest_dir / thumb_filename
            async with await anyio.open_file(thumb_dest_path, "wb") as tf:
                await tf.write(thumb_bytes)

            if category_folder and subcategory_folder:
                if asset_folder and asset_folder.strip("/\\ "):
                    clean_asset = asset_folder.strip("/\\ ")
                    thumb_url = build_central_static_url(
                        base_url, clean_cat, clean_sub, thumb_filename, asset_folder=clean_asset
                    )
                else:
                    thumb_url = build_central_static_url(base_url, clean_cat, clean_sub, thumb_filename)
            elif target_subdir in ("profiles", "profiles/"):
                relative_thumb_path = f"profiles/{thumb_filename}"
                path = f"/static/{relative_thumb_path}"
                thumb_url = f"{base_url.strip().rstrip('/')}{path}" if base_url and base_url.strip() else path
            else:
                relative_thumb_path = f"{target_subdir}/{thumb_filename}"
                thumb_url = central_media_url(relative_thumb_path, base_url=base_url)
        except Exception as err:
            logger.warning(f"Failed to extract 1st frame webp thumbnail for {safe_name}: {err}")
            thumb_url = None if is_video else public_url
    else:
        # Static image: generate scaled thumbnail if not already a thumbnail
        if not safe_name.lower().startswith(("thumb_", "thumbnail_")) and mime_type.startswith("image/"):
            try:
                scaled_bytes, thumb_ext = await anyio.to_thread.run_sync(
                    generate_scaled_thumbnail, file_bytes, 1 / 3, "WEBP", 85
                )
                stem = Path(safe_name).stem
                thumb_filename = f"thumb_{stem}.{thumb_ext}"
                thumb_dest_path = dest_dir / thumb_filename
                async with await anyio.open_file(thumb_dest_path, "wb") as tf:
                    await tf.write(scaled_bytes)

                if category_folder and subcategory_folder:
                    if asset_folder and asset_folder.strip("/\\ "):
                        clean_asset = asset_folder.strip("/\\ ")
                        thumb_url = build_central_static_url(
                            base_url, clean_cat, clean_sub, thumb_filename, asset_folder=clean_asset
                        )
                    else:
                        thumb_url = build_central_static_url(base_url, clean_cat, clean_sub, thumb_filename)
                elif target_subdir in ("profiles", "profiles/"):
                    relative_thumb_path = f"profiles/{thumb_filename}"
                    path = f"/static/{relative_thumb_path}"
                    thumb_url = f"{base_url.strip().rstrip('/')}{path}" if base_url and base_url.strip() else path
                else:
                    relative_thumb_path = f"{target_subdir}/{thumb_filename}"
                    thumb_url = central_media_url(relative_thumb_path, base_url=base_url)
            except Exception as err:
                logger.warning(f"Failed to generate scaled webp thumbnail for {safe_name}: {err}")
                thumb_url = public_url
        else:
            thumb_url = public_url

    metadata: dict[str, Any] = {
        "url": public_url,
        "thumbnail_url": thumb_url,
        "filename": safe_name,
        "mime": mime_type,
        "sha256": sha256,
        **probed,
    }

    return metadata


async def process_category_media_upload(
    category_folder: str,
    image_file: Any | None = None,
    thumbnail_file: Any | None = None,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
    thumb_option: str | None = "custom",
) -> tuple[str | None, str | None]:
    """Process uploaded or referenced media for a category based on thumb_option.

    Options:
      - 'custom': Uses thumbnail_file / thumbnail_url if provided.
      - 'auto_create': Generates a 1/3rd scaled / 1st frame thumbnail from the hero/banner image.
      - 'original': Sets thumbnail_url directly to image_url.
    """
    clean_cat = category_folder.strip("/\\ ")
    cat_dir = get_category_dir(clean_cat)
    cat_dir.mkdir(parents=True, exist_ok=True)

    final_img_url = image_url.strip() if image_url and image_url.strip() else None
    final_thumb_url = thumbnail_url.strip() if thumbnail_url and thumbnail_url.strip() else None

    image_bytes: bytes | None = None
    image_filename: str | None = None

    # 1. Image file upload
    if image_file and hasattr(image_file, "filename") and image_file.filename:
        raw = await image_file.read()
        if raw:
            image_bytes = raw
            safe_name = sanitize_filename(image_file.filename)
            image_filename = safe_name
            dest = cat_dir / safe_name
            async with await anyio.open_file(dest, "wb") as f:
                await f.write(raw)
            final_img_url = f"/static/central_data/{clean_cat}/{safe_name}"
    elif final_img_url and final_img_url.startswith("/static/"):
        local_path = ROOT_DIR / final_img_url.lstrip("/")
        if local_path.exists() and local_path.is_file():
            image_bytes = local_path.read_bytes()
            image_filename = local_path.name

    opt = (thumb_option or "custom").lower()

    if opt == "original":
        final_thumb_url = final_img_url
    else:
        # 2. Thumbnail file upload (only if custom mode or explicit file provided)
        if thumbnail_file and hasattr(thumbnail_file, "filename") and thumbnail_file.filename:
            raw = await thumbnail_file.read()
            if raw:
                safe_name = sanitize_filename(thumbnail_file.filename)
                dest = cat_dir / safe_name
                async with await anyio.open_file(dest, "wb") as f:
                    await f.write(raw)
                final_thumb_url = f"/static/central_data/{clean_cat}/{safe_name}"

        # 3. If auto_create selected or thumbnail missing, generate scaled/frame-0 thumbnail
        if (opt == "auto_create" or not final_thumb_url) and image_bytes:
            try:
                scaled_bytes, ext = await anyio.to_thread.run_sync(
                    generate_scaled_thumbnail, image_bytes, 1 / 3, "WEBP", 85
                )
                stem = Path(image_filename).stem if image_filename else "category"
                thumb_name = f"thumb_{stem}.{ext}"
                dest = cat_dir / thumb_name
                async with await anyio.open_file(dest, "wb") as f:
                    await f.write(scaled_bytes)
                final_thumb_url = f"/static/central_data/{clean_cat}/{thumb_name}"
            except Exception:
                pass

    return final_img_url, final_thumb_url


async def process_subcategory_media_upload(
    category_folder: str,
    subcategory_folder: str,
    image_file: Any | None = None,
    thumbnail_file: Any | None = None,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
    thumb_option: str | None = "custom",
) -> tuple[str | None, str | None]:
    """Process uploaded or referenced media for a subcategory based on thumb_option."""
    clean_cat = category_folder.strip("/\\ ")
    clean_sub = subcategory_folder.strip("/\\ ")
    sub_dir = get_subcategory_dir(clean_cat, clean_sub)
    sub_dir.mkdir(parents=True, exist_ok=True)

    final_img_url = image_url.strip() if image_url and image_url.strip() else None
    final_thumb_url = thumbnail_url.strip() if thumbnail_url and thumbnail_url.strip() else None

    image_bytes: bytes | None = None
    image_filename: str | None = None

    # 1. Image file upload
    if image_file and hasattr(image_file, "filename") and image_file.filename:
        raw = await image_file.read()
        if raw:
            image_bytes = raw
            safe_name = sanitize_filename(image_file.filename)
            image_filename = safe_name
            dest = sub_dir / safe_name
            async with await anyio.open_file(dest, "wb") as f:
                await f.write(raw)
            final_img_url = f"/static/central_data/{clean_cat}/{clean_sub}/{safe_name}"
    elif final_img_url and final_img_url.startswith("/static/"):
        local_path = ROOT_DIR / final_img_url.lstrip("/")
        if local_path.exists() and local_path.is_file():
            image_bytes = local_path.read_bytes()
            image_filename = local_path.name

    opt = (thumb_option or "custom").lower()

    if opt == "original":
        final_thumb_url = final_img_url
    else:
        # 2. Thumbnail file upload
        if thumbnail_file and hasattr(thumbnail_file, "filename") and thumbnail_file.filename:
            raw = await thumbnail_file.read()
            if raw:
                safe_name = sanitize_filename(thumbnail_file.filename)
                dest = sub_dir / safe_name
                async with await anyio.open_file(dest, "wb") as f:
                    await f.write(raw)
                final_thumb_url = f"/static/central_data/{clean_cat}/{clean_sub}/{safe_name}"

        # 3. Auto-generate scaled thumbnail if requested or missing
        if (opt == "auto_create" or not final_thumb_url) and image_bytes:
            try:
                scaled_bytes, ext = await anyio.to_thread.run_sync(
                    generate_scaled_thumbnail, image_bytes, 1 / 3, "WEBP", 85
                )
                stem = Path(image_filename).stem if image_filename else "subcategory"
                thumb_name = f"thumb_{stem}.{ext}"
                dest = sub_dir / thumb_name
                async with await anyio.open_file(dest, "wb") as f:
                    await f.write(scaled_bytes)
                final_thumb_url = f"/static/central_data/{clean_cat}/{clean_sub}/{thumb_name}"
            except Exception:
                pass

    return final_img_url, final_thumb_url
