import json
from database.models import TimetableChangeLog


def _entry_info(entry) -> dict:
    return {
        "day": entry.day_of_week,
        "period": entry.period,
        "subject_id": entry.subject_id,
        "teacher_id": entry.teacher_id,
        "room_id": entry.room_id,
    }


def log_entry_create(session, entry):
    log = TimetableChangeLog(
        timetable_entry_id=entry.id,
        term_id=entry.term_id,
        school_class_id=entry.school_class_id,
        change_type="created",
        details=json.dumps({"after": _entry_info(entry)}, ensure_ascii=False),
    )
    session.add(log)


def log_entry_update(session, entry, old_data: dict):
    log = TimetableChangeLog(
        timetable_entry_id=entry.id,
        term_id=entry.term_id,
        school_class_id=entry.school_class_id,
        change_type="modified",
        details=json.dumps({
            "before": old_data,
            "after": _entry_info(entry),
        }, ensure_ascii=False),
    )
    session.add(log)


def log_entry_delete(session, entry):
    log = TimetableChangeLog(
        timetable_entry_id=None,
        term_id=entry.term_id,
        school_class_id=entry.school_class_id,
        change_type="deleted",
        details=json.dumps({"deleted": _entry_info(entry)}, ensure_ascii=False),
    )
    session.add(log)
