"""
시험 시간표 + 시험 감독 시간표 API (2026-09-19 신규)

엔드포인트 구성 (권한 규칙은 기존 프로젝트 관례를 따름):
  읽기(조회)      — 로그인한 모든 사용자(get_current_user).
                    단, 일반 교사(role="teacher")는 게시(published)된
                    시험만 조회 가능 — 작성 중인 시험표의 조기 노출 방지.
  쓰기(생성/수정) — 일과계(require_scheduler).
                    감독 불가 신청은 예외적으로 교사 본인도 생성 가능
                    (본인 것만). 승인은 일과계·교감·교무부장
                    (require_admin_or_vice_principal).

라우터를 /timetable 과 분리한 이유:
  시험은 학기 내에서도 1회성 이벤트이고 수업 시간표(TimetableEntry)와
  데이터 모델이 완전히 다르며(날짜 기반 vs 요일 반복), 엔드포인트 수가
  많아 timetable.py(2300줄)에 합치면 가독성이 급격히 나빠집니다.
"""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.models import (
    User, Teacher, Grade, SchoolClass, Subject, Exam, ExamPeriod, ExamEntry,
    InvigilationAssignment, InvigilationConstraint,
)
from shared.schemas import (
    ExamCreate, ExamOut, ExamUpdate, ExamPeriodOut,
    ExamEntryOut, ExamEntryUpdate,
    InvigilationAssignmentOut, InvigilationUpdate,
    InvigilationConstraintCreate, InvigilationConstraintOut,
    InvigilationConstraintReview,
)
from server.deps import get_db, get_current_user, require_scheduler, require_admin_or_vice_principal
from core.exam_scheduler import (
    generate_exam_entries, assign_invigilations, rebuild_exam_periods,
)
# 알림 헬퍼는 timetable.py 에 이미 구현된 것을 재사용합니다 (중복 방지).
# _notify_users_async: {user_id: 메시지} 형태로 여러 사용자에게
# 각기 다른 메시지를 일괄 발송합니다.
from server.api.timetable import _notify_users_async

router = APIRouter(prefix="/exams", tags=["시험 관리"])


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _get_exam_or_404(db: Session, exam_id: int) -> Exam:
    """시험 조회 + 없으면 404. 모든 /exams/{id} 경로의 공통 전처리."""
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(404, "시험을 찾을 수 없습니다.")
    return exam


def _check_teacher_visibility(user: User, exam: Exam) -> None:
    """
    일반 교사는 draft 상태의 시험에 접근할 수 없습니다.

    관리자(일과계/교감/교무부장)는 작성 중에도 열람해야 검수가 가능하므로
    제한하지 않고, 교사(role="teacher")만 published 여부를 검사합니다.
    (게시 전 시험표/감독표가 미완성 상태로 돌아다니는 혼란 방지)
    """
    if user.role == "teacher" and exam.status != "published":
        raise HTTPException(403, "아직 게시되지 않은 시험입니다.")


def _rebuild_periods(db: Session, exam: Exam) -> int:
    """
    시험 기간(start_date~end_date)에 따라 ExamPeriod 를 재생성합니다.

    실제 구현은 core.exam_scheduler.rebuild_exam_periods 에 있습니다 —
    관리자 앱(admin_app)도 같은 교시 시각 계산 규칙을 사용해야 하므로
    core 에 단일 구현을 두고 API/앱 양쪽이 재사용합니다.

    호출 시점:
      - POST /exams (생성 직후)
      - PATCH /exams/{id} 로 기간·교시 운영 규칙이 바뀐 경우

    기존 periods 를 먼저 삭제합니다. cascade 로 이 periods 에 딸린
    시험 칸(ExamEntry)과 감독 배정(InvigilationAssignment)도 함께
    삭제되므로, 게시(published)된 시험은 PATCH 에서 거부합니다.
    """
    return rebuild_exam_periods(db, exam)


def _entry_out_with_names(db: Session, entry: ExamEntry) -> ExamEntryOut:
    """
    ExamEntry → ExamEntryOut 변환 + 과목명 주입.

    그리드에서 색상·약어 표시에 과목 정보가 필요하므로 응답에 포함합니다.
    (기존 TimetableEntryOut 의 subject_name/short/color 주입 패턴과 동일)
    """
    out = ExamEntryOut.model_validate(entry)
    subject = db.get(Subject, entry.subject_id)
    if subject is not None:
        out.subject_name = subject.name
        out.subject_short = subject.short_name
        out.subject_color = subject.color_hex
    return out


