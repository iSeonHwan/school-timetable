"""
혼합 시험실(ExamRoom) · 복도감독(CorridorDutyAssignment) · 학년별 시험
미참여 날짜(ExamGradeDateExclusion) 테스트 (2026-10-04 신규).

실제 학교에서 쓰던 2학기 1회고사 시험감독표(엑셀)로 기존 스케줄러를
검증하는 과정에서 드러난 구조적 한계 3가지를 해소하기 위해 추가된
기능입니다:
  1. 여러 반 학생이 섞이는 시험실(2학년 선택과목·3학년 공통 고사 등)
  2. 복도감독(학년별 1명, 시험 과목 담당 교사 중 배정)
  3. 학년마다 시험 참여 날짜가 다른 경우(예: 특정 학년만 첫날 정상수업)
"""
from datetime import date, time

import pytest

from shared.models import (
    AcademicTerm, Grade, SchoolClass, Subject, Teacher,
    SubjectClassAssignment, Exam, ExamPeriod, ExamEntry,
    InvigilationAssignment, ExamRoom, CorridorDutyAssignment,
    ExamGradeDateExclusion,
)
from core.exam_scheduler import (
    generate_exam_entries, assign_invigilations, assign_corridor_duty,
)


def _make_teacher(db, name, homeroom_class=None):
    t = Teacher(name=name, is_homeroom=homeroom_class is not None,
                homeroom_class_id=homeroom_class.id if homeroom_class else None)
    db.add(t)
    return t


@pytest.fixture
def mixed_room_data(db):
    """
    2학년 선택과목 시나리오 (실제 사례의 "세계사 24명 — 3반 교실" 축약):
      - 2학년 1반·2반·3반 담임 각각 T1·T2·T3
      - 선택과목 "세계사"를 1반+2반 학생이 함께 듣고(섞인 시험실),
        3반 담임 T3의 교실에서 시험을 치름 — 반 경계를 넘는 시험실이라
        ExamRoom 으로 표현. 1반+2반 학생이 섞이므로 T1·T2 담임 모두
        감독 제외돼야 함(T3 는 3반 교실이라도 "자기 반 학생"이 아니므로
        제외 대상이 아님 — 실제로는 3반 교실을 빌려 쓸 뿐 3반 학생은
        이 시험실에 없음).
      - T4 가 세계사 담당 교사 → 담당 과목 감독 금지 대상
      - T5, T6 자유 교사
    """
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()

    grade2 = Grade(grade_number=2, name="2학년")
    db.add(grade2)
    db.flush()

    c1 = SchoolClass(grade_id=grade2.id, class_number=1, display_name="2-1", student_count=20)
    c2 = SchoolClass(grade_id=grade2.id, class_number=2, display_name="2-2", student_count=20)
    c3 = SchoolClass(grade_id=grade2.id, class_number=3, display_name="2-3", student_count=20)
    db.add_all([c1, c2, c3])
    db.flush()

    t1 = _make_teacher(db, "담임1", homeroom_class=c1)
    t2 = _make_teacher(db, "담임2", homeroom_class=c2)
    t3 = _make_teacher(db, "담임3", homeroom_class=c3)
    t4 = _make_teacher(db, "세계사쌤")
    t5 = _make_teacher(db, "자유1")
    t6 = _make_teacher(db, "자유2")
    db.flush()

    subj = Subject(name="세계사", short_name="세계")
    db.add(subj)
    db.flush()

    # T4 가 1반·2반에 세계사를 가르침 (혼합 시험실 소속 반 전체)
    db.add(SubjectClassAssignment(
        school_class_id=c1.id, subject_id=subj.id, teacher_id=t4.id,
        weekly_hours=3, term_id=term.id,
    ))
    db.add(SubjectClassAssignment(
        school_class_id=c2.id, subject_id=subj.id, teacher_id=t4.id,
        weekly_hours=3, term_id=term.id,
    ))
    db.commit()

    exam = Exam(
        term_id=term.id, name="선택과목 테스트",
        target_grade_ids=f"[{grade2.id}]",
        start_date=date(2026, 10, 2), end_date=date(2026, 10, 2),   # 금요일
        first_period_start=time(9, 0), periods_per_day=1,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        ban_homeroom_invigilation=True, ban_own_subject=True,
        pair_threshold=24,
        status="draft",
    )
    db.add(exam)
    db.flush()
    p1 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 2), period=1,
                    start_time=time(9, 0), end_time=time(9, 50))
    db.add(p1)
    db.flush()

    # 혼합 시험실: 1반+2반 학생(24명)이 섞여 3반 교실에서 세계사 시험
    room = ExamRoom(
        exam_id=exam.id, period_id=p1.id, grade_id=grade2.id,
        subject_id=subj.id, source_class_ids=f"[{c1.id}, {c2.id}]",
        student_count=24, label="세계사(3반 교실)",
    )
    db.add(room)
    db.commit()

    return {
        "term": term, "grade2": grade2, "classes": {"c1": c1, "c2": c2, "c3": c3},
        "teachers": {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6},
        "subject": subj, "exam": exam, "period": p1, "room": room,
    }


