"""System-wide constants, enums, block types, scopes, and limit values."""

from enum import Enum


class BlockType(str, Enum):
    AUDIO = "audio"
    AUDIO_LIST = "audio_list"
    IMAGE = "image"
    IMAGE_LIST = "image_list"
    VIDEO = "video"
    VIDEO_LIST = "video_list"
    JSON = "json"
    FRAMES = "frames"


class Scope(str, Enum):
    ASSETS_READ = "assets:read"
    ASSETS_WRITE = "assets:write"
    CATEGORIES_READ = "categories:read"
    CATEGORIES_WRITE = "categories:write"
    ANALYTICS_READ = "analytics:read"
    KEYS_MANAGE = "keys:manage"
    PREMIUM_READ = "premium:read"


ALL_SCOPES: list[str] = [scope.value for scope in Scope]

# Upload & payload caps
MAX_UPLOAD_FILE_BYTES: int = 150 * 1024 * 1024  # 150 MB
MAX_BATCH_UPLOAD_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_BULK_ITEMS: int = 500
MAX_JSON_BLOCK_BYTES: int = 256 * 1024  # 256 KB
MAX_JSON_DEPTH: int = 8

# Allowed MIME and file extensions
ALLOWED_IMAGE_EXTENSIONS: set[str] = {"png", "jpg", "jpeg", "webp", "gif"}
ALLOWED_AUDIO_EXTENSIONS: set[str] = {"mp3", "aac", "wav", "m4a", "ogg"}
ALLOWED_VIDEO_EXTENSIONS: set[str] = {"mp4", "webm", "mov"}
ALLOWED_JSON_EXTENSIONS: set[str] = {"json"}

ALLOWED_EXTENSIONS: set[str] = (
    ALLOWED_IMAGE_EXTENSIONS
    | ALLOWED_AUDIO_EXTENSIONS
    | ALLOWED_VIDEO_EXTENSIONS
    | ALLOWED_JSON_EXTENSIONS
)

# Default asset thumbnails
DEFAULT_AUDIO_THUMBNAIL_URL: str = "/static/thumbnail_default.png"

# Pagination limits
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# Sequence spacing
SEQUENCE_STEP: int = 1

