"""
시간표 조회·생성·수정 API

GET  /timetable/entries          — 시간표 목록 (term_id, class_id, teacher_id 필터)
POST /timetable/generate         — 자동 생성 (관리자)
GET  /timetable/terms            — 학기 목록
POST /timetable/terms            — 학기 추가 (관리자)
GET  /timetable/logs             — 변경 이력 (관리자)
GET  /timetable/requests         — 변경 신청 목록
POST /timetable/requests         — 변경 신청 제출 (교사)
PATCH /timetable/requests/{id}   — 신청 승인/거절 (관리자)
"""
import json
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from shared.models import (
    AcademicTerm, TimetableEntry, TimetableChangeLog,
    TimetableChangeRequest, Subject, Teacher, Room, User,
    ApprovalWorkflow, ApprovalStep,
)
from shared.schemas import (
    AcademicTermOut, AcademicTermCreate,
    TimetableEntryOut, GenerateRequest,
    ChangeLogOut, ChangeRequestOut, ChangeRequestCreate, ChangeRequestReview,
)
from server.deps import get_db, get_current_user, require_scheduler, require_admin_or_vice_principal
from core.generator import generate_timetable

router = APIRouter(prefix="/timetable", tags=["시간표"])


# ── 학기 ───────────────────────────────────────────────────────────────────