def _invigilation_out(db: Session, a: InvigilationAssignment) -> InvigilationAssignmentOut:
    """
    InvigilationAssignment → Out 변환 + 조인 정보 주입.

    감독표 UI(반×교시 그리드)와 교사 앱 "내 감독" 화면에서 바로 쓸 수
    있도록 교시 날짜·시각, 반 이름, 교사 이름, 그 교시의 시험 과목명을
    응답에 포함합니다. (N+1 을 막으려면 조회 측에서 사전 매핑 사용 —
    목록 엔드포인트 참조)
    """
    out = InvigilationAssignmentOut.model_validate(a)
    period = db.get(ExamPeriod, a.period_id)
    if period is not None:
        out.exam_date = period.exam_date
        out.period_number = period.period
        out.start_time = period.start_time
        out.end_time = period.end_time
    sc = db.get(SchoolClass, a.school_class_id)
    if sc is not None:
        out.class_name = sc.display_name
        out.class_grade_id = sc.grade_id
        # 그 교시·학년의 시험 과목 — 감독표에서 "국어 시험" 문맥 표시용
        entry = db.query(ExamEntry).filter_by(
            exam_id=a.exam_id, period_id=a.period_id, grade_id=sc.grade_id
        ).first()
        if entry is not None:
            subject = db.get(Subject, entry.subject_id)
            out.subject_name = subject.name if subject else None
    if a.teacher_id is not None:
        t = db.get(Teacher, a.teacher_id)
        out.teacher_name = t.name if t else None
    return out


def _validate_date_range(exam: Exam) -> None:
    """기간 유효성 검사 — end < start 인 시험은 교시 생성이 불가능."""
    if exam.end_date < exam.start_date:
        raise HTTPException(400, "종료일이 시작일보다 빠를 수 없습니다.")


