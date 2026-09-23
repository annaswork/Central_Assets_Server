# Project Structure

Canonical folder layout. This file overrides any directory layout described
elsewhere, including section 3 of `.antigravityrules`. If a file doesn't have an
obvious home here, ask before inventing a new top-level folder.

---

## 1. Top level

```
asset-platform/
├── analytics/              # Monitoring list + event recording and rollups
├── authorization/          # API keys, hashing, scopes, sessions
├── config/                 # Settings, paths, constants
├── controller/             # Business logic — the layer routers call
├── database/               # Connection, indexes, model structures
├── inits/                  # Server initialization and wiring
├── middlewares/            # Request-scoped cross-cutting concerns
├── router/                 # API endpoints and admin routes
├── static/                 # Served files
│   ├── central_data/       # Central library media, hierarchical
│   └── app_data/           # Per-app-instance icons
├── templates/              # Admin panel HTML + CSS
├── utils/                  # Stateless helpers
│
├── migrations/             # Numbered, idempotent data migrations
├── tests/                  # Mirrors the source tree
├── scripts/                # One-off and operational scripts
│
├── main.py                 # Entry point: builds the app from inits/
├── requirements.txt
├── .env.example
├── .antigravityrules
├── structure.md
├── core_features.md
└── color_palette.md
```

Every package folder carries an `__init__.py` that re-exports its public names, so
callers import `from controller import asset_controller`, not deep paths.

---

## 2. Layering and import direction

```
router  ──►  controller  ──►  database
   │              │               ▲
   │              ├──► analytics ─┤
   │              ├──► authorization
   │              └──► utils
   └──► middlewares ──► analytics, authorization
```

Allowed to import downward only. Specifically:

| Layer | May import | Must never import |
|---|---|---|
| `router` | controller, database.models, authorization (deps), config | database.connection directly |
| `controller` | database, analytics, authorization, utils, config | router, middlewares |
| `database` | config, utils | controller, router, analytics |
| `analytics` | database, config, utils | router, controller |
| `authorization` | database, config, utils | router, controller |
| `middlewares` | analytics, authorization, config, utils | controller, router |
| `utils` | config only | everything else |

`utils` must stay dependency-free enough to be importable from anywhere without a
cycle. If a helper needs the database, it belongs in `controller` or `database`, not
`utils`.

**Routers hold no business logic.** A route parses input, calls one controller
function, and returns. If a route body exceeds ~15 lines, the logic is in the wrong
place.

---

## 3. `analytics/`

Recording and reporting for endpoints on the monitoring list.

```
analytics/
├── __init__.py
├── allowed_paths.py        # The monitoring list: load, cache, refresh, match
├── allowed_paths.json      # Seed list shipped with the repo
├── recorder.py             # Queue + background drain, insert_many batching
├── event_builder.py        # Request/response -> event document
├── aggregator.py           # Hourly rollups into analytics_hourly
├── reporter.py             # Query layer for dashboards and exports
├── retention.py            # TTL setup + per-endpoint retention enforcement
└── counters.py             # Asset views/downloads $inc handling
```

**`allowed_paths.py`** is the heart of the module. It holds the in-memory set of
monitored route templates loaded from the `monitored_endpoints` collection, seeded
from `allowed_paths.json` on a fresh database. It exposes:

- `is_monitored(method, path_template) -> MonitoredEndpoint | None`
- `refresh()` — reloads from Mongo; called on startup and after any admin edit
- a TTL cache of at most 30 seconds so a revoked or added path takes effect fast

Matching is on the **resolved route template** (`/api/v1/assets/{asset_id}`), never
the literal URL — IDs in the path would explode cardinality.

**`recorder.py`** never blocks a request. It pushes onto an `asyncio.Queue`; a
background task drains in batches. A full queue drops events and logs a warning.
Analytics failure must never surface to a caller.

---

## 4. `authorization/`

Everything about proving who is calling and what they may touch.

