# Core Features

Functional specification for the asset library platform. Paired with
`.antigravityrules` (engineering rules) and `color_palette.md` (design tokens).

---

## 1. Overview

The platform holds one **central library** of creative assets and lets any number of
**app instances** draw from it. Content is authored once, centrally. Each app decides
what it ships, in what order, what costs money, and measures how it performs — but it
never authors content of its own.

```
CENTRAL LIBRARY  (the only place content is created)
Category ──► Subcategory ──► Asset
   ▲              ▲             ▲
   │              │             │   reference by source_id
   │              │             │   (+ per-app settings and overrides)
   │              │             │
APP INSTANCE  "Photo Frames Pro"  (package: com.acme.frames)
ref ──────────► ref ─────────► ref
is_enabled      is_enabled     is_enabled, sequence, is_premium,
sequence        sequence       views, downloads
overrides{}     overrides{}    overrides{}
```

Two rules govern everything below:

1. **An app instance cannot create content.** It can only reference categories,
   subcategories and assets that already exist in the central library.
2. **An app's edits and deletes stay in that app.** They affect only that app's
   reference row. Central data is never modified from inside an app, and no other app
   sees the change.

Data flows one way: **central → instance**.

---

## 2. Central library

### 2.1 Hierarchy

Three fixed levels. An asset must belong to exactly one category *and* one
subcategory, and that subcategory must belong to that category — validated on write.

| Level | Purpose | Example |
|---|---|---|
| Category | Top-level browse bucket | Frames, Backgrounds, Stickers, Music |
| Subcategory | Refinement inside a category | Birthday, Wedding, Neon, Lo-fi |
| Asset | The shippable item plus its media | "Gold Ribbon Frame 04" |

### 2.2 Category

Fields: `name`, `created_at`, `updated_at`, `thumbnail_url?`, `image_url?`.

- Names are unique, case-insensitive.
- `thumbnail_url` is the small grid image; `image_url` is the large banner/hero.
- Deleting a category with children requires an explicit cascade confirmation that
  first reports how many subcategories and assets will be removed.

**Create single** — one form, immediate validation, returns the created record.

**Create in bulk** — three input paths, all landing on the same service:
1. JSON array via `POST /api/v1/categories/bulk`
2. CSV upload in the admin panel (`name,thumbnail_url,image_url`)
3. Paste-a-list box in the admin panel — one name per line, media added later

Bulk is partial-success: each row returns `created`, `skipped` (duplicate) or
`failed` with a reason. The admin panel shows a per-row result table and offers
"Retry failed rows only".

### 2.3 Subcategory

Fields: `name`, `categoryId`, `created_at`, `updated_at`, `thumbnail_url?`,
`image_url?`.

- Unique per parent category — "Birthday" can exist under both Frames and Stickers.
- Cannot be reparented to a different category once assets exist under it; instead
  move the assets first, explicitly.

**Create single** and **create in bulk**, same three input paths. Bulk accepts either
a single `categoryId` applied to every row, or a `category_name` column that is
resolved by name (with an optional `create_missing_categories` flag).

### 2.4 Asset

Fields: `name`, `description`, `categoryId`, `subCategoryId`, `thumbnail_url?`,
`created_at`, `updated_at`, `moreFields`, `folder_name?`.

- **Dedicated asset folder**: Assets reside in their own folder on disk at
  `static/central_data/<category_folder>/<subcategory_folder>/<asset_name_folder>/`. All files
  associated with the asset (thumbnail, images, audio, video, frames) are stored together in this folder.
- **Name uniqueness & availability check**: Asset names are unique per subcategory (case-insensitive).
  The system provides real-time name availability verification (`/admin/assets/check-name` and
  `GET /api/v1/assets/check-name`) as the operator types, displaying a live status (`✓ Available` or
  conflict warning) and disabling save if the name is already in use.
