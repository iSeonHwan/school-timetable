"""
시간표 자동 생성 알고리즘
- Greedy + Random Restart 방식
- Hard constraint: 교사 중복, 교실 중복, 학반 중복 방지
- Soft constraint: 교사 희망/불가 시간, 일 최대 수업 수
"""
import random
from typing import Optional
from sqlalchemy.orm import Session
from database.models import (
    SubjectClassAssignment, TimetableEntry, TeacherConstraint, AcademicTerm
)

DAYS = [1, 2, 3, 4, 5]   # 월~금
MAX_PERIODS = 7


def generate_timetable(
    session: Session,
    term_id: int,
    max_periods: int = MAX_PERIODS,
    max_retries: int = 30,
) -> tuple[bool, str]:
    """
    현재 학기(term_id)의 시간표를 생성합니다.
    반환: (성공여부, 메시지)
    """
    assignments = session.query(SubjectClassAssignment).all()
    if not assignments:
        return False, "배정된 교과/시수 정보가 없습니다."

    # 교사 불가 슬롯 수집
    unavailable: dict[int, set] = {}
    for c in session.query(TeacherConstraint).filter_by(constraint_type="unavailable").all():
        unavailable.setdefault(c.teacher_id, set()).add((c.day_of_week, c.period))

    # 교사 최대 일 수업 수
    teacher_max: dict[int, int] = {}
    from database.models import Teacher
    for t in session.query(Teacher).all():
        teacher_max[t.id] = t.max_daily_classes

    for attempt in range(max_retries):
        result = _try_generate(
            assignments, unavailable, teacher_max, max_periods
        )
        if result is not None:
            # 기존 시간표 삭제 후 저장
            session.query(TimetableEntry).filter_by(term_id=term_id).delete()
            for r in result:
                entry = TimetableEntry(
                    term_id=term_id,
                    school_class_id=r["class_id"],
                    subject_id=r["subject_id"],
                    teacher_id=r["teacher_id"],
                    room_id=r.get("room_id"),
                    day_of_week=r["day"],
                    period=r["period"],
                )
                session.add(entry)
            session.commit()
            return True, f"시간표 생성 완료 (시도 {attempt + 1}회)"

    return False, f"{max_retries}회 시도 후 시간표 생성에 실패했습니다.\n시수 합계나 교사 배정을 확인해 주세요."


def _try_generate(
    assignments: list,
    unavailable: dict,
    teacher_max: dict,
    max_periods: int,
) -> Optional[list]:
    # 수업 인스턴스 목록 생성
    lessons = []
    for a in assignments:
        for _ in range(a.weekly_hours):
            lessons.append({
                "class_id": a.school_class_id,
                "subject_id": a.subject_id,
                "teacher_id": a.teacher_id,
                "room_id": a.preferred_room_id,
            })
    random.shuffle(lessons)

    all_slots = [(d, p) for d in DAYS for p in range(1, max_periods + 1)]

    # 사용 중인 슬롯 추적
    class_slots: dict[int, set] = {}
    teacher_slots: dict[int, set] = {}
    teacher_daily: dict[tuple, int] = {}   # (teacher_id, day) -> count
    room_slots: dict[int, set] = {}

    placed = []

    for lesson in lessons:
        cid = lesson["class_id"]
        tid = lesson["teacher_id"]
        rid = lesson.get("room_id")

        random.shuffle(all_slots)
        success = False

        for day, period in all_slots:
            slot = (day, period)

            # Hard: 학반 중복
            if slot in class_slots.get(cid, set()):
                continue
            # Hard: 교사 중복
            if slot in teacher_slots.get(tid, set()):
                continue
            # Hard: 교실 중복
            if rid and slot in room_slots.get(rid, set()):
                continue
            # Hard: 교사 불가 시간
            if slot in unavailable.get(tid, set()):
                continue
            # Soft: 교사 일 최대 수업
            daily_key = (tid, day)
            if teacher_daily.get(daily_key, 0) >= teacher_max.get(tid, 5):
                continue

            # 배치
            class_slots.setdefault(cid, set()).add(slot)
            teacher_slots.setdefault(tid, set()).add(slot)
            if rid:
                room_slots.setdefault(rid, set()).add(slot)
            teacher_daily[daily_key] = teacher_daily.get(daily_key, 0) + 1

            placed.append({**lesson, "day": day, "period": period})
            success = True
            break

        if not success:
            return None   # 이번 시도 실패 → 재시도

    return placed
