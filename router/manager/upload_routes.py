"""Manager portal direct upload routes (auto-synced to Central Data) & app-level asset editing routes."""

import json
from typing import Any

import anyio
from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.manager_session import get_current_manager_session
from config.paths import TEMPLATES_DIR
from controller.app_instance_controller import get_app_instance
from controller.asset_controller import check_asset_name_availability
from controller.catalog_controller import get_resolved_single_asset
from controller.crop_controller import process_media_crop
from controller.frame_controller import detect_placeholders
from controller.manager_controller import verify_manager_instance_access
from controller.manager_upload_controller import (
    apply_frame_editor_save,
    create_central_asset_for_instance,
    create_manager_folder_with_central_sync,
    find_frame_block_key,
    list_upload_categories_for_instance,
    list_upload_subcategories_for_instance,
    normalize_asset_aliases,
    resolve_central_folders_for_upload,
    save_app_level_asset_edit_and_notify,
)
from controller.media_controller import handle_upload
from controller.media_similarity import check_filename_similarity
from controller.override_controller import reset_overrides
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationError
from utils.responses import append_query_params, safe_redirect_url
from utils.slugify import slugify

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display

router = APIRouter(prefix="/instances", tags=["Manager App Uploads & Edits"])


def _manager_endpoint_urls(instance_id: str, scope: str = "central") -> dict[str, str]:
    base = f"/manager/instances/{instance_id}"
    return {
        "media_upload_url": f"{base}/media/upload?scope={scope}",
        "media_crop_url": f"{base}/media/crop",
        "check_similarity_url": f"{base}/media/check-similarity",
        "detect_frames_url": f"{base}/media/detect-frames",
        "subcategories_api_url": f"{base}/subcategories/api/list",
        "check_name_url": f"{base}/assets/check-name",
        "create_asset_url": f"{base}/assets/create",
        "save_action_url": f"{base}/assets/save",
        "ensure_folder_url": f"{base}/folders/ensure-central",
    }


async def _require_manager_for_instance(
    request: Request, db: AsyncIOMotorDatabase, instance_id: str, *, json_mode: bool = False
) -> dict[str, Any] | Response:
    session = get_current_manager_session(request)
    if not session:
        if json_mode:
            return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
        return RedirectResponse(url="/manager/login", status_code=303)
    await verify_manager_instance_access(db, session["user_id"], instance_id)
    return session