- **Auto-naming**: If no name is provided when creating an asset, the system automatically derives
  the asset name from the very first uploaded file (formatted and title-cased from the file stem).

`moreFields` is where the actual content lives — see section 4.

---

## 3. Adding assets: two modes

The distinction is **how much media the asset carries**, and it changes the workflow.

### 3.1 Single-file assets — bulk supported

An asset whose payload is one file: one image, one audio track, one video, one JSON.

Workflow:
1. Operator picks category + subcategory once.
2. Drops 1–500 files, or supplies a CSV of URLs.
3. The system creates one asset per file.
4. Name defaults to the filename, cleaned (`gold_ribbon_04.png` → "Gold Ribbon 04")
   and is editable inline in the results table before commit.
5. Thumbnails are generated automatically where the source is visual; for audio, the
   operator can attach one shared thumbnail to the whole batch.
6. `moreFields` gets a single typed block matching the file type.

Everything is reviewable in a staging table before anything is written. Nothing is
saved until "Create N assets" is pressed.

### 3.2 Multi-file assets — individual only

An asset that bundles several files or needs per-file metadata: a frame plus its
placeholder map, a video with alternate audio tracks, an image set, a JSON config
with companion media.

Workflow: one asset at a time, with a dedicated editor.
1. Enter name (or leave empty):
   - As the name is typed, real-time validation checks the database and reports `✓ Available`
     or prevents saving if the name already exists in the subcategory.
   - If left blank, uploading the first file (thumbnail or media block) automatically auto-populates
     the asset name from the file stem and validates availability immediately.
2. Asset folder provisioning:
   - A dedicated folder is created under `static/central_data/<category>/<subcategory>/<asset_folder>/`.
   - All uploaded files for this asset are stored in this dedicated directory.
3. Upload thumbnail and add `moreFields` blocks one by one, each with its own uploader and settings.
4. For a `frames` block, run placeholder detection and correct the coordinates in the
   visual editor.
5. Preview, then save.
6. If the asset is renamed in the future, its directory on disk and media URLs are synchronized.
   If deleted, the asset directory and all contained files are cleaned up from disk.

Bulk creation is deliberately **not** offered here — the per-file metadata cannot be
inferred reliably, and a wrong frame map ships broken content to users.

### 3.3 Uploads

- Accepted: `png jpg jpeg webp gif` (image), `mp3 aac wav m4a ogg` (audio),
  `mp4 webm mov` (video), `json`.
- Per-file cap 100 MB; per-batch cap 2 GB.
- Files are stored on object storage; the database holds URLs only.
- Filenames are normalized and content-hashed to avoid collisions; re-uploading an
  identical file reuses the existing object.
- Every upload is type-sniffed from magic bytes, not just the extension.

---

## 4. `moreFields` — the extensible payload

`moreFields` is an object of typed blocks, keyed by a slug the operator chooses
(`preview`, `loop_audio`, `layers`). Each value is `{"type": ..., ...}`.

| Type | Holds | Notes |
|---|---|---|
| `audio` | One track | Duration read on upload |
| `audio_list` | Ordered tracks | Reorderable |
| `image` | One image | Width/height stored |
| `image_list` | Ordered images | Used for image sets, layer stacks |
| `video` | One clip | Duration + dimensions stored |
| `video_list` | Ordered clips | |
| `json` | Arbitrary object | Depth ≤ 8, ≤ 256 KB, validated as real JSON |
| `frames` | Frame image + placeholder map | See 4.1 |
| `string_list` | List of string items | Rendered as removable bubble chips in admin UI |

Unknown types are rejected at the API boundary. Adding a new type is a deliberate
change: model, validator, admin editor, and this document.

### 4.1 Frames and placeholder detection

When an asset is a photo frame, the platform locates every empty slot in the frame
image where a user photo will sit.

For each placeholder it records:

