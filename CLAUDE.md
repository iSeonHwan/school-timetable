# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Program Structure (3 Programs)

This project has been split into three separate programs:

| Program | Entry Point | Role |
|---|---|---|
| **Server** | `uvicorn server.main:app` | FastAPI API server + WebSocket chat hub |
| **Admin App** | `python -m admin_app.main` | Full management (vice-principal / scheduler) |
| **Teacher App** | `python -m teacher_app.main` | Timetable view + change requests + chat |

## Running the Server

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Start API server (default port 8000)
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8000

# Environment variables (optional)
export DB_URL="postgresql+psycopg2://user:pw@host/db"  # default: SQLite
export JWT_SECRET_KEY="your-secret"                     # change in production!
export ADMIN_USERNAME="admin"                           # first-run admin account
export ADMIN_PASSWORD="admin1234"                       # change immediately!
```

## Running the Apps

```bash
# Admin program
SERVER_URL=http://localhost:8000 .venv/bin/python -m admin_app.main

# Teacher program
SERVER_URL=http://localhost:8000 .venv/bin/python -m teacher_app.main
```

## Running Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

Tests use `pytest-qt` and require a display (or `QT_QPA_PLATFORM=offscreen`).

## Architecture

### Shared Layer (`shared/`)
- `models.py` — All SQLAlchemy ORM models (canonical source). `database/models.py` re-exports from here for backward compatibility.
  - New models: `User` (login accounts), `ChatMessage` (group chat)
- `schemas.py` — Pydantic v2 request/response schemas for all API endpoints
- `api_client.py` — Sync HTTP + WebSocket client used by both desktop apps

### Server (`server/`)
- `main.py` — FastAPI app entry point, lifespan (DB init + first admin creation)
- `auth_utils.py` — JWT creation/validation, bcrypt password hashing
- `deps.py` — FastAPI dependencies: DB session injection, auth/role guards
- `api/auth.py` — Login, user management (admin only)
- `api/setup.py` — Grade/class/subject/room/teacher CRUD (admin only)
- `api/timetable.py` — Timetable query/generation, change requests/logs
- `api/chat.py` — REST + WebSocket real-time group chat

### Admin App (`admin_app/`)
- Reuses existing `ui/` widgets (setup pages, timetable views, history)
- Adds login screen (`LoginWindow`) and chat panel (`ChatPanel`)
- Connects directly to PostgreSQL DB (same machine or LAN)

### Teacher App (`teacher_app/`)
- Communicates with server exclusively via `ApiClient` (REST + WebSocket)
- Pages: My Timetable, Class Timetable, Change Requests
- Chat panel shared with admin app

### Database Layer (`database/`)
- `connection.py` — Singleton engine/session factory. `init_db(url)` once, then `get_session()`.
- `models.py` — Re-exports from `shared/models.py` for backward compatibility.

### Timetable Generator (`core/generator.py`)
Greedy + Random Restart (up to 30 attempts). Returns `(bool, message)`.

### Config (`config.py`)
Reads/writes `db_config.json`. Supports SQLite (default) and PostgreSQL.
`get_db_url(cfg)` builds a SQLAlchemy URL. PostgreSQL passwords are URL-encoded.

## API Overview

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | — | Login, get JWT |
| GET | `/auth/me` | any | Current user info |
| GET/POST | `/auth/users` | admin | User management |
| GET/POST/DELETE | `/setup/grades` | admin | Grade CRUD |
| GET/POST/DELETE | `/setup/classes` | admin | Class CRUD |
| GET/POST/DELETE | `/setup/teachers` | admin | Teacher CRUD |
| GET/POST/DELETE | `/setup/subjects` | admin | Subject CRUD |
| GET/POST/DELETE | `/setup/rooms` | admin | Room CRUD |
| GET/POST | `/timetable/terms` | any/admin | Academic terms |
| GET | `/timetable/entries` | any | Timetable entries |
| POST | `/timetable/generate` | admin | Auto-generate |
| GET | `/timetable/logs` | admin | Change history |
| GET/POST | `/timetable/requests` | any | Change requests |
| PATCH | `/timetable/requests/{id}` | admin | Approve/reject |
| GET | `/chat/messages` | any | Chat history |
| WS | `/chat/ws?token=` | any | Real-time chat |