@router.get("/terms", response_model=list[AcademicTermOut])
def list_terms(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(AcademicTerm).order_by(AcademicTerm.year.desc(), AcademicTerm.semester.desc()).all()


@router.post("/terms", response_model=AcademicTermOut, status_code=201)
def create_term(body: AcademicTermCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    if body.is_current:
        db.query(AcademicTerm).filter_by(is_current=True).update({"is_current": False}, synchronize_session="evaluate")
    term = AcademicTerm(
        year=body.year, semester=body.semester,
        start_date=body.start_date, end_date=body.end_date,
        is_current=body.is_current,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


# ── 시간표 조회 ────────────────────────────────────────────────────────────

@router.get("/entries", response_model=list[TimetableEntryOut])
def list_entries(
    term_id: Optional[int] = None,
    class_id: Optional[int] = None,
    teacher_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    시간표 항목을 조회합니다.
    term_id, class_id, teacher_id 로 필터링할 수 있습니다.
    과목명·교사명·교실명을 함께 반환합니다.
    """
    q = db.query(TimetableEntry)
    if term_id:
        q = q.filter(TimetableEntry.term_id == term_id)
    if class_id:
        q = q.filter(TimetableEntry.school_class_id == class_id)
    if teacher_id:
        q = q.filter(TimetableEntry.teacher_id == teacher_id)

    entries = q.order_by(TimetableEntry.day_of_week, TimetableEntry.period).all()

    # 중첩 정보를 채워 TimetableEntryOut 으로 변환합니다.
    result = []
    for e in entries:
        subj = db.get(Subject, e.subject_id)
        tchr = db.get(Teacher, e.teacher_id)
        room = db.get(Room, e.room_id) if e.room_id else None
        out = TimetableEntryOut(
            id=e.id, term_id=e.term_id,
            school_class_id=e.school_class_id,
            subject_id=e.subject_id, teacher_id=e.teacher_id,
            room_id=e.room_id,
            day_of_week=e.day_of_week, period=e.period,
            is_fixed=e.is_fixed,
            subject_name=subj.name if subj else None,
            subject_short=subj.short_name if subj else None,
            subject_color=subj.color_hex if subj else None,
            teacher_name=tchr.name if tchr else None,
            room_name=room.name if room else None,
        )
        result.append(out)
    return result


# ── 시간표 자동 생성 ───────────────────────────────────────────────────────

@router.post("/generate")
def generate(
    body: GenerateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    지정 학기의 시간표를 자동 생성합니다. 일과계 선생님 전용.

    Body:
        term_id    : 대상 학기 ID (필수)
        max_periods: 하루 최대 교시 수 (기본 7)
        max_retries: Greedy 재시도 횟수 (기본 30)

    성공 시 기존 시간표를 삭제하고 새 배정으로 교체합니다.
    30회 내 완전 배치 실패 시 422 를 반환합니다.
    """
    ok, msg = generate_timetable(db, body.term_id, body.max_periods, body.max_retries)
    if not ok:
        raise HTTPException(status_code=422, detail=msg)
    return {"ok": True, "message": msg}


# ── 변경 이력 ──────────────────────────────────────────────────────────────

@router.get("/logs", response_model=list[ChangeLogOut])
def list_logs(
    term_id: Optional[int] = None,
    class_id: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_or_vice_principal),
):
    q = db.query(TimetableChangeLog)
    if term_id:
        q = q.filter(TimetableChangeLog.term_id == term_id)
    if class_id:
        q = q.filter(TimetableChangeLog.school_class_id == class_id)
    return q.order_by(TimetableChangeLog.changed_at.desc()).limit(limit).all()


# ── 변경 신청 ──────────────────────────────────────────────────────────────

@router.get("/requests")
def list_requests(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    변경 신청 목록을 반환합니다.

    각 응답에 활성 워크플로우의 total_steps 를 주입하여
    클라이언트가 진행 상황(현재 단계/총 단계)을 표시할 수 있게 합니다.
    """
    q = db.query(TimetableChangeRequest)
    if status:
        q = q.filter(TimetableChangeRequest.status == status)
    requests = q.order_by(TimetableChangeRequest.requested_at.desc()).all()

    wf = db.query(ApprovalWorkflow).filter_by(is_active=True).first()
    total_steps = len(wf.steps) if wf else 0

    return [_enrich_response(req, total_steps) for req in requests]


@router.post("/requests", response_model=ChangeRequestOut, status_code=201)
def submit_request(
    body: ChangeRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """교사가 시간표 변경을 신청합니다."""
    entry = db.get(TimetableEntry, body.timetable_entry_id)
    if entry is None:
        raise HTTPException(404, "시간표 항목을 찾을 수 없습니다.")
    req = TimetableChangeRequest(
        timetable_entry_id=body.timetable_entry_id,
        new_subject_id=body.new_subject_id,
        new_teacher_id=body.new_teacher_id,
        new_room_id=body.new_room_id,
        reason=body.reason,
        requested_by=current_user.username,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


@router.patch("/requests/{request_id}")
def review_request(
    request_id: int,
    body: ChangeRequestReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    변경 신청을 승인하거나 거절합니다. (동적 결재 워크플로우)

    활성 ApprovalWorkflow 를 기준으로 현재 단계(current_step)와
    사용자의 role 을 검증하여 승인/거절을 처리합니다.

    승인 흐름:
      1. 활성 워크플로우 로드 → 총 단계 수(total_steps) 파악
      2. 현재 current_step 에 해당하는 ApprovalStep 조회
      3. current_user.role 이 step.role_required 와 일치하는지 검증
      4. 승인 시:
         - approval_history JSON 배열에 기록 추가
         - 마지막 단계가 아니면 current_step += 1 (다음 단계로 진행)
         - 마지막 단계면 status = "approved", TimetableEntry 에 변경 적용

    거절: 현재 단계의 role 을 가진 사용자만 거절 가능.
          승인된/이미 거절된 건은 거절 불가.

    Body:
        action: "approve" | "reject"
        approved_by: 승인자/거절자 이름 (미입력 시 current_user.username 사용)
    """
    from datetime import datetime

    # ── 기본 검증 ──────────────────────────────────────────────────────────
    req = db.get(TimetableChangeRequest, request_id)
    if req is None:
        raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "action 은 'approve' 또는 'reject' 여야 합니다.")

    # ── 활성 워크플로우 로드 ──────────────────────────────────────────────
    wf = db.query(ApprovalWorkflow).filter_by(is_active=True).first()
    if wf is None:
        raise HTTPException(500, "활성화된 결재 워크플로우가 없습니다. 관리자에게 문의하세요.")

    total_steps = len(wf.steps)
    cur = req.current_step
    now = datetime.now()
    actor_name = current_user.username  # 항상 서버에서 결정 (위조 방지)
    user_role = current_user.role

    # ── 거절 처리 ──────────────────────────────────────────────────────────
    if body.action == "reject":
        # 교사는 거절 권한이 없습니다.
        if user_role == "teacher":
            raise HTTPException(403, "변경 신청 거절 권한이 없습니다.")

        if req.status in ("approved", "rejected"):
            raise HTTPException(400, "이미 최종 처리 완료된 신청입니다.")

        # 현재 단계의 역할 검증
        step_def = _get_step_at(wf, cur)
        if step_def is not None and user_role != step_def.role_required:
            raise HTTPException(400, f"현재 결재 단계는 '{step_def.role_required}' 역할만 처리할 수 있습니다.")

        req.status = "rejected"
        req.approved_by = actor_name
        req.approved_at = now
        _append_history(req, cur, user_role, "reject", actor_name, now)
        db.commit()
        db.refresh(req)
        return _enrich_response(req, total_steps)

    # ── 승인 처리 ──────────────────────────────────────────────────────────
    # body.action == "approve"
    if req.status not in ("pending", "scheduler_approved"):
        raise HTTPException(400, f"'대기 중' 상태인 신청만 승인할 수 있습니다. 현재 상태: {req.status}")

    # 현재 단계 확인
    step_def = _get_step_at(wf, cur)
    if step_def is None:
        raise HTTPException(500, f"워크플로우에 {cur}단계가 정의되어 있지 않습니다.")

    # 역할 검증: 현재 단계의 required role 과 사용자 role 이 일치해야 함
    if user_role != step_def.role_required:
        raise HTTPException(
            403,
            f"현재 결재 단계({cur}단계)는 '{step_def.role_required}' 역할만 승인할 수 있습니다. "
            f"당신의 역할: {user_role}",
        )

    # 승인 기록 추가
    _append_history(req, cur, user_role, "approve", actor_name, now)

    if cur < total_steps:
        # 다음 단계로 진행 (아직 최종 승인 아님)
        req.current_step = cur + 1
    else:
        # 마지막 단계: 최종 승인
        req.status = "approved"
        req.approved_by = actor_name
        req.approved_at = now

        # 실제 시간표 항목에 변경 내용을 적용합니다.
        entry = db.get(TimetableEntry, req.timetable_entry_id)
        if entry:
            from core.change_logger import log_entry_update
            before = {
                "subject_id": entry.subject_id,
                "teacher_id": entry.teacher_id,
                "room_id": entry.room_id,
            }
            if req.new_subject_id is not None:
                entry.subject_id = req.new_subject_id
            if req.new_teacher_id is not None:
                entry.teacher_id = req.new_teacher_id
            if req.new_room_id is not None:
                entry.room_id = req.new_room_id
            log_entry_update(session=db, entry=entry, before=before)

    db.commit()
    db.refresh(req)
    return _enrich_response(req, total_steps)


# ── 워크플로우 헬퍼 함수 ─────────────────────────────────────────────────────
# 이 함수들은 review_request 와 list_requests 에서 공통으로 사용하는
# 결재 워크플로우 처리 로직입니다. DB 직접 접근하는 admin_app UI 와
# 동일한 비즈니스 로직을 공유하므로, 변경 시 양쪽을 동기화해야 합니다.


def _get_step_at(workflow: ApprovalWorkflow, step_order: int) -> Optional[ApprovalStep]:
    """
    워크플로우에서 지정된 step_order 에 해당하는 ApprovalStep 을 반환합니다.

    workflow.steps 는 order_by="ApprovalStep.step_order" 로 정렬되어 있습니다.
    step_order 는 1-based: 1=첫 단계, 2=두 번째 단계, ...
    일치하는 단계가 없으면 None 을 반환합니다 (워크플로우 정의 불일치).
    """
    for step in workflow.steps:
        if step.step_order == step_order:
            return step
    return None


def _append_history(req: TimetableChangeRequest, step: int, role: str,
                    action: str, by: str, at: datetime):
    """
    approval_history JSON 배열에 승인/거절 항목을 추가합니다.

    각 항목의 필드:
      - step: 결재 단계 번호 (1-based)
      - role: 승인/거절자의 role 값 (서버가 current_user.role 로 결정 — 위조 불가)
      - action: "approve" 또는 "reject"
      - by: 승인/거절자 username (서버가 current_user.username 으로 결정 — 위조 불가)
      - at: ISO 8601 형식의 처리 시각

    보안: by 와 role 필드는 서버에서 JWT 토큰으로 인증된 current_user 정보를
    사용하므로, 클라이언트가 다른 사용자로 위장하여 승인 기록을 조작할 수 없습니다.
    """
    history = json.loads(req.approval_history or "[]")
    history.append({
        "step": step,
        "role": role,
        "action": action,
        "by": by,
        "at": at.isoformat(),
    })
    req.approval_history = json.dumps(history, ensure_ascii=False)


def _enrich_response(req: TimetableChangeRequest, total_steps: int) -> ChangeRequestOut:
    """
    ChangeRequestOut 응답에 total_steps 를 동적으로 주입하여 반환합니다.

    total_steps 는 DB 컬럼이 아니라 활성 ApprovalWorkflow 의 steps 개수로
    매 응답마다 계산됩니다. 워크플로우가 변경되면 total_steps 도 자동으로
    새로운 값이 반영됩니다.

    object.__setattr__ 를 사용하는 이유:
      ChangeRequestOut 은 Pydantic v2 모델로, model_validate() 이후에는
      일반적인 속성 할당이 제한됩니다. __setattr__ 로 우회하여
      DB 컬럼이 아닌 동적 필드를 주입합니다.
    """
    result = ChangeRequestOut.model_validate(req)
    object.__setattr__(result, "total_steps", total_steps)
    return result
