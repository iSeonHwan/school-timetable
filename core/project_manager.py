"""
프로젝트 저장/불러오기 모듈

전체 DB 데이터를 JSON 파일로 직렬화(export)하고 역직렬화(import)합니다.
UI와 독립적인 순수 Python/SQLAlchemy 로직만 포함합니다.

Export 흐름:
  1. _TABLE_ORDER 순서대로 모든 테이블을 조회
  2. 각 ORM 객체를 _row_to_dict() 로 dict 변환 (date → ISO 문자열, None → null)
  3. metadata(앱명, 버전, 내보낸 시각) + data 를 JSON 으로 저장

Import 흐름:
  1. JSON 파일 검증 (metadata + data 키 존재 여부)
  2. 역방향 테이블 순서로 모든 기존 데이터 DELETE (FK 제약 위반 방지)
  3. 정방향 순서로 새 데이터 INSERT, old_id → new_id 매핑으로 FK 변환
  4. 전체 과정이 하나의 트랜잭션으로 처리됨 (실패 시 rollback)

ID 재매핑 전략:
  import 시 DB가 할당하는 auto-increment PK 는 원본과 다르므로,
  id_map = {"tablename": {old_id: new_id}} 맵을 유지하며 모든 FK 컬럼을 변환합니다.
  _FK_COLUMN_MAP 딕셔너리가 {컬럼명: 대상테이블명} 매핑을 제공합니다.
"""
import json
import os
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect

from database.models import (
    AcademicTerm, Grade, Room, Subject, SchoolClass, Teacher,
    SubjectClassAssignment, TeacherConstraint, TimetableEntry,
    SchoolEvent, TimetableChangeLog, TimetableChangeRequest,
)

# ── 상수 ────────────────────────────────────────────────────────────────────

PROJECT_FILE_VERSION = "1.0"
APP_NAME = "학교 시간표 관리 시스템"

# 테이블 처리 순서: export 순서 = import 순서.
# FK 의존성을 고려해 Tier 0(독립) → Tier 4(가장 의존적) 순으로 정렬합니다.
# Import 시에는 이 순서의 역순으로 DELETE 하여 FK 위반을 방지합니다.
_TABLE_ORDER = [
    "academic_terms",          # Tier 0: no FKs
    "grades",
    "rooms",
    "subjects",
    "school_classes",          # Tier 1: → grades, rooms
    "teachers",                # Tier 2: → school_classes
    "subject_class_assignments",  # Tier 3: → school_classes, subjects, teachers, rooms
    "teacher_constraints",     # Tier 3: → teachers
    "timetable_entries",       # Tier 3: → academic_terms, school_classes, subjects, teachers, rooms
    "school_events",           # Tier 3: → academic_terms
    "timetable_change_logs",   # Tier 4: → timetable_entries, academic_terms, school_classes
    "timetable_change_requests",  # Tier 4: → timetable_entries, subjects, teachers, rooms
]

# FK 컬럼명 → 참조 대상 테이블명 매핑.
# import 시 old_id → new_id 변환에 사용합니다.
_FK_COLUMN_MAP = {
    "grade_id":             "grades",
    "homeroom_room_id":     "rooms",
    "homeroom_class_id":    "school_classes",
    "school_class_id":      "school_classes",
    "subject_id":           "subjects",
    "teacher_id":           "teachers",
    "room_id":              "rooms",
    "preferred_room_id":    "rooms",
    "term_id":              "academic_terms",
    "timetable_entry_id":   "timetable_entries",
    "new_subject_id":       "subjects",
    "new_teacher_id":       "teachers",
    "new_room_id":          "rooms",
}

