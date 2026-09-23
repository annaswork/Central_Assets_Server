# 📱 Admin Assets App — Client SDK / API Integration Guide

> **Version:** 1.0  
> **Base URL:** `https://your-domain.com/api/v1`  
> **Audience:** Android developers integrating creative assets (stickers, frames, overlays, fonts, audio, etc.) into mobile apps like a **Collage Maker**, **Photo Editor**, **Video Editor**, etc.

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
2. [What You Receive from the Admin](#2-what-you-receive-from-the-admin)
3. [Authentication & Security](#3-authentication--security)
4. [Endpoints Reference](#4-endpoints-reference)
   - [Get Full Catalog Tree](#41-get-full-catalog-tree)
   - [List Categories](#42-list-categories)
   - [List Subcategories](#43-list-subcategories)
   - [List Assets](#44-list-assets)
   - [Get Single Asset](#45-get-single-asset)
   - [Track View / Download Event](#46-track-view--download-event)
5. [Response Schemas](#5-response-schemas)
6. [Sorting & Filtering](#6-sorting--filtering)
7. [Error Handling](#7-error-handling)
8. [Rate Limiting](#8-rate-limiting)
9. [Security Best Practices](#9-security-best-practices)
10. [Android Integration Example (Kotlin)](#10-android-integration-example-kotlin)
11. [FAQ](#11-faq)

---

## 1. Overview & Architecture

The **Admin Assets App** is a centralized creative asset management server. It allows your admin team to:

- Upload and organize creative assets (images, audio, video, Lottie animations, JSON configs, frame packs) into **Categories → Subcategories → Assets**.
- Create multiple **App Instances** — each representing a distinct mobile app (e.g., "Collage Maker", "Photo Editor", "Video Maker").
- Each App Instance maintains its own **independent** set of enabled/disabled states, premium flags, view counts, and download counts — completely isolated from other instances and the central library.

```
┌──────────────────────────────────────────┐
│           Central Asset Library          │
│  (Admin uploads, organizes, manages)     │
└──────────┬──────────┬────────────────────┘
           │          │
    ┌──────▼───┐  ┌───▼──────────┐
    │ Collage  │  │ Photo Editor │   ← App Instances
    │ Maker    │  │ Pro          │
    │ App      │  │ App          │
    └──────────┘  └──────────────┘
         │              │
    ┌────▼────┐    ┌────▼────┐
    │ Android │    │ Android │       ← Your mobile apps
    │ Client  │    │ Client  │
    └─────────┘    └─────────┘
```

**Your mobile app** communicates exclusively with its own App Instance via the REST API. It sees only the categories, subcategories, and assets that the admin has assigned to it.

---

## 2. What You Receive from the Admin

When the admin onboards your app, you will receive **exactly three pieces of information**:

| Item | Example | Description |
|---|---|---|
| **Base URL** | `https://assets.yourcompany.com/api/v1` | The API server address |
| **App Instance ID** | `6650a3f1c2e4b80012abcdef` | A 24-character hex string uniquely identifying your app's content |
| **API Key** | `ak_prod_aBcDeFgHiJkLmNoPqRsTuV_xYzAbCdEfGhIjKlMnOpQrStUvWx` | Your secret authentication key |

> **⚠️ CRITICAL:** The API key is shown **once** at creation time and **cannot be recovered**. Store it securely in your CI/CD secrets manager or encrypted config. Never commit it to source control.

### API Key Properties

Your API key is pre-configured by the admin with:

| Property | Description |
|---|---|
| **Scopes** | Permissions granted (e.g., `assets:read`, `categories:read`). You only need read scopes. |
| **App Instance Binding** | Locked to your specific App Instance ID. Cannot access other instances. |
| **Rate Limit** | Max requests per minute (default: 60, configurable up to 10,000). |
| **Expiry** | Optional expiration date. Key stops working after this date. |

### Key Format

```
ak_<env>_<22-char-id>_<32-char-secret>
│   │      │              │
│   │      │              └─ Secret (hashed on server, never stored in plaintext)
│   │      └──────────────── Key identifier (for lookups)
│   └─────────────────────── Environment (prod, stag, dev)
└─────────────────────────── Fixed prefix
```

---

## 3. Authentication & Security

### Sending Your API Key

Every request to the API **must** include the `X-API-Key` header:

```http
GET /api/v1/instance/{instanceId}/categories HTTP/1.1
Host: assets.yourcompany.com
X-API-Key: ak_prod_aBcDeFgHiJkLmNoPqRsTuV_xYzAbCdEfGhIjKlMnOpQrStUvWx
```

### What Happens on the Server

1. **Parsing** — The key is split into `prefix` and `secret`.
2. **Lookup** — The `prefix` is matched against the database.
3. **Validation** — Checks that the key is:
   - Active (not revoked or deactivated)
   - Not expired
   - Secret hash matches (SHA-256 with constant-time comparison)
4. **Scope enforcement** — Each endpoint requires specific scopes. If your key lacks the required scope, you'll get a `403 Forbidden`.
5. **Instance isolation** — If your key is bound to an App Instance, you can **only** access data belonging to that instance. Attempting to access another instance returns `403 Forbidden`.
6. **Rate limiting** — A sliding-window rate limiter enforces your per-minute request budget.

### Required Scopes for Client Apps

| Scope | Required For |
|---|---|
| `categories:read` | Listing categories and subcategories |
| `assets:read` | Listing assets, getting asset details, tracking views/downloads |

> **💡 Tip:** Your admin should create your API key with **only** these two scopes and bind it to your App Instance ID. This follows the principle of least privilege.

---

## 4. Endpoints Reference

All endpoints are under the base path: `/api/v1/instance/{instanceId}`

Replace `{instanceId}` with the 24-character App Instance ID you received from the admin.

---

### 4.1 Get Full Catalog Tree

Retrieves the complete, pre-resolved catalog hierarchy in a single request. Ideal for initial app load or splash screen pre-fetching.

```http
GET /api/v1/instance/{instanceId}/catalog
```

**Required Scope:** `assets:read`

**Response:**
```json
{
  "app_instance_id": "6650a3f1c2e4b80012abcdef",
  "categories": [
    {
      "id": "cat_001",
      "sourceId": "central_cat_001",
      "name": "Frames",
      "thumbnail_url": "https://cdn.example.com/frames-thumb.webp",
      "is_enabled": true,
      "sequence": 1,
      "subcategories": [
        {
          "id": "sub_001",
          "sourceId": "central_sub_001",
          "name": "Birthday Frames",
          "categoryId": "cat_001",
          "is_enabled": true,
          "sequence": 1,
          "assets": [
            {
              "id": "asset_001",
              "sourceId": "central_asset_001",
              "name": "Gold Birthday Frame",
              "description": "Elegant gold photo frame",
              "thumbnail_url": "https://cdn.example.com/gold-frame-thumb.webp",
              "thumbnailUrl": "https://cdn.example.com/gold-frame-thumb.webp",
              "categoryId": "cat_001",
              "subCategoryId": "sub_001",
              "is_enabled": true,
              "is_premium": false,
              "sequence": 1,
              "views": 1250,
              "downloads": 340,
              "more_fields": { ... },
              "moreFields": { ... }
            }
          ]
        }
      ]
    }
  ]
}
```

> **📌 Note:** Only `is_enabled: true` items are included in the catalog tree. Use this endpoint for pre-loading the entire hierarchy. For granular querying, use the individual list endpoints below.

---

### 4.2 List Categories

```http
GET /api/v1/instance/{instanceId}/categories
```

**Required Scope:** `categories:read`

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `only_enabled` | `boolean` | `false` | If `true`, returns only enabled categories |

**Response:** `200 OK` — Array of category objects

```json
[
  {
    "id": "66a1b2c3d4e5f60012345678",
    "sourceId": "669f1234abcd5678ef901234",
    "name": "Stickers",
    "thumbnail_url": "https://cdn.example.com/stickers-thumb.webp",
    "image_url": "https://cdn.example.com/stickers-banner.webp",
    "is_enabled": true,
    "sequence": 1,
    "overrides": {}
  },
  {
    "id": "66a1b2c3d4e5f60012345679",
    "sourceId": "669f1234abcd5678ef901235",
    "name": "Backgrounds",
    "thumbnail_url": "https://cdn.example.com/bg-thumb.webp",
    "is_enabled": true,
    "sequence": 2,
    "overrides": {}
  }
]
```

---

### 4.3 List Subcategories

```http
GET /api/v1/instance/{instanceId}/subcategories
```

**Required Scope:** `categories:read`

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `categoryId` | `string` | — | Filter by parent category ID |
| `only_enabled` | `boolean` | `false` | If `true`, returns only enabled subcategories |

**Response:** `200 OK` — Array of subcategory objects

```json
[
  {
    "id": "66b2c3d4e5f6a70012345678",
    "sourceId": "66a01234abcd5678ef901234",
    "name": "Cute Animals",
    "categoryId": "66a1b2c3d4e5f60012345678",
    "thumbnail_url": "https://cdn.example.com/cute-animals-thumb.webp",
    "is_enabled": true,
    "sequence": 1,
    "overrides": {}
  }
]
```

---

### 4.4 List Assets

```http
GET /api/v1/instance/{instanceId}/assets
```

**Required Scope:** `assets:read`

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `categoryId` | `string` | — | Filter by category ID |
| `subCategoryId` | `string` | — | Filter by subcategory ID |
| `only_enabled` | `boolean` | `false` | If `true`, returns only enabled assets |
| `sort` | `string` | — | Sort field (see [Sorting & Filtering](#6-sorting--filtering)) |
| `order` | `string` | `asc` | Sort direction: `asc` or `desc` |

**Response:** `200 OK` — Array of asset objects

```json
[
  {
    "id": "66c3d4e5f6a7b80012345678",
    "sourceId": "66b01234abcd5678ef901234",
    "name": "Rainbow Sticker Pack",
    "description": "Colorful rainbow-themed sticker collection",
    "thumbnail_url": "https://cdn.example.com/rainbow-pack-thumb.webp",
    "thumbnailUrl": "https://cdn.example.com/rainbow-pack-thumb.webp",
    "categoryId": "66a1b2c3d4e5f60012345678",
    "subCategoryId": "66b2c3d4e5f6a70012345678",
    "category_name": "Stickers",
    "categoryName": "Stickers",
    "subcategory_name": "Cute Animals",
    "subCategoryName": "Cute Animals",
    "is_enabled": true,
    "is_premium": false,
    "sequence": 1,
    "views": 4320,
    "downloads": 891,
    "created_at": "2026-08-15T10:30:00.000Z",
    "updated_at": "2026-09-20T14:22:00.000Z",
    "more_fields": {
      "blocks": [
        {
          "type": "image",
          "label": "Sticker PNG",
          "url": "https://cdn.example.com/rainbow-sticker.png",
          "mime_type": "image/png",
          "size_bytes": 245760,
          "width": 512,
          "height": 512
        }
      ]
    },
    "moreFields": { ... },
    "overrides": {}
  }
]
```

---

### 4.5 Get Single Asset

```http
GET /api/v1/instance/{instanceId}/assets/{assetId}
```

**Required Scope:** `assets:read`

**Response:** `200 OK` — Single asset object (same schema as list items)

**Error:** `404 Not Found` if the asset doesn't exist in this instance.

---

### 4.6 Track View / Download Event

This is the **only write endpoint** available to client apps. It atomically increments the asset's view or download counter **within your app instance** and simultaneously records an analytics event for the admin dashboard.

```http
POST /api/v1/instance/{instanceId}/assets/{assetId}/track
Content-Type: application/json
X-API-Key: ak_prod_...
```

**Required Scope:** `assets:read`

**Request Body:**

```json
{
  "event": "view"
}
```

| Field | Type | Required | Allowed Values | Description |
|---|---|---|---|---|
| `event` | `string` | ✅ | `"view"` or `"download"` | The type of interaction to record |

**Response:** `200 OK` — Returns the **updated** counters after the atomic increment:

```json
{
  "views": 4321,
  "downloads": 891
}
```

#### How It Works Internally

1. **Atomic Increment** — The server uses MongoDB's `$inc` operator to atomically increment the counter by 1. This is safe under concurrent requests — no race conditions, no double counts.
2. **Per-Instance Isolation** — The counter lives on the **instance asset reference** (`INSTANCE_ASSETS` collection), not on the central asset. So:
   - Collage Maker's views are independent from Photo Editor's views.
   - Deleting an instance resets its counters. The central asset's counters are untouched.
3. **Analytics Event** — After the counter is updated, the server enqueues an analytics event with:
   - `app_instance_id` — Your instance
   - `asset_id` — The asset that was viewed/downloaded
   - `event_type` — `"view"` or `"download"`
   - `status_code` — `200`
   - Timestamp and duration
4. **Idempotency** — This endpoint is **NOT idempotent**. Each call increments by 1. Do not retry on success.

#### When to Fire Each Event

| Event | Trigger Point | Example (Collage Maker) |
|---|---|---|
| `"view"` | User **previews** or opens the detail view of an asset | User taps a frame thumbnail → the full preview appears |
| `"download"` | User **applies**, **saves**, or **exports** using the asset | User taps "Apply Frame" → the frame is composited onto their photo |

#### Error Cases

| HTTP Status | Cause |
|---|---|
| `404` | The `assetId` does not exist in this app instance |
| `422` | The `event` field is missing or has an invalid value (not `"view"` or `"download"`) |
| `401` | Missing or invalid API key |
| `403` | API key is bound to a different instance |

#### Integration Flow (Collage Maker Example)

```
User taps "Frames" category
    │
    ├─► GET /instance/{id}/assets?categoryId=...&only_enabled=true
    │   └─► Display frame grid
    │
User taps a frame thumbnail
    │
    ├─► POST /instance/{id}/assets/{assetId}/track  {"event": "view"}  ← fire & forget
    │   └─► Server: views++ (4320 → 4321), analytics event queued
    │
    ├─► GET /instance/{id}/assets/{assetId}
    │   └─► Show full frame preview with details
    │
User taps "Apply to Photo"
    │
    ├─► POST /instance/{id}/assets/{assetId}/track  {"event": "download"}  ← fire & forget
    │   └─► Server: downloads++ (891 → 892), analytics event queued
    │
    └─► Download frame image from CDN URL (moreFields.blocks[0].url)
        └─► Apply frame overlay to user's photo locally
```

> **💡 Tip:** Fire-and-forget these calls. Don't block the UI on them. If they fail, silently drop — analytics should never degrade UX. The counters will be slightly undercounted, which is acceptable.

---

## 5. Response Schemas

### Category Object

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Instance-specific category ID |
| `sourceId` | `string` | Central library source ID |
| `name` | `string` | Display name |
| `thumbnail_url` | `string?` | Category thumbnail image URL |
| `image_url` | `string?` | Category banner/header image URL |
| `is_enabled` | `boolean` | Whether this category is active |
| `sequence` | `integer` | Sort order (lower = first) |
| `overrides` | `object` | Admin-applied per-instance overrides |

### Subcategory Object

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Instance-specific subcategory ID |
| `sourceId` | `string` | Central library source ID |
| `categoryId` | `string` | Parent category ID |
| `name` | `string` | Display name |
| `thumbnail_url` | `string?` | Subcategory thumbnail URL |
| `is_enabled` | `boolean` | Whether this subcategory is active |
| `sequence` | `integer` | Sort order |
| `overrides` | `object` | Admin-applied per-instance overrides |

### Asset Object

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Instance-specific asset ID |
| `sourceId` | `string` | Central library source ID |
| `name` | `string` | Display name |
| `description` | `string?` | Asset description |
| `thumbnail_url` | `string` | Preview thumbnail URL (also available as `thumbnailUrl`) |
| `categoryId` | `string` | Parent category ID |
| `subCategoryId` | `string` | Parent subcategory ID |
| `category_name` | `string` | Human-readable category name (also as `categoryName`) |
| `subcategory_name` | `string` | Human-readable subcategory name (also as `subCategoryName`) |
| `is_enabled` | `boolean` | Whether this asset is active in this instance |
| `is_premium` | `boolean` | Whether this is a premium/paid asset |
| `sequence` | `integer` | Sort order |
| `views` | `integer` | Total view count for this instance |
| `downloads` | `integer` | Total download count for this instance |
| `created_at` | `string (ISO 8601)` | Creation timestamp |
| `updated_at` | `string (ISO 8601)` | Last update timestamp |
| `more_fields` | `object?` | Rich media blocks (also available as `moreFields`) |
| `overrides` | `object` | Instance-specific content overrides |

### The `more_fields` / `moreFields` Object

This is the **most important field** for actual asset consumption. It contains the downloadable media blocks:

```json
{
  "blocks": [
    {
      "type": "image",
      "label": "Full Resolution PNG",
      "url": "https://cdn.example.com/asset-full.png",
      "mime_type": "image/png",
      "size_bytes": 2457600,
      "width": 2048,
      "height": 2048
    },
    {
      "type": "image_list",
      "label": "Sticker Variants",
      "items": [
        {
          "url": "https://cdn.example.com/variant-1.webp",
          "mime_type": "image/webp",
          "size_bytes": 51200,
          "width": 512,
          "height": 512
        }
      ]
    },
    {
      "type": "audio",
      "label": "Sound Effect",
      "url": "https://cdn.example.com/sfx.mp3",
      "mime_type": "audio/mpeg",
      "duration_seconds": 3.5,
      "size_bytes": 56320
    },
    {
      "type": "video",
      "label": "Animation",
      "url": "https://cdn.example.com/anim.mp4",
      "mime_type": "video/mp4",
      "poster_url": "https://cdn.example.com/anim-poster.webp",
      "duration_seconds": 5.0,
      "width": 1080,
      "height": 1080,
      "size_bytes": 1048576
    },
    {
      "type": "json",
      "label": "Lottie Animation",
      "url": "https://cdn.example.com/confetti.json",
      "mime_type": "application/json",
      "size_bytes": 32768
    },
    {
      "type": "frames",
      "label": "Frame Coordinates",
      "url": "https://cdn.example.com/frame-template.png",
      "coordinates": [
        { "x": 50, "y": 120, "width": 400, "height": 400 },
        { "x": 500, "y": 120, "width": 400, "height": 400 }
      ]
    }
  ]
}
```

**Block Types:**

| Type | Description | Key Fields |
|---|---|---|
| `image` | Single image file | `url`, `mime_type`, `width`, `height`, `size_bytes` |
| `image_list` | Multiple image variants | `items[]` (each with `url`, `mime_type`, `width`, `height`) |
| `audio` | Audio file | `url`, `mime_type`, `duration_seconds`, `size_bytes` |
| `audio_list` | Multiple audio files | `items[]` (each with audio fields) |
| `video` | Video file | `url`, `mime_type`, `poster_url`, `duration_seconds`, `width`, `height` |
| `video_list` | Multiple video files | `items[]` (each with video fields) |
| `json` | JSON / Lottie animation | `url`, `mime_type`, `size_bytes` |
| `frames` | Frame template with coordinates | `url`, `coordinates[]` (each with `x`, `y`, `width`, `height`) |

---

## 6. Sorting & Filtering

### Filtering

Pass query parameters to narrow results:

```http
GET /api/v1/instance/{instanceId}/assets?categoryId=66a1b2c3...&only_enabled=true
```

| Filter | Applies To | Description |
|---|---|---|
| `categoryId` | subcategories, assets | Show items in a specific category |
| `subCategoryId` | assets | Show items in a specific subcategory |
| `only_enabled` | categories, subcategories, assets | Exclude disabled items |

### Sorting

Use the `sort` and `order` query parameters on the `/assets` endpoint:

```http
GET /api/v1/instance/{instanceId}/assets?sort=newest&order=desc
```

| `sort` Value | Description |
|---|---|
| _(empty / default)_ | By admin-defined sequence order |
| `name` or `by_name` or `title` | Alphabetical by name |
| `newest` | Most recently created first |
| `oldest` | Oldest first |
| `most_viewed` or `views` | Highest view count first |
| `most_downloaded` or `downloads` | Highest download count first |

| `order` Value | Description |
|---|---|
| `asc` _(default)_ | Ascending |
| `desc` | Descending |

---

## 7. Error Handling

All errors follow a consistent envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Referenced asset not found in this app instance",
    "details": {}
  }
}
```

### HTTP Status Codes

| Status | Code | Meaning |
|---|---|---|
| `401` | `MISSING_API_KEY` | `X-API-Key` header was not provided |
| `401` | `UNAUTHORIZED` | API key is invalid, expired, or revoked |
| `403` | `FORBIDDEN` | Key lacks required scope or is accessing another instance |
| `404` | `NOT_FOUND` | Resource (asset, category, instance) does not exist |
| `422` | `VALIDATION_ERROR` | Request body failed validation (e.g., invalid `event` type) |
| `429` | `RATE_LIMITED` | Rate limit exceeded — check `Retry-After` header |
| `500` | `INTERNAL_SERVER_ERROR` | Unexpected server error |

### Rate Limit Response

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 42
Content-Type: application/json

{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Rate limit of 60 requests/min exceeded",
    "details": {
      "retry_after": 42
    }
  }
}
```

---

## 8. Rate Limiting

- **Mechanism:** Sliding-window per API key, tracked per minute.
- **Default:** 60 requests/minute (admin can increase up to 10,000).
- **Headers:** `Retry-After` is set on 429 responses.
- **Strategy:** Implement exponential backoff in your client.

**Recommended client behavior:**

```
if (response.code == 429) {
    val retryAfter = response.header("Retry-After")?.toIntOrNull() ?: 60
    delay(retryAfter * 1000L)
    retry()
}
```

---

## 9. Security Best Practices

### 🔐 Storing the API Key

| ❌ Don't | ✅ Do |
|---|---|
| Hardcode in source code | Store in `local.properties` (gitignored) or CI secrets |
| Commit to Git / GitHub | Inject at build time via `BuildConfig` |
| Log the key in Logcat | Use ProGuard/R8 to strip debug logs |
| Ship the key in plain APK strings | Obfuscate via NDK (C/C++ `.so`) or encrypted SharedPreferences |

### Recommended: NDK-based Key Storage

Store the API key in a native C library so it's not trivially extractable from the APK:

```c
// native-lib.c
#include <jni.h>
#include <string.h>

JNIEXPORT jstring JNICALL
Java_com_example_collagemaker_security_KeyStore_getApiKey(JNIEnv *env, jobject obj) {
    // Obfuscate: split and recombine at runtime
    return (*env)->NewStringUTF(env, "ak_prod_aBcDeFgHiJk..._xYzAbCdEfGhI...");
}
```

```kotlin
// KeyStore.kt
object KeyStore {
    init { System.loadLibrary("native-lib") }
    external fun getApiKey(): String
}
```

### Recommended: BuildConfig Injection

```groovy
// build.gradle.kts
android {
    defaultConfig {
        buildConfigField("String", "ASSETS_API_KEY", "\"${project.findProperty("ASSETS_API_KEY")}\"")
        buildConfigField("String", "ASSETS_INSTANCE_ID", "\"${project.findProperty("ASSETS_INSTANCE_ID")}\"")
        buildConfigField("String", "ASSETS_BASE_URL", "\"${project.findProperty("ASSETS_BASE_URL")}\"")
    }
}
```

```properties
# local.properties (NEVER committed to git)
ASSETS_API_KEY=ak_prod_aBcDeFgHiJkLmNoPqRsTuV_xYzAbCdEfGhIjKlMnOpQrStUvWx
ASSETS_INSTANCE_ID=6650a3f1c2e4b80012abcdef
ASSETS_BASE_URL=https://assets.yourcompany.com/api/v1
```

### Network Security

- **HTTPS only** — Never make API calls over plain HTTP.
- **Certificate pinning** — Consider pinning your server's TLS certificate in `network_security_config.xml`:

```xml
<!-- res/xml/network_security_config.xml -->
<network-security-config>
    <domain-config cleartextTrafficPermitted="false">
        <domain includeSubdomains="true">assets.yourcompany.com</domain>
        <pin-set expiration="2027-01-01">
            <pin digest="SHA-256">base64encodedSHA256hash=</pin>
        </pin-set>
    </domain-config>
</network-security-config>
```

---

## 10. Android Integration Example (Kotlin)

### Project Setup

```groovy
// build.gradle.kts (app module)
dependencies {
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("io.coil-kt:coil:2.7.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
```

### API Service Definition

```kotlin
// data/remote/AssetsApiService.kt

interface AssetsApiService {

    @GET("instance/{instanceId}/catalog")
    suspend fun getCatalog(
        @Path("instanceId") instanceId: String
    ): CatalogResponse

    @GET("instance/{instanceId}/categories")
    suspend fun getCategories(
        @Path("instanceId") instanceId: String,
        @Query("only_enabled") onlyEnabled: Boolean = true
    ): List<Category>

    @GET("instance/{instanceId}/subcategories")
    suspend fun getSubcategories(
        @Path("instanceId") instanceId: String,
        @Query("categoryId") categoryId: String? = null,
        @Query("only_enabled") onlyEnabled: Boolean = true
    ): List<Subcategory>

    @GET("instance/{instanceId}/assets")
    suspend fun getAssets(
        @Path("instanceId") instanceId: String,
        @Query("categoryId") categoryId: String? = null,
        @Query("subCategoryId") subCategoryId: String? = null,
        @Query("only_enabled") onlyEnabled: Boolean = true,
        @Query("sort") sort: String? = null,
        @Query("order") order: String? = null
    ): List<Asset>

    @GET("instance/{instanceId}/assets/{assetId}")
    suspend fun getAsset(
        @Path("instanceId") instanceId: String,
        @Path("assetId") assetId: String
    ): Asset

    @POST("instance/{instanceId}/assets/{assetId}/track")
    suspend fun trackEvent(
        @Path("instanceId") instanceId: String,
        @Path("assetId") assetId: String,
        @Body payload: TrackEventPayload
    ): TrackEventResponse
}
```

### Data Models

```kotlin
// data/models/CatalogModels.kt

data class CatalogResponse(
    @SerializedName("app_instance_id") val appInstanceId: String,
    val categories: List<CategoryWithContent>
)

data class CategoryWithContent(
    val id: String,
    val sourceId: String,
    val name: String,
    @SerializedName("thumbnail_url") val thumbnailUrl: String?,
    @SerializedName("is_enabled") val isEnabled: Boolean,
    val sequence: Int,
    val subcategories: List<SubcategoryWithAssets>
)

data class SubcategoryWithAssets(
    val id: String,
    val sourceId: String,
    val name: String,
    val categoryId: String,
    @SerializedName("thumbnail_url") val thumbnailUrl: String?,
    @SerializedName("is_enabled") val isEnabled: Boolean,
    val sequence: Int,
    val assets: List<Asset>
)

data class Category(
    val id: String,
    val sourceId: String,
    val name: String,
    @SerializedName("thumbnail_url") val thumbnailUrl: String?,
    @SerializedName("image_url") val imageUrl: String?,
    @SerializedName("is_enabled") val isEnabled: Boolean,
    val sequence: Int
)

data class Subcategory(
    val id: String,
    val sourceId: String,
    val name: String,
    val categoryId: String,
    @SerializedName("thumbnail_url") val thumbnailUrl: String?,
    @SerializedName("is_enabled") val isEnabled: Boolean,
    val sequence: Int
)

data class Asset(
    val id: String,
    val sourceId: String,
    val name: String,
    val description: String?,
    @SerializedName("thumbnail_url") val thumbnailUrl: String?,
    val categoryId: String,
    val subCategoryId: String?,
    @SerializedName("category_name") val categoryName: String?,
    @SerializedName("subcategory_name") val subcategoryName: String?,
    @SerializedName("is_enabled") val isEnabled: Boolean,
    @SerializedName("is_premium") val isPremium: Boolean,
    val sequence: Int,
    val views: Int,
    val downloads: Int,
    @SerializedName("created_at") val createdAt: String?,
    @SerializedName("updated_at") val updatedAt: String?,
    @SerializedName("more_fields") val moreFields: MoreFields?
)

data class MoreFields(
    val blocks: List<MediaBlock>?
)

data class MediaBlock(
    val type: String,       // "image", "image_list", "audio", "video", "json", "frames"
    val label: String?,
    val url: String?,
    @SerializedName("mime_type") val mimeType: String?,
    @SerializedName("size_bytes") val sizeBytes: Long?,
    val width: Int?,
    val height: Int?,
    @SerializedName("duration_seconds") val durationSeconds: Double?,
    @SerializedName("poster_url") val posterUrl: String?,
    val items: List<MediaBlock>?,           // For *_list types
    val coordinates: List<FrameCoord>?      // For "frames" type
)

data class FrameCoord(
    val x: Int,
    val y: Int,
    val width: Int,
    val height: Int
)

data class TrackEventPayload(
    val event: String   // "view" or "download"
)

data class TrackEventResponse(
    val views: Int,
    val downloads: Int
)
```

### Retrofit Client with Auth Interceptor

```kotlin
// data/remote/ApiClient.kt

object ApiClient {

    private val authInterceptor = Interceptor { chain ->
        val request = chain.request().newBuilder()
            .addHeader("X-API-Key", BuildConfig.ASSETS_API_KEY)
            .build()
        chain.proceed(request)
    }

    private val rateLimitInterceptor = Interceptor { chain ->
        var response = chain.proceed(chain.request())
        var retries = 0
        while (response.code == 429 && retries < 3) {
            val retryAfter = response.header("Retry-After")?.toLongOrNull() ?: 5
            response.close()
            Thread.sleep(retryAfter * 1000)
            response = chain.proceed(chain.request())
            retries++
        }
        response
    }

    private val okHttpClient = OkHttpClient.Builder()
        .addInterceptor(authInterceptor)
        .addInterceptor(rateLimitInterceptor)
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    val service: AssetsApiService by lazy {
        Retrofit.Builder()
            .baseUrl(BuildConfig.ASSETS_BASE_URL + "/")
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(AssetsApiService::class.java)
    }
}
```

### Repository Layer

```kotlin
// data/repository/AssetsRepository.kt

class AssetsRepository {

    private val api = ApiClient.service
    private val instanceId = BuildConfig.ASSETS_INSTANCE_ID

    // ── Catalog ──────────────────────────────────────────────

    suspend fun getFullCatalog(): Result<CatalogResponse> = runCatching {
        api.getCatalog(instanceId)
    }

    // ── Categories ───────────────────────────────────────────

    suspend fun getCategories(): Result<List<Category>> = runCatching {
        api.getCategories(instanceId, onlyEnabled = true)
    }

    suspend fun getSubcategories(categoryId: String): Result<List<Subcategory>> = runCatching {
        api.getSubcategories(instanceId, categoryId = categoryId, onlyEnabled = true)
    }

    // ── Assets ───────────────────────────────────────────────

    suspend fun getAssets(
        categoryId: String? = null,
        subCategoryId: String? = null,
        sort: String? = null
    ): Result<List<Asset>> = runCatching {
        api.getAssets(
            instanceId,
            categoryId = categoryId,
            subCategoryId = subCategoryId,
            onlyEnabled = true,
            sort = sort
        )
    }

    suspend fun getAssetDetail(assetId: String): Result<Asset> = runCatching {
        api.getAsset(instanceId, assetId)
    }

    // ── Tracking (fire-and-forget) ───────────────────────────

    fun trackView(assetId: String) {
        CoroutineScope(Dispatchers.IO).launch {
            runCatching {
                api.trackEvent(instanceId, assetId, TrackEventPayload("view"))
            }
        }
    }

    fun trackDownload(assetId: String) {
        CoroutineScope(Dispatchers.IO).launch {
            runCatching {
                api.trackEvent(instanceId, assetId, TrackEventPayload("download"))
            }
        }
    }
}
```

### Usage in a ViewModel

```kotlin
// ui/collage/CollageViewModel.kt

class CollageViewModel : ViewModel() {

    private val repo = AssetsRepository()

    private val _frames = MutableStateFlow<List<Asset>>(emptyList())
    val frames: StateFlow<List<Asset>> = _frames.asStateFlow()

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    fun loadFrames(categoryId: String) {
        viewModelScope.launch {
            _loading.value = true
            repo.getAssets(categoryId = categoryId, sort = "newest")
                .onSuccess { assets ->
                    // Filter premium for free users, or show with lock icon
                    _frames.value = assets
                }
                .onFailure { error ->
                    Log.e("CollageVM", "Failed to load frames", error)
                }
            _loading.value = false
        }
    }

    fun onFramePreview(asset: Asset) {
        repo.trackView(asset.id)   // Fire-and-forget
    }

    fun onFrameApplied(asset: Asset) {
        repo.trackDownload(asset.id)   // Fire-and-forget
        // Apply the frame to the canvas...
        val frameBlock = asset.moreFields?.blocks?.firstOrNull { it.type == "frames" }
        if (frameBlock != null) {
            // Use frameBlock.url for the template image
            // Use frameBlock.coordinates for photo placement regions
        }
    }
}
```

---

## 11. FAQ

### Q: Can my API key access other app instances?

**No.** If your key is bound to an App Instance (which it should be for production), all requests are isolated to that instance. Attempting to access another instance returns `403 Forbidden`.

### Q: What happens if my API key expires?

The server returns `401 Unauthorized` with code `UNAUTHORIZED` and message "API key has expired". Contact your admin to issue a new key or rotate the existing one.

### Q: Can I create, update, or delete assets from the mobile app?

**No.** Client API keys should only have `read` scopes. Asset management is done exclusively through the admin panel. Your app is a read-only consumer.

### Q: How do I handle premium/paid assets?

Check the `is_premium` field on each asset. Show a lock icon or purchase prompt for premium assets. The admin controls which assets are marked premium on a **per-instance** basis.

### Q: Are views and downloads shared across apps?

**No.** Each App Instance tracks its own independent view and download counters. A "view" in Collage Maker does not affect the count in Photo Editor.

### Q: What is the `sourceId` field?

It references the original asset in the central library. You generally don't need it — use the `id` field for all API calls. The `sourceId` is useful only if you need to detect when two different instances share the same underlying asset.

### Q: What if the server is down or unreachable?

Implement offline fallback:
1. Cache the catalog response locally (Room DB or file cache).
2. Serve from cache when offline.
3. Refresh when network is available.
4. Set reasonable timeouts (30s connect, 30s read).

### Q: How do I download the actual media files?

The `thumbnail_url` and media block `url` fields contain direct CDN URLs. Download them using OkHttp, Coil, Glide, or any HTTP client. These URLs do **not** require the API key — they are public CDN links.

### Q: What is the `overrides` field?

It contains per-instance customizations applied by the admin (e.g., a different name or description for your specific app). The API response already merges overrides with central data, so you can ignore this field and use the top-level `name`, `description`, etc. directly.

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────────┐
│                     QUICK REFERENCE                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Auth Header:  X-API-Key: ak_prod_...                              │
│  Base Path:    /api/v1/instance/{instanceId}                       │
│                                                                     │
│  GET  /catalog            → Full tree (categories > subs > assets) │
│  GET  /categories         → List categories                        │
│  GET  /subcategories      → List subcategories (?categoryId=...)   │
│  GET  /assets             → List assets (?categoryId=&sort=...)    │
│  GET  /assets/{assetId}   → Single asset detail                    │
│  POST /assets/{id}/track  → Track view/download {"event":"view"}   │
│                                                                     │
│  Scopes needed: categories:read, assets:read                       │
│  Rate limit: check Retry-After on 429                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```