```
authorization/
├── __init__.py
├── encryption.py           # SHA-256 hashing, constant-time compare, token generation
├── api_key.py              # Key format, issue, verify, rotate, revoke
├── scopes.py               # Scope constants + require_scope() dependency
├── instance_guard.py       # Binds a key to its app_instance_id
├── rate_limiter.py         # Per-key sliding window
└── admin_session.py        # Operator login sessions for the admin panel
```

**`encryption.py`** owns every cryptographic primitive in the project. Nothing else
calls `hashlib`, `hmac` or `secrets` directly.

- `generate_key()` → `ak_<env>_<22-char id>_<32-char secret>`
- `hash_secret(secret)` → SHA-256 hex
- `verify_secret(secret, stored_hash)` → `hmac.compare_digest`
- `hash_password(password)` / `verify_password(...)` → bcrypt, for admin operators
- `sign_session(payload)` / `read_session(token)` → itsdangerous, for admin cookies

Only the hash and a short display prefix are ever stored. The full key is returned
once, at creation, and never logged.

**`scopes.py`** defines `resource:action` constants and the FastAPI dependency
`require_scope("assets:read")`. Scope checks live in dependencies, never in `if`
statements inside a route.

**`instance_guard.py`** resolves the calling key's `app_instance_id` and injects it
as a mandatory filter. Instance isolation is enforced here and in the database layer,
so a route that forgets a check still cannot leak another app's data.

---

## 5. `config/`

```
config/
├── __init__.py
├── settings.py             # Settings(BaseSettings) — all env vars, typed
├── paths.py                # Every filesystem path, derived from BASE_DIR
├── constants.py            # Enums and magic values: block types, scopes, limits
└── logging_config.py       # Structured JSON logging setup
```

**`settings.py`** is the only place `os.environ` is read. Everything else imports
`settings`. Every variable appears in `.env.example` with a safe placeholder.

**`paths.py`** derives all paths from one `BASE_DIR` so nothing hardcodes a slash:

```python
BASE_DIR           = Path(__file__).resolve().parent.parent
STATIC_DIR         = BASE_DIR / "static"
CENTRAL_DATA_DIR   = STATIC_DIR / "central_data"
APP_DATA_DIR       = STATIC_DIR / "app_data"
TEMPLATES_DIR      = BASE_DIR / "templates"
TEMPLATE_CSS_DIR   = TEMPLATES_DIR / "css"
UPLOAD_TMP_DIR     = BASE_DIR / ".tmp" / "uploads"
```

`paths.py` also holds the URL-building helpers (`central_media_url(...)`,
`app_icon_url(...)`) so the on-disk layout and the public URL shape stay in sync.

---

## 6. `controller/`

Business logic. Routers call controllers; controllers call the database. This is
where the rules from `core_features.md` are actually enforced.

```
controller/
├── __init__.py
├── base_controller.py              # Shared pagination, soft-delete, error mapping
├── category_controller.py          # Central categories: CRUD + bulk
├── subcategory_controller.py       # Central subcategories: CRUD + bulk
├── asset_controller.py             # Central assets: single + single-file bulk
├── more_fields_controller.py       # Typed block validation and assembly
├── frame_controller.py             # Placeholder detection + coordinate editing
├── media_controller.py             # Upload handling, storage, thumbnails
├── app_instance_controller.py      # App instance CRUD, icon upload
├── reference_controller.py         # Add/remove references, copy-from-instance
├── override_controller.py          # Per-app field overrides + reset
├── catalog_controller.py           # Resolved central+overrides tree for clients
├── analytics_controller.py         # Monitoring list admin + dashboard queries
├── authorization_controller.py     # Key issue/rotate/revoke, operator login
└── admin_controller.py             # Page data assembly for templates
```

**The central/instance split is enforced here.** `category_controller`,
`subcategory_controller` and `asset_controller` are the *only* modules permitted to
write to the central collections. `reference_controller`, `override_controller` and
`catalog_controller` operate exclusively on `instance_*` collections and must not
import the three central controllers or the central repositories. An import-lint test
in `tests/test_layering.py` asserts this — it is the mechanical guarantee behind
"an app can never modify central data".

Controllers raise domain errors from `utils/errors.py`. They never raise
`HTTPException` and never touch `Request` or `Response`.

