"""
실제 학교에서 사용한 26학년도 2학기 1회고사 시험감독표
(tests/data/26학년도_2학기_1회고사_시험감독표.xlsx)를 바탕으로 만든
회귀 시나리오.

이 파일은 가상 데이터가 아니라, 실제 엑셀 산출물에 적힌 교사 이름·
학급 인원·복무 제약(연가/조퇴/업무/육아시간)·감독 제외자를 그대로
가져와 core/exam_scheduler.assign_invigilations() 가 같은 조건에서
실제 운영진이 지킨 규칙을 위반하지 않는지 검증한다.

엑셀 "작성 기준" 시트에서 확인한 실제 운영 기준:
  1. 담임 자기 반 감독 금지 (3-2 이혜, 3-3 최진)
  2. 안은(평가담당)은 시험 기간 전체 감독 제외
  3. 복무: 김금·박선 매일 1교시 불가(육아시간), 유기 10/2 불가(연가),
     윤태 10/2 3교시 이후 불가(조퇴), 이선 10/2 3교시 불가(업무)
  4. 부감독(2인 1조) 기준 — 엑셀 "선택교과 인원"/"검토 체크리스트" 시트에
     명시: "한 시험실 24명 이상일 때만 정·부 2명 배정(1학기 실제 기준)".
     세계사 24명 교실만 2인 1조, 고전읽기 20명/21명 교실은 모두 단독.

  기존 core/exam_scheduler.PAIR_THRESHOLD 상수는 20명으로 고정돼 있어
  이 학교의 실제 기준(24명)과 달랐다. 2026-10-04 에 Exam.pair_threshold
  컬럼을 추가해 시험별로 조정 가능하게 했다 — 기본값은 하위 호환을 위해
  20을 유지하고, 실제 기준에 맞추려면 24로 설정한다
  (test_pair_threshold_matches_real_school_practice_when_configured).

  2026-10-04 에 추가로 해소한 구조적 한계 3가지(각각 전용 테스트 파일
  tests/test_exam_rooms_corridor.py 에서 단위 검증, 아래
  test_full_scenario_* 에서 이 실제 데이터로 통합 검증):
    - 2학년 선택과목(세계사 24명 — 1·2·3반 학생이 섞여 시험)처럼 여러 반이
      섞이는 시험실 → ExamRoom
    - 복도감독(학년별 1명, 과목 담당 교사 중 배정) → CorridorDutyAssignment
    - 3학년이 9/30 은 정상수업이고 10/1·10/2 만 시험 참여 →
      ExamGradeDateExclusion
"""
import json
from datetime import date, time

import pytest

from shared.models import (
    AcademicTerm, Grade, SchoolClass, Teacher, Subject, SubjectClassAssignment,
    Exam, ExamPeriod, ExamEntry, InvigilationAssignment, InvigilationConstraint,
    TeacherConstraint, ExamRoom, CorridorDutyAssignment, ExamGradeDateExclusion,
)
from core.exam_scheduler import assign_invigilations, assign_corridor_duty


# 실제 엑셀 "9-30(수)" 시트 B23:B45 — 익명 처리된 두 글자 실명(감독 대상 22명)
REAL_TEACHER_NAMES = [
    "고두", "권진", "김강", "김광", "김금", "김민", "김성", "김준", "남주",
    "박선", "서윤", "신소", "신택", "유기", "윤태", "이도", "이선", "이성",
    "이혜", "최정", "최진", "황세",
]
# "작성 기준" 3번: 안은(평가 담당)은 시험 기간 전체에서 제외
EXCLUDED_TEACHER_NAME = "안은"


