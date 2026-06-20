"""
시간표 자동 생성기 테스트

core/generator.py 의 그리디 + 랜덤 재시작 알고리즘을 검증합니다.
인메모리 SQLite DB 에서 최소 데이터셋을 구성하고 다음을 확인합니다:
  - 학기(term_id)별 필터링
  - 교사 불가 시간(unavailable) 제약
  - 교사 일일 최대 수업 수(max_daily_classes) 제약
  - 생성 불가능한 경우의 실패 반환
"""
from datetime import date

from database.models import (
    AcademicTerm, Grade, Room, Subject, SchoolClass, Teacher,
    SubjectClassAssignment, TeacherConstraint, TimetableEntry,
)
from core.generator import generate_timetable


def _build_minimal_dataset(db, term_kwargs=None):
    """테스트에 재사용하는 최소 데이터셋을 만들고 관련 객체 딕셔너리를 반환합니다."""
    term = AcademicTerm(year=2025, semester=1, is_current=True,
                        start_date=date(2025, 3, 2), end_date=date(2025, 8, 31))
    db.add(term)

    grade = Grade(grade_number=1, name="1학년")
    db.add(grade)

    room = Room(name="1-1 교실", room_type="일반", capacity=30, floor=1)
    db.add(room)

    subject = Subject(name="수학", short_name="수", color_hex="#E3F2FD")
    db.add(subject)
    db.flush()

    school_class = SchoolClass(grade_id=grade.id, class_number=1, display_name="1-1")
    db.add(school_class)
    db.flush()

    teacher = Teacher(name="김교사", employee_number="T001", max_daily_classes=5)
    db.add(teacher)
    db.flush()

    assignment = SubjectClassAssignment(
        term_id=term.id,
        school_class_id=school_class.id,
        subject_id=subject.id,
        teacher_id=teacher.id,
        weekly_hours=3,
        preferred_room_id=room.id,
    )
    db.add(assignment)
    db.commit()

    return {
        "term": term,
        "grade": grade,
        "room": room,
        "subject": subject,
        "school_class": school_class,
        "teacher": teacher,
        "assignment": assignment,
    }


def test_generate_filters_by_term_id(db):
    """generate_timetable 는 지정한 학기의 시수 배정만 사용해야 합니다."""
    data1 = _build_minimal_dataset(db)

    # 2학기용 추가 데이터: 다른 반 + 다른 교사 + 다른 과목
    term2 = AcademicTerm(year=2025, semester=2, is_current=False,
                         start_date=date(2025, 9, 1), end_date=date(2026, 2, 28))
    db.add(term2)
    db.flush()

    subject2 = Subject(name="국어", short_name="국", color_hex="#FFE0B2")
    db.add(subject2)
    db.flush()

    teacher2 = Teacher(name="박교사", employee_number="T002", max_daily_classes=5)
    db.add(teacher2)
    db.flush()

    class2 = SchoolClass(grade_id=data1["grade"].id, class_number=2, display_name="1-2")
    db.add(class2)
    db.flush()

    assignment2 = SubjectClassAssignment(
        term_id=term2.id,
        school_class_id=class2.id,
        subject_id=subject2.id,
        teacher_id=teacher2.id,
        weekly_hours=3,
    )
    db.add(assignment2)
    db.commit()

    ok, msg = generate_timetable(db, term_id=data1["term"].id, max_periods=7)
    assert ok, msg

    entries = db.query(TimetableEntry).filter_by(term_id=data1["term"].id).all()
    assert len(entries) == 3  # 1학기 수학 3시간

    subject_ids = {e.subject_id for e in entries}
    assert subject_ids == {data1["subject"].id}
    assert subject2.id not in subject_ids


def test_generate_respects_teacher_unavailable(db):
    """교사가 불가로 설정한 슬롯에는 수업이 배치되지 않아야 합니다."""
    data = _build_minimal_dataset(db)

    # 월요일 1교시를 불가로 설정
    constraint = TeacherConstraint(
        teacher_id=data["teacher"].id,
        day_of_week=1,
        period=1,
        constraint_type="unavailable",
    )
    db.add(constraint)
    db.commit()

    ok, msg = generate_timetable(db, term_id=data["term"].id, max_periods=3)
    assert ok, msg

    entries = db.query(TimetableEntry).filter_by(term_id=data["term"].id).all()
    assert len(entries) == 3
    for e in entries:
        assert not (e.day_of_week == 1 and e.period == 1)


