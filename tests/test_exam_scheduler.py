"""
시험 시간표 자동 배치(generate_exam_entries)와 감독 자동 배정
(assign_invigilations) 알고리즘 테스트.

검증 대상 (요구사항 번호 매핑):
  7 — 시험 과목 배치: 과목당 1회, 하루 과목 수 상한, 학년별 독립
  2 — 감독 금지 규칙: 담임 반 금지, 담당 과목 시험 감독 금지
  3 — 감독 횟수 균등 분배 (소프트 점수 검증)
  5 — 2인 1조 기준: 학생 20명 경계값(19 → 1인, 20 → 2인)
  6 — 수업 병행 검증: 시험 치르지 않는 학년의 수업 교사 자동 배제
  (+ 승인된 감독 불가 신청, 교사 주간 제약 반영)
"""
from datetime import date, time, timedelta

import pytest

from shared.models import (
    AcademicTerm, Grade, SchoolClass, Subject, Teacher,
    SubjectClassAssignment, TimetableEntry, Exam, ExamPeriod, ExamEntry,
    InvigilationAssignment, InvigilationConstraint, TeacherConstraint,
)
from core.exam_scheduler import generate_exam_entries, assign_invigilations


# ── 공통 데이터셋 ─────────────────────────────────────────────────────────────

def _make_teacher(db, name, homeroom_class=None):
    t = Teacher(name=name, is_homeroom=homeroom_class is not None,
                homeroom_class_id=homeroom_class.id if homeroom_class else None)
    db.add(t)
    return t