| Key | Meaning |
|---|---|
| `x`, `y` | Top-left corner of the unrotated box, pixels, origin top-left |
| `width`, `height` | Box size in pixels |
| `rotation` | Degrees, clockwise-positive, −180 to 180 |
| `elevation` | Stacking order hint; higher renders on top |
| `index` | Stable slot number, 0-based, used by client apps |

The `frames` block also stores the source image's own `width` and `height` so clients
can scale the coordinate space to any display size.

**Detection** runs server-side on upload: the alpha channel is thresholded, connected
transparent regions are extracted, tiny specks are discarded, and each region gets a
minimum-area rotated bounding box — which yields `rotation` directly. Regions are
ordered top-to-bottom then left-to-right to assign `index`, and `elevation` defaults
to 0.

**Detection is always a proposal.** The admin editor overlays the boxes on the image;
the operator can drag, resize, rotate, renumber, change elevation, delete a false
positive, or draw a missed slot by hand. Numeric inputs and the canvas stay in sync
both ways. Nothing is saved until the operator confirms.

A `frames` block with zero placeholders is rejected.

---

## 5. App instances

### 5.1 The instance record

Fields: `name` (unique), `package_name?` (unique when present), `app_icon?`.

An instance represents one shipped application. Package name is optional because
instances are often created before the store listing exists.

### 5.2 Referencing content from the central library

The core operation. An operator opens an instance, browses the central library, and
picks what the app should carry. Picking creates a **reference row** — a pointer at
the central document plus this app's settings for it. No content is duplicated.

**Selection granularity**
- Whole category → references the category, all its subcategories, all their assets
- Whole subcategory → references it, plus its parent category if not already present
- Individual assets → references them, plus their parent chain if not already present

Parents are always added before children; an instance can never hold an orphan
reference.

**Each new reference row gets**
- `app_instance_id` and `source_id`
- `is_enabled = true`
- `sequence` = appended to the end of its list, in the order selected
- `overrides = {}`
- assets also get `is_premium = false`, `views = 0`, `downloads = 0`

**Re-selecting is safe.** `(app_instance_id, source_id)` is unique, so picking
something already present is reported as `already_present` — never duplicated, never
reset.

**Copy the picks from another app.** An operator can seed a new instance from an
existing one: it copies that app's *selection*, its `sequence`, `is_enabled` and
`is_premium`, and optionally its overrides. Counters start at 0. The new rows still
point at the same central documents.

### 5.3 An app instance cannot create content

There is no "New category", "New subcategory" or "New asset" inside an app. The only
way something enters an app is by referencing central data.

If an operator needs content that doesn't exist yet, the flow is: create it in the
central library, then reference it. The instance UI makes this explicit — the empty
state of an app's content list offers "Choose from library" and a shortcut to the
central create screen, not an inline create form.

The API rejects instance-scoped creates with
`409 INSTANCE_CANNOT_CREATE_CONTENT`, naming the central endpoint to use instead.
This holds for uploads too: media is attached to central assets, never to a
reference row directly.

### 5.4 Editing and deleting inside an app

Both operations are **local to that app**, always.

**Editing** writes to the reference row's `overrides` object — only the fields
actually changed. Everything else keeps reading through to the live central document.

| Type | Fields an app may override |
|---|---|
| Category | name, thumbnail, banner image |
| Subcategory | name, thumbnail, banner image |
| Asset | name, description, thumbnail, `moreFields` |

An app can **not** change an item's parent category or subcategory. Reparenting would
fork the hierarchy away from central, so it's blocked; the operator changes it
centrally or picks a different asset.

`moreFields` overrides replace the whole object rather than merging block by block —
a partial merge across typed blocks produces content nobody can predict. The editor
pre-fills the central value so the operator edits from a real starting point.

Each overridden field shows an "Edited for this app" marker and a **Reset to central
value** action that clears the override and returns the field to reading through.