@pytest.fixture
def real_school_data(db):
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()

    grades = {n: Grade(grade_number=n, name=f"{n}학년") for n in (1, 2, 3)}
    db.add_all(grades.values())
    db.flush()

    # 학급 인원 — 1·2학년은 엑셀 "9-30(수)" 시트 B6:B12 실제 재적 인원.
    # 3학년은 반 단위 인원이 엑셀에 없어(선택과목·고사 단위로만 인원이 있음),
    # "선택교과 인원" 시트의 실제 시험실 인원(고전읽기 20명/21명, 세계사
    # 24명)을 그대로 가져와 PAIR_THRESHOLD 경계값 검증에 사용한다.
    classes = {
        "1-1": SchoolClass(grade_id=grades[1].id, class_number=1, display_name="1-1", student_count=19),
        "1-2": SchoolClass(grade_id=grades[1].id, class_number=2, display_name="1-2", student_count=19),
        "1-3": SchoolClass(grade_id=grades[1].id, class_number=3, display_name="1-3", student_count=18),
        "2-1": SchoolClass(grade_id=grades[2].id, class_number=1, display_name="2-1", student_count=15),
        "2-2": SchoolClass(grade_id=grades[2].id, class_number=2, display_name="2-2", student_count=16),
        "2-3": SchoolClass(grade_id=grades[2].id, class_number=3, display_name="2-3", student_count=18),
        # 고전읽기 ①(B반 20명) 대역
        "3-1": SchoolClass(grade_id=grades[3].id, class_number=1, display_name="3-1", student_count=20),
        # 고전읽기 ②(C반 21명) 대역 — 담임 최진
        "3-2": SchoolClass(grade_id=grades[3].id, class_number=2, display_name="3-2", student_count=21),
        # 세계사(24명) 대역 — 담임 이혜
        "3-3": SchoolClass(grade_id=grades[3].id, class_number=3, display_name="3-3", student_count=24),
    }
    db.add_all(classes.values())
    db.flush()

    # 담임 매핑 — 엑셀 "작성 기준" 1번에서 확인된 것은 3-2(이혜), 3-3(최진) 뿐.
    # 나머지 7개 반 담임은 엑셀에 명시되지 않아 비워둔다(가정 데이터 금지).
    teachers = {}
    for name in REAL_TEACHER_NAMES:
        homeroom_class = None
        if name == "이혜":
            homeroom_class = classes["3-2"]
        elif name == "최진":
            homeroom_class = classes["3-3"]
        t = Teacher(name=name, is_homeroom=homeroom_class is not None,
                    homeroom_class_id=homeroom_class.id if homeroom_class else None)
        db.add(t)
        teachers[name] = t
    excluded = Teacher(name=EXCLUDED_TEACHER_NAME)
    db.add(excluded)
    db.flush()
    teachers[EXCLUDED_TEACHER_NAME] = excluded
    db.commit()

    # 시험 기간 — 실제 엑셀의 10/1(목)~10/2(금), 하루 3교시로 축약
    # (9/30 은 3학년이 정상수업이라 감독 대상이 아니므로 제외 — 뒤 설명 참조)
    exam = Exam(
        term_id=term.id, name="1회고사",
        target_grade_ids=f"[{grades[1].id},{grades[2].id},{grades[3].id}]",
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 2),
        first_period_start=time(9, 0), periods_per_day=3,
        break_minutes=20, prep_minutes=5, exam_minutes=50,
        ban_homeroom_invigilation=True, ban_own_subject=True,
        status="draft",
    )
    db.add(exam)
    db.flush()

    periods = {}
    for d in (date(2026, 10, 1), date(2026, 10, 2)):
        for p in (1, 2, 3):
            ep = ExamPeriod(exam_id=exam.id, exam_date=d, period=p,
                            start_time=time(9, 0), end_time=time(9, 50))
            db.add(ep)
            db.flush()
            periods[(d, p)] = ep
    db.commit()

    # ── 복무 제약 — 엑셀 "작성 기준" 10번을 그대로 반영 ──────────────────────
    # 김금·박선: 매일(10/1, 10/2) 1교시 불가 (육아시간)
    for name in ("김금", "박선"):
        for dow in (4, 5):   # 10/1=목(4), 10/2=금(5)
            db.add(TeacherConstraint(
                teacher_id=teachers[name].id, day_of_week=dow, period=1,
                constraint_type="unavailable",
            ))
    # 유기: 10/2 전체 불가 (연가)
    db.add(InvigilationConstraint(
        exam_id=exam.id, teacher_id=teachers["유기"].id,
        exam_date=date(2026, 10, 2), period=None,
        reason="연가", status="approved",
    ))
    # 윤태: 10/2 3교시 이후 불가 (조퇴) → 이 시나리오에선 3교시가 마지막 교시
    db.add(InvigilationConstraint(
        exam_id=exam.id, teacher_id=teachers["윤태"].id,
        exam_date=date(2026, 10, 2), period=3,
        reason="조퇴", status="approved",
    ))
    # 이선: 10/2 3교시 불가 (업무 일정)
    db.add(InvigilationConstraint(
        exam_id=exam.id, teacher_id=teachers["이선"].id,
        exam_date=date(2026, 10, 2), period=3,
        reason="업무 일정", status="approved",
    ))
    # 안은: 시험 기간 전체 제외 (평가 담당) — InvigilationConstraint 에
    # "날짜 전체" 밖에 없어, 시험 기간의 날짜 수만큼 행을 만들어야 한다.
    # (관찰 #5 — "교사 전체 제외" 를 1건으로 표현할 방법이 없다)
    for d in (date(2026, 10, 1), date(2026, 10, 2)):
        db.add(InvigilationConstraint(
            exam_id=exam.id, teacher_id=teachers[EXCLUDED_TEACHER_NAME].id,
            exam_date=d, period=None,
            reason="평가담당", status="approved",
        ))
    db.commit()

    return {
        "term": term, "grades": grades, "classes": classes, "teachers": teachers,
        "exam": exam, "periods": periods,
    }