def test_generate_respects_max_daily_classes(db):
    """max_daily_classes=1 이면 교사는 하루에 한 수업만 배정받습니다."""
    data = _build_minimal_dataset(db)
    data["teacher"].max_daily_classes = 1
    db.commit()

    ok, msg = generate_timetable(db, term_id=data["term"].id, max_periods=5)
    assert ok, msg

    entries = db.query(TimetableEntry).filter_by(term_id=data["term"].id).all()
    assert len(entries) == 3

    daily_counts = {}
    for e in entries:
        daily_counts[e.day_of_week] = daily_counts.get(e.day_of_week, 0) + 1
    assert all(count <= 1 for count in daily_counts.values())


def test_generate_fails_when_over_capacity(db):
    """전체 슬롯보다 시수 합계가 많으면 생성에 실패해야 합니다."""
    data = _build_minimal_dataset(db)
    data["assignment"].weekly_hours = 50  # 5일 x 3교시 = 15슬롯보다 훨씬 많음
    db.commit()

    ok, msg = generate_timetable(db, term_id=data["term"].id, max_periods=3, max_retries=5)
    assert not ok
    assert "실패" in msg or "시도" in msg


def test_generate_prefers_preferred_slot(db):
    """preferred 제약이 설정된 슬롯이 비어있으면 해당 슬롯에 우선 배치됩니다."""
    data = _build_minimal_dataset(db)
    # 수업 1시간만 배정 (preferred 슬롯 1개 지정)
    data["assignment"].weekly_hours = 1
    db.commit()

    # 화요일 2교시를 선호 슬롯으로 설정
    db.add(TeacherConstraint(
        teacher_id=data["teacher"].id,
        day_of_week=2, period=2,
        constraint_type="preferred",
    ))
    db.commit()

    ok, msg = generate_timetable(db, term_id=data["term"].id, max_periods=7)
    assert ok, msg

    entries = db.query(TimetableEntry).filter_by(term_id=data["term"].id).all()
    assert len(entries) == 1
    # 선호 슬롯이 비어있으므로 해당 슬롯에 배치되어야 함
    e = entries[0]
    assert e.day_of_week == 2 and e.period == 2


def test_generate_avoids_avoid_slot_when_alternative_available(db):
    """avoid 슬롯 외에 다른 슬롯이 사용 가능하면 avoid 슬롯을 회피합니다."""
    data = _build_minimal_dataset(db)
    # 수업 1시간만 배정 (회피 슬롯 1개 + 다른 슬롯 모두 사용 가능)
    data["assignment"].weekly_hours = 1
    db.commit()

    # 월요일 1교시를 회피 슬롯으로 설정
    db.add(TeacherConstraint(
        teacher_id=data["teacher"].id,
        day_of_week=1, period=1,
        constraint_type="avoid",
    ))
    db.commit()

    ok, msg = generate_timetable(db, term_id=data["term"].id, max_periods=7, max_retries=10)
    assert ok, msg

    entries = db.query(TimetableEntry).filter_by(term_id=data["term"].id).all()
    assert len(entries) == 1
    # 다른 슬롯이 충분히 있으므로 avoid 슬롯(월 1교시)은 회피되어야 함
    e = entries[0]
    assert not (e.day_of_week == 1 and e.period == 1)


def test_generate_uses_avoid_slot_when_only_option(db):
    """avoid 슬롯밖에 남지 않으면 soft 이므로 배치를 허용합니다."""
    data = _build_minimal_dataset(db)
    # 수업 1시간 + max_periods=1 (사용 가능 슬롯 = 월~금 1교시 = 5슬롯)
    data["assignment"].weekly_hours = 1
    db.commit()

    # 월~금 1교시 중 4개를 unavailable 로 막고, 금요일 1교시만 avoid 로 남김
    for day in [1, 2, 3, 4]:
        db.add(TeacherConstraint(
            teacher_id=data["teacher"].id,
            day_of_week=day, period=1,
            constraint_type="unavailable",
        ))
    # 금요일 1교시는 avoid (회피하지만 배치 가능)
    db.add(TeacherConstraint(
        teacher_id=data["teacher"].id,
        day_of_week=5, period=1,
        constraint_type="avoid",
    ))
    db.commit()

    ok, msg = generate_timetable(db, term_id=data["term"].id, max_periods=1, max_retries=5)
    assert ok, msg

    entries = db.query(TimetableEntry).filter_by(term_id=data["term"].id).all()
    assert len(entries) == 1
    # 유일하게 열린 슬롯(금 1교시, avoid)에 배치되어야 함 — soft 제약은 하드처럼 차단하지 않음
    e = entries[0]
    assert e.day_of_week == 5 and e.period == 1
