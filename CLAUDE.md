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
export CHAT_RETENTION_DAYS="30"                       # chat message retention (days, 0=forever)
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
- `api/auth.py` — Login, user management (일과계 only)
- `api/setup.py` — Grade/class/subject/room/teacher CRUD (쓰기: 일과계 only, 읽기: 일과계·교감)
- `api/timetable.py` — Timetable query/generation, 2-step change request approval (일과계 1차 → 교감 최종)
- `api/chat.py` — REST + WebSocket real-time group chat (공지: 일과계·교감, 삭제: 일과계 only, 자동 정리: CHAT_RETENTION_DAYS 기준)

### Admin App (`admin_app/`)
- Reuses existing `ui/` widgets (setup pages, timetable views, history)
- Adds login screen (`LoginWindow`) and chat panel (`ChatPanel`)
- Role-based sidebar:
  - **일과계(admin)**: 8 pages (전체 관리 기능)
  - **교감(vice_principal)**: 3 pages (시간표 읽기 전용 + 변경 신청 최종 승인)
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
| GET/POST | `/auth/users` | scheduler | User management (일과계 only) |
| GET/POST/DELETE | `/setup/grades` | scheduler (write) / admin+vp (read) | Grade CRUD |
| GET/POST/DELETE | `/setup/classes` | scheduler (write) / admin+vp (read) | Class CRUD |
| GET/POST/DELETE | `/setup/teachers` | scheduler (write) / admin+vp (read) | Teacher CRUD |
| GET/POST/DELETE | `/setup/subjects` | scheduler (write) / admin+vp (read) | Subject CRUD |
| GET/POST/DELETE | `/setup/rooms` | scheduler (write) / admin+vp (read) | Room CRUD |
| GET/POST | `/timetable/terms` | any/일과계 | Academic terms |
| GET | `/timetable/entries` | any | Timetable entries |
| POST | `/timetable/generate` | scheduler | Auto-generate (일과계 only) |
| GET | `/timetable/logs` | admin+vp | Change history |
| GET/POST | `/timetable/requests` | any | Change requests |
| PATCH | `/timetable/requests/{id}` | admin+vp | 2-step approve/reject (일과계 1차 → 교감 최종) |
| GET | `/chat/messages` | any | Chat history |
| DELETE | `/chat/messages/{id}` | admin+vp | Delete single message |
| DELETE | `/chat/messages` | scheduler | Cleanup old messages (일과계 only) |
| WS | `/chat/ws?token=` | any | Real-time chat (chat, delete, cleanup events) |
