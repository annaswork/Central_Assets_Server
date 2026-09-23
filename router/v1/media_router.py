from typing import Any

import anyio
from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from authorization.scopes import require_scope
from controller.crop_controller import process_media_crop
from controller.frame_controller import detect_placeholders
from controller.media_controller import handle_upload
from controller.media_similarity import check_filename_similarity
from database.collections import CATEGORIES, SUBCATEGORIES
from router.deps import get_db
from utils.ids import to_object_id
from utils.slugify import slugify

router = APIRouter(tags=["Media Operations"])


class CheckSimilarityRequest(BaseModel):
    filenames: list[str] = Field(..., min_length=1)
    categoryId: str | None = None
    subCategoryId: str | None = None
    category_id: str | None = None
    sub_category_id: str | None = None
    assetId: str | None = None
    asset_id: str | None = None
    assetFolder: str | None = None
    asset_folder: str | None = None
    assetName: str | None = None
    asset_name: str | None = None
    existingStaged: list[str] = Field(default_factory=list)
    existing_staged: list[str] = Field(default_factory=list)


@router.post("/uploads", dependencies=[Depends(require_scope("assets:write"))])
@router.post("/media/upload", dependencies=[Depends(require_scope("assets:write"))])
async def upload_file_endpoint(
    request: Request,
    file: UploadFile = File(...),
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
) -> dict[str, Any]:
    """Upload media file, calculating hash, MIME, dimensions, and saving in hierarchy."""
    content = await file.read()
    filename = file.filename or "uploaded_file"

    cat_id = categoryId or category_id
    sub_id = subCategoryId or sub_category_id

    category_folder: str | None = None
    subcategory_folder: str | None = None
    asset_folder_name: str | None = None

    target_asset = assetName or asset_name or assetFolder or asset_folder
    if target_asset and target_asset.strip():
        asset_folder_name = slugify(target_asset.strip()) or "asset"

    if cat_id and sub_id:
        try:
            cat_doc = await db[CATEGORIES].find_one(
                {"_id": to_object_id(cat_id), "deleted_at": None}
            )
            sub_doc = await db[SUBCATEGORIES].find_one(
                {"_id": to_object_id(sub_id), "deleted_at": None}
            )
            if cat_doc and sub_doc:
                category_folder = cat_doc.get("folder_name") or slugify(cat_doc.get("name", ""))
                subcategory_folder = sub_doc.get("folder_name") or slugify(sub_doc.get("name", ""))
        except Exception:
            pass

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

    base_url = str(request.base_url).rstrip("/")
    metadata = await handle_upload(
        file_bytes=content,
        filename=filename,
        target_subdir=folder,
        category_folder=category_folder,
        subcategory_folder=subcategory_folder,
        asset_folder=asset_folder_name,
        base_url=base_url,
        client_hints=client_hints,
    )

    return {
        "success": True,
        "data": metadata,
        **metadata,
    }


@router.post("/media/check-similarity", dependencies=[Depends(require_scope("assets:read"))])
@router.post("/uploads/check-similarity", dependencies=[Depends(require_scope("assets:read"))])
async def check_similarity_endpoint(
    payload: CheckSimilarityRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Check whether candidate filenames clash with or are similar to existing assets or files."""
    cat_id = payload.categoryId or payload.category_id
    sub_id = payload.subCategoryId or payload.sub_category_id
    asset_id = payload.assetId or payload.asset_id
    asset_folder = payload.assetFolder or payload.asset_folder
    asset_name = payload.assetName or payload.asset_name
    staged = payload.existingStaged or payload.existing_staged or []
    matches = await check_filename_similarity(
        db=db,
        filenames=payload.filenames,
        category_id=cat_id,
        sub_category_id=sub_id,
        existing_staged=staged,
        asset_id=asset_id,
        asset_folder=asset_folder,
        asset_name=asset_name,
    )
    has_any_conflict = any(m.get("has_conflict", False) for m in matches)
    return {
        "success": True,
        "has_conflict": has_any_conflict,
        "matches": matches,
    }


@router.get("/media/check-similarity", dependencies=[Depends(require_scope("assets:read"))])
async def check_similarity_get_endpoint(
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
) -> dict[str, Any]:
    """Check a single filename for similarity via GET query parameters."""
    cat_id = categoryId or category_id
    sub_id = subCategoryId or sub_category_id
    target_asset_id = assetId or asset_id
    target_asset_folder = assetFolder or asset_folder
    target_asset_name = assetName or asset_name
    matches = await check_filename_similarity(
        db=db,
        filenames=[filename],
        category_id=cat_id,
        sub_category_id=sub_id,
        existing_staged=existingStaged,
        asset_id=target_asset_id,
        asset_folder=target_asset_folder,
        asset_name=target_asset_name,
    )
    has_any_conflict = any(m.get("has_conflict", False) for m in matches)
    return {
        "success": True,
        "has_conflict": has_any_conflict,
        "matches": matches,
    }


async def _execute_frame_detection(
    file_bytes: bytes | None = None,
    target_url: str | None = None,
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
        "data": {
            "width": w,
            "height": h,
            "slots": coords,
        },
    }


@router.get("/media/detect-frames")
@router.get("/detect-frames")
@router.get("/frames/detect")
async def get_detect_frame_endpoint(
    imageUrl: str | None = Query(default=None),
    image_url: str | None = Query(default=None),
) -> dict[str, Any]:
    """Analyze transparent regions in frame image from query URL."""
    target_url = imageUrl or image_url
    return await _execute_frame_detection(target_url=target_url)


@router.post("/media/detect-frames")
@router.post("/detect-frames")
@router.post("/frames/detect")
async def post_detect_frame_endpoint(
    request: Request,
    file: UploadFile | None = File(default=None),
    imageUrl: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
) -> dict[str, Any]:
    """Analyze transparent regions in uploaded frame file, form data, or JSON body."""
    content = None
    target_url = imageUrl or image_url

    if file:
        content = await file.read()
    elif not target_url:
        query_url = request.query_params.get("imageUrl") or request.query_params.get("image_url")
        if query_url:
            target_url = query_url
        else:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    target_url = body.get("imageUrl") or body.get("image_url")
            except Exception:
                pass

    return await _execute_frame_detection(file_bytes=content, target_url=target_url)


@router.post("/crop", dependencies=[Depends(require_scope("assets:write"))])
@router.post("/media/crop", dependencies=[Depends(require_scope("assets:write"))])
@router.post("/uploads/crop", dependencies=[Depends(require_scope("assets:write"))])
async def crop_media_endpoint(
    file: UploadFile = File(...),
    crop_type: str | None = Form(default=None),
    x: int | None = Form(default=None),
    y: int | None = Form(default=None),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
    target_ratio: str | None = Form(default=None),
    start_time: float | None = Form(default=None),
    end_time: float | None = Form(default=None),
) -> Response:
    """Crop image, animated GIF, or video, or cut audio file."""
    content = await file.read()
    filename = file.filename or "media_file"

    crop_box = None
    if width is not None and height is not None and width > 0 and height > 0:
        crop_box = (x or 0, y or 0, width, height)

    ratio_float: float | None = None
    if target_ratio and target_ratio != "null" and target_ratio != "Free":
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
    if "duration_ms" in result and result["duration_ms"]:
        headers["X-Media-Duration-Ms"] = str(result["duration_ms"])

    return Response(
        content=out_bytes,
        media_type=out_mime,
        headers=headers,
    )