@pytest.fixture
def scheduler_data(db):
    """
    감독 배정 테스트용 표준 시나리오.

    구성:
      - 학년 1, 2, 3 / 학기 1개
      - 1학년: A반(25명 → 2인 1조), B반(15명 → 1인)
      - 2학년: C반(20명 → 2인 1조 경계값)
      - 3학년: D반 — 시험 대상에서 제외 (수업 병행 검증용)
      - 교사:
          T1: A반 담임           → 담임 반 감독 금지 검증 대상
          T2: A반 수학 담당      → 담당 과목 감독 금지 검증 대상
          T3: 3학년 수업(시험 교시에 수업) → 수업 중 배제 검증 대상
          T4, T5, T6: 자유로운 교사 → 감독 후보 (공평성 검증 대상)
      - 시험: 1일(월요일) × 2교시, 대상 학년 = 1·2학년
    """
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()

    grades = {}
    for n in (1, 2, 3):
        g = Grade(grade_number=n, name=f"{n}학년")
        db.add(g)
        grades[n] = g
    db.flush()

    class_a = SchoolClass(grade_id=grades[1].id, class_number=1,
                          display_name="1학년 1반", student_count=25)
    class_b = SchoolClass(grade_id=grades[1].id, class_number=2,
                          display_name="1학년 2반", student_count=15)
    class_c = SchoolClass(grade_id=grades[2].id, class_number=1,
                          display_name="2학년 1반", student_count=20)   # 경계값
    class_d = SchoolClass(grade_id=grades[3].id, class_number=1,
                          display_name="3학년 1반", student_count=20)
    db.add_all([class_a, class_b, class_c, class_d])
    db.flush()

    t1 = _make_teacher(db, "담임", homeroom_class=class_a)
    t2 = _make_teacher(db, "수학쌤")
    t3 = _make_teacher(db, "삼학년쌤")
    t4 = _make_teacher(db, "자유1")
    t5 = _make_teacher(db, "자유2")
    t6 = _make_teacher(db, "자유3")
    db.flush()

    subjects = {}
    for name, short in (("국어", "국"), ("수학", "수"), ("영어", "영")):
        s = Subject(name=name, short_name=short)
        db.add(s)
        subjects[name] = s
    db.flush()

    # T2 가 A반 수학 담당 → 담당 과목 감독 금지 검증에 사용
    db.add(SubjectClassAssignment(
        school_class_id=class_a.id, subject_id=subjects["수학"].id,
        teacher_id=t2.id, weekly_hours=4, term_id=term.id,
    ))
    # T3 가 3학년 D반 국어 담당 + 시험 교시(월 1·2교시)에 실제 수업 배정
    db.add(SubjectClassAssignment(
        school_class_id=class_d.id, subject_id=subjects["국어"].id,
        teacher_id=t3.id, weekly_hours=4, term_id=term.id,
    ))
    db.add(TimetableEntry(
        term_id=term.id, school_class_id=class_d.id,
        subject_id=subjects["국어"].id, teacher_id=t3.id,
        day_of_week=1, period=1,   # 월요일 1교시 — 시험 1교시와 동일 시간대
    ))
    db.add(TimetableEntry(
        term_id=term.id, school_class_id=class_d.id,
        subject_id=subjects["국어"].id, teacher_id=t3.id,
        day_of_week=1, period=2,   # 월요일 2교시
    ))
    db.commit()

    exam = Exam(
        term_id=term.id, name="1학기 중간고사",
        exam_type="midterm", school_level="high",
        target_grade_ids=f"[{grades[1].id}, {grades[2].id}]",
        start_date=date(2026, 10, 5),   # 월요일
        end_date=date(2026, 10, 5),
        first_period_start=time(8, 30), periods_per_day=2,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=3,
        ban_homeroom_invigilation=True, ban_own_subject=True,
        status="draft",
    )
    db.add(exam)
    db.flush()

    p1 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=1,
                    start_time=time(8, 30), end_time=time(9, 20))
    p2 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=2,
                    start_time=time(9, 30), end_time=time(10, 20))
    db.add_all([p1, p2])
    db.flush()

    # 시험표: 1학년 1교시=수학(T2 담당 과목), 2학년 1교시=영어
    #          1학년 2교시=국어,   2학년 2교시=국어
    db.add(ExamEntry(exam_id=exam.id, period_id=p1.id,
                     grade_id=grades[1].id, subject_id=subjects["수학"].id))
    db.add(ExamEntry(exam_id=exam.id, period_id=p1.id,
                     grade_id=grades[2].id, subject_id=subjects["영어"].id))
    db.add(ExamEntry(exam_id=exam.id, period_id=p2.id,
                     grade_id=grades[1].id, subject_id=subjects["국어"].id))
    db.add(ExamEntry(exam_id=exam.id, period_id=p2.id,
                     grade_id=grades[2].id, subject_id=subjects["국어"].id))
    db.commit()

    return {
        "term": term, "grades": grades,
        "classes": {"a": class_a, "b": class_b, "c": class_c, "d": class_d},
        "teachers": {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6},
        "subjects": subjects, "exam": exam, "periods": [p1, p2],
    }


# ── 시험 시간표 자동 배치 (요구사항 7) ────────────────────────────────────────

