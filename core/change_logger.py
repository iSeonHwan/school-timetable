"""
시간표 변경 이력 기록 모듈

TimetableChangeLog 테이블에 생성·수정·삭제 이력을 JSON 형태로 저장합니다.
모든 함수는 세션을 받아 log 객체를 add 하기만 하며, commit 은 호출자가 담당합니다.

저장 형식 (details JSON):
  생성: {"after":   {"day": 1, "period": 2, "subject_id": 3, "teacher_id": 4, "room_id": None}}
  수정: {"before":  {...}, "after": {...}}
  삭제: {"deleted": {...}}
"""
import json
from database.models import TimetableChangeLog


def _entry_info(entry) -> dict:
    """TimetableEntry 의 핵심 필드를 딕셔너리로 추출합니다 (details JSON 공통 구조)."""
    return {
        "day":        entry.day_of_week,
        "period":     entry.period,
        "subject_id": entry.subject_id,
        "teacher_id": entry.teacher_id,
        "room_id":    entry.room_id,
    }


def log_entry_create(session, entry) -> None:
    """
    시간표 항목 생성 이력을 기록합니다.
    session.flush() 이후에 호출해야 entry.id 가 할당된 상태입니다.
    """
    log = TimetableChangeLog(
        timetable_entry_id=entry.id,
        term_id=entry.term_id,
        school_class_id=entry.school_class_id,
        change_type="created",
        details=json.dumps({"after": _entry_info(entry)}, ensure_ascii=False),
    )
    session.add(log)


def log_entry_update(session, entry, old_data: dict) -> None:
    """
    시간표 항목 수정 이력을 기록합니다.

    Args:
        old_data: 수정 전 상태를 담은 딕셔너리 (_entry_info() 형식과 동일)
    """
    log = TimetableChangeLog(
        timetable_entry_id=entry.id,
        term_id=entry.term_id,
        school_class_id=entry.school_class_id,
        change_type="modified",
        details=json.dumps(
            {"before": old_data, "after": _entry_info(entry)},
            ensure_ascii=False,
        ),
    )
    session.add(log)


def log_entry_delete(session, entry) -> None:
    """
    시간표 항목 삭제 이력을 기록합니다.
    삭제 후에는 entry 가 DB 에서 사라지므로 timetable_entry_id 를 None 으로 저장합니다.
    """
    log = TimetableChangeLog(
        timetable_entry_id=None,  # 삭제된 항목은 FK 가 없으므로 NULL 로 저장합니다.
        term_id=entry.term_id,
        school_class_id=entry.school_class_id,
        change_type="deleted",
        details=json.dumps({"deleted": _entry_info(entry)}, ensure_ascii=False),
    )
    session.add(log)
