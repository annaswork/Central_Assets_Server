# Creative Asset Library & App Instance Management Platform

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Motor_Async-47A248?style=flat-square&logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![License](https://img.shields.io/badge/License-Proprietary-blue?style=flat-square)](#)

A centralized creative asset library and multi-tenant app instance delivery platform. Author assets centrally once (Categories, Subcategories, Assets), then reference, reorder, monetize, and override metadata per mobile/web client app without data duplication.

---

## 🏗️ Architecture & Data Flow

```
CENTRAL LIBRARY (Single source of truth for authored content)
Category ──────────────► Subcategory ──────────────► Asset
   ▲                          ▲                         ▲
   │                          │                         │  reference by source_id
   │                          │                         │  (+ sparse overrides)
   │                          │                         │
APP INSTANCE "Photo Editor Pro" (package: com.app.photoeditor)
Instance Category ─────► Instance Subcategory ─────► Instance Asset
• is_enabled              • is_enabled               • is_enabled, sequence
• sequence                • sequence                 • is_premium (monetization)
• sparse overrides{}      • sparse overrides{}       • analytics (views, downloads)
```

- **One-Way Data Flow**: Edits and sequence orders made within an app instance only affect that specific app. Central content remains clean and untouched.
- **Sparse Overrides**: App instances store only the delta fields they override (e.g., custom display name, custom thumbnail, or premium status) rather than duplicating the entire asset.

---

## ✨ Key Features

- **Central Asset Catalog**:
  - 3-level fixed hierarchy: `Category` → `Subcategory` → `Asset`.
  - Flexible content blocks: images, videos, audio, text lists, and custom JSON payloads.
  - Transparent frame placeholder detection and bounding-box extraction using OpenCV.
  - Automatic video poster generation and duration/dimension probing via FFmpeg.
- **App Instance Management**:
  - Manage multiple client apps (iOS, Android, Web) independently.
  - Reference central categories/subcategories/assets or clone entire trees.
  - Drag-and-drop sequencing and monetization gating (`is_premium`).
  - Sparse field overrides with one-click reset to central defaults.
- **High-Performance Analytics**:
  - Non-blocking async queueing for client tracking events (`view`, `download`).
  - Background batch flusher with automated 30-day retention pruning.
  - Real-time API monitoring, request logs, and error rate tracking.
- **Modern Responsive Admin Panel**:
  - Full-featured web admin UI built with Jinja2 and Material Design 3 design tokens.
  - Light / Dark theme support.
  - Fast asset upload dropzones with cropping, aspect ratio locking, and video playback.
- **Enterprise Security**:
  - Scoped API key authentication (`X-API-Key`) with automated revocation.
  - Cryptographically signed, encrypted admin session cookies.
  - **HTTP Basic Authentication** on interactive Swagger UI (`/docs`), ReDoc (`/redoc`), and OpenAPI schema (`/openapi.json`).

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) (ASGI) |
| **Database** | [MongoDB](https://www.mongodb.com/) via [Motor](https://motor.readthedocs.io/) (Async Python Driver) |
| **Media Processing** | OpenCV Headless, Pillow (PIL), NumPy, `imageio-ffmpeg` |
| **Frontend / Templates** | Server-rendered Jinja2 templates, Vanilla CSS (MD3 Design System), Vanilla JS |
| **Security & Auth** | `itsdangerous` (URLSafeTimedSerializer), `bcrypt`, HTTP Basic Auth |

---

## 📂 Project Structure

```
.
├── analytics/            # Async analytics queue, batch worker, and aggregation rollups
├── authorization/        # API key verification, admin session cookies, encryption
├── config/               # Pydantic settings, constants, and filesystem path resolvers
├── controller/           # Business logic and database operations (central, instance, admin)
├── database/             # MongoDB async client, collections, and connection lifespan
├── inits/                # FastAPI application factory, middleware, routes, exception handlers
├── middlewares/          # API tracking, CORS, request IDs, rate limiting, and security headers
├── router/               # Route definitions: /api/v1 (client API) and /admin (web UI)
├── scripts/              # Administrative CLI scripts (create_admin, issue_key, etc.)
├── static/               # Central uploaded media, app icons, and static assets
├── templates/            # Jinja2 templates and CSS/JS stylesheets for Admin UI
├── utils/                # Media processing, frame extraction, error envelopes, and helpers
├── main.py               # Application entry point
├── requirements.txt      # Production dependencies
├── .env.example          # Environment variable template
└── .gitignore            # Git ignore rules
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+**
- **MongoDB 6.0+** running locally or via MongoDB Atlas
- **FFmpeg** (installed on system path for media probing)

### 1. Clone & Setup Virtual Environment

```bash
# Clone repository
git clone <repository-url>
cd "Admin Assets App"

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and configure your settings:

```bash
cp .env.example .env
```

Key environment variables in `.env`:

```ini
# Server
ENV=development
PORT=8020
HOST=0.0.0.0
LOG_LEVEL=INFO

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=admin_assets_db

# Secrets (Change in production!)
SECRET_KEY=generate_a_secure_32_char_random_string
ADMIN_SESSION_SECRET=generate_another_secure_32_char_secret

# Initial Admin Operator Bootstrap
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=your_secure_admin_password

# API Documentation Auth (HTTP Basic Auth for /docs)
DOCS_USERNAME=admin
DOCS_PASSWORD=your_secure_docs_password
```

### 3. Initialize Database & Create Admin User

Run the CLI script to create your first administrative user:

```bash
python scripts/create_admin.py --username admin --password your_secure_admin_password
```

### 4. Run the Application

#### Development Mode (with Auto-Reload):
```bash
uvicorn main:app --host 0.0.0.0 --port 8020 --reload
```

#### Production Mode:
```bash
uvicorn main:app --host 0.0.0.0 --port 8020 --workers 4
```

---

## 🔑 Utility CLI Scripts

The `scripts/` directory contains admin maintenance utilities:

| Command | Purpose |
|---|---|
| `python scripts/create_admin.py` | Create or update an admin operator user. |
| `python scripts/issue_key.py` | Generate a new API key for a client application instance. |
| `python scripts/reap_orphan_media.py` | Scan static media storage and safely delete unreferenced orphaned files. |
| `python scripts/rebuild_rollups.py` | Recalculate daily/weekly/monthly analytics rollups from raw events. |

---

## 📖 API Documentation & Authentication

The API provides interactive Swagger UI and ReDoc documentation:

- **Swagger UI**: `http://localhost:8020/docs`
- **ReDoc**: `http://localhost:8020/redoc`
- **OpenAPI Schema**: `http://localhost:8020/openapi.json`
- **Admin Panel**: `http://localhost:8020/admin/`

> [!NOTE]
> `/docs`, `/redoc`, and `/openapi.json` are protected by **HTTP Basic Authentication**. Enter the `DOCS_USERNAME` and `DOCS_PASSWORD` configured in your `.env` file when prompted.

### Consuming the Client API (`/api/v1`)

Client mobile and web apps authenticate using an API key passed in the `X-API-Key` header:

```bash
curl -X GET "http://localhost:8020/api/v1/categories" \
  -H "X-API-Key: ak_live_xxxxxxxxxxxxxxxxxxxx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

For detailed request/response schemas, refer to [API_Usage.md](API_Usage.md).

---

## 🔒 Security Best Practices for Production

1. **Environment**: Set `ENV=production` in your `.env`.
2. **Secrets**: Generate high-entropy strings for `SECRET_KEY` and `ADMIN_SESSION_SECRET`.
3. **CORS**: Set `CORS_ORIGINS` to the exact domains of your web frontends rather than `["*"]`.
4. **Docs Protection**: Use strong credentials for `DOCS_USERNAME` and `DOCS_PASSWORD`.
5. **Reverse Proxy**: Place Uvicorn behind Nginx or Caddy with TLS/HTTPS termination.