def test_mixed_room_bans_homerooms_of_source_classes(db, mixed_room_data):
    """혼합 시험실에 섞인 반(1반·2반)의 담임은 모두 감독 금지, 무관한 3반 담임은 가능."""
    data = mixed_room_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    room_slots = db.query(InvigilationAssignment).filter_by(
        exam_room_id=data["room"].id).all()
    assert room_slots, "혼합 시험실 슬롯이 생성되지 않음"
    assigned_ids = {a.teacher_id for a in room_slots}
    assert data["teachers"]["t1"].id not in assigned_ids, "1반 담임이 혼합 시험실에 배정됨"
    assert data["teachers"]["t2"].id not in assigned_ids, "2반 담임이 혼합 시험실에 배정됨"


def test_mixed_room_bans_own_subject_teacher(db, mixed_room_data):
    """세계사 담당 교사(T4)는 그 시험실 감독에서 제외."""
    data = mixed_room_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    room_slots = db.query(InvigilationAssignment).filter_by(
        exam_room_id=data["room"].id).all()
    assigned_ids = {a.teacher_id for a in room_slots}
    assert data["teachers"]["t4"].id not in assigned_ids, "담당 과목 교사가 혼합 시험실에 배정됨"


def test_mixed_room_pair_threshold(db, mixed_room_data):
    """24명(pair_threshold=24) 시험실은 2인 1조로 배정되어야 함."""
    data = mixed_room_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    room_slots = db.query(InvigilationAssignment).filter_by(
        exam_room_id=data["room"].id).all()
    assert len(room_slots) == 2, f"24명 혼합 시험실인데 슬롯이 {len(room_slots)}개"


def test_mixed_room_no_double_booking_with_class_slots(db, mixed_room_data):
    """같은 교시에 혼합 시험실 감독과 일반 반 감독이 같은 교사에게 겹치지 않음."""
    data = mixed_room_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    all_slots = db.query(InvigilationAssignment).filter_by(exam_id=data["exam"].id).all()
    teacher_ids = [a.teacher_id for a in all_slots if a.teacher_id is not None]
    assert len(teacher_ids) == len(set(teacher_ids)), f"같은 교시 중복 배정: {teacher_ids}"


def test_corridor_before_classroom_reserves_subject_teacher(db, mixed_room_data):
    """
    2026-10-04 순서 변경 검증: assign_corridor_duty() 를 먼저 실행하면,
    복도감독으로 뽑힌 교사(T4 — 세계사 유일한 담당 교사)가 assign_
    invigilations() 의 교실감독 후보에서 자동 제외된다.

    T4 는 혼합 시험실(세계사)에는 담당 과목 금지로 이미 못 들어가지만,
    같은 교시 3반(T3 담임) 교실감독에는 원래 "자유 교사"처럼 뽑힐 수
    있었다 — 이게 바로 "남은 한계"로 지적됐던 충돌 지점이다. 복도감독을
    먼저 확정해두면 그 경로가 하드 제약으로 막힌다.
    """
    data = mixed_room_data
    ok, msg = assign_corridor_duty(db, data["exam"].id)
    assert ok, msg
    duty = db.query(CorridorDutyAssignment).filter_by(exam_id=data["exam"].id).first()
    assert duty is not None
    assert duty.teacher_id == data["teachers"]["t4"].id, "세계사 유일한 담당 교사(T4)가 복도감독으로 뽑혀야 함"

    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    all_slots = db.query(InvigilationAssignment).filter_by(exam_id=data["exam"].id).all()
    assigned_ids = {a.teacher_id for a in all_slots}
    assert data["teachers"]["t4"].id not in assigned_ids, (
        "복도감독으로 이미 배정된 교사가 같은 교시 교실감독에도 배정됨"
    )


# ── 학년별 시험 미참여 날짜 (ExamGradeDateExclusion) ───────────────────────

