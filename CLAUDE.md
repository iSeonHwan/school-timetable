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
export JWT_SECRET_KEY="your-secret"                     # 운영 환경에서 반드시 설정 (미설정 시 임시키 생성)
export ADMIN_USERNAME="admin"                           # first-run admin account
export ADMIN_PASSWORD=""                                # 미설정 시 랜덤 생성 (로그에 출력됨)
export VP_USERNAME="vice_principal"                     # first-run vice-principal account
export VP_PASSWORD=""                                   # 미설정 시 랜덤 생성 (로그에 출력됨)
export CHAT_RETENTION_DAYS="60"                         # chat message retention (days, 0=forever)
export CORS_ORIGINS="http://your-server-ip:8000"        # 운영 환경에서 서버 IP/도메인으로 제한
export WS_ALLOWED_ORIGINS="http://your-server-ip:8000"  # WebSocket Origin 검증용
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
  - Exam feature models: `Exam`, `ExamPeriod`, `ExamEntry`, `InvigilationAssignment` (교실감독 — `school_class_id`/`exam_room_id` 중 하나만 채워짐), `InvigilationConstraint`, `ExamRoom`(여러 반이 섞이는 혼합 시험실), `ExamRoomStudent`(혼합 시험실 수강 학생 명단, 전부 선택 입력 — 학생 배치 안내문 생성용), `CorridorDutyAssignment`(복도감독, 학년×교시 단위), `ExamGradeDateExclusion`(학년별 시험 미참여 날짜)
  - 감독 자동 배정 호출 순서(중요): `assign_corridor_duty()` → `assign_invigilations()`. 복도감독(과목 담당 교사로 후보가 좁음)을 먼저 확정해야, 후보가 넓은 교실감독이 그 교사들을 먼저 써버려 복도감독이 미배정으로 남는 것을 막을 수 있음 (`core/exam_scheduler.py` 모듈 docstring 참조)
- `schemas.py` — Pydantic v2 request/response schemas for all API endpoints
- `api_client.py` — Sync HTTP + WebSocket client used by both desktop apps

### Server (`server/`)
- `main.py` — FastAPI app entry point, lifespan (DB init + first admin creation)
- `auth_utils.py` — JWT creation/validation, bcrypt password hashing
- `deps.py` — FastAPI dependencies: DB session injection, auth/role guards
- `api/auth.py` — Login, user management (일과계 only)
- `api/setup.py` — Grade/class/subject/room/teacher CRUD (쓰기: 일과계 only, 읽기: 일과계·교감)
- `api/timetable.py` — Timetable query/generation, change request approval via a configurable multi-step `ApprovalWorkflow` (기본값: 일과계 1차 → 교감 최종, `api/workflow.py` 로 단계 수·역할 재구성 가능)
- `api/exams.py` — 시험 시간표·감독 시간표 CRUD + 자동 생성(`core/exam_scheduler.py`). 혼합 시험실(`/exams/{id}/rooms`), 혼합 시험실 학생 명단(`/exams/rooms/{room_id}/students`, 전부 선택 입력), 복도감독(`/exams/{id}/corridor-duties`, `/exams/{id}/assign-corridor-duty` — `assign-invigilations` 보다 먼저 호출), 학년별 시험 미참여 날짜(`/exams/{id}/grade-exclusions`) 포함
- `ui/export/exam_export.py` — 시험 관련 문서 내보내기(PDF/CSV/Markdown). `export_student_exam_guide_markdown()`(학생용 — 감독교사 정보 절대 미포함)과 `export_teacher_invigilation_notice_markdown()`(교사 전용 공지물 — 교실·복도감독 배정 포함, 학생 배포 금지)는 데이터 소스를 완전히 분리해 서로 섞일 수 없게 설계됨
- `api/chat.py` — REST + WebSocket real-time group chat (공지: 일과계·교감, 개별 메시지 삭제: 일과계·교감, 일괄 정리: 일과계 only, 자동 정리 주기: CHAT_RETENTION_DAYS 기준)

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
| GET/POST | `/timetable/requests` | any (teacher role sees only requests involving them) | Change requests |
| PATCH | `/timetable/requests/{id}` | any, enforced dynamically per active `ApprovalWorkflow` step's `role_required` | 신청 시점에 정해진 결재 라인(기본값: 일과계 1차 → 교감 최종, 관리자가 자유롭게 재구성 가능) |
| GET | `/chat/messages` | any | Chat history |
| DELETE | `/chat/messages/{id}` | admin+vp | Delete single message |
| DELETE | `/chat/messages` | scheduler | Cleanup old messages (일과계 only) |
| WS | `/chat/ws` (Authorization: Bearer 헤더로 인증) | any | Real-time chat (chat, delete, cleanup events) |