@router.get("/{instance_id}/assets/new-single")
async def manager_new_single_asset_page(
    request: Request,
    instance_id: str,
    categoryId: str | None = None,
    category_id: str | None = None,
    subCategoryId: str | None = None,
    sub_category_id: str | None = None,
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render Bulk Single-File Add page scoped cleanly to a Manager App Instance."""
    auth = await _require_manager_for_instance(request, db, instance_id)
    if isinstance(auth, Response):
        return auth

    instance = await get_app_instance(db, instance_id)
    raw_cat = categoryId or category_id or ""
    raw_sub = subCategoryId or sub_category_id or ""
    c_cat_id, c_sub_id, _, _ = await resolve_central_folders_for_upload(db, instance_id, raw_cat or None, raw_sub or None)
    selected_cat = c_cat_id or raw_cat
    selected_sub = c_sub_id or raw_sub

    categories = await list_upload_categories_for_instance(db, instance_id)
    subcategories = (
        await list_upload_subcategories_for_instance(db, instance_id, selected_cat)
        if selected_cat
        else []
    )
    default_return = f"/manager/instances/{instance_id}/content"
    safe_return = safe_redirect_url(return_url, default_return)

    return templates.TemplateResponse(
        request=request,
        name="assets/form_single.html",
        context={
            "session": auth,
            "layout_template": "manager/base.html",
            "portal_mode": "manager_create",
            "instance": instance,
            "categories": categories,
            "subcategories": subcategories,
            "selected_cat": selected_cat,
            "selected_sub": selected_sub,
            "active_tab": "instances",
            "return_url": safe_return,
            **_manager_endpoint_urls(instance_id, scope="central"),
        },
    )


@router.get("/{instance_id}/assets/new-multi")
async def manager_new_multi_asset_page(
    request: Request,
    instance_id: str,
    categoryId: str | None = None,
    category_id: str | None = None,
    subCategoryId: str | None = None,
    sub_category_id: str | None = None,
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render Multi-File Single Asset creation page inside a Manager App Instance."""
    auth = await _require_manager_for_instance(request, db, instance_id)
    if isinstance(auth, Response):
        return auth

    instance = await get_app_instance(db, instance_id)
    raw_cat = categoryId or category_id or ""
    raw_sub = subCategoryId or sub_category_id or ""
    c_cat_id, c_sub_id, _, _ = await resolve_central_folders_for_upload(db, instance_id, raw_cat or None, raw_sub or None)
    selected_cat = c_cat_id or raw_cat
    selected_sub = c_sub_id or raw_sub

    categories = await list_upload_categories_for_instance(db, instance_id)
    subcategories = (
        await list_upload_subcategories_for_instance(db, instance_id, selected_cat)
        if selected_cat
        else []
    )
    default_return = f"/manager/instances/{instance_id}/content"
    safe_return = safe_redirect_url(return_url, default_return)

    return templates.TemplateResponse(
        request=request,
        name="assets/form_multi.html",
        context={
            "session": auth,
            "layout_template": "manager/base.html",
            "portal_mode": "manager_create",
            "form_mode": "manager_create",
            "instance": instance,
            "asset": None,
            "categories": categories,
            "subcategories": subcategories,
            "selected_cat": selected_cat,
            "selected_sub": selected_sub,
            "active_tab": "instances",
            "return_url": safe_return,
            **_manager_endpoint_urls(instance_id, scope="central"),
        },
    )


@router.get("/{instance_id}/assets/{asset_id}/edit")
async def manager_edit_app_asset_page(
    request: Request,
    instance_id: str,
    asset_id: str,
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render App-Level Asset Edit page (saves to instance_assets.overrides and notifies Admin)."""
    auth = await _require_manager_for_instance(request, db, instance_id)
    if isinstance(auth, Response):
        return auth

    instance = await get_app_instance(db, instance_id)
    asset = await get_resolved_single_asset(db, app_instance_id=instance_id, asset_id=asset_id)
    if not asset:
        raise NotFoundError("App instance asset not found.")

    normalize_asset_aliases(asset)

    urls = _manager_endpoint_urls(instance_id, scope="override")
    urls["save_action_url"] = f"/manager/instances/{instance_id}/assets/{asset['id']}/edit"
    urls["frames_editor_base_url"] = f"/manager/instances/{instance_id}/assets/{asset['id']}/frames"
    urls["check_name_url"] = ""
    default_return = f"/manager/instances/{instance_id}/content?active_section=assets&tab=assets"
    safe_return = safe_redirect_url(return_url, default_return)

    return templates.TemplateResponse(
        request=request,
        name="assets/form_multi.html",
        context={
            "session": auth,
            "layout_template": "manager/base.html",
            "portal_mode": "manager_override_edit",
            "form_mode": "app_override_edit",
            "instance": instance,
            "asset": asset,
            "categories": [],
            "subcategories": [],
            "active_tab": "instances",
            "return_url": safe_return,
            **urls,
        },
    )


@router.get("/{instance_id}/assets/{asset_id}/frames")
async def manager_app_asset_frame_editor_page(
    request: Request,
    instance_id: str,
    asset_id: str,
    block_key: str | None = Query(default=None),
    return_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Render Interactive Frame Placeholder Editor scoped to a Manager App Instance asset."""
    auth = await _require_manager_for_instance(request, db, instance_id)
    if isinstance(auth, Response):
        return auth

    instance = await get_app_instance(db, instance_id)
    asset = await get_resolved_single_asset(db, app_instance_id=instance_id, asset_id=asset_id)
    if not asset:
        raise NotFoundError("App instance asset not found.")
    normalize_asset_aliases(asset)

    urls = _manager_endpoint_urls(instance_id, scope="override")
    default_return = f"/manager/instances/{instance_id}/content?active_section=assets&tab=assets"
    safe_return = safe_redirect_url(return_url, default_return)
    back_url = append_query_params(
        f"/manager/instances/{instance_id}/assets/{asset['id']}/edit",
        {"return_url": safe_return} if safe_return else {},
    )
    frames_block_key = find_frame_block_key(asset.get("more_fields"), block_key)

    return templates.TemplateResponse(
        request=request,
        name="assets/frames_editor.html",
        context={
            "session": auth,
            "layout_template": "manager/base.html",
            "portal_mode": "manager_override_edit",
            "instance": instance,
            "asset": asset,
            "active_tab": "instances",
            "return_url": safe_return,
            "back_url": back_url,
            "frames_block_key": frames_block_key,
            "media_upload_url": urls["media_upload_url"],
            "detect_frames_url": urls["detect_frames_url"],
            "save_frames_url": f"/manager/instances/{instance_id}/assets/{asset['id']}/frames",
        },
    )


@router.post("/{instance_id}/assets/{asset_id}/frames")
async def manager_save_app_asset_frames(
    request: Request,
    instance_id: str,
    asset_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Save frame placeholders at app level without altering Central Data, and notify Admin."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    res = await apply_frame_editor_save(
        db,
        app_instance_id=instance_id,
        asset_id=asset_id,
        payload=payload,
        manager_user=auth,
    )
    return JSONResponse(content=res)


@router.post("/{instance_id}/assets/{asset_id}/edit")
async def manager_save_app_asset_edit(
    request: Request,
    instance_id: str,
    asset_id: str,
    name: str | None = Form(default=None),
    description: str = Form(default=""),
    thumbnail_url: str | None = Form(default=None),
    more_fields_json: str | None = Form(default=None),
    return_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Save app-level overrides on an asset without modifying Central Data, and send diff message to Admin."""
    auth = await _require_manager_for_instance(request, db, instance_id)
    if isinstance(auth, Response):
        return auth

    more_fields: dict[str, Any] | None = None
    if more_fields_json and more_fields_json.strip():
        try:
            parsed = json.loads(more_fields_json)
            if isinstance(parsed, dict):
                more_fields = parsed
        except Exception:
            pass

    res = await save_app_level_asset_edit_and_notify(
        db,
        app_instance_id=instance_id,
        asset_id=asset_id,
        payload={
            "name": name,
            "description": description,
            "thumbnail_url": thumbnail_url,
            "more_fields": more_fields,
        },
        manager_user=auth,
    )

    default_return = f"/manager/instances/{instance_id}/content?active_section=assets&tab=assets"
    target = safe_redirect_url(return_url, default_return)
    if res.get("message_sent"):
        target = append_query_params(
            target,
            {"msg": "Saved at app level & change summary sent to Admin."},
        )
    else:
        target = append_query_params(target, {"msg": "Saved app-level changes."})
    return RedirectResponse(url=target, status_code=303)


@router.post("/{instance_id}/assets/{asset_id}/reset-override")
async def manager_reset_app_asset_override(
    request: Request,
    instance_id: str,
    asset_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Clear content overrides on an app asset so it falls back to Central Data defaults."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    try:
        updated = await reset_overrides(
            db,
            app_instance_id=instance_id,
            item_type="asset",
            item_id=asset_id,
            fields=["name", "description", "thumbnail_url", "more_fields"],
        )
        return JSONResponse(status_code=200, content={"success": True, "data": updated})
    except AppError as err:
        return JSONResponse(status_code=err.status_code, content={"success": False, "message": err.message})


@router.get("/{instance_id}/subcategories/api/list")
async def manager_upload_subcategories_list(
    request: Request,
    instance_id: str,
    categoryId: str = Query(default=""),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """List subcategories scoped to a selected category for manager upload dropdowns."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    items = await list_upload_subcategories_for_instance(db, instance_id, categoryId)
    return JSONResponse(content={"items": items})


@router.post("/{instance_id}/folders/ensure-central")
async def manager_ensure_central_folder(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Idempotently find/create a central category or subcategory and link it to this app instance."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    try:
        data = await request.json()
    except Exception:
        data = {}

    try:
        res = await create_manager_folder_with_central_sync(
            db,
            app_instance_id=instance_id,
            data=data,
            manager_user=auth,
            allow_existing_in_instance=True,
        )
        return JSONResponse(status_code=200, content=res)
    except AppError as err:
        return JSONResponse(status_code=err.status_code, content={"success": False, "message": err.message})


@router.get("/{instance_id}/assets/check-name")
async def manager_check_asset_name(
    request: Request,
    instance_id: str,
    name: str = Query(default=""),
    categoryId: str | None = None,
    subCategoryId: str | None = None,
    assetId: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Check whether asset name is available in central subcategory."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    c_cat_id, c_sub_id, _, _ = await resolve_central_folders_for_upload(
        db, instance_id, categoryId, subCategoryId
    )
    res = await check_asset_name_availability(
        db=db,
        name=name,
        category_id=c_cat_id or categoryId,
        sub_category_id=c_sub_id or subCategoryId,
        asset_id=assetId,
    )
    return JSONResponse(content=res)


@router.post("/{instance_id}/media/check-similarity")
async def manager_check_similarity_post(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    filenames = payload.get("filenames") or []
    if not filenames:
        return JSONResponse(content={"success": True, "has_conflict": False, "matches": []})

    cat_id = payload.get("categoryId") or payload.get("category_id")
    sub_id = payload.get("subCategoryId") or payload.get("sub_category_id")
    c_cat_id, c_sub_id, _, _ = await resolve_central_folders_for_upload(db, instance_id, cat_id, sub_id)

    matches = await check_filename_similarity(
        db=db,
        filenames=filenames,
        category_id=c_cat_id or cat_id,
        sub_category_id=c_sub_id or sub_id,
        existing_staged=payload.get("existingStaged") or payload.get("existing_staged") or [],
        asset_id=payload.get("assetId") or payload.get("asset_id"),
        asset_folder=payload.get("assetFolder") or payload.get("asset_folder"),
        asset_name=payload.get("assetName") or payload.get("asset_name"),
    )
    return JSONResponse(
        content={
            "success": True,
            "has_conflict": any(m.get("has_conflict", False) for m in matches),
            "matches": matches,
        }
    )


@router.get("/{instance_id}/media/check-similarity")
async def manager_check_similarity_get(
    request: Request,
    instance_id: str,
    filename: str = Query(...),
    categoryId: str | None = Query(default=None),
    subCategoryId: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
    sub_category_id: str | None = Query(default=None),
    assetId: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    assetFolder: str | None = Query(default=None),
    asset_folder: str | None = Query(default=None),
    assetName: str | None = Query(default=None),
    asset_name: str | None = Query(default=None),
    existingStaged: list[str] = Query(default_factory=list),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    cat_id = categoryId or category_id
    sub_id = subCategoryId or sub_category_id
    c_cat_id, c_sub_id, _, _ = await resolve_central_folders_for_upload(db, instance_id, cat_id, sub_id)
    matches = await check_filename_similarity(
        db=db,
        filenames=[filename],
        category_id=c_cat_id or cat_id,
        sub_category_id=c_sub_id or sub_id,
        existing_staged=existingStaged,
        asset_id=assetId or asset_id,
        asset_folder=assetFolder or asset_folder,
        asset_name=assetName or asset_name,
    )
    return JSONResponse(
        content={
            "success": True,
            "has_conflict": any(m.get("has_conflict", False) for m in matches),
            "matches": matches,
        }
    )


async def _detect_frames_response(
    file_bytes: bytes | None = None, target_url: str | None = None
) -> dict[str, Any]:
    result = await detect_placeholders(image_bytes=file_bytes, image_url=target_url)
    coords = result.get("coordinates", [])
    w = result.get("width")
    h = result.get("height")
    return {
        "success": True,
        "image_url": target_url or result.get("image_url", ""),
        "width": w,
        "height": h,
        "coordinates": coords,
        "placeholders": coords,
        "data": {"width": w, "height": h, "slots": coords},
    }


@router.get("/{instance_id}/media/detect-frames")
async def manager_detect_frames_get(
    request: Request,
    instance_id: str,
    imageUrl: str | None = Query(default=None),
    image_url: str | None = Query(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    return JSONResponse(content=await _detect_frames_response(target_url=imageUrl or image_url))


@router.post("/{instance_id}/media/detect-frames")
async def manager_detect_frames_post(
    request: Request,
    instance_id: str,
    file: UploadFile | None = File(default=None),
    imageUrl: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    content = await file.read() if file else None
    target_url = imageUrl or image_url
    if not file and not target_url:
        target_url = request.query_params.get("imageUrl") or request.query_params.get("image_url")
        if not target_url:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    target_url = body.get("imageUrl") or body.get("image_url")
            except Exception:
                pass
    return JSONResponse(content=await _detect_frames_response(file_bytes=content, target_url=target_url))


@router.post("/{instance_id}/media/upload")
async def manager_media_upload(
    request: Request,
    instance_id: str,
    file: UploadFile = File(...),
    scope: str = Query(default="central"),
    categoryId: str | None = Form(default=None),
    subCategoryId: str | None = Form(default=None),
    category_id: str | None = Form(default=None),
    sub_category_id: str | None = Form(default=None),
    assetName: str | None = Form(default=None),
    asset_name: str | None = Form(default=None),
    assetFolder: str | None = Form(default=None),
    asset_folder: str | None = Form(default=None),
    folder: str = Form(default="misc"),
    duration_ms: int | None = Form(default=None),
    duration: float | None = Form(default=None),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
    filesize: int | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Upload media either into Central Data hierarchy (for new uploads) or isolated instance_overrides/ (for edits)."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    content = await file.read()
    filename = file.filename or "uploaded_file"

    client_hints: dict[str, Any] = {}
    if duration_ms is not None:
        client_hints["duration_ms"] = duration_ms
    if duration is not None:
        client_hints["duration"] = duration
    if width is not None:
        client_hints["width"] = width
    if height is not None:
        client_hints["height"] = height
    if filesize is not None:
        client_hints["filesize"] = filesize

    is_override = (scope or "").strip().lower() == "override"
    category_folder: str | None = None
    subcategory_folder: str | None = None
    asset_folder_name: str | None = None
    target_subdir = f"instance_overrides/{instance_id}" if is_override else folder

    if not is_override:
        cat_id = categoryId or category_id
        sub_id = subCategoryId or sub_category_id
        target_asset = assetName or asset_name or assetFolder or asset_folder
        if target_asset and target_asset.strip():
            asset_folder_name = slugify(target_asset.strip()) or "asset"
        _, _, category_folder, subcategory_folder = await resolve_central_folders_for_upload(
            db, instance_id, cat_id, sub_id
        )

    metadata = await handle_upload(
        file_bytes=content,
        filename=filename,
        target_subdir=target_subdir,
        category_folder=category_folder,
        subcategory_folder=subcategory_folder,
        asset_folder=asset_folder_name,
        base_url="",
        client_hints=client_hints,
    )
    return JSONResponse(content={"success": True, "data": metadata, **metadata})


@router.post("/{instance_id}/media/crop")
async def manager_media_crop(
    request: Request,
    instance_id: str,
    file: UploadFile = File(...),
    crop_type: str | None = Form(default=None),
    x: int | None = Form(default=None),
    y: int | None = Form(default=None),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
    target_ratio: str | None = Form(default=None),
    start_time: float | None = Form(default=None),
    end_time: float | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Alpha-safe image/GIF/video/audio cropper scoped to Manager App Instance."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    content = await file.read()
    filename = file.filename or "media_file"
    crop_box = (x or 0, y or 0, width, height) if (width and height and width > 0 and height > 0) else None

    ratio_float: float | None = None
    if target_ratio and target_ratio not in ("null", "Free"):
        try:
            if ":" in target_ratio:
                rw, rh = target_ratio.split(":", 1)
                ratio_float = float(rw) / float(rh)
            elif "/" in target_ratio:
                rw, rh = target_ratio.split("/", 1)
                ratio_float = float(rw) / float(rh)
            else:
                ratio_float = float(target_ratio)
        except Exception:
            ratio_float = None

    result = await anyio.to_thread.run_sync(
        process_media_crop,
        content,
        filename,
        crop_type,
        crop_box,
        ratio_float,
        start_time,
        end_time,
    )
    out_bytes = result["bytes"]
    out_filename = result["filename"]
    out_mime = result["mime"]
    headers = {
        "Content-Disposition": f'inline; filename="{out_filename}"',
        "X-Media-Mime": out_mime,
        "X-Media-Filename": out_filename,
        "X-Media-Size": str(result.get("size_bytes", len(out_bytes))),
    }
    if "width" in result:
        headers["X-Media-Width"] = str(result["width"])
    if "height" in result:
        headers["X-Media-Height"] = str(result["height"])
    if "duration" in result:
        headers["X-Media-Duration"] = str(result["duration"])
    if result.get("duration_ms"):
        headers["X-Media-Duration-Ms"] = str(result["duration_ms"])
    return Response(content=out_bytes, media_type=out_mime, headers=headers)


@router.post("/{instance_id}/assets/create", status_code=201)
async def manager_create_asset_json(
    request: Request,
    instance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """JSON asset creation endpoint (used by Bulk Single-File Add): creates centrally & auto-links to instance."""
    auth = await _require_manager_for_instance(request, db, instance_id, json_mode=True)
    if isinstance(auth, Response):
        return auth

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        res = await create_central_asset_for_instance(
            db, app_instance_id=instance_id, payload=payload, manager_user=auth
        )
        return JSONResponse(status_code=201, content=res)
    except AppError as err:
        return JSONResponse(
            status_code=err.status_code,
            content={"success": False, "error": {"message": err.message}, "message": err.message},
        )


@router.post("/{instance_id}/assets/save")
async def manager_save_multi_asset(
    request: Request,
    instance_id: str,
    name: str | None = Form(default=None),
    description: str = Form(default=""),
    category_id: str = Form(default=""),
    sub_category_id: str = Form(default=""),
    new_category_name: str | None = Form(default=None),
    new_subcategory_name: str | None = Form(default=None),
    thumbnail_url: str | None = Form(default=None),
    more_fields_json: str | None = Form(default=None),
    names_list: str | None = Form(default=None),
    return_url: str | None = Form(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    """Save Multi-File Single Asset or text-list intake: publishes to Central Data and links into instance."""
    auth = await _require_manager_for_instance(request, db, instance_id)
    if isinstance(auth, Response):
        return auth

    more_fields: dict[str, Any] = {}
    if more_fields_json and more_fields_json.strip():
        try:
            parsed = json.loads(more_fields_json)
            if isinstance(parsed, dict):
                more_fields = parsed
        except Exception:
            pass

    default_return = f"/manager/instances/{instance_id}/content"
    safe_return = safe_redirect_url(return_url, default_return)

    try:
        await create_central_asset_for_instance(
            db,
            app_instance_id=instance_id,
            payload={
                "name": name,
                "description": description,
                "category_id": category_id or None,
                "sub_category_id": sub_category_id or None,
                "new_category_name": new_category_name,
                "new_subcategory_name": new_subcategory_name,
                "thumbnail_url": thumbnail_url,
                "more_fields": more_fields,
                "names_list": names_list,
            },
            manager_user=auth,
        )
        return RedirectResponse(
            url=append_query_params(safe_return, {"msg": "Asset created in Central Library & added to app."}),
            status_code=303,
        )
    except (ConflictError, ValidationError, NotFoundError) as err:
        instance = await get_app_instance(db, instance_id)
        categories = await list_upload_categories_for_instance(db, instance_id)
        subcategories = (
            await list_upload_subcategories_for_instance(db, instance_id, category_id)
            if category_id
            else []
        )
        return templates.TemplateResponse(
            request=request,
            name="assets/form_multi.html",
            context={
                "session": auth,
                "layout_template": "manager/base.html",
                "portal_mode": "manager_create",
                "form_mode": "manager_create",
                "instance": instance,
                "asset": {
                    "id": None,
                    "name": (name or "").strip(),
                    "description": description,
                    "categoryId": category_id,
                    "category_id": category_id,
                    "subCategoryId": sub_category_id,
                    "sub_category_id": sub_category_id,
                    "thumbnailUrl": thumbnail_url,
                    "thumbnail_url": thumbnail_url,
                    "moreFields": more_fields,
                    "more_fields": more_fields,
                },
                "categories": categories,
                "subcategories": subcategories,
                "error": f"{err.message} Please choose a different name or retry.",
                "active_tab": "instances",
                "return_url": safe_return,
                **_manager_endpoint_urls(instance_id, scope="central"),
            },
            status_code=err.status_code,
        )
