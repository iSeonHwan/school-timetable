"""
시험 도메인 신규 모델(Exam / ExamPeriod / ExamEntry / InvigilationAssignment /
InvigilationConstraint)과 기존 모델 확장(SchoolClass.student_count,
TimetableChangeRequest 감독 스왑 필드)의 스키마 정합성 테스트.

이 테스트가 존재하는 이유:
  시험 기능의 스키마는 감독 배정·스왑 승인 라인 재사용이라는 복잡한 관계를
  가지므로, API/알고리즘 구현 전에 모델 레벨(테이블 생성·관계·유니크 제약·
  cascade)이 올바른지 먼저 검증합니다. 마이그레이션 경로(create_all)와
  레거시 경로(_migrate_columns + Alembic) 중 테스트는 create_all 경로를
  검증하며, NOT NULL 완화는 별도 시나리오로 검증합니다.
"""
from datetime import date, time

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from database.connection import get_session
from shared.models import (
    AcademicTerm, Grade, Room, SchoolClass, Subject, Teacher,
    TimetableChangeRequest, ChangeRequestStep,
    Exam, ExamPeriod, ExamEntry, InvigilationAssignment, InvigilationConstraint,
)


@pytest.fixture
def dataset(db):
    """
    시험 테스트에 필요한 최소 데이터셋.

    3개 학년 × 1개 반, 교사 3명, 과목 3개, 학기 1개를 생성합니다.
    (알고리즘 테스트(test_exam_scheduler.py)에서도 동일 구조를 재사용)
    """
    term = AcademicTerm(year=2026, semester=1, is_current=True)
    db.add(term)
    db.flush()

    grades = []
    for n in (1, 2, 3):
        g = Grade(grade_number=n, name=f"{n}학년")
        db.add(g)
        grades.append(g)
    db.flush()

    # 학생 수가 다른 두 반 — 조 구성(20명 기준) 경계값 테스트에 사용
    room = Room(name="101", capacity=30)
    db.add(room)
    db.flush()

    small_class = SchoolClass(
        grade_id=grades[0].id, class_number=1, display_name="1학년 1반",
        homeroom_room_id=room.id, student_count=19,   # 20명 미만 → 1인 감독
    )
    big_class = SchoolClass(
        grade_id=grades[1].id, class_number=1, display_name="2학년 1반",
        homeroom_room_id=room.id, student_count=25,   # 20명 이상 → 2인 1조
    )
    db.add_all([small_class, big_class])
    db.flush()

    teachers = []
    for n in (1, 2, 3):
        t = Teacher(name=f"교사{n}")
        db.add(t)
        teachers.append(t)
    # 교사1 을 1학년 1반 담임으로 지정 — 담임 반 감독 금지 검증용
    teachers[0].is_homeroom = True
    teachers[0].homeroom_class_id = small_class.id
    db.flush()

    subjects = []
    for name, short in (("국어", "국"), ("수학", "수"), ("영어", "영")):
        s = Subject(name=name, short_name=short)
        db.add(s)
        subjects.append(s)
    db.commit()

    return {
        "term": term, "grades": grades,
        "small_class": small_class, "big_class": big_class,
        "teachers": teachers, "subjects": subjects, "room": room,
    }


# ── 테이블·컬럼 존재 검증 ─────────────────────────────────────────────────────

def test_new_tables_created(db):
    """시험 기능의 5개 신규 테이블이 create_all() 로 생성되는지 확인."""
    from database.connection import _engine
    names = set(inspect(_engine).get_table_names())
    for table in ("exams", "exam_periods", "exam_entries",
                  "invigilation_assignments", "invigilation_constraints"):
        assert table in names, f"테이블 {table} 이(가) 생성되지 않았습니다."


def test_school_class_student_count_column(db):
    """SchoolClass.student_count 컬럼이 스키마에 존재하는지 확인."""
    from database.connection import _engine
    cols = {c["name"] for c in inspect(_engine).get_columns("school_classes")}
    assert "student_count" in cols


def test_change_request_new_columns_and_nullable(db):
    """
    감독 스왑 지원을 위한 기존 테이블 확장 검증.

    - timetable_entry_id 가 nullable 로 완화되었는지 (감독 스왑 신청은 NULL)
    - request_type / invigilation FK 컬럼이 존재하는지
    """
    from database.connection import _engine
    insp = inspect(_engine)

    tcr_cols = {c["name"]: c for c in insp.get_columns("timetable_change_requests")}
    assert tcr_cols["timetable_entry_id"]["nullable"] is True
    assert "request_type" in tcr_cols
    assert "invigilation_assignment_id" in tcr_cols
    assert "swap_partner_invigilation_id" in tcr_cols

    step_cols = {c["name"] for c in insp.get_columns("change_request_steps")}
    assert "source_invigilation_id" in step_cols
    assert "target_invigilation_id" in step_cols