@pytest.fixture
def grade_date_exclusion_data(db):
    """
    실제 사례 축약: 3학년은 첫날(월)은 정상수업, 둘째 날(화)부터 시험(자습).
    1학년은 매일 시험.
    """
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    g1 = Grade(grade_number=1, name="1학년")
    g3 = Grade(grade_number=3, name="3학년")
    db.add_all([g1, g3])
    db.flush()
    c1 = SchoolClass(grade_id=g1.id, class_number=1, display_name="1-1", student_count=18)
    c3 = SchoolClass(grade_id=g3.id, class_number=1, display_name="3-1", student_count=18)
    db.add_all([c1, c3])
    db.flush()
    teacher = _make_teacher(db, "쌤")
    teacher2 = _make_teacher(db, "쌤2")   # 화요일에 1학년·3학년이 동시에 필요한 여유 인력
    db.flush()
    s1 = Subject(name="국어", short_name="국")
    s2 = Subject(name="수학", short_name="수")
    db.add_all([s1, s2])
    db.flush()
    for s in (s1, s2):
        db.add(SubjectClassAssignment(
            school_class_id=c1.id, subject_id=s.id, teacher_id=teacher.id,
            weekly_hours=2, term_id=term.id))
    # 3학년은 미참여 날짜(월) 제외 후 가용 교시가 1개(화 1교시)뿐이므로
    # 과목도 1개만 배정 — 안 그러면 "배치 불가(과목 수 > 가용 교시)"가
    # 먼저 발동해 이 테스트의 의도(미참여 날짜 자체가 걸러지는지)를 가린다.
    db.add(SubjectClassAssignment(
        school_class_id=c3.id, subject_id=s1.id, teacher_id=teacher.id,
        weekly_hours=2, term_id=term.id))
    db.commit()

    exam = Exam(
        term_id=term.id, name="미참여일 테스트",
        target_grade_ids=f"[{g1.id},{g3.id}]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 6),   # 월, 화
        first_period_start=time(9, 0), periods_per_day=1,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=2,
        status="draft",
    )
    db.add(exam)
    db.flush()
    p_mon = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=1,
                       start_time=time(9, 0), end_time=time(9, 50))
    p_tue = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 6), period=1,
                       start_time=time(9, 0), end_time=time(9, 50))
    db.add_all([p_mon, p_tue])
    db.flush()

    # 3학년은 월요일(첫날) 시험 미참여 — 정상수업
    db.add(ExamGradeDateExclusion(
        exam_id=exam.id, grade_id=g3.id, exam_date=date(2026, 10, 5),
    ))
    db.commit()

    return {
        "term": term, "g1": g1, "g3": g3, "classes": {"c1": c1, "c3": c3},
        "teacher": teacher, "subjects": {"국어": s1, "수학": s2},
        "exam": exam, "periods": {"mon": p_mon, "tue": p_tue},
    }


def test_grade_exclusion_skips_entry_placement_on_excluded_date(db, grade_date_exclusion_data):
    """3학년은 월요일(미참여)에 시험 과목이 배치되지 않고, 화요일에만 배치됨."""
    data = grade_date_exclusion_data
    ok, msg = generate_exam_entries(db, data["exam"].id)
    assert ok, msg

    g3_entries = db.query(ExamEntry).filter_by(
        exam_id=data["exam"].id, grade_id=data["g3"].id).all()
    assert all(e.period_id == data["periods"]["tue"].id for e in g3_entries), (
        "3학년 시험 과목이 미참여 날짜(월요일)에 배치됨"
    )
    # 1학년은 미참여 날짜가 없으므로 월·화 모두 배치 가능
    g1_entries = db.query(ExamEntry).filter_by(
        exam_id=data["exam"].id, grade_id=data["g1"].id).all()
    assert len(g1_entries) == 2


def test_grade_exclusion_skips_invigilation_slots_on_excluded_date(db, grade_date_exclusion_data):
    """3학년 반에는 월요일(미참여) 감독 슬롯이 생성되지 않음."""
    data = grade_date_exclusion_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    c3_mon_slots = db.query(InvigilationAssignment).filter_by(
        period_id=data["periods"]["mon"].id, school_class_id=data["classes"]["c3"].id,
    ).all()
    assert c3_mon_slots == [], "3학년 미참여 날짜에 감독 슬롯이 생성됨"

    c3_tue_slots = db.query(InvigilationAssignment).filter_by(
        period_id=data["periods"]["tue"].id, school_class_id=data["classes"]["c3"].id,
    ).all()
    assert len(c3_tue_slots) == 1, "3학년 참여 날짜에는 감독 슬롯이 있어야 함"

    # 1학년은 미참여 날짜가 없으므로 월요일에도 슬롯이 있어야 함
    c1_mon_slots = db.query(InvigilationAssignment).filter_by(
        period_id=data["periods"]["mon"].id, school_class_id=data["classes"]["c1"].id,
    ).all()
    assert len(c1_mon_slots) == 1


