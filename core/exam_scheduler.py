"""
시험 시간표·감독 시간표 자동 생성 알고리즘 (2026-09-19 신규)

기존 수업 시간표 생성기(core/generator.py)와 동일한 설계 철학을 따릅니다:
  - 하드 제약(위반 시 절대 배치 불가)은 set/dict 조회로 O(1) 배제
  - 소프트 제약(지키면 좋은 것)은 점수(score) 기반으로 최선의 선택
  - 랜덤 재시작(random restart)으로 우연에 의존하는 배치를 여러 번 시도하고
    가장 좋은 결과를 채택

제공 함수:
  generate_exam_entries(session, exam_id)
      — 시험 시간표(과목 배치) 자동 생성
  assign_invigilations(session, exam_id)
      — 시험 감독 배정 자동 생성

두 함수 모두 (bool, message) 튜플을 반환합니다 (generator.py 와 동일한 규약).
"""
import json
import logging
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from shared.models import (
    Exam, ExamPeriod, ExamEntry, InvigilationAssignment, InvigilationConstraint,
    SchoolClass, SubjectClassAssignment, TimetableEntry, TeacherConstraint,
    Grade, Subject, Teacher,
)

# ── 소프트 제약 점수 가중치 ──────────────────────────────────────────────────
# 값이 클수록 배정 결과에 강하게 반영됩니다. 절대적 기준이 아니라
# 상대적 우선순위를 표현합니다 (score 는 후보 교사마다 비교에만 사용).

# 감독 횟수 균등 분배(요구사항 3) — 가장 중요한 형평성 지표이므로 최대 가중치.
# 이미 많이 배정된 교사일수록 큰 감점을 받아, 적게 배정된 교사가
# 다음 슬롯에서 우선적으로 선택됩니다.
W_TOTAL_COUNT = -10
# 같은 날짜에 감독이 몰리는 것을 방지 (하루 집중 부담 완화).
W_SAME_DAY = -3
# 직전 교시에 이어서 감독하면 이동이 없어 교사 부담이 적으므로 가점.
# (연속 감독 회피보다 이동 최소화가 실무적으로 더 선호된다는 가정 —
#  절반 나눠 배정되는 것보다 붙어 있는 쪽이 쉬는시간 활용에 유리)
W_ADJACENT = 2

# 자동 배정 시 랜덤 재시작 횟수. 각 시도는 슬롯/후보 순서를 무작위로 섞어
# 다른 결과를 만들며, 그중 "미배정 수 → 감독 횟수 분산" 순으로 최선을 고릅니다.
MAX_ATTEMPTS = 10

# 학생 수 미입력 반의 기본 가정 학생 수.
# 기본값을 20 이상으로 두는 이유: 실제 학급 학생 수를 모르는 상태에서
# 감독이 부족하게 배정되는 사고(시험 중 교사 1명)는 과잉 배정보다
# 훨씬 위험하기 때문입니다. 20 = 2인 1조 판단 기준(요구사항 5).
DEFAULT_STUDENT_COUNT = 30

# 2인 1조 판단 기준 학생 수 (요구사항 5: 20명 이상 → 2인 1조)
PAIR_THRESHOLD = 20

_logger = logging.getLogger(__name__)


