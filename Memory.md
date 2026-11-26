# 🧠 Comprehensive Project Memory & Architectural Reference (`Memory.md`)

> **Single Source of Truth** for the Creative Asset Library & App Instance Management Platform.  
> **Purpose:** This document provides an exhaustive, authoritative reference for the architecture, data models, business logic, endpoints, asset processing pipelines, and chronological changelog of the entire codebase. Future modifications should reference this file directly without needing to re-analyze the entire codebase.
>
> **Last Updated:** November 26, 2026 (Manager Direct Uploads -> Central Sync, App-Level Content Editing + Admin Proposal Review, Non-Destructive Manager Deletion, and 2FA API Key Reveal)

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
   - [Supported Formats (Images, SVG, Videos, Animations, HTML, Documents)](#51-supported-formats)
   - [Alpha Transparency, Non-Destructive Cropping & GIF Dither Suppression](#52-alpha-transparency-non-destructive-cropping--gif-dither-suppression)
   - [OpenCV Transparent Frame Placeholder Detection](#53-opencv-transparent-frame-placeholder-detection)
   - [HTML Asset Support & Iframe Sandboxing](#54-html-asset-support--iframe-sandboxing)
   - [Bulk Single-File Add, Asset-Name Grouping & Custom Block Keys (`moreFields`)](#55-bulk-single-file-add-asset-name-grouping--custom-block-keys-morefields)
6. [App Instance Hierarchy & Import Workflow](#6-app-instance-hierarchy--import-workflow)
   - [Auto-Tab Switching in Content Pickers](#61-auto-tab-switching-in-content-pickers)
   - [Scoped Import into Target Folders](#62-scoped-import-into-target-folders)
   - [Custom Folder Creation (Admin & Manager)](#63-custom-folder-creation-admin--manager)
   - [Detaching & Reference Removal](#64-detaching--reference-removal)
   - [Tagging, Reordering, and Monetization Overrides](#65-tagging-reordering-and-monetization-overrides)
   - [Tier & Frequency Distribution Engine (`N-1` Cap, Alternate Paid & Bulk Rules)](#66-tier--frequency-distribution-engine-n-1-cap-alternate-paid--bulk-rules)
7. [API Endpoints Reference](#7-api-endpoints-reference)
   - [Client API (`/api/v1`)](#71-client-api-apiv1)
   - [Admin Portal Endpoints (`/admin`)](#72-admin-portal-endpoints-admin)
   - [Manager Portal Endpoints (`/manager`)](#73-manager-portal-endpoints-manager)
8. [Chronological Project Changelog & All Updates Done](#8-chronological-project-changelog--all-updates-done)
9. [Project Directory Tree & Key File Map](#9-project-directory-tree--key-file-map)
10. [Configuration, CLI Scripts, Operational Rules & Change Playbook](#10-configuration-cli-scripts-operational-rules--change-playbook)

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
    - Direct asset creation (`Bulk Single-File Add` and `Multi-File Asset`) inside assigned App Instances that automatically creates or reuses Categories/Subcategories in Central Data and links items into the app (`detach` removes only the instance link).
    - App-level editing of Category, Subcategory (`name`, `thumbnail_url`, `image_url`, `tags`), and Asset content (`name`, `description`, `thumbnail_url`, `more_fields` via `instance_*.overrides` + isolated `instance_overrides/<app_id>/` storage), automatically sending structured `asset_update` diff proposals to Admin Inbox when asset content changes.
    - Monetization controls: toggle `is_premium`, `is_rewarded`, and set `rewarded_credits`.
    - Single and bulk asset tagging with live DOM updates.
    - Detach folders and assets safely without mutating central records.
  - Manage API keys for assigned instances (create, 2FA-verified full key reveal, revoke, configure IP limits and surge ceilings).
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
| `ASSETS` | `assets` | Central library assets | `_id`, `category_id`, `sub_category_id`, `name`, `folder_name`, `thumbnail_url`, `more_fields` (polymorphic named blocks), `is_enabled`, `is_premium`, `sequence`, `views`, `downloads`, `deleted_at`. |
| `APP_INSTANCES` | `app_instances` | Client app delivery configurations | `_id`, `name`, `package_name`, `app_icon`, `owner_id`, `ownership_transferred_to`, `previous_owner_username`, `tags` (app tag presets), `bulk_asset_tier_distribution_settings`, `created_at`. Unique index on `package_name`. |
| `INSTANCE_SUPER_CATEGORIES` | `instance_super_categories` | Super categories linked or created in an app instance | `_id`, `app_instance_id`, `source_id` (ObjectId or None), `name`, `sequence`, `is_enabled`, `is_premium`, `overrides: {}`, `deleted_at`. Unique `(app_instance_id, source_id)`. |
| `INSTANCE_CATEGORIES` | `instance_categories` | Categories linked or created in an app instance (`super_category_id` → instance super category `_id`, or None) | `_id`, `app_instance_id`, `source_id` (ObjectId or None), `super_category_id`, `name`, `sequence`, `is_enabled`, `is_premium`, `is_rewarded`, `tags`, `tier_distribution_settings`, `bulk_asset_tier_distribution_settings`, `overrides: {}`, `deleted_at`. |
| `INSTANCE_SUBCATEGORIES` | `instance_subcategories` | Subcategories linked or created in an app instance | `_id`, `app_instance_id`, `source_id` (ObjectId or None), `category_id`, `name`, `sequence`, `is_enabled`, `is_premium`, `is_rewarded`, `tags`, `tier_distribution_settings`, `overrides: {}`, `deleted_at`. |
| `INSTANCE_ASSETS` | `instance_assets` | Assets linked into an app instance | `_id`, `app_instance_id`, `source_id`, `category_id`, `sub_category_id`, `sequence`, `is_enabled`, `is_premium`, `is_rewarded`, `rewarded_credits`, `views`, `downloads`, `tags`, `overrides: {}` (`name`, `description`, `thumbnail_url`, `more_fields`, `is_priced`, `tags`), `deleted_at`. |
| `ADMIN_USERS` | `admin_users` | Super Admin operator accounts | `_id`, `username`, `email`, `password_hash`, `is_active`, `is_2fa_enabled`, `totp_secret`, `created_at`. |
| `MANAGERS` | `managers` | Product manager operator accounts | `_id`, `username`, `email`, `password_hash`, `is_active`, `status`, `is_2fa_enabled`, `totp_secret`, `created_at`. |
| `APP_INSTANCE_ACCESS` | `app_instance_access` | Granted manager ↔ app instance access links | `_id`, `manager_id`, `app_instance_id`, `created_at`. |
| `APP_INSTANCE_ACCESS_REQUESTS` | `app_instance_access_requests` | Requests for instance access or creation | `_id`, `manager_id`, `request_type`, `app_instance_id`, `status` (`pending`, `approved`, `rejected`), `notes`. |
| `MESSAGES` | `messages` | In-app messaging & structured proposals between managers & admins | `_id`, `manager_id`, `sender_role`, `sender_name`, `subject`, `content`, `payload_type` (`category`, `subcategory`, `asset`, `asset_update`), `data_payload`, `status` (`unread`, `read`, `applied`, `kept_app_only`), `created_at`. |
| `API_KEYS` | `api_keys` | Authenticated client app API keys | `_id`, `key_prefix`, `secret_hash`, `encrypted_key` (Fernet cipher for 2FA reveal), `app_instance_id`, `owner_id`, `owner_role`, `previous_owner_username`, `scopes`, `rate_limit_per_min`, `app_surge_ceiling_per_min`, `is_active`, `last_revealed_at`. |
| `MONITORED_ENDPOINTS` | `monitored_endpoints` | Registered route templates for analytics tracking | `_id`, `path_template`, `method`, `name`. |
| `ANALYTICS_EVENTS` | `analytics_events` | Raw client tracking events (`view`, `download`) | `_id`, `app_instance_id`, `asset_id`, `event_type`, `client_ip`, `user_agent`, `created_at`. |
| `ANALYTICS_HOURLY` | `analytics_hourly` | Pre-aggregated hourly analytics metrics | `_id`, `app_instance_id`, `hour`, `total_views`, `total_downloads`, `unique_ips`. |
| `MIGRATIONS` | `_migrations` | Startup schema & link reconciliation markers | `_id`, `name`, `applied_at`. |

---

## 5. Asset Pipeline & Supported Media Formats

### 5.1 Supported Formats
The platform supports six categories of assets across `ASSET_TYPE_RULES` (`controller/asset_controller.py`):
1. **Static Images:** `PNG`, `JPG`, `JPEG`, `WEBP`, `BMP`, `AVIF`.
2. **SVG Vectors:** `.svg` / `image/svg+xml`, validated with `is_safe_svg()` (`utils/file_utils.py`) to reject scripts/event handlers/`foreignObject`, stored as its own thumbnail, and served with `Content-Security-Policy: default-src 'none'`.
3. **Videos:** `MP4`, `WEBM`, `MOV`, `AVI`, `MKV` (with automatic FFmpeg duration, dimensions, and poster frame extraction).
4. **Animations:** `GIF`, `APNG`, Animated `WEBP`, and Lottie `JSON` animations.
5. **Audio:** `MP3`, `WAV`, `OGG`, `M4A`, `AAC`, `FLAC`, `OPUS`, `WMA` (dimensions stripped by rule).
6. **Interactive HTML & Documents/Generic Files:** `.html`/`.htm` (`text/html`, previewed in sandboxed iframes) and `.xml`, `.pdf`, `.txt`, `.csv`, `.doc*`, `.xls*`, `.zip`, `.rar`, `.7z`, `.tar`, `.gz` with automatic MIME classification and `file` block assignment.

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

### 5.5 Bulk Single-File Add, Asset-Name Grouping & Custom Block Keys (`moreFields`)
Implemented in `templates/assets/form_single.html` (`GET /admin/assets/new-single`) with backend/editor safeguards in `controller/asset_controller.py` and `templates/assets/form_multi.html`:
- **Per-Item Custom Block Key (`blockName`):** Each staged row exposes an editable monospace **Block Name (Key)** input sanitized via `sanitizeBlockKey()` (`[a-zA-Z0-9_-]`), defaulting to its detected type (`image`, `svg`, `video`, `audio`, `json`, `frames`, `html`, `file`).
- **Auto-Separate & Bulk Staged Toolbar:**
  - `#bulkAutoSeparateBlocks` toggle calls `recomputeAutoBlockNames()` to assign distinct block keys (`image`, `image_2`, ...) automatically within an asset group while preserving manually edited keys (`blockNameCustom: true`).
  - `#stagedBulkToolbar` provides batch controls for checked rows: **Apply Block Name** (with optional sequential `_1, _2...` numbering), **Use Filename as Block**, **Split Duplicate Blocks** (`splitDuplicateBlocks()`), **Group Selected** (`groupSelectedUnderAsset()`), plus single-row `✕` removal (`removeStagedRow()`).
  - Live inline hints (`formatBlockHintHtml()` / `refreshStagedBlockHints()`) show whether blocks in the same asset are separate, merging into an array, or colliding on dict keys (`json`/`frames`), with an inline **Split** button.
- **Asset-Name Grouping & Upload Collision Protection:**
  - When `#bulkGroupSameName` is checked, `groupStagedIndices()` groups items by normalized **Generated Asset Name** (`groupKeyOf()`), enabling multiple files with different OS filenames (e.g., `bg.png` + `overlay.png`) to be bundled into one asset under separate blocks (`{"background": [...], "foreground": [...]}`).
  - `startBulkUpload()` uploads all group members under the shared `groupAssetName` folder and deduplicates colliding disk filenames within the group (`usedGroupFilenames` + `getNextCandidateName()`), while `mergeBlocks()` concatenates matching array keys, keeps distinct keys separate, and auto-suffixes dict-vs-array collisions.
- **Safeguards:** `enrich_more_fields_metadata()` (`controller/asset_controller.py`) detects frames blocks by `coordinates`/`placeholders` lists regardless of block key name; `form_multi.html` (`normalizeBlock()` and save serialization) infers `.html`/documents by extension/MIME and avoids misclassifying custom visual blocks named `*frame*`, `*audio*`, `*html*`, or `*file*`.

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
- **Bulk & Single Asset Tagging:** `POST /{admin|manager}/instances/{id}/assets/bulk-tags` supports `add`, `replace`, and `remove` operations across assets (in both List and Block views via `templates/js/instance_asset_selection.js`) with instant client DOM updates and loading dialog feedback (`withLoading()`).
- **Folder Tagging & App Tag Bubbles:**
  - Categories and subcategories support individual and multi-select bulk tagging (`POST /{admin|manager}/instances/{id}/folders/bulk-tags` via `bulk_update_folder_tags()`).
  - App instances maintain reusable tag bubble presets (`PUT /{admin|manager}/instances/{id}/tags` -> `app_instances.tags`) rendered as clickable pills inside the folder tag modal.
- **Drag-and-Drop Reordering:** `POST /{admin|manager}/instances/{id}/reorder` updates integer sequences for super categories, categories, subcategories, or assets.
- **Monetization & Content Overrides:** Managed via `PATCH /{admin|manager}/instances/{id}/assets/{assetId}/override`, `POST /{admin|manager}/instances/{id}/assets/{assetId}/edit`, `PATCH /{admin|manager}/instances/{id}/folders/{folder_type}/{folder_id}/override`, and `POST .../reset-override`:
  - Assets: `is_premium`, `is_rewarded`, `rewarded_credits`, `overrides.is_priced`, `name`, `description`, `thumbnail_url`, `more_fields` (media uploaded in edit mode stores isolated files in `/static/central_data/instance_overrides/<app_id>/`). Manager asset edits also send `payload_type: "asset_update"` diff proposals to Admin Inbox (`apply-proposal` vs `dismiss-proposal`).
  - Categories / Subcategories: `is_premium`, `is_rewarded`, `name`, `thumbnail_url`, `image_url`, and `tags`.

### 6.6 Tier & Frequency Distribution Engine (`N-1` Cap, Alternate Paid & Bulk Rules)
Implemented in `controller/override_controller.py` (`compute_tier_distribution()`, `distribute_item_tiers()`, `bulk_distribute_subcategory_assets()`, `clamp_counts_for_total()`, `resolve_effective_counts()`) and shared frontend UI (`templates/partials/tier_distribution_modal.html`, `templates/js/tier_distribution.js` parameterized by `window.TIER_PORTAL_BASE` and `window.INSTANCE_BULK_SUB_META`):
- **`N - 1` Normal Preservation Rule:** Out of $N$ items in a container (`subcategories` in a category, or `assets` in a subcategory/category), at most $N - 1$ items combined may be Premium + Rewarded so at least 1 item remains Normal/Free.
- **Sequential Frequency Cycles:** Accepts batch lengths (`normal_frequency`, `premium_frequency`, `rewarded_frequency`):
  - **Combined mode (`alternate_paid: false`):** Emits `N` → `P` → `R` per cycle until paid budgets exhaust, filling remaining slots with `N`.
  - **Alternating Paid mode (`alternate_paid: true`):** Alternates paid batches across cycles after Free batches (e.g., `2N, 1P, 1R` over 10 assets produces `N, N, P, N, N, R, N, N, P, N`).
- **Bulk Multi-Subcategory Assets Distribution (`POST /{admin|manager}/instances/{id}/bulk-distribute-assets`):**
  - Targets explicit `subcategory_ids`, all subcategories inside a `parent_category_id`, or `apply_to_all: true` across the entire app instance (e.g., 50+ subcategories) in one MongoDB query + batched `bulk_write`.
  - Supports `count_mode: "fixed"` (proportionally clamped to `total - 1` per subcategory when a subcategory has fewer assets) and `count_mode: "percentage"` (e.g. `40%` Premium, `20%` Rewarded, combined strictly `< 100%`).
- **Persistent Settings Memory:** Last-used configuration saves automatically to `tier_distribution_settings` (per category/subcategory) and `bulk_asset_tier_distribution_settings` (per category or app instance), pre-populating the modal on reopen and updating `data-tier-settings` / `window.INSTANCE_BULK_SUB_META` immediately.
- **Badge Visibility Rule:** `templates/css/components.css` defines `[hidden] { display: none !important; }` at the top of the stylesheet so `.badge` utility display rules never override `element.hidden = true` on `REWARDED` / `PREMIUM` pills.

---

## 7. API Endpoints Reference

### 7.1 Client API (`/api/v1`)
All endpoints require `X-API-Key: <key>` header (or `api_key` query / `Authorization: Bearer <key>`), and `/app-instances/{id}` / `/instance/{id}` routes enforce `require_instance_access`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/instance/{instanceId}/catalog` | Preload entire enabled hierarchy (`super_categories` → `categories` → `subcategories` → `assets`) |
| `GET` | `/api/v1/app-instances/{id}/super-categories` | List super categories in an app instance |
| `GET` | `/api/v1/instance/{instanceId}/categories` | List active categories for this app instance (`?superCategoryId=`) |
| `GET` | `/api/v1/instance/{instanceId}/subcategories` | List subcategories (optional filter: `?categoryId=...`) |
| `GET` | `/api/v1/instance/{instanceId}/assets` | Paginated assets list (filters: `categoryId`, `subCategoryId`, `type`, `search`) |
| `GET` | `/api/v1/instance/{instanceId}/assets/{assetId}` | Get single asset details with overrides applied |
| `POST` | `/api/v1/app-instances/{id}/distribute-tiers` | Distribute Premium/Rewarded tiers sequentially in a category or subcategory |
| `POST` | `/api/v1/app-instances/{id}/bulk-distribute-assets` | Bulk distribute Premium/Rewarded asset tiers across multiple or all subcategories |
| `POST` | `/api/v1/app-instances/{id}/reorder` | Reorder `super_category`, `category`, `subcategory`, or `asset` items |
| `POST` | `/api/v1/app-instances/{id}/bulk-flags` | Bulk update `is_enabled` / `is_premium` flags |
| `GET` | `/api/v1/app-instances/{id}/unresolved` | List broken central asset references in instance |
| `POST` | `/api/v1/instance/{instanceId}/events` | Ingest analytics tracking events (`view`, `download`) |
| `GET` | `/api/v1/search` | Full-text and tag search across accessible catalog assets |

### 7.2 Admin Portal Endpoints (`/admin`)
Requires `admin_session` cookie.

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/dashboard` | Main system dashboard with KPI metrics and recent activity |
| `GET/POST` | `/admin/super-categories` | Manage central super categories (`super_categories`) |
| `GET/POST` | `/admin/categories` | Manage central categories (`?superCategoryId=`, `?page_size=`: 20-500, CSV column updates) |
| `GET/POST` | `/admin/subcategories`| Manage central subcategories (`?categoryId=`, `?page_size=`: 20-500, CSV column updates) |
| `GET/POST` | `/admin/assets` | Central asset library (filter/search, `?page_size=`: 20-500, CSV column updates) |
| `GET` | `/admin/assets/new-single` | Bulk Single-File Add UI with custom/separate `moreFields` block renaming & grouping |
| `GET` | `/admin/assets/new-multi` | Multi-block polymorphic asset creation/edit form |
| `GET` | `/admin/instances` | List/search App Instances (by instance name or `package_name`) and create new instances |
| `GET` | `/admin/instances/{id}/content` | App instance working set management (super categories, folders, assets, tier distribution) |
| `GET` | `/admin/instances/{id}/picker` | Central content picker with super-category filter & auto-tab switching |
| `POST` | `/admin/instances/{id}/references` | Import central super categories, categories, subcategories, or assets |
| `POST` | `/admin/instances/{id}/folders/create` | Create custom super category, category, or subcategory folder in instance |
| `PATCH` | `/admin/instances/{id}/folders/{folder_type}/{folder_id}/override` | Update folder `is_enabled`, `is_premium`, `is_rewarded`, `name`, `thumbnail_url`, `image_url`, or `tags` |
| `POST` | `/admin/instances/{id}/folders/{folder_type}/{folder_id}/reset-override` | Clear app-level folder overrides back to Central defaults |
| `GET/POST` | `/admin/instances/{id}/assets/{assetId}/edit` | Edit asset content at app level only (`instance_assets.overrides`) |
| `GET/POST` | `/admin/instances/{id}/assets/{assetId}/frames` | App-level Interactive Frame Placeholder Editor (`instance_assets.overrides`) |
| `POST` | `/admin/instances/{id}/assets/{assetId}/reset-override` | Clear app-level asset overrides back to Central defaults |
| `PUT` | `/admin/instances/{id}/tags` | Replace app-wide tag preset bubble list |
| `POST` | `/admin/instances/{id}/folders/bulk-tags` | Batch add, remove, or replace tags across selected categories & subcategories |
| `POST` | `/admin/instances/{id}/distribute-tiers` | Sequential Premium/Rewarded tier distribution (`subcategories` or `assets`) |
| `POST` | `/admin/instances/{id}/bulk-distribute-assets` | Bulk distribute asset tiers across selected, category-wide, or all subcategories |
| `DELETE` | `/admin/instances/{id}/categories/{catId}` | Detach category folder from instance |
| `DELETE` | `/admin/instances/{id}/subcategories/{subId}` | Detach subcategory folder from instance |
| `DELETE` | `/admin/instances/{id}/assets/{assetId}` | Detach asset reference from instance |
| `GET/POST` | `/admin/managers` | Approve/reject manager registrations, non-destructively delete managers (transferring apps & API keys to Admin), and assign instances |
| `GET/POST` | `/admin/messages` | Admin-manager messaging threads, central creation/update proposal diff review (`apply-proposal`, `dismiss-proposal`) |
| `GET/POST` | `/admin/keys` | Generate, inspect (`POST /admin/keys/{id}/reveal` via Admin 2FA), and manage global & transferred API keys |

### 7.3 Manager Portal Endpoints (`/manager`)
Requires `manager_session` cookie.

| Method | Path | Description |
|---|---|---|
| `GET` | `/manager/dashboard` | Manager overview of assigned instances and aggregate traffic |
| `GET` | `/manager/instances` | List/search accessible instances (shows `package_name`), request access or creation |
| `GET` | `/manager/instances/{id}/content` | Manage working set, custom folders, tags, tier distribution & asset overrides |
| `GET` | `/manager/categories` | Manager view of central categories (supports `page_size`, `pageSize`, `limit`: 20-200) |
| `GET` | `/manager/subcategories` | Manager view of central subcategories (supports `categoryId`, `page_size`: 20-200) |
| `GET` | `/manager/assets` | Manager central asset catalog (filter by cat/sub/type/search; supports `page_size`: 20-200) |
| `GET` | `/manager/instances/{id}/picker` | Manager central content picker (with super-category filter & auto-tab routing) |
| `GET` | `/manager/instances/{id}/picker/categories` | JSON search for central categories (`?superCategoryId=`) |
| `GET` | `/manager/instances/{id}/picker/subcategories` | JSON search for central subcategories |
| `GET` | `/manager/instances/{id}/picker/assets` | JSON search for central assets |
| `POST` | `/manager/instances/{id}/references` | Import central items into instance or target folders |
| `POST` | `/manager/instances/{id}/folders/create` | Create category/subcategory folder (auto-synced to Central Data) or custom super category in instance |
| `POST` | `/manager/instances/{id}/folders/ensure-central` | Idempotent inline folder creation/reuse in Central Data for upload forms |
| `GET` | `/manager/instances/{id}/assets/new-single` | Manager Bulk Single-File Add UI (auto-syncs to Central Data + links to app) |
| `GET` | `/manager/instances/{id}/assets/new-multi` | Manager Multi-File Asset creation UI (auto-syncs to Central Data + links to app) |
| `POST` | `/manager/instances/{id}/assets/create` | JSON asset creation (Central + app link, `409` on duplicate in central subcat) |
| `POST` | `/manager/instances/{id}/assets/save` | Multi-file / bulk text asset submission (Central + app link) |
| `GET/POST` | `/manager/instances/{id}/assets/{assetId}/edit` | App-level asset edit (`instance_assets.overrides`) + automatic `asset_update` Admin proposal message |
| `GET/POST` | `/manager/instances/{id}/assets/{assetId}/frames` | Scoped Interactive Frame Placeholder Editor saving to `instance_assets.overrides` + Admin proposal |
| `POST` | `/manager/instances/{id}/assets/{assetId}/reset-override` | Clear app-level asset overrides back to Central defaults |
| `GET/POST` | `/manager/instances/{id}/media/{upload,crop,check-similarity,detect-frames}` | Scoped media operations (`?scope=override` isolates files into `instance_overrides/<id>/`) |
| `DELETE` | `/manager/instances/{id}/super-categories/{super_id}` | Detach super category folder and child categories from instance |
| `DELETE` | `/manager/instances/{id}/categories/{cat_id}` | Detach category folder and child items from instance (central untouched) |
| `DELETE` | `/manager/instances/{id}/subcategories/{sub_id}` | Detach subcategory folder from instance (central untouched) |
| `DELETE` | `/manager/instances/{id}/assets/{assetId}` | Detach individual asset from instance (central untouched) |
| `PATCH` | `/manager/instances/{id}/assets/{assetId}/override` | Update sequence, flags, credits, name (with optional `propose_to_central`), description, `thumbnail_url`, `more_fields`, tags |
| `PATCH` | `/manager/instances/{id}/folders/{folder_type}/{folder_id}/override` | Update folder `is_enabled`, `is_premium`, `is_rewarded`, `name`, `thumbnail_url`, `image_url`, or `tags` |
| `POST` | `/manager/instances/{id}/folders/{folder_type}/{folder_id}/reset-override` | Clear app-level folder overrides back to Central defaults |
| `PUT` | `/manager/instances/{id}/tags` | Replace app-wide tag preset bubble list |
| `POST` | `/manager/instances/{id}/folders/bulk-tags` | Batch add, remove, or replace tags on categories/subcategories |
| `POST` | `/manager/instances/{id}/assets/bulk-tags` | Batch add, remove, or replace tags on assets |
| `POST` | `/manager/instances/{id}/distribute-tiers` | Sequential Premium/Rewarded tier distribution (`subcategories` or `assets`) |
| `POST` | `/manager/instances/{id}/bulk-distribute-assets` | Bulk distribute asset tiers across selected, category-wide, or all subcategories |
| `POST` | `/manager/instances/{id}/reorder` | Drag-and-drop sequencing of folders or assets |
| `GET/POST` | `/manager/keys` | Create, inspect (`POST /manager/keys/{id}/reveal` via Manager 2FA), and manage API keys |
| `GET/POST` | `/manager/messages` | Send and view messages & proposals to/from Super Admin operators |

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

### Update 23: Super Category Picker Filter & Multi-Super-Category Membership
- **Picker Super Category Filter (`bc946fd`):** Added `superCategoryId` scoping to Admin and Manager pickers (`instance_workspace_controller.py`, `templates/instances/picker.html`, `templates/manager/instances/picker.html`) across Categories, Subcategories, and Assets tabs.
- **Category in Multiple Super Categories (`1f771ad`):** Updated `database/indexes.py`, `reference_controller.py`, and `instance_workspace_controller.py` so the unique instance category index includes `super_category_id`, letting the same central category sit under multiple super categories as independent links while preserving shared subcategories/assets when removing one placement.

### Update 24: Streaming CSV Column Updates with Batched `bulk_write`
- Updated `utils/csv_utils.py` (`iter_csv_rows`) and `controller/csv_update_controller.py` (`BULK_BATCH_SIZE = 1000`, `MAX_REPORTED_ROWS = 500`) to stream CSV rows lazily from uploaded files instead of buffering the full file in RAM, apply MongoDB updates via batched `bulk_write`, and cap UI row report payloads while preserving full summary counts (`tests/test_csv_update_large.py`).

### Update 25: Same-Name Asset Grouping in Bulk Upload & Multi-Form JSON Upload
- Updated `templates/assets/form_single.html` with `#bulkGroupSameName` grouping and `mergeBlocks()` / `buildBlocks()` so matching-stem files (`cat.webp + cat.json + cat.mp3`) bundle into a single central asset with separate typed blocks (`image`, `json`, `audio`) and single-group conflict checking.
- Added `.json` file button/drop support inside `templates/assets/form_multi.html` JSON blocks.

### Update 26: Instance Folder Tagging, App Tag Bubbles, Rewarded Badges (`[hidden]` Fix) & Action Loading Spinner
- Added folder-level (`category` / `subcategory`) individual and bulk tagging (`bulk_update_folder_tags` in `controller/override_controller.py`, `POST /{admin|manager}/instances/{id}/folders/bulk-tags`), plus per-app tag preset bubbles (`PUT /{admin|manager}/instances/{id}/tags` -> `available_tags`) in `templates/partials/instance_super_categories.html` & `instance_folder_controls.html` (`tests/test_bulk_folder_tags.py`).
- Added Rewarded pill (`asset-card-rewarded-pill`) and bulk Rewarded actions, and added `[hidden] { display: none !important; }` at the top of `templates/css/components.css` so `.badge` CSS does not override the HTML `hidden` attribute on folder Rewarded badges (`481736e`).
- Added `.asset-loading-dialog` / `.asset-loading-spinner` (`withLoading` in `templates/js/instance_asset_selection.js`) and automatic unselection after bulk operations (`66b041a`, `d1f2801`).

### Update 27: Sequential Tier Distribution Model, Alternate Pro/Rewarded & Bulk Subcategory Asset Rules
- Implemented sequential tier distribution (`814cca6`, `1c2c945`) in `controller/override_controller.py` (`compute_tier_distribution()`, `distribute_item_tiers()`, `bulk_distribute_subcategory_assets()`):
  - Enforces $N - 1$ max combined Premium + Rewarded count per container so at least 1 item remains Normal/Free.
  - Supports customizable consecutive frequency batches (`normal_frequency`, `premium_frequency`, `rewarded_frequency`) and **Alternate Paid** mode (`alternate_paid: true`), alternating Premium and Rewarded blocks across Free cycles (`N, N, P, N, N, R...`).
  - Supports bulk asset distribution across multiple selected subcategories, a whole category, or all subcategories in an app instance (50+) using either fixed counts (proportionally clamped per subcategory) or percentage targets (`< 100%`), batched in MongoDB `bulk_write`.
  - Saves and restores previous settings (`tier_distribution_settings` and `bulk_asset_tier_distribution_settings`) across MongoDB, `controller/catalog_controller.py`, DOM `data-tier-settings`, and shared `templates/js/tier_distribution.js` + `templates/partials/tier_distribution_modal.html` (`tests/test_tier_distribution.py`).

### Update 28: App Instance `package_name` Display & Package Search
- Fixed `app_instances` listings (`f4b781d`): normalized empty/`"None"` `package_name` handling in `controller/app_instance_controller.py` (`create_app_instance()`, `update_app_instance()`), added `package_name` / `packageName` regex matching to `list_app_instances(search=...)`, and ensured `templates/instances/list.html`, `templates/manager/instances/list.html`, `templates/instances/content.html`, and `templates/keys/list.html` render `inst.package_name or inst.packageName` safely.

### Update 29: Custom & Separate Block Names (`more_fields` Keys) in Bulk Single-File Add
- Updated `templates/assets/form_single.html` (`59f4a71`): added per-row editable **Block Name (Key)** (`sanitizeBlockKey()`), `#bulkAutoSeparateBlocks` checkbox (`recomputeAutoBlockNames()`), live merge/collision hints with inline `Split` button (`formatBlockHintHtml()` / `splitBlockGroup()`), `#stagedBulkToolbar` (`Apply Block Name` with `_1, _2...`, `Use Filename as Block`, `Split Duplicate Blocks`, `Group Selected`, single-row `✕` remove), Normalized Asset Name grouping (`groupKeyOf()`), and intra-group upload filename deduplication (`usedGroupFilenames`).
- Updated `controller/asset_controller.py` (`enrich_more_fields_metadata()`) to recognize custom-keyed frames blocks via `coordinates`/`placeholders` lists regardless of key name, and updated `templates/assets/form_multi.html` (`normalizeBlock()` and save serialization) so HTML/document blocks and custom visual blocks (`photo_frame`, `audio_cover`, etc.) preserve their true types when edited (`tests/test_bulk_single_blocks.py`).

### Update 30: Manager Central Uploads, App-Level Content Overrides + Admin Proposals, Non-Destructive Manager Deletion & 2FA API Key Reveal
- **Manager Direct Authoring -> Central Library Auto-Sync (`controller/manager_upload_controller.py`, `router/manager/upload_routes.py`):**
  - Added dedicated Bulk Single-File Add (`/manager/instances/{id}/assets/new-single`) and Multi-File Asset (`/manager/instances/{id}/assets/new-multi`) flows inside Manager App Instances reusing parameterized `templates/assets/form_single.html` & `form_multi.html`, `uploader.js`, and `media_cropper.js`.
  - Automatically reuses or creates Central `CATEGORIES` and `SUBCATEGORIES` (plus inline `+ New Category` / `+ New Subcategory` creation and `+ Create Folder` sync), creates Central `ASSETS` with `409` duplicate protection, stamps `created_by_role="manager"` metadata, and attaches only the targeted items to the App Instance (`ensure_category_link`, `ensure_subcategory_link`, `add_references`), preserving detach-only removal without mutating `test_instance_isolation.py` boundaries.
- **App-Level Editing (`instance_*.overrides`) + Admin Proposal Diff Workflow:**
  - Extended `parse_folder_override_payload()` and `parse_asset_override_payload()` (`controller/instance_workspace_controller.py`) plus shared `templates/partials/edit_folder_modal.html` and `form_multi.html` (`app_override_edit` mode) so managers and admins can edit Categories/Subcategories (`name`, `thumbnail_url`, `image_url`, `tags`) and Assets (`name`, `description`, `thumbnail_url`, `more_fields`) strictly at app level with isolated media storage (`central_data/instance_overrides/<app_id>/`).
  - Editing an asset from Manager Portal (or checking optional *"propose rename"* in inline Rename) dispatches a structured `payload_type: "asset_update"` diff proposal via `send_manager_message`.
  - Updated `controller/admin_manager_controller.py`, `router/admin/admin_message_routes.py`, and `templates/admin/messages/index.html` to render a before/proposed field diff table with **`Apply Update to Central Data`** (`apply_message_proposal_to_central()` promoting override media cleanly to central asset folder & calling `update_asset()`) vs **`Keep as App-Only Change`** (`dismiss_message_proposal()` marking status `kept_app_only`).
- **Non-Destructive Manager Deletion -> Ownership Transfer (`controller/admin_manager_controller.py`):**
  - Updated `delete_manager_account(db, manager_id, admin_id)` to preserve all manager-owned `APP_INSTANCES` (plus `instance_*` hierarchies, overrides, and analytics) and `API_KEYS`, reassigning `owner_id` / `owner_role="admin"` / `previous_owner_username` metadata to Admin and preserving any unreviewed `asset_update` proposal messages (`tests/test_manager_uploads_and_deletion.py`).
- **2FA-Protected API Key Reveal (`authorization/encryption.py`, `authorization/api_key.py`, `templates/partials/reveal_api_key_modal.html`):**
  - Added Fernet key encryption (`encrypt_api_key` / `decrypt_api_key`) at key issuance/rotation while stripping `encrypted_key` & `secret_hash` from list queries (`can_reveal` flag only).
  - Extracted shared `verify_actor_2fa()`, `reveal_api_key_for_admin()`, and `reveal_api_key_for_manager()` + `POST /{admin,manager}/keys/{id}/reveal` routes, fixed `templates/keys/list.html` prefix display & `templates/admin/managers/list.html` 2FA link (`/admin/settings/2fa/setup`), and verified via `tests/test_api_key_reveal_2fa.py`.

### Update 31: Category/Subcategory Folder Block UI Overhaul & App-Scoped Interactive Frame Editor
- **Outlined Button Border Specificity & Structured Folder Blocks (`templates/css/components.css`, `templates/manager/instances/content.html`, `templates/instances/content.html`, `templates/partials/instance_folder_controls.html`):**
  - Fixed CSS specificity bug where `a.btn, button.btn { border: 1px solid transparent; }` (`0,1,1`) stripped borders from `.btn-outlined` `<button>` / `<a>` elements (`0,1,0`); elevated `.btn.btn-outlined`, `.btn.btn-destructive-outlined`, `.btn.btn-success-outlined`, and `.btn.btn-warning-outlined` + added `.btn-sm` / `.btn-xs` utility classes and bumped `components.css?v=7` in `templates/base.html` and `templates/manager/base.html`.
  - Replaced cramped single-row flex wraps with clean Material 3 `.instance-cat-card` (header + toolbar bar) and `.instance-sub-grid` / `.instance-sub-card` (`minmax(310px, 1fr)` 3-band layout: full-width header, action strip, footer controls) while preserving all drag-and-drop, checkbox, collapse (`.subs-collapsed`), and tier distribution selectors.
- **Scoped Interactive Frame Editor for Managers & App Instances (`controller/manager_upload_controller.py`, `router/manager/upload_routes.py`, `router/admin/instance_routes.py`, `templates/assets/frames_editor.html`, `templates/assets/form_multi.html`, `templates/js/asset_preview_modal.js`):**
  - Fixed `'Not Found'` errors caused by hardcoded `/admin/assets/{id}/frames` links on instance asset edits (`instance_assets` IDs) and hidden preview modal links. Added `GET/POST /manager/instances/{instance_id}/assets/{asset_id}/frames` and `GET/POST /admin/instances/{id}/assets/{asset_id}/frames` backed by shared `apply_frame_editor_save()`, `find_frame_block_key()` (supporting custom frame keys), and partial-update preservation in `save_app_level_asset_edit_and_notify()`.
  - Updated `form_multi.html` (`openFrameInteractiveEditor`) to automatically upload & save staged frame photos before entering the editor, and enabled scoped `Interactive Editor 🖼️` + `Edit` links in `asset_preview_modal.js` for `/manager/instances/*` and `/admin/instances/*`.

---

## 9. Project Directory Tree & Key File Map

```
/Admin Assets App
├── analytics/                       # Event collection, counters, rollups & PKT reporting
├── authorization/
│   ├── admin_session.py             # Admin cookie session signing & validation
│   ├── api_key.py                   # X-API-Key / Bearer / query hash verification
│   ├── instance_guard.py            # Router-level require_instance_access & require_unbound_key
│   ├── manager_session.py           # Manager cookie session signing & validation
│   ├── rate_limiter.py              # Dual-layer IP & surge rate limiter
│   ├── scopes.py                    # Scope enforcement dependencies
│   ├── totp.py                      # 2FA TOTP verification
│   └── encryption.py                # bcrypt password hashing & serializer tokens
├── config/
│   ├── settings.py                  # Pydantic environment configuration (.env)
│   ├── constants.py                 # Media formats, limits, defaults
│   └── paths.py                     # Static, templates, and upload directory paths
├── controller/
│   ├── app_instance_controller.py   # App instance CRUD, unique package_name & search
│   ├── asset_controller.py          # Central asset CRUD, ASSET_TYPE_RULES & metadata enrichment
│   ├── asset_preview_controller.py  # Asset preview payload, media stats & frames blocks
│   ├── super_category_controller.py # Central super categories (optional level above categories)
│   ├── category_controller.py       # Central category business logic
│   ├── subcategory_controller.py    # Central subcategory business logic
│   ├── catalog_controller.py        # Resolved instance catalog & parent/override pipelines
│   ├── reference_controller.py      # Instance reference linking, ensure folder links & destination scoping
│   ├── override_controller.py       # Sparse overrides, folder/asset tags & tier distribution engine
│   ├── instance_workspace_controller.py # Shared Admin/Manager instance content, override parsers & folder logic
│   ├── manager_upload_controller.py # Manager direct central uploads & app-level asset diff proposals
│   ├── csv_update_controller.py     # Streaming CSV column updates via batched bulk_write
│   ├── manager_controller.py        # Manager auth, access verification, 2FA & 2FA key reveal
│   ├── admin_manager_controller.py  # Admin governance, non-destructive manager delete & proposal review
│   ├── frame_controller.py          # Frame placeholder coordinate detection
│   ├── crop_controller.py           # Alpha-preserving image, GIF (dither-free) & video cropper
│   ├── media_controller.py          # Media upload handler & thumbnail generation
│   └── media_similarity.py          # Duplicate/similar filename detection in uploads
├── database/
│   ├── collections.py               # Canonical MongoDB collection constants
│   ├── connection.py                # Async Motor client singleton & get_database()
│   ├── indexes.py                   # Index declarations (unique compound hierarchy & sequence indexes)
│   ├── repository.py                # CentralRepository / InstanceRepository & instance_collection guard
│   └── models/                      # Pydantic schemas (asset.py, instance_content.py, more_fields.py, etc.)
├── router/
│   ├── admin/                       # Super Admin web routes (/admin/...)
│   │   ├── instance_routes.py       # Admin instance CRUD, workspace content, app overrides & tier distribution
│   │   ├── asset_routes.py          # Central asset list, new-single, new-multi & CSV update routes
│   │   ├── admin_message_routes.py  # Manager inbox threads, proposal apply & dismiss-proposal routes
│   │   ├── settings_routes.py       # Admin API key issuance, 2FA setup & 2FA API key reveal
│   │   ├── super_category_routes.py # Central super category CRUD
│   │   ├── category_routes.py       # Central category routes (dynamic pagination & CSV)
│   │   └── subcategory_routes.py    # Central subcategory routes (dynamic pagination & CSV)
│   ├── manager/                     # Manager web routes (/manager/...)
│   │   ├── central_data_routes.py   # Manager central data browse (dynamic pagination)
│   │   ├── instance_routes.py       # Manager instance workspace, picker, tags & tier distribution
│   │   ├── upload_routes.py         # Manager direct upload -> central sync & app-level asset editing
│   │   └── key_routes.py            # Manager API key issuance & 2FA API key reveal
│   └── v1/                          # Client & integration REST API (/api/v1/...)
│       ├── catalog_router.py        # Full catalog preload
│       ├── instance_content_router.py # Scoped instance delivery, overrides, distribute-tiers & bulk-distribute
│       └── media_router.py          # Media upload, similarity check & frame detection
├── static/
│   └── central_data/                # Uploaded physical images, videos, frames (+ instance_overrides/)
├── templates/
│   ├── base.html                    # Admin base layout (MD3 theme)
│   ├── js/                          # Extracted cached client scripts (Admin + Manager)
│   │   ├── tier_distribution.js     # Shared tier distribution & bulk subcategory modal logic
│   │   ├── instance_content.js      # Admin instance content DOM/AJAX handlers
│   │   ├── manager_instance_content.js # Manager instance content DOM/AJAX handlers
│   │   ├── instance_asset_selection.js # Shared list/block checkbox swipe selection & loading modal
│   │   ├── asset_preview_modal.js   # Central & instance preview modal + inline override toggles
│   │   ├── bulk_actions.js          # Asset/folder bulk selection & tag bar actions
│   │   ├── csv_update_modal.js      # CSV column update modal logic
│   │   ├── uploader.js              # Background uploader with configurable uploadUrl endpoint
│   │   ├── media_cropper.js         # Client crop/cut UI for images & videos (configurable cropUrl)
│   │   └── security.js              # Portal anti-inspection protection
│   ├── partials/                    # Shared Jinja components (edit_folder_modal.html, reveal_api_key_modal.html, tier_distribution_modal.html, ...)
│   ├── assets/                      # list.html, form_single.html (Bulk Single-File Add), form_multi.html (Admin/Manager create + app_override_edit), editors
│   ├── instances/                   # Admin instance list, form, content, picker, unresolved
│   └── manager/                     # Manager portal templates matching Admin views
├── tests/                           # Regression & feature verification scripts (run via .venv/bin/python)
│   ├── test_bulk_single_blocks.py   # Bulk Single-File Add block rename, grouping & enrichment
│   ├── test_manager_uploads_and_deletion.py # Manager direct uploads, app overrides, asset proposals & non-destructive deletion
│   ├── test_api_key_reveal_2fa.py   # 2FA API key reveal (Admin, Manager, legacy keys, cross-tenant isolation)
│   ├── test_tier_distribution.py    # Sequential tier distribution, alternate paid & bulk rules
│   ├── test_bulk_folder_tags.py     # Folder tags & app tag preset bubbles
│   ├── test_asset_type_rules.py     # ASSET_TYPE_RULES DB filter vs in-memory parity
│   ├── test_instance_isolation.py   # Static AST check blocking central writes from instance modules
│   ├── test_api_key_isolation.py    # HTTP tests for API key instance scoping
│   ├── test_add_references.py       # Reference importer parity & race handling
│   ├── test_super_categories.py     # 4-level hierarchy flows
│   ├── test_csv_update_large.py     # Streaming CSV updates
│   └── test_svg_upload.py           # SVG safety sanitization & CSP headers
├── scripts/
│   ├── create_admin.py              # CLI: Bootstrap admin operator
│   ├── issue_key.py                 # CLI: Issue client API key
│   ├── migrate_instance_ids.py      # Backfill assigned instance parent IDs
│   ├── crop_media.py                # CLI: Standalone image, GIF & video cropper
│   └── reap_orphan_media.py         # CLI: Clean unreferenced media files
└── main.py                          # ASGI application entrypoint
```

---

## 10. Configuration, CLI Scripts, Operational Rules & Change Playbook

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
10. **Shared Workspace Logic Rule:** Never duplicate instance workspace/picker/folder/tier logic separately in `router/admin/instance_routes.py` vs `router/manager/instance_routes.py` or `instance_content.js` vs `manager_instance_content.js`. Put shared backend logic in `controller/instance_workspace_controller.py` / `controller/override_controller.py` and shared frontend logic in `templates/js/*.js` + `templates/partials/*.html`.

### 10.3 Change Playbook ("Where to Define New Features & Updates")

| Type of Change | Primary Source Files to Update | Tests / Checks to Run |
|---|---|---|
| **New Asset Media Format / `more_fields` Block Type** | 1. `config/constants.py` (extensions/MIME)<br>2. `database/models/more_fields.py` (`TypedBlock`)<br>3. `controller/asset_controller.py` (`ASSET_TYPE_RULES`, `enrich_more_fields_metadata`)<br>4. `templates/assets/form_single.html` (`DATA_TYPE_CONFIG`, `classifyFile`, `buildBlocks`) & `form_multi.html` (`normalizeBlock`, serialization) | `.venv/bin/python tests/test_asset_type_rules.py`<br>`.venv/bin/python tests/test_bulk_single_blocks.py` |
| **Instance Working-Set / Picker / Folder Features (Admin + Manager)** | 1. `controller/instance_workspace_controller.py` (`build_instance_content`, `build_picker_page`, folder helpers)<br>2. `router/admin/instance_routes.py` & `router/manager/instance_routes.py` (thin route wrappers)<br>3. `templates/partials/*.html` + `templates/js/instance_content.js` / `manager_instance_content.js` | `.venv/bin/python tests/test_instance_workspace.py`<br>`.venv/bin/python tests/test_shared_subfolder.py`<br>`.venv/bin/python tests/test_instance_isolation.py` |
| **Monetization, Folder Tags, or Tier Distribution Rules** | 1. `database/models/instance_content.py` (payload schemas)<br>2. `controller/override_controller.py` (`compute_tier_distribution`, `distribute_item_tiers`, `bulk_distribute_subcategory_assets`, `bulk_update_folder_tags`)<br>3. `controller/catalog_controller.py` (project persisted fields/settings)<br>4. `templates/partials/tier_distribution_modal.html` + `templates/js/tier_distribution.js`<br>5. `router/{admin,manager}/instance_routes.py` & `router/v1/instance_content_router.py` | `.venv/bin/python tests/test_tier_distribution.py`<br>`.venv/bin/python tests/test_bulk_folder_tags.py`<br>`node --check` on modified `templates/js/*.js` |
| **App Instance CRUD & API Key Scoping / 2FA Reveal** | 1. `database/models/app_instance.py`, `database/models/api_key.py`<br>2. `authorization/encryption.py`, `authorization/api_key.py`, `authorization/instance_guard.py`<br>3. `controller/authorization_controller.py`, `controller/manager_controller.py` (`verify_actor_2fa`, reveal helpers)<br>4. `templates/partials/reveal_api_key_modal.html`, `templates/keys/list.html`, `templates/manager/keys/list.html` | `.venv/bin/python tests/test_api_key_isolation.py`<br>`.venv/bin/python tests/test_api_key_reveal_2fa.py` |
| **Manager Authoring, App Overrides, Proposals & Manager Lifecycle** | 1. `controller/manager_upload_controller.py`, `router/manager/upload_routes.py`<br>2. `controller/admin_manager_controller.py` (`delete_manager_account`, `apply_message_proposal_to_central`, `dismiss_message_proposal`)<br>3. `templates/partials/edit_folder_modal.html`, `templates/admin/messages/index.html`, `templates/assets/form_{single,multi}.html` | `.venv/bin/python tests/test_manager_uploads_and_deletion.py`<br>`.venv/bin/python tests/test_instance_isolation.py` |
| **CSV Batch Update Columns or Limits** | `utils/csv_utils.py` (`iter_csv_rows`) & `controller/csv_update_controller.py` (`_convert_value`, `apply_csv_column_updates`) | `.venv/bin/python tests/test_csv_update_large.py` |