# ── 모델 동작 검증 ───────────────────────────────────────────────────────────

def test_exam_period_time_calculation(db, dataset):
    """
    Exam 생성 → ExamPeriod 자동 생성 규칙 검증.

    1교시 08:30 시작, 시험 50분, 쉬는시간 10분이라면:
      1교시 08:30~09:20, 2교시 09:30~10:20, 3교시 10:30~11:20
    (시험 종료는 종료령과 동시 — end = start + exam_minutes)
    """
    from datetime import datetime as dt, timedelta
    exam = Exam(
        term_id=dataset["term"].id, name="1학기 중간고사",
        exam_type="midterm", school_level="high",
        target_grade_ids="[]",
        first_period_start=time(8, 30), periods_per_day=3,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=3,
        start_date=date(2026, 9, 20), end_date=date(2026, 9, 22),
    )
    db.add(exam)
    db.flush()

    # 서버/스케줄러가 기간을 순회하며 교시를 생성하는 방식을 여기서 재현 검증
    d = date(2026, 9, 20)
    base = dt.combine(d, time(8, 30))
    for p in (1, 2, 3):
        start_dt = base + timedelta(minutes=(p - 1) * (50 + 10))
        end_dt = start_dt + timedelta(minutes=50)
        db.add(ExamPeriod(
            exam_id=exam.id, exam_date=d, period=p,
            start_time=start_dt.time(), end_time=end_dt.time(),
        ))
    db.commit()

    periods = db.query(ExamPeriod).filter_by(exam_id=exam.id).order_by(ExamPeriod.period).all()
    assert len(periods) == 3
    assert periods[0].start_time == time(8, 30)
    assert periods[0].end_time == time(9, 20)
    assert periods[1].start_time == time(9, 30)
    assert periods[2].end_time == time(11, 20)


def test_exam_period_unique_constraint(db, dataset):
    """같은 시험·날짜·교시의 중복 생성이 DB 레벨에서 차단되는지 확인."""
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()

    d = date(2026, 9, 20)
    db.add(ExamPeriod(exam_id=exam.id, exam_date=d, period=1,
                      start_time=time(8, 30), end_time=time(9, 20)))
    db.commit()

    db.add(ExamPeriod(exam_id=exam.id, exam_date=d, period=1,
                      start_time=time(8, 30), end_time=time(9, 20)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_exam_entry_unique_constraint(db, dataset):
    """같은 시험·교시·학년에 과목 2개 배치가 차단되는지 확인."""
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()
    period = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 9, 20), period=1,
                        start_time=time(8, 30), end_time=time(9, 20))
    db.add(period)
    db.flush()

    db.add(ExamEntry(exam_id=exam.id, period_id=period.id,
                     grade_id=dataset["grades"][0].id,
                     subject_id=dataset["subjects"][0].id))
    db.commit()

    db.add(ExamEntry(exam_id=exam.id, period_id=period.id,
                     grade_id=dataset["grades"][0].id,
                     subject_id=dataset["subjects"][1].id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invigilation_assignment_pair_slots(db, dataset):
    """
    조 구성 슬롯 검증 — 20명 기준.

    2인 1조(25명 반)는 pair_index 1, 2 두 슬롯이, 1인(19명 반)은
    pair_index 1 슬롯만 존재할 수 있습니다. UniqueConstraint 로
    같은 조 번호의 중복도 차단됩니다.
    """
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()
    period = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 9, 20), period=1,
                        start_time=time(8, 30), end_time=time(9, 20))
    db.add(period)
    db.flush()

    # 25명 반 → 2인 1조 (pair 1, 2)
    db.add(InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                  school_class_id=dataset["big_class"].id,
                                  teacher_id=dataset["teachers"][0].id, pair_index=1))
    db.add(InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                  school_class_id=dataset["big_class"].id,
                                  teacher_id=dataset["teachers"][1].id, pair_index=2))
    # 19명 반 → 1인 감독 (pair 1 만)
    db.add(InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                  school_class_id=dataset["small_class"].id,
                                  teacher_id=dataset["teachers"][2].id, pair_index=1))
    db.commit()

    assert db.query(InvigilationAssignment).count() == 3

    # 같은 반·같은 조 번호 중복 차단 확인
    db.add(InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                  school_class_id=dataset["small_class"].id,
                                  teacher_id=dataset["teachers"][1].id, pair_index=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invigilation_assignment_unassigned_slot(db, dataset):
    """teacher_id=NULL (미배정) 슬롯이 허용되는지 확인 — 후보 부족 시 수동 배정 여지."""
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()
    period = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 9, 20), period=1,
                        start_time=time(8, 30), end_time=time(9, 20))
    db.add(period)
    db.flush()

    db.add(InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                  school_class_id=dataset["small_class"].id,
                                  teacher_id=None, pair_index=1))
    db.commit()
    slot = db.query(InvigilationAssignment).one()
    assert slot.teacher_id is None