def test_real_constraints_are_respected(db, real_school_data):
    """
    실제 복무 제약·담임 제외·전체 제외자가 자동 배정에서 전부 지켜지는지 검증.
    엑셀 "검토 체크리스트" A(기초 정보)·B(원칙 준수) 항목에 대응.
    """
    data = real_school_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    all_slots = db.query(InvigilationAssignment).filter_by(exam_id=data["exam"].id).all()
    by_id = {t.id: name for name, t in data["teachers"].items()}

    # 체크리스트 5번: 안은이 감독표 어디에도 없다
    excluded_id = data["teachers"][EXCLUDED_TEACHER_NAME].id
    assert all(a.teacher_id != excluded_id for a in all_slots), "감독 제외자(안은)가 배정됨"

    # 체크리스트 7번: 담임이 자기 반을 감독하지 않는다
    hye_id = data["teachers"]["이혜"].id
    jin_id = data["teachers"]["최진"].id
    for a in all_slots:
        if a.school_class_id == data["classes"]["3-2"].id:
            assert a.teacher_id != hye_id, "이혜가 자기 담임 반(3-2)을 감독함"
        if a.school_class_id == data["classes"]["3-3"].id:
            assert a.teacher_id != jin_id, "최진이 자기 담임 반(3-3)을 감독함"

    # 복무 제약: 김금/박선 10/1·10/2 1교시, 유기 10/2 전체,
    # 윤태/이선 10/2 3교시
    period_lookup = {p.id: p for p in data["periods"].values()}
    for a in all_slots:
        p = period_lookup[a.period_id]
        name = by_id[a.teacher_id] if a.teacher_id else None
        if name in ("김금", "박선") and p.period == 1:
            assert False, f"{name}이 1교시(육아시간 불가)에 배정됨 — {p.exam_date}"
        if name == "유기" and p.exam_date == date(2026, 10, 2):
            assert False, "유기가 10/2(연가) 에 배정됨"
        if name in ("윤태", "이선") and p.exam_date == date(2026, 10, 2) and p.period == 3:
            assert False, f"{name}이 10/2 3교시(불가)에 배정됨"

    # 체크리스트 9번: 같은 교시에 한 사람이 두 곳에 있지 않다
    by_period: dict = {}
    for a in all_slots:
        if a.teacher_id is not None:
            by_period.setdefault(a.period_id, []).append(a.teacher_id)
    for pid, tids in by_period.items():
        assert len(tids) == len(set(tids)), f"교시 {pid} 에서 중복 배정 발생: {tids}"


def test_real_school_fairness_target(db, real_school_data):
    """
    체크리스트 13번: "총 횟수 최대-최소 차이 1 이하"가 목표.
    소프트 점수 기반이라 완전히 같은 결과는 보장 못 하므로, 여기서는
    실제 운영 기준(엑셀 실측: 전원 4회, 유기만 3회 → 편차 1)에 근접하는지
    확인한다. 편차가 크면 W_TOTAL_COUNT 가중치 튜닝이 필요하다는 신호.
    """
    data = real_school_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    counts: dict[int, int] = {}
    for a in db.query(InvigilationAssignment).filter_by(exam_id=data["exam"].id):
        if a.teacher_id is not None:
            counts[a.teacher_id] = counts.get(a.teacher_id, 0) + 1
    assert counts
    diff = max(counts.values()) - min(counts.values())
    # 실제 운영 결과(편차 1)보다 과하게 벌어지면 실패로 표시해 회귀를 잡는다.
    # 소프트 제약이라 여유를 조금 둔다.
    assert diff <= 2, f"감독 횟수 편차가 실제 운영(1) 대비 크게 벌어짐: {counts}"