def test_generate_entries_basic_rules(db):
    """과목당 1회 + 하루 상한 + 학년별 독립 배치 검증."""
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    g1 = Grade(grade_number=1, name="1학년")
    g2 = Grade(grade_number=2, name="2학년")
    db.add_all([g1, g2])
    db.flush()
    c1 = SchoolClass(grade_id=g1.id, class_number=1, display_name="1-1")
    c2 = SchoolClass(grade_id=g2.id, class_number=1, display_name="2-1")
    db.add_all([c1, c2])
    db.flush()
    s1 = Subject(name="국어", short_name="국")
    s2 = Subject(name="수학", short_name="수")
    s3 = Subject(name="영어", short_name="영")
    s4 = Subject(name="과학", short_name="과")
    db.add_all([s1, s2, s3, s4])
    db.flush()
    teacher = _make_teacher(db, "쌤")
    db.flush()
    # 1학년: 과목 4개 / 2학년: 과목 2개 — 학년별 다른 과목 수
    for s in (s1, s2, s3, s4):
        db.add(SubjectClassAssignment(
            school_class_id=c1.id, subject_id=s.id,
            teacher_id=teacher.id, weekly_hours=2, term_id=term.id))
    for s in (s1, s2):
        db.add(SubjectClassAssignment(
            school_class_id=c2.id, subject_id=s.id,
            teacher_id=teacher.id, weekly_hours=2, term_id=term.id))
    db.commit()

    # 2일 × 2교시 = 칸 4개, 하루 상한 2 → 1학년 과목 4개는 2+2로 분산
    exam = Exam(
        term_id=term.id, name="배치테스트", target_grade_ids="[]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 6),
        first_period_start=time(8, 30), periods_per_day=2,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=2,
    )
    db.add(exam)
    db.flush()
    for d in (date(2026, 10, 5), date(2026, 10, 6)):
        for p in (1, 2):
            db.add(ExamPeriod(
                exam_id=exam.id, exam_date=d, period=p,
                start_time=time(8, 30), end_time=time(9, 20)))
    db.commit()

    ok, msg = generate_exam_entries(db, exam.id)
    assert ok, msg

    entries = db.query(ExamEntry).filter_by(exam_id=exam.id).all()
    # 1학년 4칸 + 2학년 2칸
    assert len(entries) == 6

    # 과목당 1회 (같은 학년에서 과목 중복 없음)
    g1_subjects = [e.subject_id for e in entries if e.grade_id == g1.id]
    assert len(g1_subjects) == len(set(g1_subjects)) == 4

    # 하루 상한: 10/05 에는 1학년 과목이 최대 2개
    per_day = {}
    for e in entries:
        per_day.setdefault((e.grade_id, e.period.exam_date), 0)
        per_day[(e.grade_id, e.period.exam_date)] += 1
    assert all(v <= 2 for v in per_day.values())


def test_generate_entries_insufficient_slots(db):
    """과목 수가 가용 교시보다 많으면 (False, 사유) 반환."""
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    g = Grade(grade_number=1, name="1학년")
    db.add(g)
    db.flush()
    c = SchoolClass(grade_id=g.id, class_number=1, display_name="1-1")
    db.add(c)
    db.flush()
    t = _make_teacher(db, "쌤")
    db.flush()
    for i in range(4):
        s = Subject(name=f"과목{i}", short_name=f"과{i}")
        db.add(s)
        db.flush()
        db.add(SubjectClassAssignment(
            school_class_id=c.id, subject_id=s.id,
            teacher_id=t.id, weekly_hours=1, term_id=term.id))
    db.commit()

    exam = Exam(
        term_id=term.id, name="부족테스트", target_grade_ids="[]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
        first_period_start=time(8, 30), periods_per_day=2,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=2,
    )
    db.add(exam)
    db.flush()
    for p in (1, 2):
        db.add(ExamPeriod(
            exam_id=exam.id, exam_date=date(2026, 10, 5), period=p,
            start_time=time(8, 30), end_time=time(9, 20)))
    db.commit()

    ok, msg = generate_exam_entries(db, exam.id)
    assert not ok
    assert "초과" in msg


# ── 감독 자동 배정 — 하드 제약 (요구사항 2·6 + 불가 신청/주간 제약) ──────────

def test_assign_invigilations_hard_constraints(db, scheduler_data):
    """
    하드 제약 5종 통합 검증:
      T1(담임)은 자기 반 A 슬롯에 배정되지 않음
      T2(수학 담당)은 A반 1교시(수학 시험) 슬롯에 배정되지 않음
      T3(시험 교시에 3학년 수업)은 전혀 배정되지 않음
    """
    data = scheduler_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    class_a = data["classes"]["a"]
    t1, t2, t3 = data["teachers"]["t1"], data["teachers"]["t2"], data["teachers"]["t3"]
    p1, p2 = data["periods"]

    a_slots = db.query(InvigilationAssignment).filter_by(
        school_class_id=class_a.id).all()

    # 제약 2-1: 담임(T1)은 자기 반(A) 감독 금지
    assert all(a.teacher_id != t1.id for a in a_slots), "담임이 자기 반에 배정됨"

    # 제약 2-2: 수학 담당(T2)은 A반 1교시(수학 시험) 감독 금지
    a_p1 = [a for a in a_slots if a.period_id == p1.id]
    assert all(a.teacher_id != t2.id for a in a_p1), "담당 과목 교사가 해당 시험 시간에 배정됨"

    # 제약 6: 시험 교시에 수업 중인 교사(T3)는 전 슬롯 배제
    all_slots = db.query(InvigilationAssignment).filter_by(
        exam_id=data["exam"].id).all()
    assert all(a.teacher_id != t3.id for a in all_slots), "수업 중인 교사가 배정됨"