---

## 7. `database/`

```
database/
├── __init__.py
├── connection.py           # Motor client singleton, get_db() dependency, health check
├── collections.py          # Named collection accessors — no string literals elsewhere
├── indexes.py              # Declarative index definitions, applied at startup
├── repository.py           # CentralRepository / InstanceRepository base classes
├── seed.py                 # First-run seed data (allowed paths, root admin)
└── models/
    ├── __init__.py
    ├── common.py           # PyObjectId, TimestampMixin, MongoModel, Page
    ├── category.py         # CategoryCreate / Update / Out / InDB
    ├── subcategory.py
    ├── asset.py
    ├── more_fields.py      # Discriminated union: audio, image, video, json, frames
    ├── frames.py           # Placeholder: x, y, width, height, elevation, rotation
    ├── app_instance.py
    ├── instance_content.py # Reference rows: source_id, is_enabled, sequence,
    │                       # is_premium, views, downloads, overrides
    ├── api_key.py
    ├── admin_user.py
    └── analytics.py        # MonitoredEndpoint, AnalyticsEvent, HourlyRollup
```

**`models/`** holds Pydantic schemas only — no database calls. Each entity gets four
shapes: `Create`, `Update` (all optional), `Out` (API response), `InDB` (storage).
Don't collapse them into one.

**`repository.py`** exposes two base classes. `InstanceRepository` binds only to
`instance_*` collections and raises at construction if handed a central collection.
Writes to `categories`, `subcategories` and `assets` are reachable solely through
`CentralRepository`.

**`connection.py`** is imported by controllers and `inits`, never by routers.

---

## 8. `inits/`

Server construction. Nothing here contains feature logic — it wires parts together.

```
inits/
├── __init__.py
├── server.py               # create_app() -> FastAPI
├── lifespan.py             # Startup/shutdown: connect Mongo, build indexes,
│                           # load allowed_paths, start analytics drain + rollup jobs
├── register_routers.py     # Mounts router/ modules onto the app
├── register_middlewares.py # Adds middlewares in the correct order
├── register_static.py      # Mounts /static and the admin CSS from templates/
├── register_handlers.py    # Exception handlers, domain error -> HTTP mapping
└── register_docs.py        # OpenAPI metadata, tags, security scheme
```

`main.py` stays three lines:

```python
from inits.server import create_app

app = create_app()
```

**Middleware order matters** and is fixed in `register_middlewares.py`, outermost
first:

1. `request_id` — every log line needs it
2. `error_handler` — must wrap everything below
3. `cors`
4. `authorization_middleware` — resolve the key before analytics records who called
5. `analytics_middleware` — innermost, so it measures real handler time

---

## 9. `middlewares/`

```
middlewares/
├── __init__.py
├── request_id_middleware.py      # Generates/propagates X-Request-ID
├── authorization_middleware.py   # Reads X-API-Key, resolves key, attaches to state
├── analytics_middleware.py       # Times the request, queues an event if monitored
├── rate_limit_middleware.py      # Applies the key's per-minute limit
├── error_middleware.py           # Catches unhandled errors, returns the error envelope
└── cors_middleware.py
```

`authorization_middleware` resolves and attaches; it does **not** reject on missing
scope — that's the route's `require_scope` dependency, which knows what the route
needs. It does reject a missing, malformed, expired or revoked key with 401.

`analytics_middleware` asks `analytics.allowed_paths.is_monitored(...)` and does
nothing at all when the answer is no. It never awaits a database write in the
request path.

---

## 10. `router/`

Endpoints only. Path, dependencies, response model, one controller call.

