# 🧠 Comprehensive Project Memory & Architectural Reference (`Memory.md`)

> **Single Source of Truth** for the Creative Asset Library & App Instance Management Platform.  
> **Purpose:** This document provides an exhaustive, authoritative reference for the architecture, data models, business logic, endpoints, asset processing pipelines, and chronological changelog of the entire codebase. Future modifications should reference this file directly without needing to re-analyze the entire codebase.
>
> **Last Updated:** October 26, 2026 (Instance content page scales with large instances)

---

## 📑 Table of Contents

1. [High-Level Overview & Core Philosophy](#1-high-level-overview--core-philosophy)
2. [Dual-Domain Data Architecture](#2-dual-domain-data-architecture)
   - [Central Library (Global Content Domain)](#21-central-library-global-content-domain)
   - [App Instance Working Sets (Client Delivery Domain)](#22-app-instance-working-sets-client-delivery-domain)
   - [Sparse Overrides & Standalone Custom Folders](#23-sparse-overrides--standalone-custom-folders)
3. [User Roles, Authentication & Portals](#3-user-roles-authentication--portals)
   - [Super Admin Portal (`/admin`)](#31-super-admin-portal-admin)
   - [Manager Portal (`/manager`)](#32-manager-portal-manager)
   - [Client Mobile/Web API (`/api/v1`)](#33-client-mobileweb-api-apiv1)
   - [Interactive Developer Docs (`/docs`, `/redoc`)](#34-interactive-developer-docs-docs-redoc)
4. [Database Collections & Schemas (MongoDB / Motor)](#4-database-collections--schemas-mongodb--motor)
5. [Asset Pipeline & Supported Media Formats](#5-asset-pipeline--supported-media-formats)
   - [Supported Formats (Images, Videos, Animations, HTML)](#51-supported-formats)
   - [Alpha Transparency, Non-Destructive Cropping & GIF Dither Suppression](#52-alpha-transparency-non-destructive-cropping--gif-dither-suppression)
   - [OpenCV Transparent Frame Placeholder Detection](#53-opencv-transparent-frame-placeholder-detection)
   - [HTML Asset Support & Iframe Sandboxing](#54-html-asset-support--iframe-sandboxing)
6. [App Instance Hierarchy & Import Workflow](#6-app-instance-hierarchy--import-workflow)
   - [Auto-Tab Switching in Content Pickers](#61-auto-tab-switching-in-content-pickers)
   - [Scoped Import into Target Folders](#62-scoped-import-into-target-folders)
   - [Custom Folder Creation (Admin & Manager)](#63-custom-folder-creation-admin--manager)
   - [Detaching & Reference Removal](#64-detaching--reference-removal)
   - [Tagging, Reordering, and Monetization Overrides](#65-tagging-reordering-and-monetization-overrides)
7. [API Endpoints Reference](#7-api-endpoints-reference)
   - [Client API (`/api/v1`)](#71-client-api-apiv1)
   - [Admin Portal Endpoints (`/admin`)](#72-admin-portal-endpoints-admin)
   - [Manager Portal Endpoints (`/manager`)](#73-manager-portal-endpoints-manager)
8. [Chronological Project Changelog & All Updates Done](#8-chronological-project-changelog--all-updates-done)
9. [Project Directory Tree & Key File Map](#9-project-directory-tree--key-file-map)
10. [Configuration, CLI Scripts & Operational Rules](#10-configuration-cli-scripts--operational-rules)

---

## 1. High-Level Overview & Core Philosophy

The **Creative Asset Library & App Instance Management Platform** is a multi-tenant backend built with **FastAPI**, **MongoDB (Motor)**, **OpenCV**, and **Pillow**.

### Primary Problems Solved:
1. **Author Once, Deploy Everywhere:** Creative digital assets (photo frames, stickers, collage templates, fonts, video overlays, background patterns, and interactive HTML widgets) are uploaded and organized centrally in a global catalog.
2. **Multi-App Multi-Tenant Delivery:** Multiple independent client applications (e.g., "Photo Editor Pro", "Collage Maker iOS", "Romantic Frames Android") consume tailored subsets of the central library without duplicating physical files or database records.
3. **Decoupled Customization:** Client app instances can customize display names, thumbnails, ordering sequences, visibility, tags, and monetization tiers (`free`, `premium`, `rewarded`) without mutating central data.
4. **Autonomous Manager Workspaces:** Product managers can independently manage their assigned app instances, organize folders, import central assets, manage rate limits, and generate API keys without requiring Super Admin intervention for daily operations.

---

## 2. Dual-Domain Data Architecture

The platform strictly separates content authoring from content delivery through a dual-domain model:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          CENTRAL ASSET CATALOG (Global)                          │
│                                                                                  │
│   Category ────────────────────► Subcategory ────────────────────► Asset         │
│   (e.g., "Frames")               (e.g., "Love Frames")             (e.g., SVG/PNG)│
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
                   Referenced by source_id │ (Zero Data Duplication)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   APP INSTANCE WORKING SET (e.g., "Photo Editor iOS")             │
│                                                                                  │
│   Instance Category ───────────► Instance Subcategory ──────────► Instance Asset │
│   • source_id (or None if custom) • source_id (or None)         • source_id      │
│   • is_enabled, sequence          • is_enabled, sequence        • is_enabled     │
│   • sparse overrides{}            • sparse overrides{}          • sequence       │
│                                                                 • is_premium     │
│                                                                 • is_rewarded    │
│                                                                 • overrides{}    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Central Library (Global Content Domain)
- **Hierarchy:** `Super Category` (optional) → `Category` → `Subcategory` → `Asset`. Only categories link upward (`categories.super_category_id`); subcategories, assets and storage paths are unaware of the super level. Categories may stay ungrouped.
- **Single Source of Truth:** Central assets, categories, and subcategories cannot be deleted or mutated by app instances.
- **Physical Media Storage:** Stored in `/static/central_data/` partitioned by content type (`images`, `videos`, `frames`, `html`, etc.).

### 2.2 App Instance Working Sets (Client Delivery Domain)
- Represents an individual deployed mobile or web client application (identified by a unique `app_instance_id` and unique `package_name` like `com.company.photoeditor`).
- Collections: `instance_categories`, `instance_subcategories`, `instance_assets`.
- An instance links to central items via `source_id`.

### 2.3 Sparse Overrides & Standalone Custom Folders
1. **Sparse Overrides Pattern:** If an instance changes the title of an asset, the original document is never cloned. The instance doc stores `overrides: {"name": "Custom Title"}`. The API dynamically overlays overrides upon central records via `get_resolved_assets()`.
2. **Custom / Standalone Folders:**
   - App instances can have custom Category and Subcategory folders created directly within the instance.
   - For custom folders, `source_id = None`. Their canonical identifier is their own MongoDB `_id`.
   - Subcategories and assets can be imported from the central library directly into these custom folders.

---

## 3. User Roles, Authentication & Portals

### 3.1 Super Admin Portal (`/admin`)
- **Access:** Global administrative privileges.
- **Features:**
  - Complete control of central catalog (`Categories`, `Subcategories`, `Assets`).
  - Single asset upload & multi-asset bulk upload with real-time image cropping and video poster generation.
  - Transparent frame placeholder detection and bounding box coordinate generator.
  - App Instance creation, configuration, and direct working set editing.
  - Manager governance: approve/reject manager registrations, grant/revoke instance access, review instance creation requests.
  - Global API key management and dual-layer rate limit configuration.
  - Admin messaging inbox with manager broadcast/direct response capability.
  - Platform-wide analytics dashboard, bandwidth tracking, and error logs.
- **Session:** Signed HTTP-only cookie `admin_session` verified via `authorization/admin_session.py`.

### 3.2 Manager Portal (`/manager`)
- **Access:** Product Managers, App Producers, and Content Curators.
- **Features:**
  - Login, profile management, and optional TOTP 2FA.
  - View only assigned/accessible App Instances.
  - Request access to other existing App Instances with optional operator notes.
  - Submit requests to create new App Instances (subject to Admin approval).
  - Manage working set content:
    - Create top-level Category folders (`/folders/create`).
    - Create nested Subcategory folders inside existing or custom categories.
    - Central Library Picker with automatic tab switching (`/picker`).
    - 1-Click quick import of entire categories, subcategories, or individual assets.
    - Import central data directly into target categories and subcategories.
    - Drag-and-drop sequencing for folders, subcategories, and assets.
    - Monetization controls: toggle `is_premium`, `is_rewarded`, and set `rewarded_credits`.
    - Single and bulk asset tagging with live DOM updates.
    - Detach folders and assets safely without mutating central records.
  - Manage API keys for assigned instances (create, revoke, configure IP limits and surge ceilings).
  - Dedicated Manager Analytics: view impressions, downloads, bandwidth, and daily trend charts.
  - Direct 2-way messaging with Admin operators.
- **Session:** Signed HTTP-only cookie `manager_session` verified via `authorization/manager_session.py`.

### 3.3 Client Mobile/Web API (`/api/v1`) & Protected Media
- **Audience:** iOS, Android, Flutter, React Native, Unity, and Web client apps.
- **Authentication Channels:**
  1. `X-API-Key` HTTP Header (standard for mobile apps and programmatic REST clients).
  2. Query Parameter `api_key`, `apiKey`, or `key` (e.g. `?api_key=ak_...` — required for Chrome URL bar navigation, browser image tabs, and standard HTML `<img src="...">` / `<video>` / `<audio>` tags).
  3. `Authorization: Bearer <key>` or `Authorization: ApiKey <key>`.
- **Protected Static Media Security (`/static/central_data/...`):**
  - All creative assets in `/static/central_data/` (thumbnails, images, videos, audios, animations, documents, and interactive HTML widgets) strictly require API key authentication or an active `admin_session`/`manager_session` cookie. Direct unauthenticated access without an API key returns `401 Unauthorized`.
  - Public static assets are strictly limited to the default fallback thumbnail (`/static/thumbnail_default.png`), user profile avatars (`/static/profiles/`), and app icons (`/static/app_data/`).
- **Dual-Layer Rate Limiting:**
  1. *Per-Client IP Limit (`user_ip_limit`):* Default 60 requests/minute per client IP.
  2. *App-Wide Surge Ceiling (`app_surge_ceiling`):* Default 10,000 requests/minute across all users of the app.
- **Media Resolution:** Root-relative paths (e.g. `/static/central_data/...`) that clients prepend with the server origin.

### 3.4 Interactive Developer Docs (`/docs`, `/redoc`)
- OpenAPI documentation endpoints (`/docs`, `/redoc`, `/openapi.json`) are secured via **HTTP Basic Authentication** using `DOCS_USERNAME` and `DOCS_PASSWORD`.

---

## 4. Database Collections & Schemas (MongoDB / Motor)

Database Name: `admin_assets_db` (configured via `MONGODB_DB_NAME`).

| Collection Constant | MongoDB Collection Name | Description | Key Fields & Indexes |
|---|---|---|---|
| `SUPER_CATEGORIES` | `super_categories` | Central optional top level grouping categories | `_id`, `name`, `folder_name` (`_super/<slug>`), `thumbnail_url`, `image_url`, `sequence`, `deleted_at`. Unique ci index on `name`. |
| `CATEGORIES` | `categories` | Central library categories (`super_category_id`: optional parent) | `_id`, `name`, `thumbnail_url`, `sequence`, `is_enabled`, `deleted_at`. Unique index on `name` where `deleted_at: null`. |
| `SUBCATEGORIES` | `subcategories` | Central library subcategories | `_id`, `category_id`, `name`, `thumbnail_url`, `sequence`, `is_enabled`, `deleted_at`. Compound index on `(category_id, name)`. |
| `ASSETS` | `assets` | Central library assets | `_id`, `category_id`, `sub_category_id`, `name`, `type` (`image`, `video`, `html`, etc.), `file_url`, `thumbnail_url`, `tags`, `frame_metadata`, `deleted_at`. |
| `APP_INSTANCES` | `app_instances` | Client app delivery configurations | `_id`, `name`, `package_name`, `owner_id`, `is_active`, `created_at`. Unique index on `package_name`. |
| `INSTANCE_SUPER_CATEGORIES` | `instance_super_categories` | Super categories linked or created in an app instance | `_id`, `app_instance_id`, `source_id` (ObjectId or None), `name`, `sequence`, `is_enabled`, `overrides: {}`, `deleted_at`. Unique `(app_instance_id, source_id)`. |
| `INSTANCE_CATEGORIES` | `instance_categories` | Categories linked or created in an app instance (`super_category_id` → instance super category `_id`, or None) | `_id`, `app_instance_id`, `source_id` (ObjectId or None), `name`, `sequence`, `is_enabled`, `overrides: {}`, `deleted_at`. Compound index on `(app_instance_id, source_id)`. |
| `INSTANCE_SUBCATEGORIES` | `instance_subcategories` | Subcategories linked or created in an app instance | `_id`, `app_instance_id`, `source_id` (ObjectId or None), `category_id` (parent link), `name`, `sequence`, `is_enabled`, `overrides: {}`, `deleted_at`. |
| `INSTANCE_ASSETS` | `instance_assets` | Assets linked into an app instance | `_id`, `app_instance_id`, `source_id`, `category_id`, `sub_category_id`, `sequence`, `is_enabled`, `is_premium`, `is_rewarded`, `rewarded_credits`, `tags`, `overrides: {}`, `deleted_at`. |
| `MANAGERS` | `managers` | Product manager operator accounts | `_id`, `username`, `email`, `password_hash`, `is_active`, `status`, `two_factor_enabled`, `totp_secret`, `created_at`. |
| `MANAGER_ACCESS_REQUESTS`| `manager_access_requests` | Requests for instance access or creation | `_id`, `manager_id`, `request_type` (`access_instance`, `create_instance`), `app_instance_id`, `status` (`pending`, `approved`, `rejected`), `notes`. |
| `MANAGER_MESSAGES` | `manager_messages` | In-app messaging between managers & admins | `_id`, `sender_type` (`manager`, `admin`), `sender_id`, `recipient_id`, `subject`, `message`, `is_read`, `created_at`. |
| `API_KEYS` | `api_keys` | Authenticated client app API keys | `_id`, `key_prefix`, `key_hash`, `app_instance_id`, `owner_id`, `scopes`, `user_ip_limit`, `app_surge_ceiling`, `status` (`active`, `revoked`). |
| `ANALYTICS_EVENTS` | `analytics_events` | Raw client tracking events (`view`, `download`) | `_id`, `app_instance_id`, `asset_id`, `event_type`, `client_ip`, `user_agent`, `created_at`. Time-series or 30-day TTL. |
| `ANALYTICS_ROLLUPS` | `analytics_rollups` | Pre-aggregated daily/monthly metrics | `_id`, `app_instance_id`, `date`, `total_views`, `total_downloads`, `unique_ips`. |

---

## 5. Asset Pipeline & Supported Media Formats

### 5.1 Supported Formats
The platform supports five primary categories of assets:
1. **Static Images:** `PNG`, `JPG`, `JPEG`, `WEBP`.
2. **Videos:** `MP4`, `WEBM`, `MOV` (with automatic FFmpeg duration, dimensions, and poster frame extraction).
3. **Animations:** `GIF`, `APNG`, Animated `WEBP`, and Lottie `JSON` animations.
4. **Interactive HTML:** `.html` / `text/html` rich widgets, mini-games, and custom web components.
5. **Documents & Generic Files:** `.xml`, `.pdf`, `.txt`, `.csv`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.zip`, `.rar`, `.7z`, `.tar`, `.gz`, and arbitrary documents with automatic MIME classification, default document thumbnail assignment, download/preview links, and dedicated filter tags.

### 5.2 Alpha Transparency, Non-Destructive Cropping & GIF Dither Suppression
- **Zero Background Contamination:** The media cropper strictly preserves transparent PNG/WEBP alpha channels. Cropping operations never apply black or white letterbox fills.
- **Animated GIF Dither Suppression & Clean Transparency:**
  - Standard quantization dithering can introduce speckles, banding, and dirty grayish edges around transparent pixels in animated GIFs.
  - Implemented `clean_frame_dither(frame)` in `controller/crop_controller.py` and `scripts/crop_media.py`:
    - **Palette Mode (`P`):** Inspects the frame's color palette and maps all near-black color entries ($R, G, B \le 15$) to true black $(0, 0, 0)$, eliminating dark fringe noise.
    - **RGBA / RGB Mode:** Quantizes using `Image.Quantize.FASTOCTREE` with `dither=Image.Dither.NONE`.
  - GIF export enforces `dither=Image.Dither.NONE`, `optimize=False`, and frame disposal `disposal=2` (restore background) across all frames. This completely prevents frame ghosting, dirty pixel trails, or re-dithering across animated cycles.
- **Aspect Ratio Locking & Video Codec Alignment:**
  - Common presets (`1:1`, `4:5`, `9:16`, `16:9`, Freeform) are supported in both UI modal croppers and CLI tools.
  - Video cropping via FFmpeg automatically forces even dimensions ($w \% 2 == 0, h \% 2 == 0$) required by `libx264` (`yuv420p`), preserves AAC audio tracks (or strips audio via `-an` if silent), and attaches `+faststart` metadata for instant progressive streaming.
- **Unified Standalone CLI Tool:** `scripts/crop_media.py` provides an offline/batch CLI command mirroring the full cropper pipeline for images, animated GIFs, and videos.

### 5.3 OpenCV Transparent Frame Placeholder Detection
- Located in `controller/frame_controller.py` and `utils/frame_extractor.py`.
- **Workflow:**
  1. Inspects image alpha channel (`cv2.split(img)[3]`).
  2. Identifies completely transparent regions (`alpha == 0`).
  3. Uses contour detection and polygon bounding box approximation to find user photo insertion placeholders.
  4. Extracts normalized coordinate ratios (`left`, `top`, `width`, `height`) and exports structured frame layout JSON for client photo-framing apps.

### 5.4 HTML Asset Support & Iframe Sandboxing
- Supported via asset type `"html"`.
- Validates file extensions (`.html`) and MIME type (`text/html`).
- Generates or allows custom thumbnail assignments for UI cards.
- Previews render inside sandboxed iframes (`sandbox="allow-scripts"`) to prevent CSS/JS leakage into Admin and Manager dashboards.

---

## 6. App Instance Hierarchy & Import Workflow

### 6.1 Auto-Tab Switching in Content Pickers
When navigating to the Central Content Picker from an App Instance working set:
- **Clicking "📥 Import Central Data" on a Category Folder:**  
  URL: `/instances/{id}/picker?target_category_id={cat_id}&tab=subcategories`  
  *Result:* The picker opens with the **Subcategories (Sub-folders)** tab active, allowing the operator to select central subcategories to import into that specific category.
- **Clicking "📥 Import" on a Subcategory Folder:**  
  URL: `/instances/{id}/picker?target_category_id={cat_id}&target_sub_category_id={sub_id}&tab=assets`  
  *Result:* The picker opens with the **Individual Assets** tab active, with a prominent banner confirming the target folder is active. Selected assets are placed directly into that subcategory.

### 6.2 Scoped Import into Target Folders
Implemented in `controller/reference_controller.py` (`add_references`):
1. **Target Category Resolution:**  
   If `target_category_id` is supplied, the system inspects `INSTANCE_CATEGORIES` for matching `_id` or `source_id`.
   - If pointing to a custom created folder (`source_id: None`), `cat_link_id = target_inst_cat["_id"]`.
   - If pointing to a central reference, `cat_link_id = target_inst_cat["source_id"]`.
2. **Target Subcategory Resolution:**  
   If `target_sub_category_id` is supplied, `sub_link_id` is similarly resolved.
3. **Asset Assignment:**  
   When central assets are imported into a target subcategory, `INSTANCE_ASSETS` documents are created (or updated if already present) with:
   ```json
   {
     "category_id": cat_link_id,
     "sub_category_id": sub_link_id
   }
   ```
   This guarantees that assets appear strictly under the desired parent folder in the app instance working set.

### 6.3 Custom Folder Creation (Admin & Manager)
- Endpoint: `POST /{admin|manager}/instances/{id}/folders/create`
- **Category Folder:**
  - Validates name uniqueness within the app instance (case-insensitive regex).
  - Automatically calculates next sequence (`compute_next_sequence`).
  - Sets `source_id: None` to mark it as an instance-native folder.
- **Subcategory Folder:**
  - Requires a valid parent category within the instance (`parent_category_id`).
  - Sets `category_id` to the parent folder's identifier.
  - Sets `source_id: None`.

### 6.4 Detaching & Reference Removal
- Endpoints:
  - `DELETE /{admin|manager}/instances/{id}/categories/{cat_id}`
  - `DELETE /{admin|manager}/instances/{id}/subcategories/{sub_id}`
  - `DELETE /{admin|manager}/instances/{id}/assets/{assetId}`
- Soft-deletes (`deleted_at: utc_now()`) or removes references in a cascading fashion (detaching a category also detaches all child subcategories and assets in that instance).
- **Central Library data is never modified or deleted.**

### 6.5 Tagging, Reordering, and Monetization Overrides
- **Bulk & Single Tagging:** `POST /{admin|manager}/instances/{id}/assets/bulk-tags` supports `add`, `replace`, and `remove` operations with instant client DOM updates.
- **Drag-and-Drop Reordering:** `POST /{admin|manager}/instances/{id}/reorder` updates integer sequences for folders, subcategories, or assets.
- **Monetization Tiers:** Managed via `PATCH /{admin|manager}/instances/{id}/assets/{assetId}/override`:
  - `is_premium: true|false`
  - `is_rewarded: true|false`
  - `rewarded_credits: integer`

---

## 7. API Endpoints Reference

### 7.1 Client API (`/api/v1`)
All endpoints require `X-API-Key: <key>` header.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/instance/{instanceId}/catalog` | Preload entire enabled hierarchy (Categories → Subcategories → Assets) |
| `GET` | `/api/v1/instance/{instanceId}/categories` | List active categories for this app instance |
| `GET` | `/api/v1/instance/{instanceId}/subcategories` | List subcategories (optional filter: `?categoryId=...`) |
| `GET` | `/api/v1/instance/{instanceId}/assets` | Paginated assets list (filters: `categoryId`, `subCategoryId`, `type`, `search`) |
| `GET` | `/api/v1/instance/{instanceId}/assets/{assetId}` | Get single asset details with overrides applied |
| `POST` | `/api/v1/instance/{instanceId}/events` | Ingest analytics tracking events (`view`, `download`) |
| `GET` | `/api/v1/search` | Full-text and tag search across accessible catalog assets |

### 7.2 Admin Portal Endpoints (`/admin`)
Requires `admin_session` cookie.

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/dashboard` | Main system dashboard with KPI metrics and recent activity |
| `GET/POST` | `/admin/categories` | Manage central categories (list, create, edit, delete; accepts `page_size`, `pageSize`, `limit`: 20-200, default 20) |
| `GET/POST` | `/admin/subcategories`| Manage central subcategories (list, create, edit, delete; accepts `categoryId`, `page_size`: 20-200, default 20) |
| `GET/POST` | `/admin/assets` | Central asset library (upload, filter, delete; accepts `page_size`: 20, 40, 60, 100, 200 up to 500) |
| `GET` | `/admin/instances` | List and create App Instances |
| `GET` | `/admin/instances/{id}/content` | App instance working set management (folders & assets) |
| `GET` | `/admin/instances/{id}/picker` | Central content picker with auto-tab switching |
| `POST` | `/admin/instances/{id}/references` | Import central categories, subcategories, or assets |
| `POST` | `/admin/instances/{id}/folders/create` | Create custom category or subcategory folder in instance |
| `DELETE` | `/admin/instances/{id}/categories/{catId}` | Detach category folder from instance |
| `DELETE` | `/admin/instances/{id}/subcategories/{subId}` | Detach subcategory folder from instance |
| `DELETE` | `/admin/instances/{id}/assets/{assetId}` | Detach asset reference from instance |
| `GET/POST` | `/admin/managers` | Approve/reject manager registrations and assign instances |
| `GET/POST` | `/admin/messages` | Admin-manager messaging threads and direct replies |
| `GET/POST` | `/admin/keys` | Generate and manage global API keys |

### 7.3 Manager Portal Endpoints (`/manager`)
Requires `manager_session` cookie.

| Method | Path | Description |
|---|---|---|
| `GET` | `/manager/dashboard` | Manager overview of assigned instances and aggregate traffic |
| `GET` | `/manager/instances` | List accessible instances and request access to others |
| `GET` | `/manager/instances/{id}/content` | Manage working set, custom folders, and asset overrides |
| `GET` | `/manager/categories` | Manager view of central categories (supports `page_size`, `pageSize`, `limit`: 20-200) |
| `GET` | `/manager/subcategories` | Manager view of central subcategories (supports `categoryId`, `page_size`: 20-200) |
| `GET` | `/manager/assets` | Manager central asset catalog (filter by cat/sub/type/search; supports `page_size`: 20-200) |
| `GET` | `/manager/instances/{id}/picker` | Manager central content picker (with auto-tab routing) |
| `GET` | `/manager/instances/{id}/picker/categories` | JSON search for central categories |
| `GET` | `/manager/instances/{id}/picker/subcategories` | JSON search for central subcategories |
| `GET` | `/manager/instances/{id}/picker/assets` | JSON search for central assets |
| `POST` | `/manager/instances/{id}/references` | Import central items into instance or target folders |
| `POST` | `/manager/instances/{id}/folders/create` | Create custom category or subcategory folder in instance |
| `DELETE` | `/manager/instances/{id}/categories/{cat_id}` | Detach category folder and child items from instance |
| `DELETE` | `/manager/instances/{id}/subcategories/{sub_id}` | Detach subcategory folder from instance |
| `DELETE` | `/manager/instances/{id}/assets/{assetId}` | Detach individual asset from instance |
| `PATCH` | `/manager/instances/{id}/assets/{assetId}/override` | Update sequence, premium flag, rewarded credits, tags |
| `POST` | `/manager/instances/{id}/assets/bulk-tags` | Batch add, remove, or replace tags on assets |
| `POST` | `/manager/instances/{id}/reorder` | Drag-and-drop sequencing of folders or assets |
| `GET/POST` | `/manager/keys` | Create and manage API keys for accessible instances |
| `GET/POST` | `/manager/messages` | Send and view messages to/from Super Admin operators |

---

## 8. Chronological Project Changelog & All Updates Done

### Update 1: Interactive HTML Asset Support
- Added `.html` / `text/html` asset format support across central upload forms (`templates/assets/form_single.html`, `templates/assets/form_multi.html`).
- Added MIME type detection and validation in `controller/asset_controller.py`.
- Implemented secure iframe sandbox viewing for HTML assets in list views and detail modals.
- Updated API response serialization to provide HTML file links and thumbnail cards.

### Update 2: Destination Folder Import Fix (`reference_controller.py`)
- **Problem:** When importing central subcategories or assets into a custom created folder in an App Instance, the system previously ignored the destination folder and re-created the original central category.
- **Fix:** Refactored `add_references` in `controller/reference_controller.py`:
  - Added resolution logic for `target_category_id` and `target_sub_category_id`.
  - Checks `INSTANCE_CATEGORIES` for matching `_id` (custom folders with `source_id: None`) or `source_id`.
  - Links imported subcategories and assets directly to `target_category_link_id` and `target_sub_category_link_id`.
  - Handled re-importing existing assets by updating their destination links rather than duplicating them.

### Update 3: Automatic Tab Switching in Content Picker
- Updated Admin content view (`templates/instances/content.html`):
  - "Import Central Data" button on Category card links to `&tab=subcategories`.
  - "Import" button on Subcategory card links to `&tab=assets`.
- Updated Admin picker view (`templates/instances/picker.html`):
  - Reads `tab` URL parameter on `DOMContentLoaded`.
  - Automatically switches to the `Subcategories` or `Assets` tab and displays the active target folder banner.

### Update 4: Manager Custom Folder Creation & Picker Implementation
- Added backend routes in `router/manager/instance_routes.py`:
  - `GET /{instance_id}/picker`: Manager picker template response.
  - `GET /{instance_id}/picker/categories`, `subcategories`, `assets`: JSON query endpoints.
  - `POST /{instance_id}/references`: Manager import handler.
  - `POST /{instance_id}/folders/create`: Manager category & subcategory folder creation.
  - `DELETE /{instance_id}/categories/{cat_id}`, `subcategories/{sub_id}`, `assets/{assetId}`: Detach endpoints.
- Created `templates/manager/instances/picker.html`:
  - Full-featured picker UI extending `"manager/base.html"` with 1-click quick-import, bulk selection, and auto-tab activation.
- Updated `templates/manager/instances/content.html`:
  - Added "+ Create Folder" header button and "+ New Folder / Sub-folder" section button.
  - Added "📥 Import Central Data", "+ Add Sub-folder", and "Detach Folder" to category cards.
  - Added "📥 Import" and "Detach" to subcategory cards.
  - Added `createFolderModal` markup and JavaScript AJAX handlers.

### Update 5: XML and Generic Document File Support in Asset Blocks
- **Allowed Document Extensions:** Added `.xml`, `.pdf`, `.txt`, `.csv`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.zip`, `.rar`, `.7z`, `.tar`, `.gz` to `ALLOWED_DOCUMENT_EXTENSIONS` and `ALLOWED_EXTENSIONS` in `config/constants.py`.
- **MIME Sniffing & XML Detection:** Enhanced `utils/file_utils.py` to identify XML magic headers (`<?xml` and arbitrary `<...></...>`) as `application/xml` alongside document MIME mappings.
- **Pydantic Validation Models:** Added `FileItem`, `FileBlock`, and `FileListBlock` to `database/models/more_fields.py` and included in the `TypedBlock` discriminated union.
- **Upload Processing:** Updated `controller/media_controller.py` to recognize documents and assign `DEFAULT_DOCUMENT_THUMBNAIL_URL` (`/static/thumbnail_default.png`) without attempting video/image rasterization.
- **Filtering & Search:** Updated `controller/asset_controller.py` (`build_asset_type_filter` and `asset_has_type`) to query and filter `file`, `files`, `document`, `xml`, and `doc` assets across MongoDB polymorphic blocks.
- **Multi-Asset Form (`templates/assets/form_multi.html`):**
  - Added "File / Document Block" option to block type selector.
  - Added document icon 📁, file size & filename display, and "↗ View" direct link.
  - Excluded documents from image/video cropping tools.
- **Single-Asset Form (`templates/assets/form_single.html`):**
  - Added "📁 Files / Documents" bulk ingest checkbox card.
  - Updated `classifyFile` to identify document files and automatically package them as a `file` block.
- **Asset List Views:** Added "Files / Docs" filter option to Admin and Manager asset catalog views.

### Update 6: Fix "Add Block" Button in Multi-Asset Form
- **Scoping Fix in `renderPayloadBlocks()` (`templates/assets/form_multi.html`):**
  - The variable `isNonCroppable` was previously declared inside the `items.map(...)` callback. When adding any new payload block, `items` is initially empty (`[]`), causing `items.map` not to execute.
  - As a result, the subsequent dropzone HTML template evaluation of `${!isNonCroppable ? ... : ''}` threw a fatal JavaScript `ReferenceError: isNonCroppable is not defined`.
  - Moved `const isNonCroppable` to the parent `if (isMediaBlock)` block level so it is properly defined even when a block has zero items, restoring the `+ Add Block` rendering behavior for all block types.

### Update 7: GIF Dithering Artifact Suppression & Media Cropper Overhaul
- **Problem:** When cropping animated GIFs with transparency or gradients, Pillow's default palette quantization created visible dithering speckles, grayish fringing, and background ghosting where prior animation frames bled into subsequent cycles.
- **Root Cause & Resolution:**
  - Added `clean_frame_dither(frame)` in `controller/crop_controller.py`:
    - Palette mode (`P`): Clamps near-black RGB color values ($R, G, B \le 15$) in the frame palette to true black $(0, 0, 0)$, eliminating speckle artifacts around transparent contours.
    - RGBA/RGB mode: Quantizes frames with `Image.Quantize.FASTOCTREE` and explicit `dither=Image.Dither.NONE`.
  - Exported GIF frames using `dither=Image.Dither.NONE`, `optimize=False`, and frame disposal `disposal=2` (restore background), preventing transparent backgrounds from retaining ghosted pixels across frames.
- **Standalone Media Cropper CLI (`scripts/crop_media.py`):**
  - Added standalone CLI utility supporting images (`PNG`, `WEBP`, `JPEG`), animated GIFs (`GIF`), and videos (`MP4`, `WEBM`, `MOV`, `AVI`, `MKV`).
  - Implements ratio crops (`--ratio`) with alignment (`center`, `top`, `bottom`) and manual rectangles (`--crop x,y,w,h`).
  - Enforces even dimensions ($w \% 2 == 0, h \% 2 == 0$) with H.264 / AAC and `+faststart` metadata for video output.

### Update 8: Dynamic Pagination & Per-Page Item Size Selector
- **Configurable `page_size` in Admin & Manager Routes:**
  - Updated `router/admin/category_routes.py`, `router/admin/subcategory_routes.py`, `router/admin/asset_routes.py`, and `router/manager/central_data_routes.py` (`manager_categories`, `manager_subcategories`, `manager_assets`).
  - Accepts query parameters `page_size`, `pageSize`, or `limit` with safe bounds: $\min=1, \max=500$ (standard options: `20`, `40`, `60`, `100`, `200`, default: `20`).
- **Reusable Pagination Component (`templates/partials/pagination.html`):**
  - Added "Show: [20 / 40 / 60 / 100 / 200] per page" selector dropdown.
  - Added inline client-side handler `changePaginationPageSize(size)` that preserves existing query parameters while updating `page_size` and resetting `page=1`.
- **Integrated Filter Bar Selectors:**
  - Added per-page selector dropdowns to asset list filter headers in both Admin (`templates/assets/list.html`) and Manager (`templates/manager/assets/list.html`).
  - Preserves selected `page_size` across category/subcategory filtering, type selections, search queries, and "Clear" resets.

### Update 9: Instance Isolation Sanitization & Assigned Instance ID Resolution
- **Issue 1: Instance Mismatch Error Sanitization:**
  - Updated `authorization/instance_guard.py` (`get_instance_filter`): When an API key bound to an app instance is used against a mismatched instance ID, the error response no longer leaks the original bound instance ID or requested instance ID in error messages or details.
  - Standardized the exception to `ForbiddenError("API key not matching with the instance, verify again.")` with empty details.
  - Added instance filter guard validation to `/app-instances/{id}` endpoints in `router/v1/instance_content_router.py`.
- **Issue 2: Uniform Invalid API Key Message:**
  - Updated `authorization/api_key.py` (`verify_api_key`): When secret hash verification fails, replaced the error message `"Invalid API key secret"` with `"Invalid API key"` to prevent disclosing internal key validation stages to callers.
- **Issue 3: Assigned App Instance ID Resolution & Central ID Stripping:**
  - **Resolution Pipeline (`controller/catalog_controller.py`):**
    - Removed `sourceId` and central IDs from client-facing responses across `get_resolved_categories`, `get_resolved_subcategories`, `get_resolved_assets`, `get_resolved_single_asset`, and `get_instance_catalog`.
    - Added MongoDB `$lookup` joins on `INSTANCE_CATEGORIES` and `INSTANCE_SUBCATEGORIES` to dynamically resolve assigned parent `_id` values (`categoryId`, `subCategoryId`) so client apps can query hierarchy trees seamlessly using only assigned instance IDs.
    - Updated query filter matching (`match_filter`) to transparently match both assigned `_id`s and `source_id`s.
  - **Reference Ingestion (`controller/reference_controller.py`):**
    - Updated `add_category_reference`, `add_subcategory_references`, and `import_assets_to_instance` so imported subcategories and assets store their parents' assigned `instance_categories._id` and `instance_subcategories._id`.
  - **Custom Folder Creation (`router/admin/instance_routes.py` & `router/manager/instance_routes.py`):**
    - Enforced `cat_link_id = parent_cat["_id"]` for newly created subfolder items.
  - **Pydantic Response Schemas (`database/models/instance_content.py`):**
    - Removed `source_id` / `sourceId` fields from `ResolvedCategoryOut`, `ResolvedSubcategoryOut`, and `ResolvedAssetOut`.
  - **Database Migration (`scripts/migrate_instance_ids.py`):**
    - Backfilled existing `instance_subcategories` and `instance_assets` documents to reference assigned instance category and subcategory `_id`s.
  - **Asset Response Field Deduplication (`controller/catalog_controller.py` & `database/models/instance_content.py`):**
    - Removed duplicate camelCase keys (`categoryName`, `subCategoryName`, `thumbnailUrl`, `moreFields`), retaining canonical snake_case fields (`category_name`, `subcategory_name`, `thumbnail_url`, `more_fields`).

### Update 10: Error Telemetry Detail Modal & PKT Timezone Formatting
- **Error Details Modal Client-Side Cache & Serialization:**
  - In `templates/analytics/dashboard.html` and `templates/manager/analytics/dashboard.html`, embedded preloaded `recent_errors` datasets into client-side templates (`recentErrorsJson` / `mgrRecentErrorsJson`).
  - Updated `viewErrorDetails` and `viewManagerErrorDetails` to look up error details directly from the in-memory cache first, eliminating `TypeError: Failed to fetch` errors while retaining network fetch as a fallback.
  - In `router/admin/analytics_routes.py` and `router/manager/analytics_routes.py`, wrapped event detail responses with `serialize_mongo_doc()` to prevent JSON serialization errors on MongoDB `ObjectId` or nested structures.
- **Pakistan Standard Time (PKT) Formatting:**
  - Added `format_pkt_datetime(val)` and `PKT_TIMEZONE = timezone(timedelta(hours=5))` in `utils/datetimes.py`.
  - Converted UTC timestamps across `analytics/reporter.py` (`recent_errors`, `reasons_breakdown`, `get_analytics_event_details`) to PKT (`%Y-%m-%d %H:%M:%S PKT`).
### Update 11: Accurate Live Asset and Sub-folder Counts for App Instances
- **Root Cause Diagnosis:**
  - In `router/admin/instance_routes.py` and `router/manager/instance_routes.py`, `cat["subcategories_count"]`, `cat["assets_count"]`, and `sub["assets_count"]` were computed via isolated `count_documents` queries with a single `ObjectId`.
  - Because `sourceId` was intentionally projected out of client-facing resolved schemas, queries only looked up `cat["id"]` or `sub["id"]`, missing database documents where `category_id` or `sub_category_id` held central `source_id` references or string representations. This caused folder badges to report `0 Assets` and `0 Sub-folders` even when items were present.
- **Unified Live Aggregation:**
  - Updated both `admin_instance_content_view` and `manager_instance_content` to compute counts directly from the resolved `all_subcategories` and `all_instance_assets` hierarchies (`sub_asset_counts`, `cat_asset_counts`, `cat_sub_counts`).
  - Added robust database fallbacks searching all candidate IDs (`_id` and `source_id`, both `ObjectId` and string formats) if any folder reports zero counts.
- **Automated Startup Reconciliation:**
  - Integrated `reconcile_instance_links(db)` into application startup in `inits/lifespan.py`, automatically linking any unmigrated instance subcategory or asset references to their assigned instance `_id`s.
- **Ingestion ID Safety:**
  - Fixed `inserted_id` attribute access in `controller/reference_controller.py` (lines 95, 156, 315, 380) to safely handle `ObjectId` returns from `InstanceRepository.insert_one`.

### Update 12: Media Security & Multi-Channel API Key Protection for Thumbnails and Media Files
- **Problem:**
  - Thumbnails (`thumb_*`, `thumbnail_*`) and shallow media paths (`len(rel_parts) <= 3`) were previously marked as public in `is_public_static_path()`, allowing unauthenticated users to view images, covers, and thumbnails by entering direct `/static/central_data/...` URLs in Chrome without any API key or session.
  - Media requests only checked the HTTP header `X-API-Key`, which prevented users from viewing media directly in Chrome URL address bars or standard HTML media tags where custom request headers cannot be set.
- **Root Cause & Resolution:**
  - **Closed Static Media Bypass (`middlewares/authorization_middleware.py`):**
    - Removed public whitelist exceptions for `thumb_`, `thumbnail_`, and category/subcategory depth rules in `is_public_static_path()`.
    - Protected all media files under `/static/central_data/` (thumbnails, images, videos, audios, animations, documents, HTML widgets).
    - Public access is strictly restricted to `/static/thumbnail_default.png`, `/static/profiles/`, and `/static/app_data/`.
  - **Multi-Channel API Key Extraction (`extract_api_key`):**
    - Supports API key authentication across three complementary channels:
      1. `X-API-Key` or `x-api-key` HTTP Header (used by Android, iOS, Flutter, and REST client libraries).
      2. Query Parameters `api_key`, `apiKey`, or `key` (e.g., `?api_key=ak_...` — allows direct access in Chrome address bar, browser tabs, `<img src="...">`, `<video>`, `<audio>` tags, and media downloads).
      3. `Authorization: Bearer <key>` or `Authorization: ApiKey <key>`.
  - **Session-Aware Web Portal Rendering:**
    - Preserved automatic access for active `admin_session` and `manager_session` cookies, ensuring Admin (`/admin`) and Manager (`/manager`) dashboards render media and thumbnails without requiring explicit API keys in template URLs.
  - **Uniform API Route Support:**
    - Applied `extract_api_key` to `/api/v1` routes as well, enabling developers to test API endpoints via query parameters in browsers alongside standard header authentication.

### Update 13: Admin & Manager Portal Anti-Inspection Protection
- **Requirement:** Prevent inspection of web dashboard pages via mouse right-click or developer keyboard shortcuts.
- **Implementation:**
  - Created client-side security controller in `templates/js/security.js` mounted at `/admin-assets/js/security.js`.
  - Included `<script src="/admin-assets/js/security.js"></script>` in `<head>` across all base layouts (`templates/base.html` and `templates/manager/base.html`).
  - **Right-Click Suppression:** Intercepts and cancels `contextmenu` events globally (`e.preventDefault()`, `e.stopPropagation()`), blocking browser context menu options ("Inspect", "Inspect Element", "View Page Source").
  - **Keyboard Shortcut Interception:** Captures and suppresses:
    - `F12` (DevTools shortcut across browsers)
    - `Ctrl + Shift + I` / `Cmd + Option + I` (Inspect Elements)
    - `Ctrl + Shift + J` / `Cmd + Option + J` (DevTools Console)
    - `Ctrl + Shift + C` / `Cmd + Option + C` (Element Picker)
    - `Ctrl + Shift + K` / `Ctrl + Shift + E` (Firefox Console & Network Monitor)
    - `Ctrl + U` / `Cmd + Option + U` (View Page Source)
    - `Ctrl + S` (Save Page HTML)
  - **Element Dragging Prevention:** Prevents dragging sensitive images and link elements outside the viewport.
  - **Anti-Debugging Protection:** Integrates a periodic debugger trap (`Function('debugger')()`) that halts script execution if DevTools is forced open via browser application menus.

### Update 14: Subcategory & Category Cross-Folder Duplication, Import Marked Badges, Clickable App Instance Rows & Asset Table Column Sizing
- **Requirement 1: Allow Duplicate Subcategories and Categories Across Folders in an App Instance:**
  - **Root Cause:** In `database/indexes.py`, `instance_subcategories` had a unique index on `("app_instance_id", 1), ("source_id", 1)` (`uniq_instance_subcategory_source`), and `instance_assets` had `("app_instance_id", 1), ("source_id", 1)` (`uniq_instance_asset_source`). In addition, `controller/reference_controller.py` checked existence using `{"app_instance_id": inst_oid, "source_id": s_oid}` globally. When a user tried to import or copy the same subcategory into Category 2, the unique index and queries re-parented or blocked the subcategory, removing it from Category 1.
  - **Resolution:**
    - Dropped old instance-wide unique indexes and replaced with parent-hierarchy compound unique indexes:
      - `instance_subcategories`: `[("app_instance_id", 1), ("category_id", 1), ("source_id", 1)]` (`uniq_instance_subcat_parent_source`).
      - `instance_assets`: `[("app_instance_id", 1), ("category_id", 1), ("sub_category_id", 1), ("source_id", 1)]` (`uniq_instance_asset_hierarchy_source`).
      - Non-unique reverse lookup index on `[("app_instance_id", 1), ("source_id", 1)]` retained for fast source lookups.
    - Updated `controller/reference_controller.py` (`add_references` and `copy_references_from_instance`):
      - Query filters now check `{"app_instance_id": inst_oid, "category_id": cat_link_id, "source_id": s_oid}` for subcategories, and `{"app_instance_id": inst_oid, "category_id": cat_link_id, "sub_category_id": sub_inst_id, "source_id": a_oid}` for assets.
      - Category imports into target folders cleanly create and populate subcategories and assets under the target category without overwriting or moving existing instances in other categories.
- **Requirement 2: Mark Already Added Content in Central Import Picker:**
  - **Backend Support (`router/admin/instance_routes.py` & `router/manager/instance_routes.py`):**
    - `admin_instance_picker`, `admin_instance_picker_categories`, `admin_instance_picker_subcategories`, `admin_instance_picker_assets` (and their Manager portal counterparts) now query existing instance references (`instance_categories`, `instance_subcategories`, `instance_assets`).
    - Added booleans:
      - `already_added`: Item is linked anywhere within this app instance.
      - `already_in_target`: Item is linked specifically into the active target folder (`target_category_id` / `target_sub_category_id`).
  - **Frontend UI (`templates/instances/picker.html` & `templates/manager/instances/picker.html`):**
    - Categories & subcategories that are already added show a prominent `✓ Already Added` badge with green accent border and subtle background tint.
    - Assets grid dynamically renders `✓ In target` or `✓ Added` badges and green outline styling on cards.
- **Requirement 3: Clickable App Instance Rows & Remove "+ Add Central Data" Column Button:**
  - In `templates/instances/list.html` and `templates/manager/instances/list.html`:
    - Removed `+ Add Central Items` from the table row action column.
    - Added `.clickable-row` styling (`cursor: pointer; transition: background-color 0.15s;`) to each `<tr>`.
    - Clicking anywhere on the row navigates directly to browse the content of that app (`/admin/instances/{id}/content` or `/manager/instances/{id}/content`).
    - Action buttons (`Browse Content`, `Edit`, `Delete`) stop event propagation so button clicks execute their intended actions without conflicting with row navigation.
- **Requirement 4: Eliminate Horizontal Scrolling in Referenced Assets Table via Column Sizing:**
  - In `templates/instances/content.html` and `templates/manager/instances/content.html`:
    - Added dedicated CSS class `.instance-assets-table` and `.manager-instance-assets-table` reducing cell padding from `0.9rem 1rem` to `0.45rem 0.35rem`, saving over 300px of wasted whitespace across 12-13 columns.
    - Explicit compact widths assigned to all numeric and toggle columns:
      - Drag handle: `28px`
      - Seq: `48px`
      - Thumb: `44px`
      - Views / Downloads: `50px`
      - Enabled / Premium / Rewarded toggles: `46px`
      - Credits: `52px`
      - Actions: `130px` (Admin) / `75px` (Manager)
    - Applied text ellipsis truncation to Asset Name, Description, Category, Subcategory, and Tags so table naturally fits standard desktop/laptop displays (>= 950px) without horizontal scrollbar. Responsive horizontal overflow container retained for small screens.

### Update 14: App Instance Preview Modal, Styled Rename Popup, `isPriced` Flag, Clear Filters & Folder-Scoped Import Marking
- **Requirement 1: Original Asset Preview Modal on App Instance Page:**
  - Added click handler `openAssetPreviewModal('{{ asset.source_id or asset.sourceId or asset.id }}')` to asset thumbnails in both Admin (`templates/instances/content.html`) and Manager (`templates/manager/instances/content.html`) portals with hover pointer cue.
  - Enhanced `templates/partials/asset_preview_modal.html` with dynamic portal route awareness (`/manager/api/...` vs `/api/...`) and a responsive embedded `more_fields` inspector (`#previewEmbeddedMoreFields`).
  - Added visual rendering for all `more_fields` polymorphic blocks: images, audio (with playback), video (with playback), generic files/documents, text, colors, and key-values.
  - For Frames and Templates: added embedded canvas rendering that draws color-coded bounding boxes over the base image alongside an interactive table of placeholder coordinates (X, Y, W, H, Rotation, Aspect Ratio, z-index).
  - In `controller/asset_preview_controller.py`: added root-level `coordinates` and `placeholders` normalization into the standard `frames` block, and fallback resolution from instance asset docs to central asset docs via `source_id`.
  - In `templates/css/components.css`: increased `.asset-preview-modal-container` max-width to `780px` to fit coordinates table and canvas stages comfortably.
  - **Manager Asset Preview Route Fix (404 Resolution):** Mounted `@router.get("/api/assets/{asset_id}/preview")` in `router/manager/dashboard_routes.py` so it resolves at `/manager/api/assets/{asset_id}/preview` matching frontend modal requests (previously shadowed under `/manager/instances/...`). Also made `refreshAssetPreviewStats` portal-aware and hid the admin-only Interactive Editor link from manager modals.
- **Requirement 2: Custom Material 3 Popup Modal for Asset Renaming:**
  - Replaced the browser native `prompt(...)` dialog with a styled Material 3 modal `#renameAssetModal` in both Admin and Manager instance content pages.
  - Includes backdrop blur, input autofocus with text auto-selection, Enter key submission, Escape key dismissal, and async save with loading spinner.
- **Requirement 3: `isPriced` (`is_priced`) Flag & Decoupled Credits Editing:**
  - Added `is_priced` toggle flag column alongside `is_premium` and `is_rewarded` in Admin and Manager referenced asset tables.
  - Decoupled credit value editing: the credits input field is enabled exclusively when `is_priced` is enabled (independent of `is_rewarded`).
  - In `controller/catalog_controller.py`: resolved `is_priced` from `overrides.is_priced` or asset root `is_priced`, and projected it in API outputs.
  - In `controller/override_controller.py`, `router/admin/instance_routes.py`, and `router/manager/instance_routes.py`: added support for updating and persisting `is_priced` in `overrides.is_priced`.
- **Requirement 4: Auto-Clear Filters on App Instance Assets List:**
  - Added `autocomplete="off"` to the filter form and dropdowns in `templates/instances/content.html` and `templates/manager/instances/content.html`.
  - Added URL query param checks on tab switch (`switchInstanceTab('assets')` / `switchTab('assets')`) and page load (`DOMContentLoaded`) to explicitly reset `assetCategorySelect` and `assetSubCategorySelect` when no category filter is active in the URL.
- **Requirement 5: Folder-Scoped "Already Added" Marking in Central Import Picker:**
  - In `router/admin/instance_routes.py` and `router/manager/instance_routes.py`: resolved comprehensive `valid_target_cat_keys` (handling both ObjectId and string representations of `_id` and `source_id`) to compute `target_sub_ids` and `target_asset_ids`.
  - In `templates/instances/picker.html` and `templates/manager/instances/picker.html`:
    - Updated subcategory cards to evaluate `{% set is_sub_marked = (sub.already_in_target if target_category_id else sub.already_added) %}`.
    - Subcategories existing in `category1` are NOT labeled "Already Added" or highlighted in green when importing into empty `category2`; they show clean cards with "⚡ Import Subcategory".
    - Updated asset card JavaScript rendering to scope card borders and badges to `isAlreadyInTarget` whenever a target destination folder is active.
    - Added explicit `target_cat_oid = to_object_id(target_category_id) if target_category_id else None` in `admin_instance_picker` to guarantee safe initialization across all request pathways.

### Update 15: Shared Admin/Manager Instance Workspace Controller (SOLID / DRY Refactor)
- **Problem:** `router/admin/instance_routes.py` and `router/manager/instance_routes.py` duplicated ~1,000 lines of business logic (content view counts/filters, picker "already added" marking, folder creation, import/override payload parsing), so every fix had to be applied twice.
- **Resolution:** Moved the shared logic into `controller/instance_workspace_controller.py`:
  - `build_instance_content` (folders, live counts, filters, name fallbacks), `build_picker_page`, `picker_categories`, `picker_subcategories`, `picker_assets`, `create_instance_folder`, `parse_reference_payload`, `parse_asset_override_payload`.
  - Routers now only do auth / `verify_manager_instance_access` and rendering. Folder creation errors raise `ValidationError`, which routes turn into `400 {"success": false, "message": ...}`.
- **Behavior changes (intentional parity):** Admin asset search now also matches tags, and the Admin asset override accepts `tags` (both were Manager-only before).
- **Bug fix:** Admin `POST /admin/instances/{id}/edit` was raising `NameError` (missing `AppInstanceUpdate` import).
- **Rule:** Any new instance working-set logic goes in `instance_workspace_controller.py`, never in a portal router.

### Update 16: `add_references` Split into Per-Kind Importers
- **Problem:** `add_references` in `controller/reference_controller.py` was a single 715-line function that repeated the same "find link → restore if soft-deleted → else insert with next sequence → handle DuplicateKeyError" block 9 times across its category, subcategory, and asset branches.
- **Resolution:** Same file, same public signature and return shape:
  - `_ensure_link(db, coll, key, now)`: one find-or-create for any instance reference; the sequence scope is the key minus `source_id`, and asset docs get monetization/analytics defaults. Inserts still go through `InstanceRepository`, so the central-collection guard applies.
  - `_restore_target`: resolves a target folder by `_id` or `source_id` and revives it if soft-deleted (the asset-import target subcategory is also re-parented).
  - `_import_category`, `_import_subcategory`, `_import_asset`, `_link_asset`: one function per import kind. `add_references` is now about 15 lines of dispatch.
- **Verified:** old vs new produced identical counts and identical `instance_*` state across 11 import scenarios on a seeded throwaway DB. `tests/test_add_references.py` is the lasting check.
- **Only behavior change:** on the concurrent-insert race (`DuplicateKeyError`) path, selected/child items now always count as `already_present` (the old code was inconsistent there). Auto-added parents still don't count.

### Update 17: Single `ASSET_TYPE_RULES` Table for Asset Type Filtering
- **Problem:** `build_asset_type_filter` (MongoDB query, central asset lists) and `asset_has_type` (in-memory, app instance content page) each kept their own `if/elif` chain over 7 types with hand-copied regexes and excluded-type lists. These had drifted apart, so the same type filter could give different results on the central and instance pages. For example, `.flac/.opus/.wma` matched audio only in the DB, and frames found by their `/frames/` URL or MIME matched only in the DB.
- **Resolution (`controller/asset_controller.py`):**
  - `ASSET_TYPE_RULES`: one entry per type (`aliases`, `own` block types, `key`/`url`/`mime` regexes). Each type's excluded block types are derived as "every other type's `own`" rather than listed by hand.
  - Both functions read the same table and regexes. The DB filter's rules were kept as the source of truth, and the in-memory check now mirrors them.
  - **Adding a type = adding one table entry.**
- **Behavior changes:** the in-memory check now matches the DB filter (all 8 audio extensions, frame URL/MIME, document MIME, `data` must be an object for JSON). Both now treat `file`/`file_list` blocks as their own type, so a `.png` inside a `file` block counts as a file, not an image.
- **Verified:** identical match sets on all 213 dev-DB central assets for every alias, before and after. `tests/test_asset_type_rules.py` asserts DB filter == in-memory check == expected on fixtures covering every type and the old drift cases.

### Update 18: Central-Data Isolation Enforced (Guard Helper + Static Test)
- **Audit result:** no instance-scoped module writes to `categories` / `subcategories` / `assets`. Every raw central write is an Admin central-library operation (bulk actions, CSV updates, asset toggle/reset). The invariant held, but nothing enforced it.
- **Decision:** the ~250 raw `db[...]` calls were **not** mass-converted to repositories. `BaseRepository` silently adds `deleted_at: None` to finds and updates, which would break the restore-soft-deleted lookups, and the conversion would add no protection that the guard below doesn't already give.
- **Changes:**
  - `database/repository.py`: `instance_collection(db, name)` is a raw collection handle (no soft-delete filtering) that raises `ValueError` for central collections.
  - Every write whose collection is a *variable* now goes through it: `reference_controller.py`, `instance_workspace_controller.py`, `override_controller.py`.
  - `tests/test_instance_isolation.py`: AST scan of instance modules (reference/override/workspace/catalog controllers, admin instance routes, all manager routes, v1 instance content/reference routers). It fails on a raw central write, on a dynamic `db[var]` write, or on `CentralRepository` use. Mutation-checked: an injected violation is reported.
- **Open finding (not changed):** `/api/v1/reorder` and `/api/v1/assets` write *central* data, gated only by the `assets:write` scope. API keys with scope `*` (one exists in the dev DB, bound to an app instance) can therefore reorder or edit the central library. Decide whether app-bound keys should ever get central write scope.

### Update 19: Optional 4th Level — Super Categories (Super Category → Category → Subcategory → Asset)
- **Design:** only categories point up (`categories.super_category_id`, `instance_categories.super_category_id`). Subcategories, assets, storage paths and all existing `category_id` links are untouched. One instance category per central category, as before; its super category is a movable parent link.
- **Central (Admin):**
  - `controller/super_category_controller.py`: CRUD; unpaginated (marked `ponytail:`).
  - `router/admin/super_category_routes.py` and `templates/super_categories/list.html`. `templates/categories/form.html` is reused via `entity_label`/`base_path`; media goes under `central_data/_super/<slug>/`.
  - Category form: Super Category dropdown. Category list: Super column and `superCategoryId` filter. Nav: drawer and rail.
  - Deleting a super category is refused while categories are assigned. After deletion, apps keep their categories, ungrouped.
- **Instance flow (Admin & Manager, via `instance_workspace_controller.py`):**
  - `add_references(super_category_ids=…, target_super_category_id=…)`. Importing a super category brings all its categories and their contents.
  - A *newly* added category auto-joins its central super category (auto-added, like parent categories for subcategories). `target_super_category_id` places or moves imported categories.
  - Custom folders: `folder_type: "supercategory"`, plus `parent_super_category_id` for categories.
  - Move or ungroup: `POST /{admin|manager}/instances/{id}/categories/{catId}/super`. Detach (cascades to its categories): `DELETE /{admin|manager}/instances/{id}/super-categories/{superId}`.
  - Overrides, reorder and bulk flags accept `item_type: "super_category"` (`override_controller._collection_for`, which replaced 4 duplicated ternaries).
  - UI: shared partials `instance_super_categories.html` (strip with All / Ungrouped / per-super filters, import, add, detach), `category_super_select.html` (per-category move) and `picker_super_categories_tab.html` (picker tab). The create-folder modal gains the Super Category level.
- **Client API (additive, non-breaking):**
  - `GET /api/v1/{instance|app-instances}/{id}/super-categories`.
  - `?superCategoryId=` on categories endpoints; every category has `superCategoryId`.
  - `/catalog` gains `super_categories[]`, each with `categoryIds`.
  - `DELETE /api/v1/app-instances/{id}/super-categories/{superId}` (with instance guard).
- **Tests:** `tests/test_super_categories.py` covers central → import → auto-parent → target/move → custom folders → catalog → detach cascade → guarded delete. All 48 existing route cases and all `add_references` scenarios are unchanged on data without super categories.
- **Known gaps (pre-existing, not fixed):**
  - `copy_references_from_instance` copies parent ids verbatim (so copied subcategories and assets point at the source app's folders) and does not copy super categories.
  - `API_Usage.md` examples still show the removed `sourceId`.

### Update 20: Category → Super Category Placement Fix & API Key Instance Isolation
- **Bug:** inside an app instance, a category could only be placed in a super category already linked to *that app*. With central super categories but none in the app, the per-card selector didn't render and the create-folder list was empty. Category cards were also `draggable`, which could swallow clicks on the selector.
- **Fix:**
  - The selector and the create-folder dialog also list central super categories not yet in the app (optgroup "Central library"). Picking one links it in and places the category in it: `reference_controller.link_super_category`, used by `instance_workspace_controller._instance_super_id`.
  - Focusing the selector switches its card's drag off (`setCardDraggable`).
  - The content strip explains how to start when the app has no super categories.
- **API key isolation (security):**
  - Router-level dependencies in `authorization/instance_guard.py` replace per-route calls.
  - `require_instance_access` covers every `/api/v1/app-instances/{id}/…` and `/api/v1/instance/{id}/…` route. Previously 13 instance routes (PATCH/DELETE/reorder/bulk-flags/track/unresolved/references) let a key bound to app A act on app B. `copy-from` also checks the *source* app.
  - `require_unbound_key` covers `/api/v1/keys` and `/api/v1/app-instances`. Previously a bound key with `*` could list every app or mint an unbound `*` key.
  - Admin sessions and unbound keys behave as before.
  - `tests/test_api_key_isolation.py` exercises this over HTTP through the real middleware. Mutation-checked: removing a guard fails it.
- **Still open:** app-bound keys with `assets:write` / `categories:write` can still write the *central* library (`/api/v1/assets`, `/categories`, `/subcategories`, `/reorder`, `/media/*`).

### Update 21: App Instance Content Page — Speed, Layout & Super-Category Blocks (Admin & Manager)
- **Speed:** `instance_workspace_controller.py` no longer runs per-folder `count_documents` loops.
  - `_group_counts` does one `$group` aggregation per (collection, field). It is used for the content page's folder badge fallback counts and for `picker_categories` / `picker_subcategories`. The manager content page calls both on every load; their per-subcategory `ASSETS.sub_category_id` counts were unindexed collection scans.
  - Server-rendered thumbnails use `loading="lazy"`.
- **Layout:**
  - `.card` is `flex-direction: column`, so cards that need a row must set `flex-direction:row` inline (sub-folder cards do).
  - Sub-folder grids use `repeat(auto-fill, minmax(260px, 1fr))`. Cards wrap their actions when tight, and long names end in an ellipsis.
  - More than 4 sub-folders: class `.subs-collapsed` hides `:nth-child(n+5)` (`!important`, to beat the cards' inline `display:flex`), and a "Show More (N)" button toggles it.
  - Each category shows its instance `id` (what client apps receive as `categories[].id`).
  - `.badge-primary` / `.badge-secondary` are now defined in `components.css`; they were used but unstyled.
- **Super-category blocks:** a super category holding 2+ of the shown categories renders as one collapsible `<details>` block. It is open when filtering by `folder_super`.
  - `build_instance_content` reorders `categories` so each super category's members sit together at its first member's position (a stable sort, keeping their sequence order).
  - The template opens and closes the block using `loop.previtem` / `loop.nextitem`.
  - Drag-reorder is unchanged: it saves the DOM order of all category cards. Dragging a card out of its block does not change its super category; use the ⭐ selector for that.
- **Client API:** no endpoint changes. The docs now explain grouping by `superCategoryId` / `categoryIds`.

### Update 22: App Instance Content Page — Scales With Large Instances (Admin & Manager)
- **Default view** (sequence order, no search/type filter): `build_instance_content` no longer loads every asset row into Python. It gets the total with `count_documents` and the page with `skip/limit` on the new `idx_instance_asset_live_sequence` index (`app_instance_id, deleted_at, sequence, _id`). The unfiltered query hints that index, because the planner otherwise picks an in-memory sort. If the index is missing, it falls back to the unhinted query.
- **Folder badge counts:** one `$group` over (`category_id`, `sub_category_id`) in MongoDB. Asset rows store instance folder ids, so these stored counts are the live ones.
- **Unresolved assets:** `dead_asset_row_ids` (catalog_controller) starts from soft-deleted central assets instead of running a `$lookup` per instance row. It is used for the content page exclusions and by `get_unresolved_references`. Rows pointing at hard-deleted central assets are not reported, since hard deletes already remove instance rows (`base_controller`).
- **`get_resolved_subcategories`:** the parent category is resolved in Python (`_folder_index` / `_pick_parent`) instead of an unindexable `$expr` `$lookup` per subcategory. Output is unchanged.
- **Measured (50k assets in one instance):** default page 2.2s → 0.17s, unresolved count 1.3s → 0.02s.
- **Still scanning every asset:** text search, type filter, and the name/newest/oldest/views/downloads sorts (~2–6s at 50k).

---

## 9. Project Directory Tree & Key File Map

```
/Admin Assets App
├── authorization/
│   ├── admin_session.py             # Admin cookie session signing & validation
│   ├── manager_session.py           # Manager cookie session signing & validation
│   └── encryption.py                # bcrypt password hashing & serializer tokens
├── config/
│   ├── settings.py                  # Pydantic environment configuration (.env)
│   ├── constants.py                 # Media formats, limits, defaults
│   └── paths.py                     # Static, templates, and upload directory paths
├── controller/
│   ├── asset_controller.py          # Central asset CRUD & upload validation
│   ├── super_category_controller.py # Central super categories (optional level above categories)
│   ├── category_controller.py       # Central category business logic
│   ├── subcategory_controller.py    # Central subcategory business logic
│   ├── reference_controller.py      # Instance reference linking & destination scoping
│   ├── override_controller.py       # Sparse field overrides, tags, monetization
│   ├── instance_workspace_controller.py # Shared Admin/Manager instance content, picker & folder logic
│   ├── manager_controller.py        # Manager auth, access verification, 2FA
│   ├── frame_controller.py          # Frame placeholder coordinate detection
│   └── crop_controller.py           # Alpha-preserving image, GIF (dither-free) & video cropper
├── database/
│   ├── collections.py               # MongoDB collection string constants
│   ├── connection.py                # Async Motor client singleton & get_database()
│   └── models/                      # Pydantic data schemas
├── router/
│   ├── admin/                       # Super Admin web routes (/admin/...)
│   │   ├── instance_routes.py       # Admin instance management & picker
│   │   ├── asset_routes.py          # Central asset routes (dynamic pagination)
│   │   ├── category_routes.py       # Central category routes (dynamic pagination)
│   │   └── subcategory_routes.py    # Central subcategory routes (dynamic pagination)
│   ├── manager/                     # Manager web routes (/manager/...)
│   │   ├── central_data_routes.py   # Manager central data browse (dynamic pagination)
│   │   ├── instance_routes.py       # Manager instance management, picker & folders
│   │   └── key_routes.py            # Manager API key issuance
│   └── v1/                          # Client REST API (/api/v1/...)
│       ├── catalog_router.py        # Full catalog preload
│       ├── instance_content_router.py# Scoped instance content delivery
│       └── media_router.py          # Media stream & download proxy
├── static/
│   └── central_data/                # Uploaded physical images, videos, frames
├── templates/
│   ├── base.html                    # Admin base layout (MD3 theme)
│   ├── partials/
│   │   └── pagination.html          # Shared pagination bar with dynamic page_size selector
│   ├── assets/
│   │   ├── list.html                # Admin asset catalog with page-size filter
│   │   ├── form_single.html         # Single asset upload modal/form
│   │   └── form_multi.html          # Multi-asset & polymorphic block upload form
│   ├── instances/
│   │   ├── content.html             # Admin instance working set UI
│   │   └── picker.html              # Admin central picker UI
│   └── manager/
│       ├── base.html                # Manager base layout
│       ├── assets/
│       │   └── list.html            # Manager asset catalog with page-size filter
│       └── instances/
│           ├── content.html         # Manager instance working set UI
│           └── picker.html          # Manager central picker UI
├── scripts/
│   ├── create_admin.py              # CLI: Bootstrap admin operator
│   ├── issue_key.py                 # CLI: Issue client API key
│   ├── crop_media.py                # CLI: Standalone image, GIF & video cropper
│   └── reap_orphan_media.py         # CLI: Clean unreferenced media files
└── main.py                          # ASGI application entrypoint
```

---

## 10. Configuration, CLI Scripts & Operational Rules

### 10.1 Key `.env` Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `ENV` | `development` | Runtime mode (`development` or `production`) |
| `PORT` | `8020` | Server HTTP listen port |
| `HOST` | `0.0.0.0` | Server bind host address |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection connection string |
| `MONGODB_DB_NAME` | `admin_assets_db` | Primary database name |
| `SECRET_KEY` | *(Required)* | High-entropy signing key |
| `ADMIN_SESSION_SECRET` | *(Required)* | Cookie encryption secret |
| `DOCS_USERNAME` | `admin` | HTTP Basic Auth user for `/docs` |
| `DOCS_PASSWORD` | *(Required)* | HTTP Basic Auth password for `/docs` |

### 10.2 Maintenance & Operational Invariants
1. **Never mutate Central Data during Instance Operations:** Creating, modifying, detaching, or reordering folders and assets in an App Instance must never touch the `categories`, `subcategories`, or `assets` collections. Enforced by `tests/test_instance_isolation.py`; use `instance_collection(db, name)` when the collection name is a variable.
2. **Access Control Verification:** Every manager endpoint under `/manager/instances/{id}` must call `await verify_manager_instance_access(db, user_id, instance_id)` before reading or mutating instance data.
3. **Preserve Alpha Transparency:** Any image cropping or resizing operation must maintain RGBA / alpha channels without introducing black or white background fills.
4. **GIF Dither Suppression & Clean Disposal:** Always use `clean_frame_dither(frame)`, `dither=Image.Dither.NONE`, and `disposal=2` (restore background) when saving multi-frame animated GIFs to avoid animation ghosting and quantization noise.
5. **Video Encoding Dimensions:** All video crops must enforce even dimensions ($w \% 2 == 0, h \% 2 == 0$) for H.264 compatibility, and attach `+faststart` metadata for streaming.
6. **Dynamic Pagination Limits:** All catalog listing endpoints must constrain `page_size` to $1 \le \text{page\_size} \le 500$ and support standard steps (20, 40, 60, 100, 200).
7. **Duplicate Name Guards:** Folder creation must verify case-insensitive uniqueness within that instance and parent category to prevent user confusion.
8. **Cascading Detach:** Detaching a category folder must soft-delete its child subcategories and referenced assets within that specific app instance. Detaching a super category detaches its categories the same way.
9. **Super Category Link Direction:** Only categories reference a super category (`super_category_id`). Never add super-category ids to subcategories, assets or storage paths.