def test_assign_invigilations_pair_composition(db, scheduler_data):
    """요구사항 5 — 20명 경계값: 25명(A)=2조, 15명(B)=1조, 20명(C)=2조."""
    data = scheduler_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    p1 = data["periods"][0]
    for cls, expected in (("a", 2), ("b", 1), ("c", 2)):
        slots = db.query(InvigilationAssignment).filter_by(
            period_id=p1.id, school_class_id=data["classes"][cls].id).all()
        assert len(slots) == expected, f"{cls}반 조 슬롯 수 오류: {len(slots)} != {expected}"


def test_assign_invigilations_fairness(db, scheduler_data):
    """
    요구사항 3 — 감독 횟수 균등 분배.

    시나리오의 가용 교사는 T2, T4, T5, T6 (T1 담임·A반 한정 금지지만
    B/C반은 가능하므로 포함; T3 전면 배제).
    정확한 균등 계산은 배정 결과에 따라 달라지므로, 여기서는
    "가장 많이 배정된 교사와 가장 적게 배정된 교사의 차이 ≤ 2"로
    형평성을 검증합니다 (소프트 점수 기반이므로 완전 균등은 최선 시도).
    """
    data = scheduler_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    all_slots = db.query(InvigilationAssignment).filter_by(
        exam_id=data["exam"].id).filter(
        InvigilationAssignment.teacher_id.isnot(None)).all()
    counts = {}
    for a in all_slots:
        counts[a.teacher_id] = counts.get(a.teacher_id, 0) + 1
    assert counts, "배정 결과가 없습니다."
    diff = max(counts.values()) - min(counts.values())
    assert diff <= 2, f"감독 횟수 편차가 큽니다: {counts}"


def test_assign_invigilations_no_double_booking(db, scheduler_data):
    """동일 교시에 한 교사가 두 반을 동시 감독하지 않는지 검증."""
    data = scheduler_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    for p in data["periods"]:
        period_slots = db.query(InvigilationAssignment).filter_by(
            period_id=p.id).filter(InvigilationAssignment.teacher_id.isnot(None)).all()
        teacher_ids = [a.teacher_id for a in period_slots]
        assert len(teacher_ids) == len(set(teacher_ids)), \
            f"{p.period}교시에 중복 감독 발생: {teacher_ids}"


def test_approved_constraint_excludes_teacher(db, scheduler_data):
    """
    승인된 감독 불가 신청(전 교시)이 하드 제약으로 반영되는지 검증.

    주의: T4 를 배제하면 1교시 가용 교사가 슬롯 수(5개)보다 줄어들어
    부분 배정이 되기 때문에, 배제 검증만으로는 규칙 반영 여부와
    "배정 실패"를 구분할 수 없습니다. 따라서 여유 교사 T7 을 추가해
    전량 배정이 가능한 상황에서 T4 만 빠지는지를 확인합니다.
    """
    data = scheduler_data
    t4 = data["teachers"]["t4"]
    _make_teacher(db, "자유4")   # T7 — 배제 검증용 여유 교사
    db.commit()

    db.add(InvigilationConstraint(
        exam_id=data["exam"].id, teacher_id=t4.id,
        exam_date=date(2026, 10, 5), period=None,
        reason="공결", status="approved",
    ))
    db.commit()

    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    all_slots = db.query(InvigilationAssignment).filter_by(
        exam_id=data["exam"].id).all()
    assert all(a.teacher_id != t4.id for a in all_slots), "승인된 감독 불가 교사가 배정됨"