# __tablename__ → Model Class 매핑 (lazy init)
_MODEL_MAP = {
    "academic_terms":            AcademicTerm,
    "grades":                    Grade,
    "rooms":                     Room,
    "subjects":                  Subject,
    "school_classes":            SchoolClass,
    "teachers":                  Teacher,
    "subject_class_assignments": SubjectClassAssignment,
    "teacher_constraints":       TeacherConstraint,
    "timetable_entries":         TimetableEntry,
    "school_events":             SchoolEvent,
    "timetable_change_logs":     TimetableChangeLog,
    "timetable_change_requests": TimetableChangeRequest,
}

# 모델별 컬럼명 캐시 (module-level, 한 번만 inspect)
_COLUMN_CACHE: dict[str, list[str]] = {}


def _get_column_names(table_name: str) -> list[str]:
    """SQLAlchemy inspect 로 테이블의 컬럼명 목록을 가져옵니다 (캐시 사용)."""
    if table_name not in _COLUMN_CACHE:
        model = _MODEL_MAP[table_name]
        mapper = sa_inspect(model)
        _COLUMN_CACHE[table_name] = [c.key for c in mapper.columns]
    return _COLUMN_CACHE[table_name]


# ── 직렬화 헬퍼 ─────────────────────────────────────────────────────────────

