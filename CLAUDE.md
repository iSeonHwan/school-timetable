# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python3 main.py
```

Install dependencies first (use the project venv):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Running Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

Tests use `pytest-qt` and require a display (or a headless environment via `QT_QPA_PLATFORM=offscreen`).

## Architecture

This is a Korean school timetable management desktop app built with **PyQt6** + **SQLAlchemy**.

### Entry Point

`main.py` initializes the DB via `database/connection.py`, then launches `ui/main_window.MainWindow`. If the configured DB fails, it falls back to a local SQLite file (`timetable.db`).

### Database Layer (`database/`)

- `connection.py` — module-level singleton engine/session factory. Call `init_db(url)` once at startup, then `get_session()` anywhere to get a new `Session`. Sessions must be closed manually (no context manager is used globally).
- `models.py` — SQLAlchemy ORM models: `Grade` → `SchoolClass`, `Teacher`, `Subject`, `SubjectClassAssignment` (links class + subject + teacher + weekly hours), `TimetableEntry` (one row per scheduled lesson slot), `TeacherConstraint` (unavailable/preferred/avoid slots), `Room`, `AcademicTerm`.

### Timetable Generator (`core/generator.py`)

`generate_timetable(session, term_id)` uses **Greedy + Random Restart** (up to 30 attempts). Each attempt shuffles lessons and slots, then places lessons one-by-one enforcing hard constraints (no double-booking of class, teacher, or room; teacher unavailable slots) and soft constraints (teacher daily max). Returns `(bool, message)`. Runs in a `QThread` (`GenerateWorker`) to keep the UI responsive.

### UI Layer (`ui/`)

`main_window.py` — sidebar navigation (`QStackedWidget` with 6 pages) + dialogs for term management, auto-generation, and DB config.

Setup pages (`ui/setup/`):
- `class_setup.py` — grade/class CRUD
- `teacher_setup.py` — teacher CRUD + unavailable-time grid
- `subject_setup.py` — subject CRUD + per-class weekly-hours assignment
- `room_setup.py` — room CRUD

Timetable view pages (`ui/timetable/`):
- `class_view.py` — per-class grid (days × periods); calls `refresh()` on page switch
- `teacher_view.py` — per-teacher grid; calls `refresh()` on page switch
- `neis_grid.py` — shared grid widget used by both views

### Config (`config.py`)

Reads/writes `db_config.json` in the project root. Supports SQLite (default) and PostgreSQL. `get_db_url(cfg)` builds a SQLAlchemy URL from the config dict.