def test_pending_constraint_not_reflected(db, scheduler_data):
    """미승인(pending) 감독 불가 신청은 배정에 반영되지 않는지 검증."""
    data = scheduler_data
    t4 = data["teachers"]["t4"]
    db.add(InvigilationConstraint(
        exam_id=data["exam"].id, teacher_id=t4.id,
        exam_date=date(2026, 10, 5), period=None,
        reason="사정", status="pending",
    ))
    db.commit()

    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    # pending 이라 t4 도 감독 후보에 포함되어야 정상
    all_slots = db.query(InvigilationAssignment).filter_by(
        exam_id=data["exam"].id).filter(
        InvigilationAssignment.teacher_id == t4.id).all()
    assert len(all_slots) > 0, "pending 신청이 하드 제약으로 잘못 반영됨"


def test_weekly_unavailable_constraint_excludes(db, scheduler_data):
    """
    교사 주간 제약(TeacherConstraint, unavailable)이 반영되는지 검증.

    T5 를 월 1교시에 배제하면 1교시 가용 교사 수가 슬롯 수와 같아지므로,
    여유 교사 T7 을 추가해 전량 배정 상황에서 T5 만 1교시에 빠지는지 확인.
    """
    data = scheduler_data
    t5 = data["teachers"]["t5"]
    _make_teacher(db, "자유4")   # T7 — 배제 검증용 여유 교사
    db.commit()

    db.add(TeacherConstraint(
        teacher_id=t5.id, day_of_week=1, period=1,   # 월 1교시
        constraint_type="unavailable",
    ))
    db.commit()

    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    p1 = data["periods"][0]
    p1_slots = db.query(InvigilationAssignment).filter_by(
        period_id=p1.id).all()
    assert all(a.teacher_id != t5.id for a in p1_slots), "주간 제약 교사가 해당 교시에 배정됨"


def test_insufficient_candidates_leaves_unassigned(db, scheduler_data):
    """
    후보 부족 시 미배정 슬롯 처리 검증.

    T3(수업 중), T2(담당 과목 1교시) 외 대부분을 배제하고 1교시 슬롯을
    강제로 감당 가능한 교사 수보다 많게 만들면, 미배정 슬롯이
    teacher_id=NULL 로 저장되고 (False, 안내 메시지) 를 반환해야 합니다.
    """
    data = scheduler_data
    # 모든 자유 교사(T4~T6)에게 주간 제약을 걸어 1교시 후보를 T2 만 남김
    # (T2 는 A반 1교시만 금지, C반 1교시는 가능 → 부분 배정만 가능)
    for key in ("t4", "t5", "t6"):
        db.add(TeacherConstraint(
            teacher_id=data["teachers"][key].id,
            day_of_week=1, period=1, constraint_type="unavailable",
        ))
    # 담임 T1 도 전면 불가 처리해 후보 수를 더 줄임
    db.add(TeacherConstraint(
        teacher_id=data["teachers"]["t1"].id,
        day_of_week=1, period=1, constraint_type="unavailable",
    ))
    db.commit()

    ok, msg = assign_invigilations(db, data["exam"].id)
    assert not ok, "후보 부족인데 성공으로 잘못 보고됨"
    assert "미배정" in msg

    p1 = data["periods"][0]
    p1_slots = db.query(InvigilationAssignment).filter_by(period_id=p1.id).all()
    # 1교시 슬롯은 A반 2조 + B반 1조 + C반 2조 = 5개가 존재해야 함
    assert len(p1_slots) == 5
    # 미배정 슬롯이 teacher_id=NULL 로 저장되어 있는지
    assert any(a.teacher_id is None for a in p1_slots)