# ── 시험 CRUD ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ExamOut])
def list_exams(
    include_draft: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    시험 목록. 교사는 게시된 시험만, 관리자는 전체(작성 중 포함) 조회.
    정렬: 최근 생성 순 — 관리자 화면에서 마지막에 만든 시험을 먼저 보여주기 위함.

    include_draft=True (교사 전용 파라미터):
      교사 앱의 "감독 불가 신청" 폼에서 사용합니다. 감독 불가 신청은
      현실적인 업무 순서상 시험 게시 "전"(초안 상태)에 제출해야 하므로
      신청 폼에서는 초안 시험도 선택할 수 있어야 합니다.
      (게시 전 시험표/감독표 내용을 보는 것과는 별개로, 신청 대상
       선택 목록에만 노출하는 것으로 정보 노출을 최소화합니다.)
    """
    q = db.query(Exam).order_by(Exam.id.desc())
    if user.role == "teacher" and not include_draft:
        q = q.filter_by(status="published")
    return q.all()


@router.post("", response_model=ExamOut, status_code=201)
def create_exam(
    body: ExamCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    시험 생성 + 기간에 따른 교시(ExamPeriod) 자동 생성.

    target_grade_ids 는 리스트로 받아 JSON 문자열로 저장합니다.
    (SQLite 텍스트 컬럼에 배열을 저장하는 기존 관례 — approval_history 참조)
    """
    if body.end_date < body.start_date:
        raise HTTPException(400, "종료일이 시작일보다 빠를 수 없습니다.")

    exam = Exam(
        term_id=body.term_id,
        name=body.name,
        exam_type=body.exam_type,
        school_level=body.school_level,
        target_grade_ids=json.dumps(body.target_grade_ids),
        start_date=body.start_date,
        end_date=body.end_date,
        first_period_start=body.first_period_start,
        periods_per_day=body.periods_per_day,
        break_minutes=body.break_minutes,
        prep_minutes=body.prep_minutes,
        exam_minutes=body.exam_minutes,
        max_subjects_per_day=body.max_subjects_per_day,
        ban_homeroom_invigilation=body.ban_homeroom_invigilation,
        ban_own_subject=body.ban_own_subject,
        status="draft",
    )
    db.add(exam)
    db.flush()                       # exam.id 확보 후 교시 생성
    _rebuild_periods(db, exam)
    db.commit()
    db.refresh(exam)
    return exam


@router.get("/{exam_id}", response_model=ExamOut)
def get_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """시험 단건 조회 (교사는 게시된 시험만)."""
    exam = _get_exam_or_404(db, exam_id)
    _check_teacher_visibility(user, exam)
    return exam


@router.patch("/{exam_id}", response_model=ExamOut)
def update_exam(
    exam_id: int,
    body: ExamUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    시험 정보 수정.

    기간·시각·교시 수가 바뀌면 교시(ExamPeriod)를 재생성합니다.
    이때 기존 시험 칸·감독 배정이 함께 삭제되는 파괴적 변경이므로
    게시된(published) 시험은 수정을 거부합니다 — 확정된 시험표를
    조용히 리셋하는 사고를 막기 위함입니다.
    """
    exam = _get_exam_or_404(db, exam_id)
    if exam.status == "published":
        raise HTTPException(400, "게시된 시험은 수정할 수 없습니다.")

    # 부분 수정 — None 이 아닌 필드만 반영 (PATCH 관례)
    changes = body.model_dump(exclude_unset=True)
    affects_periods = any(
        k in changes for k in (
            "start_date", "end_date", "first_period_start",
            "periods_per_day", "break_minutes", "exam_minutes",
        )
    )
    if "target_grade_ids" in changes:
        exam.target_grade_ids = json.dumps(changes.pop("target_grade_ids"))
    for key, value in changes.items():
        setattr(exam, key, value)
    _validate_date_range(exam)
    if affects_periods:
        _rebuild_periods(db, exam)
    db.commit()
    db.refresh(exam)
    return exam


@router.delete("/{exam_id}")
def delete_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """시험 삭제. cascade 로 교시·시험 칸·감독 배정·감독 불가 신청이 함께 삭제됩니다."""
    exam = _get_exam_or_404(db, exam_id)
    db.delete(exam)
    db.commit()
    return {"ok": True}


@router.get("/{exam_id}/periods", response_model=list[ExamPeriodOut])
def list_exam_periods(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """시험 교시 목록(날짜·교시·시각) — 그리드 헤더 표시용."""
    exam = _get_exam_or_404(db, exam_id)
    _check_teacher_visibility(user, exam)
    return (
        db.query(ExamPeriod).filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )


# ── 시험 시간표 (과목 배치) ──────────────────────────────────────────────────

@router.get("/{exam_id}/entries", response_model=list[ExamEntryOut])
def list_exam_entries(
    exam_id: int,
    grade_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    시험 시간표 조회. grade_id 지정 시 해당 학년만.

    응답에 과목명·약어·색상을 주입해 UI 에서 바로 렌더링할 수 있게 합니다.
    (과목 수는 시험 칸 수보다 훨씬 적으므로 매 칸마다 db.get 하는
    오버헤드가 크지 않고, SQLAlchemy 세션은 동일 객체를 재사용합니다.)
    """
    exam = _get_exam_or_404(db, exam_id)
    _check_teacher_visibility(user, exam)
    q = db.query(ExamEntry).filter_by(exam_id=exam.id)
    if grade_id is not None:
        q = q.filter_by(grade_id=grade_id)
    entries = q.order_by(ExamEntry.period_id, ExamEntry.grade_id).all()
    return [_entry_out_with_names(db, e) for e in entries]


@router.put("/entries/{entry_id}", response_model=ExamEntryOut)
def update_exam_entry(
    entry_id: int,
    body: ExamEntryUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    시험 시간표 칸 수동 편집 (관리자가 그리드에서 더블클릭 시 호출).

    is_manual=True 로 표시해, 이후 자동 배치 재실행 시 이 칸이
    수동 작업이었다는 사실을 안내할 수 있게 합니다.
    게시된 시험은 과목이 바뀌면 시험지·안내가 어긋나므로 수정 거부.
    """
    entry = db.get(ExamEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "시험 시간표 칸을 찾을 수 없습니다.")
    exam = db.get(Exam, entry.exam_id)
    if exam is not None and exam.status == "published":
        raise HTTPException(400, "게시된 시험의 시험표는 수정할 수 없습니다.")
    if db.get(Subject, body.subject_id) is None:
        raise HTTPException(404, "과목을 찾을 수 없습니다.")
    entry.subject_id = body.subject_id
    entry.is_manual = True
    db.commit()
    db.refresh(entry)
    return _entry_out_with_names(db, entry)


@router.post("/{exam_id}/generate-entries")
def auto_generate_entries(
    exam_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    시험 시간표 자동 배치 실행 (core.exam_scheduler.generate_exam_entries).

    규칙: 과목당 1회, 하루 과목 수 상한, 학년별 독립 배치.
    결과 메시지에 수동 편집 칸 덮어씀 여부를 포함합니다.
    """
    exam = _get_exam_or_404(db, exam_id)
    if exam.status == "published":
        raise HTTPException(400, "게시된 시험은 재배치할 수 없습니다.")
    ok, msg = generate_exam_entries(db, exam_id)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


# ── 감독 시간표 ──────────────────────────────────────────────────────────────

@router.get("/my/invigilations", response_model=list[InvigilationAssignmentOut])
def list_my_invigilations(
    exam_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    현재 로그인 교사의 감독 목록 (교사 앱 "내 감독" 페이지용).

    exam_id 미지정 시 게시된 모든 시험에서 본인 감독을 조회합니다.
    teacher_id 가 없는 계정(관리자 전용 계정)은 빈 목록을 반환합니다.

    주의: 이 라우트는 "/{exam_id}/invigilations" 보다 먼저 등록되어야
    합니다. FastAPI 는 등록 순서대로 경로를 매칭하므로, "/my" 가
    "{exam_id}" 로 파싱되는 것을 방지하기 위함입니다.
    """
    if user.teacher_id is None:
        return []
    q = (
        db.query(InvigilationAssignment)
        .filter(InvigilationAssignment.teacher_id == user.teacher_id)
        .join(Exam, Exam.id == InvigilationAssignment.exam_id)
        .join(ExamPeriod, ExamPeriod.id == InvigilationAssignment.period_id)
        .filter(Exam.status == "published")
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
    )
    if exam_id is not None:
        q = q.filter(InvigilationAssignment.exam_id == exam_id)
    return [_invigilation_out(db, a) for a in q.all()]


@router.get("/{exam_id}/invigilations", response_model=list[InvigilationAssignmentOut])
def list_invigilations(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """감독표 전체 조회(관리자용) — 교시 날짜순 정렬 + 조인 정보 주입."""
    exam = _get_exam_or_404(db, exam_id)
    _check_teacher_visibility(user, exam)
    rows = (
        db.query(InvigilationAssignment).filter_by(exam_id=exam.id)
        .order_by(InvigilationAssignment.period_id, InvigilationAssignment.school_class_id)
        .all()
    )
    return [_invigilation_out(db, a) for a in rows]


@router.post("/{exam_id}/assign-invigilations")
def auto_assign_invigilations(
    exam_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    감독 자동 배정 실행 (core.exam_scheduler.assign_invigilations).

    하드 제약(수업 중 배제·담임 반 금지·담당 과목 금지·감독 불가·주간 제약)과
    감독 횟수 균등 분배(소프트 점수)를 적용합니다.
    후보 부족 시 미배정 슬롯을 남기고 400 이 아니라 결과 메시지로 안내합니다.
    """
    exam = _get_exam_or_404(db, exam_id)
    ok, msg = assign_invigilations(db, exam_id)
    # 부분 성공(ok=False)이어도 배정 결과는 저장되었으므로 200 + 안내 반환.
    # 400 을 반환하지 않는 이유: 관리자가 미배정 슬롯만 수동으로 채우면 되는데,
    # 오류로 표시하면 "배정이 아예 안 된 것"으로 오해하게 됨.
    return {"ok": ok, "message": msg}


@router.put("/invigilations/{assignment_id}", response_model=InvigilationAssignmentOut)
def update_invigilation(
    assignment_id: int,
    body: InvigilationUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    감독 배정 수동 변경 (미배정 슬롯 채우기 / 교체).

    게시 후에도 허용하는 이유: 시험 당일 질병·출장 등으로 감독 교체는
    게시 이후에 발생하는 정상 업무이기 때문입니다. (시험표 과목 수정과 다름)
    같은 교시에 이미 다른 반을 감독 중인 교사는 배정 거부(409).
    """
    a = db.get(InvigilationAssignment, assignment_id)
    if a is None:
        raise HTTPException(404, "감독 배정을 찾을 수 없습니다.")

    new_teacher_id = body.teacher_id
    if new_teacher_id is not None:
        if db.get(Teacher, new_teacher_id) is None:
            raise HTTPException(404, "교사를 찾을 수 없습니다.")
        # 동시간 중복 검사 — 한 교사가 같은 교시에 두 반을 감독할 수 없음
        conflict = (
            db.query(InvigilationAssignment)
            .filter(
                InvigilationAssignment.period_id == a.period_id,
                InvigilationAssignment.teacher_id == new_teacher_id,
                InvigilationAssignment.id != a.id,
            )
            .first()
        )
        if conflict is not None:
            raise HTTPException(409, "이 교사는 같은 교시에 이미 다른 반 감독이 배정되어 있습니다.")
    a.teacher_id = new_teacher_id
    db.commit()
    db.refresh(a)
    return _invigilation_out(db, a)


# ── 감독 불가 신청 ──────────────────────────────────────────────────────────

@router.get("/{exam_id}/constraints", response_model=list[InvigilationConstraintOut])
def list_constraints(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    감독 불가 신청 목록.

    관리자(일과계·교감·교무부장)는 전체 목록을, 일반 교사는 본인 신청만
    조회합니다 — 다른 교사의 사유(공결·병가 등 개인 정보)가 노출되지 않도록.
    draft 시험에서도 조회 허용(신청 화면 자체가 게시 전 동작 — create 참조).
    """
    exam = _get_exam_or_404(db, exam_id)
    q = db.query(InvigilationConstraint).filter_by(exam_id=exam.id)
    if user.role == "teacher":
        q = q.filter_by(teacher_id=user.teacher_id)
    rows = q.order_by(InvigilationConstraint.requested_at.desc()).all()
    result = []
    for c in rows:
        out = InvigilationConstraintOut.model_validate(c)
        t = db.get(Teacher, c.teacher_id)
        out.teacher_name = t.name if t else None
        result.append(out)
    return result


@router.post("/{exam_id}/constraints", response_model=InvigilationConstraintOut, status_code=201)
def create_constraint(
    exam_id: int,
    body: InvigilationConstraintCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    감독 불가 신청 제출 (교사 본인).

    - 신청 즉시 반영되지 않고 pending 상태로 관리자 승인을 기다립니다.
      (미승인 상태로 감독이 빠지는 사고 방지 — 모델 docstring 참조)
    - exam_id 는 경로에서, teacher_id 는 로그인 사용자에서 가져와
      다른 교사 명의로 신청하는 것을 원천 차단합니다.
    - exam_date 가 시험 기간 밖이면 400 — 오타로 엉뚱한 날짜 신청 방지.
    - teacher_id 가 연결되지 않은 계정(관리자 전용 계정)은 403.

    주의 — draft 시험에도 신청을 허용합니다(_check_teacher_visibility 미적용):
      감독 불가 신청은 "자동 배정 → 게시" 보다 먼저 들어와야 합니다.
      (실무 순서: 시험 등록 → 교사 불가 신청 접수 → 승인 → 자동 배정 → 게시)
      신청 화면에는 시험 날짜·교시만 노출되고 시험표·감독표는 여전히
      게시 전까지 교사가 조회할 수 없으므로 조기 노출 문제가 없습니다.
    """
    exam = _get_exam_or_404(db, exam_id)
    if user.teacher_id is None:
        raise HTTPException(403, "교사 계정이 연결된 사용자만 신청할 수 있습니다.")

    if not (exam.start_date <= body.exam_date <= exam.end_date):
        raise HTTPException(400, "신청 날짜가 시험 기간 범위 밖입니다.")
    if body.period is not None and body.period > exam.periods_per_day:
        raise HTTPException(400, f"교시는 1~{exam.periods_per_day} 사이여야 합니다.")

    # 중복 신청 방지 — 같은 날짜·교시에 이미 신청/승인된 경우 409
    duplicate = (
        db.query(InvigilationConstraint)
        .filter_by(
            exam_id=exam.id, teacher_id=user.teacher_id,
            exam_date=body.exam_date, period=body.period,
        )
        .filter(InvigilationConstraint.status.in_(("pending", "approved")))
        .first()
    )
    if duplicate is not None:
        raise HTTPException(409, "같은 날짜·교시에 이미 신청된 감독 불가가 있습니다.")

    c = InvigilationConstraint(
        exam_id=exam.id,
        teacher_id=user.teacher_id,
        exam_date=body.exam_date,
        period=body.period,
        reason=body.reason,
        status="pending",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    out = InvigilationConstraintOut.model_validate(c)
    out.teacher_name = user.teacher.name if user.teacher else None
    return out


@router.patch("/constraints/{constraint_id}", response_model=InvigilationConstraintOut)
def review_constraint(
    constraint_id: int,
    body: InvigilationConstraintReview,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_or_vice_principal),
):
    """
    감독 불가 신청 승인/거절 (일과계·교감·교무부장).

    approved 로 승인하면 다음 감독 자동 배정 실행부터 하드 제약으로
    반영됩니다. reviewed_by 는 요청값을 무시하고 로그인 사용자명으로
    기록합니다 (actor impersonation 방지 — ChangeRequestReview 와 동일 정책).
    """
    c = db.get(InvigilationConstraint, constraint_id)
    if c is None:
        raise HTTPException(404, "감독 불가 신청을 찾을 수 없습니다.")
    if c.status != "pending":
        raise HTTPException(400, "이미 처리된 신청입니다.")
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "action 은 approve 또는 reject 여야 합니다.")

    c.status = "approved" if body.action == "approve" else "rejected"
    c.reviewed_by = user.username
    c.reviewed_at = datetime.now()
    db.commit()
    db.refresh(c)
    out = InvigilationConstraintOut.model_validate(c)
    t = db.get(Teacher, c.teacher_id)
    out.teacher_name = t.name if t else None
    return out


# ── 게시 ─────────────────────────────────────────────────────────────────────

@router.post("/{exam_id}/publish")
def publish_exam(
    exam_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    시험 게시: draft → published.

    게시가 하는 일:
      1. 교사 앱에서 시험표·감독표가 조회 가능해집니다.
      2. 전체 사용자에게 exam_published 알림을 보냅니다.
      3. 감독이 배정된 각 교사에게 본인 감독 안내(invigilation_assigned)
         알림을 개별 메시지로 보냅니다.

    알림은 BackgroundTasks 로 응답 후 처리합니다 — 알림 DB 저장/전송
    지연이 게시 응답을 늦추지 않도록 하기 위함입니다 (기존 승인 라인과 동일).
    """
    exam = _get_exam_or_404(db, exam_id)
    if exam.status == "published":
        raise HTTPException(400, "이미 게시된 시험입니다.")

    exam.status = "published"
    db.commit()

    # ── 알림 1: 전체 사용자에게 시험 게시 공지 (exam_published) ───────────────
    all_users = db.query(User).filter(User.is_active == True).all()  # noqa: E712
    general_messages = {
        u.id: f"[시험 게시] {exam.name} 시험표·감독표가 게시되었습니다. 시험 관리에서 확인하세요."
        for u in all_users
    }
    background_tasks.add_task(_notify_users_async, general_messages, "exam_published", None)

    # ── 알림 2: 감독 배정 교사별 개별 안내 (invigilation_assigned) ────────────
    # 각 교사에게 본인 감독 목록을 날짜·교시·반·과목까지 포함해 알려줍니다.
    assignments = (
        db.query(InvigilationAssignment)
        .filter_by(exam_id=exam.id)
        .filter(InvigilationAssignment.teacher_id.isnot(None))
        .all()
    )
    # 과목·날짜 표기를 위해 관련 엔티티 사전 로드 (N+1 방지)
    periods = {p.id: p for p in db.query(ExamPeriod).filter_by(exam_id=exam.id)}
    classes = {c.id: c for c in db.query(SchoolClass)}
    entries = db.query(ExamEntry).filter_by(exam_id=exam.id).all()
    subject_of = {(e.period_id, e.grade_id): e.subject_id for e in entries}
    subjects = {s.id: s for s in db.query(Subject)}

    # 교사별 메시지 누적 — 한 교사가 여러 감독을 맡으면 한 알림에 모두 표기
    duty_messages: dict[int, str] = {}
    for a in assignments:
        teacher_user = db.query(User).filter_by(teacher_id=a.teacher_id, is_active=True).first()
        if teacher_user is None:
            continue  # 앱 계정이 없는 교사는 알림을 받을 수 없음 (DB 조회로 확인)
        p = periods.get(a.period_id)
        c = classes.get(a.school_class_id)
        if p is None or c is None:
            continue
        subject = subjects.get(subject_of.get((a.period_id, c.grade_id)))
        subject_text = f" ({subject.name})" if subject else ""
        line = (
            f"{p.exam_date.strftime('%m/%d')} {p.period}교시 {c.display_name} 감독{subject_text} "
            f"{p.start_time.strftime('%H:%M')}~{p.end_time.strftime('%H:%M')}"
        )
        if teacher_user.id in duty_messages:
            duty_messages[teacher_user.id] += "\n" + line
        else:
            duty_messages[teacher_user.id] = (
                f"[감독 배정] {exam.name} 감독 배정이 확정되었습니다.\n" + line
            )
    if duty_messages:
        background_tasks.add_task(_notify_users_async, duty_messages, "invigilation_assigned", None)

    return {"ok": True, "message": f"{exam.name} 이(가) 게시되었습니다."}