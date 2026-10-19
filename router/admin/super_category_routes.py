"""Admin pages for central Super Categories (the optional level above Categories)."""

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from authorization.admin_session import get_current_admin_session
from config.paths import TEMPLATES_DIR
from controller.media_controller import process_category_media_upload
from controller.super_category_controller import (
    create_super_category,
    delete_super_category,
    get_super_category,
    list_super_categories,
    super_category_folder,
    update_super_category,
)
from database.models.super_category import SuperCategoryCreate, SuperCategoryUpdate
from router.deps import get_db
from utils.datetimes import format_datetime_display
from utils.errors import ConflictError, NotFoundError

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["format_datetime"] = format_datetime_display
router = APIRouter(prefix="/super-categories", tags=["Admin Super Categories"])

LIST_URL = "/admin/super-categories"
FORM_CONTEXT = {"entity_label": "Super Category", "base_path": LIST_URL, "active_tab": "super_categories"}


def _form(request: Request, session: dict, item: dict | None, error: str | None = None, status_code: int = 200) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="categories/form.html",
        context={**FORM_CONTEXT, "session": session, "category": item, "error": error, "return_url": LIST_URL},
        status_code=status_code,
    )


@router.get("")
async def admin_list_super_categories(
    request: Request,
    search: str | None = None,
    msg: str | None = None,
    error: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="super_categories/list.html",
        context={
            "session": session,
            "items": await list_super_categories(db, search=search),
            "search": search or "",
            "toast_message": msg,
            "error": error,
            "active_tab": "super_categories",
        },
    )


@router.get("/new")
async def admin_new_super_category_page(request: Request) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    return _form(request, session, None)


@router.post("/new")
async def admin_create_super_category(
    request: Request,
    name: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    image_file: UploadFile | None = File(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    try:
        img, thumb = await process_category_media_upload(
            category_folder=super_category_folder(name),
            image_file=image_file,
            thumbnail_file=thumbnail_file,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            thumb_option=thumb_option,
        )
        await create_super_category(
            db, SuperCategoryCreate(name=name, thumbnail_url=thumb or None, image_url=img or None)
        )
    except ConflictError as err:
        return _form(request, session, {"name": name, "thumbnail_url": thumbnail_url, "image_url": image_url}, err.message, 409)
    return RedirectResponse(url=LIST_URL, status_code=303)


@router.get("/{id}/edit")
async def admin_edit_super_category_page(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    return _form(request, session, await get_super_category(db, id))


@router.post("/{id}/edit")
async def admin_update_super_category(
    request: Request,
    id: str,
    name: str = Form(...),
    thumbnail_url: str | None = Form(default=None),
    image_url: str | None = Form(default=None),
    thumb_option: str | None = Form(default="custom"),
    thumbnail_file: UploadFile | None = File(default=None),
    image_file: UploadFile | None = File(default=None),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    existing = await get_super_category(db, id)
    try:
        img, thumb = await process_category_media_upload(
            category_folder=existing.get("folder_name") or super_category_folder(name),
            image_file=image_file,
            thumbnail_file=thumbnail_file,
            image_url=image_url if image_url is not None else existing.get("image_url"),
            thumbnail_url=thumbnail_url if thumbnail_url is not None else existing.get("thumbnail_url"),
            thumb_option=thumb_option,
        )
        await update_super_category(
            db, id, SuperCategoryUpdate(name=name, thumbnail_url=thumb or None, image_url=img or None)
        )
    except ConflictError as err:
        return _form(request, session, {**existing, "name": name}, err.message, 409)
    return RedirectResponse(url=LIST_URL, status_code=303)


@router.post("/{id}/delete")
async def admin_delete_super_category(
    request: Request, id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Response:
    session = get_current_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin/login", status_code=303)
    try:
        name = (await get_super_category(db, id)).get("name", "Super category")
        await delete_super_category(db, id)
        return RedirectResponse(url=f"{LIST_URL}?msg={quote_plus(f'{name} was deleted.')}", status_code=303)
    except (ConflictError, NotFoundError) as err:
        return RedirectResponse(url=f"{LIST_URL}?error={quote_plus(err.message)}", status_code=303)