def test_preserve_existing_mirrors_real_teacher_exclusion_event(db, real_school_data):
    """
    엑셀 "이번 수정 내역" 시트가 기록한 실제 사건을 재현한다: 원래 배정이
    끝난 뒤 박철 선생님이 감독 명단에서 제외되면서 "4자리 대체 + 2자리
    조정"만 하고 나머지는 그대로 썼다("작성 기준" 11번 — 변경 최소화).

    이 테스트는 그 상황을 좁혀서 모델링한다: 이미 배정이 끝난 뒤 특정
    교사 한 명이 전체 기간에서 제외되면, assign_invigilations() 가
    (기본값 preserve_existing=True) 로 재배정했을 때 그 교사의 자리만
    바뀌고 나머지는 그대로 유지되는지 확인한다.
    """
    data = real_school_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg
    before = {
        (a.period_id, a.school_class_id, a.pair_index): a.teacher_id
        for a in db.query(InvigilationAssignment).filter_by(exam_id=data["exam"].id)
    }

    # 안은은 이미 제외돼 있으니, 배정된 교사 중 아무나 하나를 "박철"처럼
    # 새로 제외되는 교사로 골라 전체 기간 불가 신청을 승인 상태로 추가한다.
    newly_excluded_id = next(iter(
        tid for tid in before.values() if tid is not None
    ))
    for d in (date(2026, 10, 1), date(2026, 10, 2)):
        db.add(InvigilationConstraint(
            exam_id=data["exam"].id, teacher_id=newly_excluded_id,
            exam_date=d, period=None, reason="요청", status="approved",
        ))
    db.commit()

    ok, msg = assign_invigilations(db, data["exam"].id)   # preserve_existing=True(기본값)
    assert ok, msg
    after = {
        (a.period_id, a.school_class_id, a.pair_index): a.teacher_id
        for a in db.query(InvigilationAssignment).filter_by(exam_id=data["exam"].id)
    }

    changed_keys = {k for k in before if before[k] != after.get(k)}
    # 바뀐 자리는 전부 "새로 제외된 교사"가 원래 맡고 있던 자리여야 한다 —
    # 그 외 다른 교사의 자리까지 덩달아 뒤섞이면 변경 최소화 실패.
    for key in changed_keys:
        assert before[key] == newly_excluded_id, (
            f"제외와 무관한 자리까지 바뀜: {key} ({before[key]} → {after.get(key)})"
        )
    # 새로 제외된 교사는 결과 어디에도 없어야 한다
    assert newly_excluded_id not in after.values()
    assert changed_keys, "제외된 교사의 자리가 하나도 안 바뀜 — 테스트 조건이 잘못됨"


def test_pair_threshold_matches_real_school_practice_when_configured(db, real_school_data):
    """
    엑셀 "선택교과 인원"/"검토 체크리스트" 시트에 명시된 실제 기준:
      "부감독은 한 시험실 24명 이상일 때만 배정한다(1학기 실제 기준)."
      → 세계사(24명)만 2인 1조, 고전읽기 20명·21명 교실은 단독.

    Exam.pair_threshold 는 시험별로 설정 가능하다(기본값 20 — 과거 동작과의
    하위 호환). 기본값일 때는 실제 학교 기준과 달리 20·21명 교실에도
    2인 1조가 배정되고, 실제 기준(24)으로 설정하면 그 학교가 실제로
    운영한 결과와 일치하는지 확인한다.
    """
    data = real_school_data
    exam = data["exam"]
    p1 = data["periods"][(date(2026, 10, 1), 1)]

    def pair_count(class_key):
        return db.query(InvigilationAssignment).filter_by(
            period_id=p1.id, school_class_id=data["classes"][class_key].id,
        ).count()

    # 기본값(20명 이상 → 2인 1조): 20명/21명/24명 반 모두 2인 1조가 됨
    assert exam.pair_threshold == 20
    ok, msg = assign_invigilations(db, exam.id)
    assert ok, msg
    assert pair_count("3-1") == 2   # 실제 학교 기준(24명)으로는 1이어야 함 (20명)
    assert pair_count("3-2") == 2   # 실제 학교 기준으로는 1이어야 함 (21명)
    assert pair_count("3-3") == 2   # 24명 — 기본값과 실제 기준이 일치하는 유일한 경우

    # 실제 학교 기준(24)으로 설정하면 20·21명 반은 단독이 되어 실제 운영과 일치.
    exam.pair_threshold = 24
    db.commit()
    ok, msg = assign_invigilations(db, exam.id)
    assert ok, msg
    assert pair_count("3-1") == 1, "pair_threshold=24 로 설정해도 20명 반이 2인 1조로 남음"
    assert pair_count("3-2") == 1, "pair_threshold=24 로 설정해도 21명 반이 2인 1조로 남음"
    assert pair_count("3-3") == 2, "24명 반은 여전히 2인 1조여야 함"