**Deleting** removes the reference row and nothing else. The central asset is
untouched and remains visible to every other app. The admin panel labels the action
"Remove from this app" rather than "Delete", and the confirmation says explicitly
that central data is unaffected. Removing a category or subcategory reference removes
its child references in that app only, with the count shown first.

Nothing an operator can do from inside an app writes to central data — not an edit,
not a delete, not a counter.

### 5.5 What happens when central data changes

Because instance rows are references, central edits propagate automatically:

| Central change | Effect in an app |
|---|---|
| Field edited, app has no override on it | Visible immediately |
| Field edited, app has overridden it | App keeps its own value |
| New asset added centrally | Not in any app until referenced — apps never auto-grow |
| Asset soft-deleted centrally | Reference becomes unresolvable |

An unresolvable reference is hidden from client catalog responses immediately and
listed in the app's content screen as **Source removed**, with one action: remove the
reference. Operators also get a "Referenced by N apps" count on every central item,
and the delete confirmation names those apps before proceeding.

### 5.6 Instance-only controls

These fields exist only on the reference row. They have no central counterpart, so
they are never overrides and never conflict with anything.

| Field | Applies to | What it does |
|---|---|---|
| `is_enabled` | category, subcategory, asset | Hides from the app without deleting. Disabling a category hides everything under it in client responses |
| `sequence` | category, subcategory, asset | Display order. Drag-and-drop in the admin panel; also settable via a reorder API taking an ordered list of IDs |
| `is_premium` | asset | Gated behind the app's paywall. Client responses always include the flag; premium media URLs are only returned to keys with the `premium` scope or to entitled clients |
| `views` | asset | Incremented via the track endpoint |
| `downloads` | asset | Incremented via the track endpoint |

Bulk actions on a selection: enable, disable, mark premium, unmark premium, remove
from instance, move to position.

`sequence` allows gaps and is reassigned in steps of 10 on a full reorder so single
insertions don't require rewriting every row.

### 5.7 What client apps see

`GET /api/v1/instance/{instance_id}/catalog` returns the enabled tree in sequence
order, with premium flags, ready to render.

Each item is **resolved** before it goes out: the central document is joined on
`source_id`, the app's `overrides` are layered on top, and the instance-only fields
are attached. Clients receive one flat object and never see that an override existed
— though `sourceId` is included so support tooling can trace an item back to central.
Resolution happens in a single aggregation, not a per-item fetch.

Items whose source has been deleted centrally are omitted. The API key determines
which instance is accessible; an instance-scoped key cannot read another instance's
catalog even if it guesses the ID.

---

## 6. Authentication and authorization

- Every API request carries `X-API-Key`. No key, no response.
- Keys look like `ak_live_<id>_<secret>`. Only a SHA-256 hash of the secret is
  stored, alongside a short prefix used for lookup and display. The full key is
  revealed once, at creation, and never again.
- Each key holds: a name, optional `app_instance_id` binding, a scope list, an
  active flag, an optional expiry, a per-minute rate limit, and a last-used
  timestamp.
- Scopes are `resource:action` — `categories:read`, `assets:write`,
  `analytics:read`, `keys:manage`, `premium:read`.
- An instance-bound key is confined to that instance's data. The filter is applied in
  the data layer, so a route that forgets to check still cannot leak.
- Rate limiting is per key, sliding window, returning 429 with `Retry-After`.
- Keys can be rotated (issue new, keep old alive for a grace period) and revoked
  (immediate). Revocation is instant — no cached allow-lists longer than 30 seconds.
- The admin panel has its own operator logins with session cookies. Admin sessions
  cannot call the client API, and API keys cannot open the admin panel.

**Key management screens**: list with prefix, scopes, instance, last used, status;
create with a one-time reveal and copy button; revoke with confirmation; usage chart
sourced from analytics.

---

## 7. Analytics

### 7.1 The monitoring list