def rebuild_exam_periods(session: Session, exam: Exam) -> int:
    """
    시험 기간(exam.start_date ~ end_date)에 맞춰 ExamPeriod 를 재생성합니다.

    서버 API(server/api/exams.py)와 관리자 앱(admin_app)이 모두 사용하는
    공통 로직입니다 — 두 곳에 각자 두면 교시 시각 계산 규칙이 어긋날 위험이
    있으므로 core 에 단일 구현을 둡니다.

    시각 계산 (요구사항 4 — 종료령과 동시 종료):
      N교시 시작 = 1교시 시작 + (N-1) × (시험시간 + 쉬는시간)
      N교시 종료 = N교시 시작 + 시험시간
      (준비령 = 종료 - prep_minutes 은 파생값이라 저장하지 않음)

    주의 — 기존 periods 를 먼저 삭제합니다. cascade 로 딸린 시험 칸
    (ExamEntry)과 감독 배정(InvigilationAssignment)도 함께 삭제되는
    파괴적 변경이므로, 게시(published)된 시험에 대해서는 호출 금지
    (서버 API 에서 published 검증 후 호출).

    Args:
        session: SQLAlchemy 세션
        exam: 기간·교시 규칙이 세팅된 Exam 객체

    Returns:
        생성된 교시 수
    """
    session.query(ExamPeriod).filter_by(exam_id=exam.id).delete()

    base = datetime.combine(exam.start_date, exam.first_period_start)
    slot_minutes = exam.exam_minutes + exam.break_minutes
    created = 0
    d = exam.start_date
    while d <= exam.end_date:
        # 버그 수정: 예전 코드는 start_date~end_date 사이의 모든 달력일에
        # 교시를 생성해, 시험 기간이 주말을 걸치면(예: 금요일 시작 ~ 다음 주
        # 월요일 종료) 토·일요일에도 ExamPeriod 가 만들어졌습니다. 정규
        # 시간표(TimetableEntry)는 평일(day_of_week 1~5)만 존재하므로, 주말
        # 교시는 (1) 실제로 시험을 치르지 않는 날에 감독/시험표가 생성되고,
        # (2) _collect_hard_constraints 의 busy/weekly_unavailable 매핑이
        # 주말 dow(6, 7)에 대해서는 아무 데이터도 없어 제약이 사실상 전부
        # 무력화된 상태로 배정이 진행되는 이중의 문제가 있었습니다.
        # weekday() 는 월=0 ~ 금=4, 토=5, 일=6 이므로 5 미만(평일)만 생성합니다.
        if d.weekday() < 5:
            for p in range(1, exam.periods_per_day + 1):
                start_dt = base + timedelta(minutes=(p - 1) * slot_minutes)
                end_dt = start_dt + timedelta(minutes=exam.exam_minutes)
                session.add(ExamPeriod(
                    exam_id=exam.id, exam_date=d, period=p,
                    start_time=start_dt.time(), end_time=end_dt.time(),
                ))
                created += 1
        d += timedelta(days=1)
    return created


def _parse_target_grade_ids(exam: Exam) -> list[int]:
    """
    Exam.target_grade_ids(JSON 문자열)를 파싱해 학년 ID 목록을 반환.

    빈 리스트의 의미: "해당 학기의 전체 학년이 시험 대상".
    JSON 파싱 실패 시 안전하게 빈 리스트(전체 학년)로 처리합니다 —
    잘못 저장된 데이터 때문에 시험 기능 전체가 막히지 않도록 하기 위함.

    버그 수정: 이 폴백은 "파싱 실패 → 전체 학년 대상"으로 범위를 오히려
    넓히는 쪽으로 조용히 동작합니다. 예를 들어 특정 학년(예: 3학년)만
    대상인 시험인데 target_grade_ids 데이터가 손상되면, 아무 로그도 없이
    전체 학년이 그 시험의 대상이 되어 관계없는 학년까지 시험 시간표·감독
    배정이 생성될 수 있습니다. 동작(빈 리스트 반환)은 기존과 동일하게
    유지하되(하위 호환·가용성 우선이라는 원래 설계 의도 존중), 이 상황이
    더 이상 "조용히" 지나가지 않도록 경고 로그를 남겨 원인 추적이 가능하게
    합니다.
    """
    try:
        ids = json.loads(exam.target_grade_ids or "[]")
        return [int(i) for i in ids if isinstance(i, (int, str))]
    except (ValueError, TypeError):
        _logger.warning(
            "Exam(id=%s).target_grade_ids 파싱 실패 — 원본값=%r. "
            "전체 학년을 대상으로 폴백합니다. 데이터 손상 여부를 확인하세요.",
            getattr(exam, "id", None), exam.target_grade_ids,
        )
        return []