# ── 통합 시나리오: 혼합 시험실·복도감독·학년별 미참여 날짜 (2026-10-04) ────
#
# 엑셀 실제 사례 3가지를 한 시나리오에 모아 검증한다:
#   - 2학년 세계사(24명) — 2-1·2-2·2-3 학생이 섞여 시험(ExamRoom),
#     담당 교사 신소는 그 시험실 감독에서 제외되고 복도감독으로 배정된다.
#   - 3학년은 9/30(첫날)은 정상수업이라 시험 대상이 아니고,
#     10/1·10/2 에만 참여한다(ExamGradeDateExclusion).

@pytest.fixture
def full_scenario_data(db):
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    grades = {n: Grade(grade_number=n, name=f"{n}학년") for n in (2, 3)}
    db.add_all(grades.values())
    db.flush()

    g2_classes = {
        f"2-{i}": SchoolClass(grade_id=grades[2].id, class_number=i,
                              display_name=f"2-{i}", student_count=c)
        for i, c in ((1, 15), (2, 16), (3, 18))   # 실제 9/30 시트 2학년 재적 인원
    }
    g3_classes = {
        f"3-{i}": SchoolClass(grade_id=grades[3].id, class_number=i, display_name=f"3-{i}",
                              student_count=18)   # < pair_threshold(24) → 단독 감독
        for i in (1, 2, 3)
    }
    db.add_all(list(g2_classes.values()) + list(g3_classes.values()))
    db.flush()

    hye = Teacher(name="이혜", is_homeroom=True, homeroom_class_id=g3_classes["3-2"].id)
    jin = Teacher(name="최진", is_homeroom=True, homeroom_class_id=g3_classes["3-3"].id)
    sinso = Teacher(name="신소")   # 실제 사례: 세계사 담당 교사
    # 자유 교사 10명 — 매 교시 최대 동시 수요(6자리: 2학년 3반+3학년 3반,
    # 혼합 시험실 교시는 2-3반+혼합시험실 2석+3학년 3반) 대비 여유를 둬
    # 랜덤 재시작 탐욕 알고리즘이 매번 전량 배정에 성공하게 한다(여유가
    # 빠듯하면(예: 정확히 6명) 그리디 특성상 가끔 실패할 수 있음 — 이
    # 테스트의 목적은 그 성공/실패 자체가 아니라 특정 슬롯의 배정 내용 검증).
    frees = [Teacher(name=f"자유{i}") for i in range(1, 11)]
    db.add_all([hye, jin, sinso] + frees)
    db.flush()

    subj = Subject(name="세계사", short_name="세계")
    db.add(subj)
    db.flush()
    for cls in g2_classes.values():
        db.add(SubjectClassAssignment(
            school_class_id=cls.id, subject_id=subj.id, teacher_id=sinso.id,
            weekly_hours=3, term_id=term.id,
        ))
    db.commit()

    exam = Exam(
        term_id=term.id, name="통합 시나리오",
        target_grade_ids=f"[{grades[2].id},{grades[3].id}]",
        start_date=date(2026, 9, 30), end_date=date(2026, 10, 2),
        first_period_start=time(9, 0), periods_per_day=3,
        break_minutes=20, prep_minutes=5, exam_minutes=50,
        ban_homeroom_invigilation=True, ban_own_subject=True,
        pair_threshold=24,   # 실제 학교 기준
        status="draft",
    )
    db.add(exam)
    db.flush()
    periods = {}
    for d in (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)):
        for p in (1, 2, 3):
            ep = ExamPeriod(exam_id=exam.id, exam_date=d, period=p,
                            start_time=time(9, 0), end_time=time(9, 50))
            db.add(ep)
            db.flush()
            periods[(d, p)] = ep
    db.commit()

    # 3학년은 9/30(첫날) 정상수업 — 시험 미참여
    for cls_key in g3_classes:
        db.add(ExamGradeDateExclusion(
            exam_id=exam.id, grade_id=grades[3].id, exam_date=date(2026, 9, 30),
        ))
        break   # grade_id 기준이라 반복 불필요 — 한 번만 등록
    db.commit()

    # 2학년 세계사(24명, 1·2·3반 혼합) — 10/2 3교시
    p_world_history = periods[(date(2026, 10, 2), 3)]
    room = ExamRoom(
        exam_id=exam.id, period_id=p_world_history.id, grade_id=grades[2].id,
        subject_id=subj.id,
        source_class_ids=json.dumps([c.id for c in g2_classes.values()]),
        student_count=24, label="세계사(3반 교실)",
    )
    db.add(room)
    db.commit()

    return {
        "term": term, "grades": grades, "g2": g2_classes, "g3": g3_classes,
        "teachers": {"이혜": hye, "최진": jin, "신소": sinso, "frees": frees},
        "subject": subj, "exam": exam, "periods": periods, "room": room,
    }