Analytics is opt-in per endpoint. `monitored_endpoints` holds the route templates
being watched, each with an active flag, a sample rate, retention in days, and notes.
Operators add or remove endpoints from a screen in the admin panel — no deploy
needed.

### 7.2 Recording

Middleware runs on every request and checks the **matched route template**
(`/api/v1/assets/{asset_id}`), not the literal URL, so IDs never inflate cardinality.
If the template is monitored and passes the sample rate, an event is queued.

Each event records: route template, method, status code, duration in ms, API key ID,
app instance ID, error code if any, request and response byte counts, optional
client hints (platform, app version, country), and a timestamp.

Writes are fire-and-forget through an in-memory queue drained by a background task in
batches. **Analytics can never slow down or fail a request** — if the queue is full,
events are dropped and a warning is logged.

### 7.3 Reading

- Raw events power the last 24 hours and drill-downs.
- An hourly rollup job aggregates count, error count, p50/p95/p99 latency and bytes
  per route template per instance. Anything older than a day reads from rollups.
- Raw events expire on a TTL index using each endpoint's retention setting
  (default 30 days). Rollups are kept for 13 months.

### 7.4 Dashboard

- Traffic over time, filterable by endpoint, instance, key and status class
- Top endpoints by volume and by error rate
- Latency percentiles per endpoint
- Per-key usage, with a quick path to revoke a misbehaving key
- Content performance: most viewed and most downloaded assets per instance
- CSV export of any view

Asset `views` and `downloads` are counted separately from request analytics, via
`POST /api/v1/instance/{id}/assets/{asset_id}/track`, so they survive changes to the
monitoring list and can be batched by clients when offline.

---

## 8. Admin panel

Server-rendered, no frontend framework. Works without JavaScript for reading and
basic forms; JS enhances bulk selection, drag ordering and the frame editor.

**Screens**
- Dashboard — counts, recent activity, analytics summary
- Categories — list, single create, bulk create, edit, media, delete
- Subcategories — same, filtered by category
- Assets — list with filters (category, subcategory, type, date), single-file bulk
  add, multi-file individual add, `moreFields` editor, frame editor
- App instances — list, create, icon upload, per-instance content browser
- Instance content — library picker, drag reorder, enable/disable, premium toggles,
  counters, per-field override editor with "Edited for this app" markers and reset,
  "Remove from this app" (never "Delete"), and an unresolved-references tray. No
  create forms appear anywhere in this section
- API keys — issue, scope, rotate, revoke, usage
- Analytics — monitoring list management, dashboard, exports
- Settings — theme, operators, storage config

**Behavior**
- Light and dark themes, toggleable, remembered per browser, defaulting to the OS
  preference, applied before first paint so there's no flash.
- Material 3 color roles throughout, with no default Material purple anywhere.
- Responsive from 320px up: bottom navigation on phones, a rail on tablets, a drawer
  on desktop; data tables become stacked cards on narrow screens.