def generate_exam_entries(session: Session, exam_id: int) -> tuple[bool, str]:
    """
    시험 시간표(과목 배치) 자동 생성.

    동작:
      1. 시험 대상 학년별로, 해당 학년 반이 학기(term)에 배정받은 과목
         집합을 SubjectClassAssignment 에서 수집합니다.
         (담당 교사가 있는 과목만 시험 과목이 됩니다 — 시수 배정이 곧
          "이 반에서 가르치는 과목"이라는 학교 업무 관례를 그대로 반영)
      2. 시험 교시(ExamPeriod)를 날짜·교시 순으로 늘어놓고, 학년별로
         과목을 순서대로 배치합니다.

    배치 규칙 (요구사항 7):
      - 과목당 1회: 같은 학년에서 같은 과목이 두 번 시험되지 않음
      - 하루 과목 수 상한: 학년별 하루 max_subjects_per_day 초과 금지
      - 학년 독립: 다른 학년의 배치와 상호 간섭 없음
        (모든 반이 같은 교시에 같은 과목을 응시하는 학년 단위 배치 — ExamEntry 참조)

    기존 배치 처리:
      이미 시험표(수동 편집 포함)가 있으면 삭제 후 재배치합니다.
      수동 편집 칸(is_manual)이 있었다면 결과 메시지로 안내해
      재배치로 수동 작업이 덮어써졌음을 관리자가 알 수 있게 합니다.

    Returns:
        (True, 안내 메시지) 또는 (False, 실패 사유)
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return False, "시험을 찾을 수 없습니다."

    # 시험 교시를 날짜·교시 순으로 정렬
    periods = (
        session.query(ExamPeriod)
        .filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )
    if not periods:
        return False, "시험 교시(ExamPeriod)가 없습니다. 시험 기간을 먼저 설정하세요."

    # 시험 대상 학년 결정 — 빈 리스트면 전체 학년
    target_grades = _parse_target_grade_ids(exam)
    if not target_grades:
        target_grades = [g.id for g in session.query(Grade).order_by(Grade.grade_number).all()]
    if not target_grades:
        return False, "학년 정보가 없습니다."

    # 학년별 시험 과목 수집 — 해당 학년 반들의 학기 시수 배정 과목(중복 제거)
    # (과목 순서를 id 순으로 고정해 실행할 때마다 같은 결과가 나오게 함)
    grade_subjects: dict[int, list[int]] = {}
    for grade_id in target_grades:
        rows = (
            session.query(SubjectClassAssignment.subject_id)
            .join(SchoolClass, SchoolClass.id == SubjectClassAssignment.school_class_id)
            .filter(
                SchoolClass.grade_id == grade_id,
                SubjectClassAssignment.term_id == exam.term_id,
            )
            .distinct()
            .order_by(SubjectClassAssignment.subject_id)
            .all()
        )
        subject_ids = [r[0] for r in rows]
        if not subject_ids:
            return False, f"{grade_id}번 학년에 배정된 과목이 없습니다. 시수 배정을 먼저 하세요."
        grade_subjects[grade_id] = subject_ids

    # 칸 수 검증 — 과목 수가 가용 교시보다 많으면 배치 자체가 불가능
    total_slots = len(periods)
    for grade_id, subject_ids in grade_subjects.items():
        if len(subject_ids) > total_slots:
            return False, (
                f"배치 불가: {grade_id}번 학년 과목 수({len(subject_ids)})가 "
                f"가용 교시 수({total_slots})를 초과합니다."
            )

    # 수동 편집 칸 존재 여부 확인 — 삭제 후 재배치되므로 안내에 사용
    manual_count = session.query(ExamEntry).filter_by(exam_id=exam.id, is_manual=True).count()

    # 기존 배치 전체 삭제 후 재배치 (자동 배치는 "재생성" 개념)
    session.query(ExamEntry).filter_by(exam_id=exam.id).delete()

    # 학년별 순차 배치
    # 각 날짜에 배치된 과목 수를 세어 하루 상한을 검사합니다.
    period_ids_by_date: dict = {}
    for p in periods:
        period_ids_by_date.setdefault(p.exam_date, []).append(p)

    placed = 0
    for grade_id, subject_ids in grade_subjects.items():
        idx = 0                       # 다음에 배치할 과목 인덱스
        per_day_count = 0             # 오늘(현재 순회 중 날짜)에 넣은 과목 수
        current_date = None
        for p in periods:
            if p.exam_date != current_date:
                current_date = p.exam_date
                per_day_count = 0
            # 하루 상한 도달 시 오늘은 더 못 넣음 → 다음 날짜로 이동
            if per_day_count >= exam.max_subjects_per_day:
                continue
            if idx >= len(subject_ids):
                break  # 이 학년 과목 전부 배치 완료
            session.add(ExamEntry(
                exam_id=exam.id, period_id=p.id,
                grade_id=grade_id, subject_id=subject_ids[idx],
            ))
            idx += 1
            per_day_count += 1
            placed += 1
        # 루프가 끝났는데 과목이 남음 = 상한 때문에 못 넣은 과목 (칸 수는
        # 위에서 검증했으므로 실제로는 발생하지 않아야 정상)
        if idx < len(subject_ids):
            session.rollback()
            return False, (
                f"배치 실패: {grade_id}번 학년의 {len(subject_ids) - idx}개 과목이 "
                f"하루 상한({exam.max_subjects_per_day}) 때문에 배치되지 못했습니다."
            )

    session.commit()

    msg = f"시험 시간표 자동 배치 완료 — {placed}칸 배치."
    if manual_count:
        msg += f" (주의: 기존 수동 편집 {manual_count}칸이 재배치로 덮어써졌습니다.)"
    return True, msg


def _build_slots(session: Session, exam: Exam, periods: list[ExamPeriod],
                 classes: list[SchoolClass]) -> list[dict]:
    """
    감독 슬롯 목록 생성.

    각 슬롯은 (교시 × 반 × 조 번호) 하나이며, 반 학생 수에 따라
    조 슬롯 수가 결정됩니다 (요구사항 5):
      - 학생 20명 이상(student_count >= 20) → pair_index 1, 2 두 슬롯
      - 학생 20명 미만                     → pair_index 1 한 슬롯
      - student_count 미입력               → 기본 30명 가정 → 2인 1조
        (감독 부족 사고가 과잉 배정보다 위험하므로 안전한 쪽을 택함)

    반환 슬롯(dict) 구성:
      period_id / period / exam_date / class_id / grade_id / pair_index
    """
    slots = []
    for p in periods:
        for sc in classes:
            count = sc.student_count if sc.student_count is not None else DEFAULT_STUDENT_COUNT
            pair_total = 2 if count >= PAIR_THRESHOLD else 1
            for pair_index in range(1, pair_total + 1):
                slots.append({
                    "period_id": p.id, "period": p.period,
                    "exam_date": p.exam_date,
                    "class_id": sc.id, "grade_id": sc.grade_id,
                    "pair_index": pair_index,
                })
    return slots


def _collect_hard_constraints(
    session: Session, exam: Exam, periods: list[ExamPeriod], target_grades: list[int],
):
    """
    감독 배정의 하드 제약 데이터를 사전 수집합니다.

    Args:
        target_grades: 이번 시험을 치르는 학년 ID 목록 (assign_invigilations 가
            _parse_target_grade_ids() 로 계산한 값을 그대로 전달). 1번 제약
            계산에서 "시험 보는 반"의 정규 수업을 제외하기 위해 필요합니다.

    제약 5종 (위반 시 해당 교사는 그 슬롯의 후보에서 완전 배제):
      1. 수업 병행(요구사항 6): 시험 치르지 않는 학년은 그 교시에도 수업이
         있으므로, 일반 시간표(TimetableEntry)에서 그 시간대에 수업 중인
         교사를 모두 배제합니다. 시험 교시 → 일반 교시는 1:1 매핑으로
         가정합니다 (시험 1교시 = 월~금 기준 같은 요일의 일반 1교시).
         버그 수정: "시험 치르지 않는 학년은" 이라는 설계 의도와 달리, 예전
         구현은 학년 구분 없이 (요일,교시) 가 일치하는 TimetableEntry 를 전부
         "수업 중"으로 계산했습니다. 그런데 시험 보는 학년의 반은 시험 기간
         동안 정규 수업이 열리지 않으므로(학생이 시험 응시 중), 그 반만
         가르치는 교사는 실제로는 그 시간에 비어 있는데도 "수업 중"으로 잘못
         집계되어 감독 후보에서 제외되었습니다(over-restriction → 감독 인력
         부족, 미배정 슬롯 증가). target_grades 에 속한 반의 수업은 busy 계산에서
         제외해 바로잡습니다.
      2. 담임 반 감독 금지(요구사항 2, ban_homeroom_invigilation):
         부정 행위 감독의 공정성을 위해 담임은 자기 반을 감독하지 않습니다.
      3. 담당 과목 시험 감독 금지(요구사항 2, ban_own_subject):
         시험지 보안(사전 노출 위험)을 위해 그 과목을 그 반에 가르치는
         교사는 해당 시험 시간 감독에서 제외됩니다.
      4. 감독 불가 신청(승인된 InvigilationConstraint):
         공결·출장·연수 등 특정 날짜(+교시)의 불가. 승인된 것만 반영합니다.
      5. 교사 주간 제약(TeacherConstraint, unavailable):
         매주 해당 요일·교시에 불가능한 교사는 시험 감독도 불가.

    반환값 (모두 set/dict 조회용):
      busy: {(dow, period): set(teacher_id)} — 1번 제약
      homeroom: {teacher_id: class_id} — 2번 제약
      own_subject: {(class_id, subject_id): set(teacher_id)} — 3번 제약
      unavailable_days: {teacher_id: set(date)} / unavailable_slots: {(t_id, date, period)}
      exam_subject_of: {(period_id, grade_id): subject_id} — 시험 과목 조회용
    """
    # ── 1. 수업 병행 검증용: 교시별 수업 중 교사 집합 ─────────────────────────
    # 시험 교시에 상응하는 일반 시간표의 (요일, 교시) 조합을 모아 한 번에 조회.
    # 요일: 파이썬 weekday()는 월=0 이지만 TimetableEntry.day_of_week 은 월=1
    # 이므로 +1 보정이 필요합니다.
    dow_period_pairs = {(p.exam_date.weekday() + 1, p.period) for p in periods}

    # 시험을 치르는 학년의 반 ID 집합 — 이 반들의 정규 수업은 시험 기간 동안
    # 열리지 않으므로 busy 계산에서 제외해야 합니다 (위 1번 제약 버그 수정 참조).
    exam_class_ids: set[int] = set()
    if target_grades:
        exam_class_ids = {
            row[0] for row in
            session.query(SchoolClass.id).filter(SchoolClass.grade_id.in_(target_grades)).all()
        }

    busy: dict[tuple, set] = {}
    if dow_period_pairs:
        # 기간이 여러 주에 걸쳐도 (요일,교시) 조합 수는 적으므로
        # OR 조건 묶음으로 1회 쿼리로 해결 (N+1 방지).
        from sqlalchemy import or_, tuple_
        conds = [tuple_(TimetableEntry.day_of_week, TimetableEntry.period) == pair
                 for pair in dow_period_pairs]
        query = (
            session.query(
                TimetableEntry.day_of_week, TimetableEntry.period, TimetableEntry.teacher_id
            )
            .filter(TimetableEntry.term_id == exam.term_id, or_(*conds))
        )
        if exam_class_ids:
            # 시험 보는 반의 정규 수업은 "수업 중"이 아니므로 제외 (버그 수정).
            query = query.filter(TimetableEntry.school_class_id.notin_(exam_class_ids))
        for dow, period, teacher_id in query.all():
            busy.setdefault((dow, period), set()).add(teacher_id)

    # ── 2. 담임 반 매핑 ────────────────────────────────────────────────────
    homeroom: dict[int, int] = {}
    if exam.ban_homeroom_invigilation:
        for t in session.query(Teacher).filter(Teacher.homeroom_class_id.isnot(None)):
            homeroom[t.id] = t.homeroom_class_id

    # ── 3. (반, 과목) 담당 교사 집합 ─────────────────────────────────────────
    own_subject: dict[tuple, set] = {}
    if exam.ban_own_subject:
        rows = (
            session.query(
                SubjectClassAssignment.school_class_id,
                SubjectClassAssignment.subject_id,
                SubjectClassAssignment.teacher_id,
            )
            .filter(SubjectClassAssignment.term_id == exam.term_id)
            .all()
        )
        for class_id, subject_id, teacher_id in rows:
            own_subject.setdefault((class_id, subject_id), set()).add(teacher_id)

    # ── 4. 승인된 감독 불가 신청 ────────────────────────────────────────────
    unavailable_days: dict[int, set] = {}     # 특정 날짜 전체 불가
    unavailable_slots: set = set()            # 특정 날짜·교시 불가
    rows = session.query(InvigilationConstraint).filter_by(
        exam_id=exam.id, status="approved"
    ).all()
    for c in rows:
        if c.period is None:
            unavailable_days.setdefault(c.teacher_id, set()).add(c.exam_date)
        else:
            unavailable_slots.add((c.teacher_id, c.exam_date, c.period))

    # ── 5. 교사 주간 제약(unavailable) ──────────────────────────────────────
    weekly_unavailable: set = set()   # (teacher_id, dow, period)
    rows = session.query(TeacherConstraint).filter_by(constraint_type="unavailable").all()
    for c in rows:
        weekly_unavailable.add((c.teacher_id, c.day_of_week, c.period))

    # ── 시험 교시별 (학년별) 시험 과목 조회 테이블 ────────────────────────────
    exam_subject_of: dict[tuple, int] = {}
    for e in session.query(ExamEntry).filter_by(exam_id=exam.id).all():
        exam_subject_of[(e.period_id, e.grade_id)] = e.subject_id

    return {
        "busy": busy, "homeroom": homeroom, "own_subject": own_subject,
        "unavailable_days": unavailable_days,
        "unavailable_slots": unavailable_slots,
        "weekly_unavailable": weekly_unavailable,
        "exam_subject_of": exam_subject_of,
    }


def _slot_is_allowed(teacher_id: int, slot: dict, hard: dict) -> bool:
    """
    하드 제약 5종을 통과하는지 검사.

    감독 슬롯마다 후보 교사 전원에 대해 호출되므로, 모든 검사는
    사전 수집된 set/dict 조회로 O(1)에 끝나야 합니다 (generator.py 방식).
    """
    date = slot["exam_date"]
    period = slot["period"]
    class_id = slot["class_id"]
    grade_id = slot["grade_id"]
    dow = date.weekday() + 1   # TimetableEntry.day_of_week 은 월=1

    # 1. 그 시간대에 수업 중인 교사는 감독 불가 (요구사항 6)
    if teacher_id in hard["busy"].get((dow, period), set()):
        return False
    # 2. 담임은 자기 반 감독 불가 (요구사항 2)
    if hard["homeroom"].get(teacher_id) == class_id:
        return False
    # 3. 시험 과목 담당 교사는 그 시험 시간 감독 불가 (요구사항 2)
    subject_id = hard["exam_subject_of"].get((slot["period_id"], grade_id))
    if subject_id is not None:
        if teacher_id in hard["own_subject"].get((class_id, subject_id), set()):
            return False
    # 4. 승인된 감독 불가 신청 (특정 날짜 전체 / 특정 교시)
    if date in hard["unavailable_days"].get(teacher_id, set()):
        return False
    if (teacher_id, date, period) in hard["unavailable_slots"]:
        return False
    # 5. 매주 해당 요일·교시 불가 제약
    if (teacher_id, dow, period) in hard["weekly_unavailable"]:
        return False
    return True


def _try_assign(slots: list[dict], teacher_ids: list[int], hard: dict) -> dict | None:
    """
    감독 배정 1회 시도 (랜덤 재시작의 단위).

    슬롯을 날짜·교시 순으로 순회하며, 각 슬롯에 대해 하드 제약을 통과한
    후보 중 소프트 점수가 가장 높은 교사를 배정합니다.

    소프트 점수 (높을수록 우선 배정):
        score = W_TOTAL_COUNT × (지금까지 배정된 총 감독 수)
              + W_SAME_DAY    × (같은 날 배정된 감독 수)
              + W_ADJACENT    × (직전 교시 감독 여부: 1 or 0)
    - W_TOTAL_COUNT(-10)가 가중치가 가장 크므로, 결과적으로 감독 횟수가
      전 교사에게 근등하게 분배됩니다 (요구사항 3).
    - 동점 후보가 여럿이면 random.choice 로 선택해 시도마다 다른 결과를
      만듭니다 (랜덤 재시작의 의미).

    Returns:
        배정 결과 {slot_key: teacher_id or None}. 슬롯 key 는
        (period_id, class_id, pair_index) 튜플 — DB 유니크 제약과 동일한 단위.
    """
    assignment: dict = {}
    total_count: dict[int, int] = {}       # 교사별 누적 감독 횟수
    same_day: dict[tuple, int] = {}        # (교사, 날짜)별 감독 횟수
    last_period_date: dict[tuple, int] = {}  # (교사, 날짜) → 직전 감독 교시

    # 슬롯 순서: 교시(날짜·교시) 순은 유지하되, 같은 교시 내 반 순서는 섞어
    # 특정 반에 특정 교사가 계속 걸리는 편향을 방지합니다.
    slots = sorted(slots, key=lambda s: (s["exam_date"], s["period"]))

    # 후보 목록도 시도마다 섞어 시작 점수의 동점 우선순위를 다양화
    shuffled_teachers = list(teacher_ids)
    random.shuffle(shuffled_teachers)

    # 같은 교시 단위로 묶어 처리 — 교시 내 순서 무작위화 + 동시간 중복 방지
    by_period: dict[tuple, list[dict]] = {}
    for s in slots:
        by_period.setdefault((s["exam_date"], s["period"]), []).append(s)

    for (date, period) in sorted(by_period.keys()):
        group = by_period[(date, period)]
        random.shuffle(group)
        assigned_this_period: set[int] = set()
        for slot in group:
            key = (slot["period_id"], slot["class_id"], slot["pair_index"])
            best: tuple[int, list[int]] | None = None
            for tid in shuffled_teachers:
                if tid in assigned_this_period:
                    continue  # 같은 교시에 한 교사가 두 반을 동시 감독 불가
                if not _slot_is_allowed(tid, slot, hard):
                    continue
                adjacent = 1 if last_period_date.get((tid, date)) == period - 1 else 0
                score = (
                    W_TOTAL_COUNT * total_count.get(tid, 0)
                    + W_SAME_DAY * same_day.get((tid, date), 0)
                    + W_ADJACENT * adjacent
                )
                if best is None or score > best[0]:
                    best = (score, [tid])
                elif best is not None and score == best[0]:
                    best[1].append(tid)
            if best is not None:
                chosen = random.choice(best[1])
                assignment[key] = chosen
                assigned_this_period.add(chosen)
                total_count[chosen] = total_count.get(chosen, 0) + 1
                same_day[(chosen, date)] = same_day.get((chosen, date), 0) + 1
                last_period_date[(chosen, date)] = period
            else:
                # 후보 부족 — 미배정 슬롯으로 남겨 수동 배정 여지를 남김
                assignment[key] = None
    return assignment


def _solution_quality(assignment: dict, teacher_ids: list[int]) -> tuple[int, float]:
    """
    배정 결과의 품질 점수 — 낮을수록 좋은 결과.

    우선순위:
      1. 미배정 슬롯 수 (0이 가장 좋음 — 모든 반에 감독이 배정되어야 함)
      2. 감독 횟수의 분산 (작을수록 공평 — 요구사항 3)
         분산 대신 "제곱합"을 쓰는 이유: 교사 수가 고정이면 두 값의
         대소 관계가 같아 더 계산이 단순하기 때문입니다.

    여러 랜덤 시도의 결과를 이 함수로 비교해 최선을 채택합니다.
    """
    unassigned = sum(1 for v in assignment.values() if v is None)
    counts = {tid: 0 for tid in teacher_ids}
    for v in assignment.values():
        if v is not None:
            counts[v] = counts.get(v, 0) + 1
    sq = sum(c * c for c in counts.values())
    return (unassigned, float(sq))


def assign_invigilations(session: Session, exam_id: int) -> tuple[bool, str]:
    """
    시험 감독 자동 배정 (요구사항 2·3·5·6 종합).

    동작 순서:
      1. 시험 대상 학년의 반들을 대상으로 감독 슬롯을 생성합니다.
         (학생 20명 이상 반은 2인 1조 — _build_slots 참조)
      2. 하드 제약 데이터를 사전 수집합니다 (_collect_hard_constraints).
      3. 랜덤 재시작(MAX_ATTEMPTS회)으로 배정을 시도하고,
         "미배정 수 → 감독 횟수 분산" 기준으로 최선의 결과를 채택합니다.
      4. 기존 배정을 삭제하고 최선 결과를 저장합니다.
         미배정 슬롯도 teacher_id=NULL 로 저장해, 어떤 반·교시에 감독이
         비었는지 관리자가 확인하고 수동 배정할 수 있게 합니다.

    Returns:
        모든 슬롯에 배정 성공 → (True, 요약 메시지)
        일부 미배정           → (False, 미배정 안내 메시지)
        슬롯/후보 부족 등      → (False, 사유)
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return False, "시험을 찾을 수 없습니다."

    periods = (
        session.query(ExamPeriod)
        .filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )
    if not periods:
        return False, "시험 교시(ExamPeriod)가 없습니다. 시험 기간을 먼저 설정하세요."

    target_grades = _parse_target_grade_ids(exam)
    if not target_grades:
        target_grades = [g.id for g in session.query(Grade).order_by(Grade.grade_number).all()]
    if not target_grades:
        return False, "학년 정보가 없습니다."

    classes = (
        session.query(SchoolClass)
        .filter(SchoolClass.grade_id.in_(target_grades))
        .order_by(SchoolClass.grade_id, SchoolClass.class_number)
        .all()
    )
    if not classes:
        return False, "시험 대상 학년에 반이 없습니다."

    teachers = session.query(Teacher).order_by(Teacher.id).all()
    if not teachers:
        return False, "교사 정보가 없습니다."
    teacher_ids = [t.id for t in teachers]

    slots = _build_slots(session, exam, periods, classes)
    if not slots:
        return False, "감독 슬롯이 없습니다."

    hard = _collect_hard_constraints(session, exam, periods, target_grades)

    # ── 버그 수정: 담당 과목 감독 금지 제약의 전제 데이터 부재를 눈에 띄게 함 ──
    # _slot_is_allowed() 의 3번 검사(담당 과목 시험 감독 금지)는
    # hard["exam_subject_of"].get((period_id, grade_id)) 가 None 이면(=해당
    # 시험 시간표(ExamEntry)가 아직 생성되지 않음) 조용히 검사를 건너뛰고
    # 통과시킵니다. generate_exam_entries() 를 먼저 호출하지 않고
    # assign_invigilations() 를 실행하면, "자기 과목 자기 반 감독 금지"라는
    # 부정행위 방지 하드 제약을 검증할 데이터가 없어 사실상 적용되지 않습니다.
    #
    # 시험 시간표(ExamEntry) 생성과 감독 배정은 이 코드베이스에서 서로 독립된
    # 선택 기능으로 설계되어 있어(시험 시간표 없이 감독만 배정하는 것도 정상
    # 사용 흐름 — test_invigilation_grid_assign_and_summary 등에서 검증),
    # "시험 시간표 없음"을 무조건 에러로 막으면 이 정상 흐름이 깨집니다.
    # 그래서 동작은 바꾸지 않고(하위 호환 유지), 관리자가 이 상황을 알아챌 수
    # 있도록 경고 로그만 남깁니다 — "조용히" 무력화되는 문제만 해소합니다.
    if exam.ban_own_subject and not hard["exam_subject_of"]:
        _logger.warning(
            "Exam(id=%s) 의 ban_own_subject=True 이지만 ExamEntry(시험 시간표)가 "
            "아직 생성되지 않아 '담당 과목 감독 금지' 제약을 검증할 수 없습니다. "
            "이번 배정에서는 이 제약이 적용되지 않습니다. 이 제약을 실제로 "
            "적용하려면 generate_exam_entries() 를 먼저 실행하세요.",
            exam.id,
        )

    # 랜덤 재시작 — 각 시도는 동점 후보/슬롯 순서를 다르게 하여
    # 다른 배정 결과를 만들고, 그중 품질이 가장 좋은 것을 채택합니다.
    best: tuple | None = None
    for _ in range(MAX_ATTEMPTS):
        result = _try_assign(slots, teacher_ids, hard)
        quality = _solution_quality(result, teacher_ids)
        if best is None or quality < best[0]:
            best = (quality, result)
        if quality[0] == 0 and quality[1] == 0:
            break  # 완벽한 배정(전 슬롯 배정 + 분산 0)이면 더 시도할 필요 없음

    quality, result = best
    unassigned, sq = quality

    # 기존 배정 전체 삭제 후 최선 결과 저장 ("재생성" 개념)
    session.query(InvigilationAssignment).filter_by(exam_id=exam.id).delete()
    for slot in slots:
        key = (slot["period_id"], slot["class_id"], slot["pair_index"])
        session.add(InvigilationAssignment(
            exam_id=exam.id, period_id=slot["period_id"],
            school_class_id=slot["class_id"],
            teacher_id=result.get(key),          # 미배정이면 None
            pair_index=slot["pair_index"],
        ))
    session.commit()

    total = len(slots)
    assigned = total - unassigned
    # 감독 횟수 통계 — 공평성(요구사항 3) 확인용 안내
    counts: dict[int, int] = {}
    for v in result.values():
        if v is not None:
            counts[v] = counts.get(v, 0) + 1
    if counts:
        lo, hi = min(counts.values()), max(counts.values())
        fairness = f"교사별 감독 {lo}~{hi}회 (총 {total}슬롯)"
    else:
        fairness = f"총 {total}슬롯"

    if unassigned == 0:
        return True, f"감독 자동 배정 완료 — {fairness}"
    return False, (
        f"감독 자동 배정 완료(부분): {assigned}/{total} 슬롯 배정, "
        f"{unassigned}슬롯 미배정(후보 부족 — 감독 불가 승인 상태나 교사 수 확인). "
        f"미배정 슬롯은 감독표에서 수동 배정하세요. {fairness}"
    )