def test_full_scenario_mixed_room_excludes_subject_teacher_and_uses_real_threshold(
    db, full_scenario_data,
):
    """세계사 24명 혼합 시험실: pair_threshold=24 기준으로 2인 1조 + 담당 교사(신소) 제외."""
    data = full_scenario_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    room_slots = db.query(InvigilationAssignment).filter_by(
        exam_room_id=data["room"].id).all()
    assert len(room_slots) == 2, "24명 혼합 시험실은 2인 1조여야 함"
    assigned = {a.teacher_id for a in room_slots}
    assert data["teachers"]["신소"].id not in assigned, "세계사 담당 교사가 그 시험실에 배정됨"


def test_full_scenario_grade3_skips_first_day_only(db, full_scenario_data):
    """3학년은 9/30(정상수업)엔 슬롯이 없고, 10/1·10/2엔 슬롯이 있어야 함."""
    data = full_scenario_data
    ok, msg = assign_invigilations(db, data["exam"].id)
    assert ok, msg

    for d in (date(2026, 9, 30),):
        for p in (1, 2, 3):
            period = data["periods"][(d, p)]
            slots = db.query(InvigilationAssignment).filter_by(
                period_id=period.id, school_class_id=data["g3"]["3-1"].id,
            ).all()
            assert slots == [], f"3학년 정상수업일({d})에 감독 슬롯이 생성됨"

    for d in (date(2026, 10, 1), date(2026, 10, 2)):
        period = data["periods"][(d, 1)]
        slots = db.query(InvigilationAssignment).filter_by(
            period_id=period.id, school_class_id=data["g3"]["3-1"].id,
        ).all()
        assert len(slots) == 1, f"3학년 참여일({d})엔 감독 슬롯이 있어야 함"


def test_full_scenario_corridor_duty_picks_subject_teacher_for_mixed_room(
    db, full_scenario_data,
):
    """
    복도감독은 그 시험실의 과목 담당 교사(신소) 중에서 배정된다 — 교실
    감독에서는 제외됐지만(담당 과목 금지) 복도감독 후보에는 포함된다.

    classroom 자동 배정을 먼저 실행하지 않는 이유: 이 픽스처의 신소는
    2학년 세계사 시험실에서만 제외되고 3학년 반 등 무관한 교실감독
    자리에는 여전히 "자유 교사"로서 후보에 들 수 있다. 랜덤 재시작
    탐욕 알고리즘이 그런 무관한 자리에 신소를 우연히 먼저 소모해버리면
    복도감독 차례에 신소가 이미 그 교시에 바쁜 상태가 되어 이 테스트가
    검증하려는 "신소가 선택된다"가 실행마다 들쭉날쭉해진다. 복도감독
    함수 자체는 교실감독 없이도 독립적으로 동작하도록 설계돼 있으므로
    (docstring 참조), 여기서는 그 조건만 떼어 확정적으로 검증한다.
    """
    data = full_scenario_data
    ok, msg = assign_corridor_duty(db, data["exam"].id)
    assert ok, msg

    p_world_history = data["periods"][(date(2026, 10, 2), 3)]
    duty = db.query(CorridorDutyAssignment).filter_by(
        exam_id=data["exam"].id, period_id=p_world_history.id, grade_id=data["grades"][2].id,
    ).first()
    assert duty is not None
    assert duty.teacher_id == data["teachers"]["신소"].id, (
        "세계사 교시의 복도감독은 세계사 담당 교사(신소)여야 함"
    )