```
router/
├── __init__.py
├── deps.py                     # Shared dependencies: db, current key, pagination
├── health_router.py            # /health, /ready
├── v1/
│   ├── __init__.py             # api_v1 = APIRouter(prefix="/api/v1")
│   ├── category_router.py
│   ├── subcategory_router.py
│   ├── asset_router.py
│   ├── media_router.py         # /uploads, /frames/detect
│   ├── app_instance_router.py
│   ├── reference_router.py     # /app-instances/{id}/references
│   ├── instance_content_router.py  # PATCH, reset-overrides, DELETE, reorder, flags
│   ├── catalog_router.py       # /instance/{id}/catalog, /track
│   ├── analytics_router.py
│   └── key_router.py
└── admin/
    ├── __init__.py             # admin = APIRouter(prefix="/admin")
    ├── auth_routes.py
    ├── dashboard_routes.py
    ├── category_routes.py
    ├── subcategory_routes.py
    ├── asset_routes.py
    ├── instance_routes.py
    ├── analytics_routes.py
    └── settings_routes.py
```

There is deliberately **no** create endpoint under `reference_router` or
`instance_content_router`. An app instance cannot author content; instance-scoped
creates return `409 INSTANCE_CANNOT_CREATE_CONTENT` pointing at the central endpoint.

Admin routes return `TemplateResponse`; v1 routes return JSON. Never mix.

---

## 11. `static/`

Served directly. Mounted at `/static`.

### `static/central_data/` — the central library's media

Mirrors the Category → Subcategory → Asset hierarchy on disk, so a human can find a
file without querying Mongo.

```
static/central_data/
└── {category_id}/
    ├── _category/
    │   ├── thumbnail.webp
    │   └── image.webp
    └── {subcategory_id}/
        ├── _subcategory/
        │   ├── thumbnail.webp
        │   └── image.webp
        └── {asset_id}/
            ├── thumbnail.webp
            ├── source.png              # single-file assets
            └── more_fields/
                ├── {block_key}/        # one folder per moreFields block
                │   ├── 00_audio.mp3
                │   ├── 01_audio.mp3
                │   └── data.json
                └── frames/
                    ├── frame.png
                    └── placeholders.json   # cached detection output
```

Rules:

- Folders are named by **ObjectId**, never by display name — names change, IDs don't.
- Filenames are content-hashed on write; re-uploading an identical file reuses the
  existing object rather than duplicating it.
- Media belongs to **central assets only**. An app instance never writes here, since
  it never creates content. Its overrides reference existing central URLs or media
  uploaded through the central asset editor.
- `placeholders.json` is a cache of the detection proposal. The authoritative
  coordinates live in the asset's `more_fields.frames` document in Mongo.
- Deleting an asset soft-deletes the document; files are removed by a scheduled
  reaper in `scripts/` after the recovery window, never inline.

### `static/app_data/` — per-app-instance files

```
static/app_data/
└── {app_instance_id}/
    ├── icon.png
    └── icon_thumbnail.webp
```

Only app-level branding lives here: the icon, and any future per-app branding asset.
Content media never appears under `app_data/` — that would mean an app owns content,
which it does not.

---

## 12. `templates/`

Admin panel markup and styles. Jinja2. No frontend framework.

```
templates/
├── base.html                   # <html data-theme>, nav, theme toggle, blocks
├── partials/
│   ├── nav_drawer.html         # expanded+ breakpoint
│   ├── nav_rail.html           # medium breakpoint
│   ├── nav_bottom.html         # compact breakpoint
│   ├── topbar.html
│   ├── pagination.html
│   ├── data_table.html         # collapses to stacked cards under 600px
│   ├── bulk_result_table.html  # per-row created / skipped / failed
│   ├── override_badge.html     # "Edited for this app" + reset action
│   ├── confirm_dialog.html
│   └── flash.html
├── auth/
│   └── login.html
├── dashboard/
│   └── index.html
├── categories/
│   ├── list.html
│   ├── form.html
│   └── bulk.html
├── subcategories/
│   ├── list.html
│   ├── form.html
│   └── bulk.html
├── assets/
│   ├── list.html
│   ├── form_single.html        # single-file asset, bulk-capable
│   ├── form_multi.html         # multi-file asset, individual only
│   ├── more_fields_editor.html
│   └── frames_editor.html      # canvas overlay + coordinate inputs
├── instances/
│   ├── list.html
│   ├── form.html
│   ├── content.html            # references, reorder, enable, premium
│   ├── picker.html             # choose from the central library
│   ├── override_form.html
│   └── unresolved.html         # references whose source was deleted
├── analytics/
│   ├── dashboard.html
│   └── allowed_paths.html      # manage the monitoring list
├── keys/
│   ├── list.html
│   └── created.html            # one-time full-key reveal
├── settings/
│   └── index.html
├── errors/
│   ├── 404.html
│   └── 500.html
├── css/
│   ├── tokens.css              # generated from color_palette.md — single source of color
│   ├── base.css                # reset, type scale, layout primitives
│   ├── components.css          # buttons, tables, forms, chips, dialogs
│   ├── admin.css               # page-specific rules
│   └── responsive.css          # 600 / 905 / 1240 breakpoints
└── js/
    ├── theme.js                # light/dark toggle, localStorage "ui.theme"
    ├── bulk.js                 # CSV parse, drag-drop, staging table
    ├── frames.js               # placeholder drag/resize/rotate/elevation
    ├── reorder.js              # drag ordering, posts sequence
    ├── picker.js               # library selection tree
    └── table.js                # selection, filters, stacked-card behaviour
```

