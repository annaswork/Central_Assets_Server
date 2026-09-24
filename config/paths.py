"""Filesystem paths and URL generation helpers.

Every filesystem path is derived from BASE_DIR to ensure consistency across environments.
"""

from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent
ROOT_DIR: Path = BASE_DIR

# Static directories
STATIC_DIR: Path = BASE_DIR / "static"
CENTRAL_DATA_DIR: Path = STATIC_DIR / "central_data"
APP_DATA_DIR: Path = STATIC_DIR / "app_data"
PROFILES_DIR: Path = STATIC_DIR / "profiles"
MEDIA_UPLOAD_DIR: Path = CENTRAL_DATA_DIR

# Templates & admin asset directories
TEMPLATES_DIR: Path = BASE_DIR / "templates"
TEMPLATE_CSS_DIR: Path = TEMPLATES_DIR / "css"
TEMPLATE_JS_DIR: Path = TEMPLATES_DIR / "js"

# Temporary upload buffer directory
UPLOAD_TMP_DIR: Path = BASE_DIR / ".tmp" / "uploads"


def ensure_directories_exist() -> None:
    """Create essential static, template, and upload directories if they do not exist."""
    for directory in (
        STATIC_DIR,
        CENTRAL_DATA_DIR,
        APP_DATA_DIR,
        PROFILES_DIR,
        TEMPLATES_DIR,
        TEMPLATE_CSS_DIR,
        TEMPLATE_JS_DIR,
        UPLOAD_TMP_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def get_category_dir(category_folder: str) -> Path:
    """Return filesystem path to a central category folder."""
    clean_folder = category_folder.strip("/\\ ")
    return CENTRAL_DATA_DIR / clean_folder


def get_subcategory_dir(category_folder: str, subcategory_folder: str) -> Path:
    """Return filesystem path to a central subcategory folder under its parent category."""
    clean_cat = category_folder.strip("/\\ ")
    clean_sub = subcategory_folder.strip("/\\ ")
    return CENTRAL_DATA_DIR / clean_cat / clean_sub


def get_asset_dir(
    category_folder: str,
    subcategory_folder: str,
    asset_folder: str,
) -> Path:
    """Return filesystem path to a central asset folder under its parent subcategory."""
    clean_cat = category_folder.strip("/\\ ")
    clean_sub = subcategory_folder.strip("/\\ ")
    clean_asset = asset_folder.strip("/\\ ")
    return CENTRAL_DATA_DIR / clean_cat / clean_sub / clean_asset


def build_central_static_url(
    base_url: str | None,
    category_folder: str,
    subcategory_folder: str,
    filename: str,
    asset_folder: str | None = None,
) -> str:
    """Generate static URL for a central asset file."""
    clean_cat = category_folder.strip("/\\ ")
    clean_sub = subcategory_folder.strip("/\\ ")
    clean_file = filename.strip("/\\ ")
    if asset_folder and asset_folder.strip("/\\ "):
        clean_asset = asset_folder.strip("/\\ ")
        path = f"/static/central_data/{clean_cat}/{clean_sub}/{clean_asset}/{clean_file}"
    else:
        path = f"/static/central_data/{clean_cat}/{clean_sub}/{clean_file}"
    if base_url and base_url.strip():
        base = base_url.strip().rstrip("/")
        return f"{base}{path}"
    return path


def central_media_url(relative_path: str, base_url: str | None = None) -> str:
    """Build public URL for central static media."""
    clean_path = relative_path.lstrip("/")
    path = f"/static/central_data/{clean_path}"
    if base_url and base_url.strip():
        base = base_url.strip().rstrip("/")
        return f"{base}{path}"
    return path


def app_icon_url(instance_id: str, filename: str) -> str:
    """Build public URL for an app instance icon."""
    return f"/static/app_data/{instance_id}/{filename}"