# ── 복도감독 (CorridorDutyAssignment) ──────────────────────────────────────

@pytest.fixture
def corridor_data(db):
    """
    1학년 1개 반, 시험 과목 "국어" 담당 교사 T1·T2(공동 수업은 아니지만
    같은 학년 다른 반을 가르치는 상황을 피하기 위해 반 1개만 사용).
    T1 이 교실감독으로 이미 배정되면, 복도감독은 겸임 불가능하므로 T2 가
    선택돼야 한다.
    """
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    g1 = Grade(grade_number=1, name="1학년")
    db.add(g1)
    db.flush()
    c1 = SchoolClass(grade_id=g1.id, class_number=1, display_name="1-1", student_count=18)
    db.add(c1)
    db.flush()
    t1 = _make_teacher(db, "국어1")
    t2 = _make_teacher(db, "국어2")
    db.add_all([t1, t2])
    db.flush()
    subj = Subject(name="국어", short_name="국")
    db.add(subj)
    db.flush()
    db.add(SubjectClassAssignment(
        school_class_id=c1.id, subject_id=subj.id, teacher_id=t1.id,
        weekly_hours=4, term_id=term.id))
    # T2 도 국어 담당(공동 수업·보결 등으로 같은 반에 2명 배정된 상황을 가정)
    db.add(SubjectClassAssignment(
        school_class_id=c1.id, subject_id=subj.id, teacher_id=t2.id,
        weekly_hours=4, term_id=term.id))
    db.commit()

    exam = Exam(
        term_id=term.id, name="복도감독 테스트",
        target_grade_ids=f"[{g1.id}]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
        first_period_start=time(9, 0), periods_per_day=1,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        ban_homeroom_invigilation=False, ban_own_subject=False,
        status="draft",
    )
    db.add(exam)
    db.flush()
    p1 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=1,
                    start_time=time(9, 0), end_time=time(9, 50))
    db.add(p1)
    db.flush()
    db.add(ExamEntry(exam_id=exam.id, period_id=p1.id, grade_id=g1.id, subject_id=subj.id))
    db.commit()

    return {
        "term": term, "g1": g1, "class": c1, "teachers": {"t1": t1, "t2": t2},
        "subject": subj, "exam": exam, "period": p1,
    }


def test_corridor_duty_picks_subject_teacher(db, corridor_data):
    """복도감독은 그 교시 시험 과목 담당 교사(T1 또는 T2) 중에서 배정됨."""
    data = corridor_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    ok, msg = assign_corridor_duty(db, data["exam"].id)
    assert ok, msg

    duty = db.query(CorridorDutyAssignment).filter_by(
        exam_id=data["exam"].id, period_id=data["period"].id, grade_id=data["g1"].id,
    ).first()
    assert duty is not None
    assert duty.teacher_id in (data["teachers"]["t1"].id, data["teachers"]["t2"].id)


def test_corridor_duty_does_not_double_book_classroom_teacher(db, corridor_data):
    """교실감독으로 이미 배정된 교사는 같은 교시 복도감독에 겸임되지 않음."""
    data = corridor_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    classroom_teacher = db.query(InvigilationAssignment).filter_by(
        exam_id=data["exam"].id, period_id=data["period"].id,
    ).first().teacher_id
    assert classroom_teacher is not None

    ok, msg = assign_corridor_duty(db, data["exam"].id)
    assert ok, msg
    duty = db.query(CorridorDutyAssignment).filter_by(
        exam_id=data["exam"].id, period_id=data["period"].id, grade_id=data["g1"].id,
    ).first()
    assert duty.teacher_id != classroom_teacher, "교실감독 교사가 복도감독에 겸임 배정됨"


def test_corridor_duty_preserve_existing(db, corridor_data):
    """preserve_existing=True(기본값)면 지금도 유효한 기존 복도감독 배정을 유지."""
    data = corridor_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    ok, msg = assign_corridor_duty(db, data["exam"].id)
    assert ok, msg
    before = db.query(CorridorDutyAssignment).filter_by(exam_id=data["exam"].id).first().teacher_id

    ok, msg = assign_corridor_duty(db, data["exam"].id)   # 재실행 — 변경 없음
    assert ok, msg
    after = db.query(CorridorDutyAssignment).filter_by(exam_id=data["exam"].id).first().teacher_id
    assert before == after, "변경 사항이 없는데도 복도감독 배정이 바뀜"