`templates/css` and `templates/js` are mounted read-only at `/admin-assets` by
`inits/register_static.py`, keeping admin styling next to the markup it belongs to
while `static/` stays reserved for uploaded content.

`tokens.css` must match `color_palette.md` exactly. Changing one without the other is
a bug. No hardcoded hex values anywhere outside `tokens.css`.

---

## 13. `utils/`

Stateless helpers. No database, no request context, no cycles.

```
utils/
├── __init__.py
├── errors.py               # AppError hierarchy: NotFound, Conflict, Validation, Forbidden
├── responses.py            # Envelope builders: page(), error(), bulk_result()
├── ids.py                  # ObjectId <-> str, validation, PyObjectId
├── datetimes.py            # utc_now(), ISO serialization
├── slugify.py              # filename -> display name cleanup for bulk asset naming
├── file_utils.py           # Magic-byte sniffing, content hashing, safe filenames
├── image_utils.py          # Dimensions, thumbnail generation, alpha analysis
├── frame_detector.py       # Transparent-region -> rotated bounding boxes
├── csv_utils.py            # Bulk import parsing with per-row error reporting
├── pagination.py           # PageParams, skip/limit math
├── sequencing.py           # Step-of-10 sequence assignment and reordering
└── validators.py           # Shared Pydantic validators
```

`frame_detector.py` is CPU-bound and synchronous. Controllers must call it through
`anyio.to_thread.run_sync` so it never blocks the event loop.

---

## 14. `tests/`, `migrations/`, `scripts/`

```
tests/
├── conftest.py                 # Fresh DB per test, app fixture, key fixtures
├── test_layering.py            # Import-lint: instance code cannot reach central repos
├── controller/
├── router/
├── analytics/
├── authorization/
├── utils/
└── fixtures/
    ├── frames/                 # Known images + expected placeholder coordinates
    └── csv/

migrations/
├── 0001_initial_indexes.py
├── 0002_seed_allowed_paths.py
└── runner.py                   # Tracks applied migrations in a collection

scripts/
├── create_admin.py
├── issue_key.py
├── rebuild_rollups.py
└── reap_orphan_media.py        # Deletes files past the recovery window
```

Tests mirror the source tree one-for-one. `test_layering.py` is not optional — it is
what mechanically prevents an app instance from ever writing to central data.

---

## 15. Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Folders | lowercase singular, as listed above | `controller/`, `router/` |
| Module files | `snake_case` with a role suffix | `asset_controller.py`, `key_router.py` |
| Mongo collections | plural snake_case | `instance_assets` |
| Mongo fields | snake_case | `sub_category_id` |
| API JSON fields | camelCase via Pydantic alias | `subCategoryId`, `moreFields` |
| CSS custom properties | `--md-*` for M3 roles, `--app-*` for domain roles | `--app-premium` |
| Template files | `snake_case.html`, grouped by feature | `instances/content.html` |
| Error codes | SCREAMING_SNAKE | `INSTANCE_CANNOT_CREATE_CONTENT` |

One module per concern. When a controller passes ~400 lines, split it by use case
rather than adding a `_helpers.py`.