def test_invigilation_constraint_period_null_means_all(db, dataset):
    """감독 불가 신청에서 period=NULL 이 '전 교시 불가'로 저장되는지 확인."""
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()

    db.add(InvigilationConstraint(
        exam_id=exam.id, teacher_id=dataset["teachers"][0].id,
        exam_date=date(2026, 9, 20), period=None,
        reason="공결", status="approved",
    ))
    db.commit()
    c = db.query(InvigilationConstraint).one()
    assert c.period is None
    assert c.status == "approved"


def test_exam_cascade_delete(db, dataset):
    """시험 삭제 시 자식(periods/entries/invigilations/constraints)이 함께 삭제되는지 확인."""
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()
    period = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 9, 20), period=1,
                        start_time=time(8, 30), end_time=time(9, 20))
    db.add(period)
    db.flush()
    db.add(ExamEntry(exam_id=exam.id, period_id=period.id,
                     grade_id=dataset["grades"][0].id,
                     subject_id=dataset["subjects"][0].id))
    db.add(InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                  school_class_id=dataset["small_class"].id,
                                  pair_index=1))
    db.add(InvigilationConstraint(
        exam_id=exam.id, teacher_id=dataset["teachers"][0].id,
        exam_date=date(2026, 9, 20), period=1,
    ))
    db.commit()
    exam_id = exam.id

    db.delete(exam)
    db.commit()

    assert db.query(ExamPeriod).filter_by(exam_id=exam_id).count() == 0
    assert db.query(ExamEntry).filter_by(exam_id=exam_id).count() == 0
    assert db.query(InvigilationAssignment).filter_by(exam_id=exam_id).count() == 0
    assert db.query(InvigilationConstraint).filter_by(exam_id=exam_id).count() == 0


def test_change_request_invigilation_fields(db, dataset):
    """
    감독 스왑 신청 레코드가 기존 테이블에 저장되는지 확인.

    timetable_entry_id=None + request_type="invigilation" + 감독 배정 FK 로
    신청을 생성할 수 있어야 합니다 (NOT NULL 완화 검증).
    """
    exam = Exam(term_id=dataset["term"].id, name="중간고사",
                first_period_start=time(8, 30),
                start_date=date(2026, 9, 20), end_date=date(2026, 9, 22))
    db.add(exam)
    db.flush()
    period = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 9, 20), period=1,
                        start_time=time(8, 30), end_time=time(9, 20))
    db.add(period)
    db.flush()
    a1 = InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                school_class_id=dataset["small_class"].id,
                                teacher_id=dataset["teachers"][0].id, pair_index=1)
    a2 = InvigilationAssignment(exam_id=exam.id, period_id=period.id,
                                school_class_id=dataset["big_class"].id,
                                teacher_id=dataset["teachers"][1].id, pair_index=1)
    db.add_all([a1, a2])
    db.flush()

    req = TimetableChangeRequest(
        timetable_entry_id=None,          # 감독 스왑은 시간표 슬롯 없음
        request_type="invigilation",
        invigilation_assignment_id=a1.id,
        swap_partner_invigilation_id=a2.id,
        status="pending",
        affected_teacher_id=dataset["teachers"][1].id,
        consent_status="pending",
    )
    db.add(req)
    db.commit()

    loaded = db.query(TimetableChangeRequest).filter_by(request_type="invigilation").one()
    assert loaded.timetable_entry_id is None
    assert loaded.invigilation_assignment_id == a1.id
    assert loaded.swap_partner_invigilation_id == a2.id
    assert loaded.invigilation_assignment.period.period == 1