- Destructive actions are confirmed and state their blast radius ("This removes 1
  category, 6 subcategories and 214 assets").
- Long operations report progress and can be left running.

---

## 9. API surface

```
Auth: X-API-Key header on every route below.

Central library
  GET    /api/v1/categories
  POST   /api/v1/categories
  POST   /api/v1/categories/bulk
  GET    /api/v1/categories/{id}
  PATCH  /api/v1/categories/{id}
  DELETE /api/v1/categories/{id}

  GET    /api/v1/subcategories?categoryId=
  POST   /api/v1/subcategories
  POST   /api/v1/subcategories/bulk
  GET    /api/v1/subcategories/{id}
  PATCH  /api/v1/subcategories/{id}
  DELETE /api/v1/subcategories/{id}

  GET    /api/v1/assets?categoryId=&subCategoryId=&q=
  POST   /api/v1/assets                      # single, any moreFields
  POST   /api/v1/assets/bulk                 # single-file assets only
  GET    /api/v1/assets/{id}
  PATCH  /api/v1/assets/{id}
  DELETE /api/v1/assets/{id}

Media
  POST   /api/v1/uploads                     # returns stored URL + metadata
  POST   /api/v1/frames/detect               # image -> proposed placeholders

App instances
  GET    /api/v1/app-instances
  POST   /api/v1/app-instances
  GET    /api/v1/app-instances/{id}
  PATCH  /api/v1/app-instances/{id}
  DELETE /api/v1/app-instances/{id}

Instance content  — references only; no create endpoints exist here by design
  POST   /api/v1/app-instances/{id}/references           # {categoryIds, subCategoryIds, assetIds}
  POST   /api/v1/app-instances/{id}/references/copy-from # {sourceInstanceId, includeOverrides}
  GET    /api/v1/app-instances/{id}/categories           # resolved: central + overrides
  GET    /api/v1/app-instances/{id}/subcategories
  GET    /api/v1/app-instances/{id}/assets
  GET    /api/v1/app-instances/{id}/assets/{assetId}
  PATCH  /api/v1/app-instances/{id}/assets/{assetId}     # is_enabled, is_premium, sequence,
                                                         # and overrides.* — never central
  POST   /api/v1/app-instances/{id}/assets/{assetId}/reset-overrides  # {fields: [...] | all}
  DELETE /api/v1/app-instances/{id}/assets/{assetId}     # removes the reference only
  POST   /api/v1/app-instances/{id}/reorder              # {type, orderedIds}
  POST   /api/v1/app-instances/{id}/bulk-flags           # enable/disable/premium in bulk
  GET    /api/v1/app-instances/{id}/unresolved           # references whose source was deleted
  POST   /api/v1/instance/{id}/assets/{assetId}/track    # {event: view|download}
  GET    /api/v1/instance/{id}/catalog                   # client-facing resolved tree

  (categories and subcategories expose the same PATCH / reset-overrides / DELETE trio)

Central reverse lookup
  GET    /api/v1/assets/{id}/references                  # which apps reference this

Analytics
  GET    /api/v1/analytics/endpoints
  POST   /api/v1/analytics/endpoints
  PATCH  /api/v1/analytics/endpoints/{id}
  DELETE /api/v1/analytics/endpoints/{id}
  GET    /api/v1/analytics/summary?from=&to=&instanceId=
  GET    /api/v1/analytics/endpoints/{id}/series
  GET    /api/v1/analytics/export

Keys
  GET    /api/v1/keys
  POST   /api/v1/keys
  POST   /api/v1/keys/{id}/rotate
  DELETE /api/v1/keys/{id}
```

**Conventions** — lists return `{items, total, page, page_size, has_next}`; errors
return `{error: {code, message, details}}`; bulk returns 207 with per-item results
keyed by input index; mutating routes accept `Idempotency-Key`.

---

## 10. Non-functional requirements

| Area | Target |
|---|---|
| Latency | p95 under 200 ms for catalog reads at 10k assets per instance |
| Availability | Analytics outage never affects the API |
| Pagination | Mandatory on every list; max page size 100 |
| Bulk size | 500 items per request |
| Security | Keys hashed, constant-time comparison, never logged; instance isolation enforced in the data layer |
| Accessibility | 4.5:1 contrast both themes, keyboard operable, reduced motion respected |
| Observability | Structured JSON logs with a request ID on every line; health and readiness endpoints |
| Data safety | Soft deletes with recovery window; cascade deletes preview their impact; no instance action can write to central collections, enforced in the data layer |
| Read cost | Resolving references adds at most one aggregation stage per list — no N+1 lookups |


## 11. Deliberately out of scope for v1

- Public sign-up or self-service tenancy
- Real-time push of content updates to running apps
- Asset versioning and rollback
- CDN purge automation
- Machine-learned tagging or auto-categorization
- A/B testing of catalog ordering

Any of these arriving later must not require breaking the data models in section 4