def _serialize_value(val: Any):
    """
    Python 값 → JSON 직렬화 가능한 값.
    date/datetime → ISO 문자열, None → null, 그 외는 그대로.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, time):
        return val.isoformat()
    return val


def _row_to_dict(row) -> dict:
    """
    ORM 인스턴스를 {컬럼명: 값} dict 로 변환합니다.
    """
    table_name = row.__tablename__
    cols = _get_column_names(table_name)
    return {c: _serialize_value(getattr(row, c)) for c in cols}


# ── 역직렬화 헬퍼 ────────────────────────────────────────────────────────────

def _deserialize_value(table_name: str, col: str, val: Any):
    """
    JSON 값 → Python 값. ISO 날짜/시간 문자열을 date/datetime 으로 복원합니다.
    """
    if val is None:
        return None
    model = _MODEL_MAP[table_name]
    col_type = getattr(model, col).type
    type_name = str(col_type).lower()

    if isinstance(val, str):
        # Date: "2025-03-02"
        if "date" in type_name:
            if "datetime" in type_name or "timestamp" in type_name:
                return datetime.fromisoformat(val)
            return date.fromisoformat(val)
    return val


def _dict_to_kwargs(table_name: str, data: dict, id_map: dict[str, dict]) -> dict:
    """
    dict → ORM 생성자 kwargs 로 변환합니다.
    - 'id' 컬럼은 제거 (DB auto-increment 에 맡김)
    - FK 컬럼은 id_map 을 참조해 old_id → new_id 변환
    - 날짜/시간 컬럼은 문자열 → Python 객체 변환
    """
    kwargs = {}
    for col, val in data.items():
        if col == "id":
            continue
        if col in _FK_COLUMN_MAP and val is not None:
            target_table = _FK_COLUMN_MAP[col]
            new_id = id_map.get(target_table, {}).get(val)
            if new_id is None:
                raise ValueError(
                    f"'{table_name}.{col}' 값 {val} 에 해당하는 "
                    f"'{target_table}' 레코드를 찾을 수 없습니다. 파일이 손상되었을 수 있습니다."
                )
            val = new_id
        kwargs[col] = _deserialize_value(table_name, col, val)
    return kwargs


# ── Public API ───────────────────────────────────────────────────────────────

def export_project(session: Session, filepath: str) -> int:
    """
    모든 DB 테이블 데이터를 JSON 파일로 내보냅니다.

    Args:
        session: 열린 SQLAlchemy 세션
        filepath: 저장할 .json 파일 경로

    Returns:
        내보낸 총 행(row) 수

    Raises:
        IOError: 파일 쓰기 실패 시
    """
    data: dict[str, list[dict]] = {}
    total = 0

    for table_name in _TABLE_ORDER:
        model = _MODEL_MAP[table_name]
        rows = session.query(model).all()
        data[table_name] = [_row_to_dict(r) for r in rows]
        total += len(rows)

    project = {
        "metadata": {
            "app_name": APP_NAME,
            "file_version": PROJECT_FILE_VERSION,
            "exported_at": datetime.now().isoformat(),
        },
        "data": data,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)

    return total


def validate_project_file(filepath: str) -> tuple[bool, str]:
    """
    프로젝트 파일의 기본 구조를 검증합니다 (데이터 import 없이 파일만 검사).

    검사 항목:
      - 파일 존재 여부
      - 유효한 JSON 형식
      - "metadata" 키 존재
      - "data" 키 존재

    Args:
        filepath: 검사할 .json 파일 경로

    Returns:
        (True, "")  : 유효한 파일
        (False, msg): 오류 설명
    """
    if not os.path.exists(filepath):
        return False, f"파일을 찾을 수 없습니다: {filepath}"

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            project = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"올바른 JSON 형식이 아닙니다:\n{e}"
    except IOError as e:
        return False, f"파일을 읽을 수 없습니다:\n{e}"

    if not isinstance(project, dict):
        return False, "파일의 최상위 구조가 객체(dict)가 아닙니다."

    if "metadata" not in project:
        return False, "'metadata' 섹션이 없습니다. 올바른 프로젝트 파일이 아닙니다."

    if "data" not in project:
        return False, "'data' 섹션이 없습니다. 올바른 프로젝트 파일이 아닙니다."

    if not isinstance(project["data"], dict):
        return False, "'data' 섹션이 객체(dict)가 아닙니다."

    # file_version 확인 (향후 호환성 체크용)
    version = project["metadata"].get("file_version", "0.0")
    if version != PROJECT_FILE_VERSION:
        # 현재는 동일 버전만 허용. 향후 마이그레이션 로직 추가 가능.
        return False, (
            f"파일 버전({version})이 현재 버전({PROJECT_FILE_VERSION})과 다릅니다. "
            "다른 버전의 파일은 불러올 수 없습니다."
        )

    return True, ""


def import_project(session: Session, filepath: str) -> dict[str, int]:
    """
    JSON 프로젝트 파일에서 데이터를 불러와 DB 를 완전히 대체합니다.

    전체 과정이 하나의 트랜잭션으로 처리됩니다.
    실패 시 기존 데이터는 그대로 보존됩니다.

    Args:
        session: 열린 SQLAlchemy 세션
        filepath: 불러올 .json 파일 경로

    Returns:
        {테이블명: 가져온_행_수} dict

    Raises:
        ValueError: 파일 형식 오류 또는 FK 참조 불일치
        IOError: 파일 읽기 실패
    """
    # 1) 파일 읽기 및 기본 검증
    valid, error = validate_project_file(filepath)
    if not valid:
        raise ValueError(error)

    with open(filepath, "r", encoding="utf-8") as f:
        project = json.load(f)

    raw_data: dict[str, list[dict]] = project["data"]

    # 2) 정방향 테이블 순서로 import 실행
    summary: dict[str, int] = {}
    id_map: dict[str, dict[int, int]] = {}   # {table_name: {old_id: new_id}}

    def _clear_all():
        """역방향 순서로 모든 테이블 데이터 삭제 (FK 위반 방지)."""
        for table_name in reversed(_TABLE_ORDER):
            model = _MODEL_MAP[table_name]
            session.query(model).delete()

    try:
        _clear_all()

        for table_name in _TABLE_ORDER:
            rows = raw_data.get(table_name, [])
            model = _MODEL_MAP[table_name]
            id_map[table_name] = {}

            for row_dict in rows:
                kwargs = _dict_to_kwargs(table_name, row_dict, id_map)
                instance = model(**kwargs)
                session.add(instance)
                session.flush()  # auto-increment PK 확보
                id_map[table_name][row_dict["id"]] = instance.id

            summary[table_name] = len(rows)

        # 3) 전체 commit
        session.commit()
        return summary

    except Exception:
        session.rollback()
        raise
