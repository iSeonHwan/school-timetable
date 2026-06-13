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
GET  /timetable/suggestions      — 교체 가능한 대안 제안 (교사)
PATCH /timetable/requests/{id}/consent — 피교사 동의/거절 (교사)
"""
import json
import logging                          # 로깅: 오류/경고를 콘솔·파일에 기록
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, joinedload  # joinedload: N+1 쿼리 방지용 즉시 로딩
from shared.models import (
    AcademicTerm, TimetableEntry, TimetableChangeLog,
    TimetableChangeRequest, Subject, Teacher, Room, User,
    ApprovalWorkflow, ApprovalStep, SubjectClassAssignment, SchoolClass,
)
from shared.schemas import (
    AcademicTermOut, AcademicTermCreate,
    TimetableEntryOut, GenerateRequest,
    ChangeLogOut, ChangeRequestOut, ChangeRequestCreate, ChangeRequestReview,
    SuggestionResponse, SuggestionCurrent, SuggestionOption,
    ConsentReview,
)
from server.deps import get_db, get_current_user, require_scheduler, require_admin_or_vice_principal
from core.generator import generate_timetable
from server.api.chat import create_and_send_notification

router = APIRouter(prefix="/timetable", tags=["시간표"])

# 모듈 수준 로거 — logging.getLogger(__name__) 은 파일 경로에 따라
# 자동으로 이름이 결정됩니다 (예: "server.api.timetable").
# uvicorn 기본 설정에서는 WARNING 이상만 콘솔에 출력됩니다.
# 전체 로그를 보려면 uvicorn --log-level debug 옵션을 사용하세요.
_logger = logging.getLogger(__name__)


async def _notify_user_async(user_id: int, notif_type: str, change_request_id: Optional[int], message: str):
    """
    백그라운드에서 알림을 생성·전송하는 헬퍼.

    FastAPI BackgroundTasks 는 동기/비동기 함수 모두 실행할 수 있습니다.
    DB 세션을 요청 핸들러와 분리하기 위해 별도 세션을 생성합니다.
    """
    from database.connection import get_session
    db = get_session()
    try:
        await create_and_send_notification(db, user_id, notif_type, change_request_id, message)
    finally:
        db.close()


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

    # ── N+1 쿼리 방지: joinedload 로 관련 테이블을 한 번에 로드 ───────────────
    # 기존 코드는 for 루프 안에서 db.get(Subject, ...) / db.get(Teacher, ...) /
    # db.get(Room, ...) 를 매 항목마다 호출하여, 시간표 항목이 N개이면 최대
    # 3N 번의 추가 SELECT 쿼리가 발생하는 N+1 문제가 있었습니다.
    #
    # joinedload(TimetableEntry.subject) 등을 지정하면 SQLAlchemy 가 첫 쿼리에
    # LEFT OUTER JOIN 을 추가하여 연관 테이블을 한 번에 가져옵니다.
    # 그 결과 e.subject, e.teacher, e.room 속성이 이미 메모리에 올라와 있으므로
    # 루프 안에서 추가 DB 왕복이 발생하지 않습니다.
    q = q.options(
        joinedload(TimetableEntry.subject),   # subjects 테이블 JOIN
        joinedload(TimetableEntry.teacher),   # teachers 테이블 JOIN
        joinedload(TimetableEntry.room),      # rooms 테이블 JOIN (LEFT OUTER — room 없어도 OK)
    )

    entries = q.order_by(TimetableEntry.day_of_week, TimetableEntry.period).all()

    # 이제 e.subject, e.teacher, e.room 은 이미 로드된 ORM 객체입니다.
    # db.get() 을 다시 호출할 필요 없이 속성에 직접 접근합니다.
    result = []
    for e in entries:
        out = TimetableEntryOut(
            id=e.id, term_id=e.term_id,
            school_class_id=e.school_class_id,
            subject_id=e.subject_id, teacher_id=e.teacher_id,
            room_id=e.room_id,
            day_of_week=e.day_of_week, period=e.period,
            is_fixed=e.is_fixed,
            # 관계 속성에서 직접 읽기 — 추가 쿼리 없음
            subject_name=e.subject.name if e.subject else None,
            subject_short=e.subject.short_name if e.subject else None,
            subject_color=e.subject.color_hex if e.subject else None,
            teacher_name=e.teacher.name if e.teacher else None,
            room_name=e.room.name if e.room else None,
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    교사가 시간표 변경을 신청합니다.

    2026-06-13 변경:
      - 피교사 동의가 필요한 경우 consent_status=pending 으로 설정하고,
        current_step=0 으로 두어 일과계가 먼저 승인하지 못하도록 합니다.
      - 피교사에게 실시간 알림을 전송합니다.
      - 교환(swap) 신청의 경우 상대 슬롯의 교사를 affected_teacher_id 로 설정.
    """
    entry = db.get(TimetableEntry, body.timetable_entry_id)
    if entry is None:
        raise HTTPException(404, "시간표 항목을 찾을 수 없습니다.")

    # 피교사 동의가 필요한지 판단
    affected_teacher_id: Optional[int] = None
    consent_status = "not_required"
    current_step = 1

    # 1) 교환(swap) 신청: 상대 슬롯의 현재 교사에게 동의 요청
    if body.swap_partner_entry_id is not None:
        partner = db.get(TimetableEntry, body.swap_partner_entry_id)
        if partner is None:
            raise HTTPException(404, "교환 상대 슬롯을 찾을 수 없습니다.")
        if partner.term_id != entry.term_id:
            raise HTTPException(400, "교환 상대 슬롯은 같은 학기여야 합니다.")
        affected_teacher_id = partner.teacher_id
        consent_status = "pending"
        current_step = 0
    # 2) 교사 변경: 새 교사에게 동의 요청
    elif body.new_teacher_id is not None and body.new_teacher_id != entry.teacher_id:
        new_teacher = db.get(Teacher, body.new_teacher_id)
        if new_teacher is None:
            raise HTTPException(404, "지정한 교사를 찾을 수 없습니다.")
        affected_teacher_id = new_teacher.id
        consent_status = "pending"
        current_step = 0

    # ── 신청 시점 스냅샷 저장 ──────────────────────────────────────────────
    # 결재 기간이 길어지면(예: 며칠 뒤 최종 승인) 그 사이에 다른 변경 신청이
    # 같은 슬롯을 수정할 수 있습니다. 최종 승인 시 스냅샷과 현재 DB 상태를
    # 비교하여 이 타이밍 충돌(race condition)을 감지합니다.
    #
    # 스냅샷에는 신청 시점의 entry(대상 슬롯) 상태와,
    # 교환(swap) 신청인 경우 partner(상대 슬롯) 상태도 저장합니다.
    _snap: dict = {
        "entry": {
            "subject_id": entry.subject_id,
            "teacher_id": entry.teacher_id,
            "room_id":    entry.room_id,
        }
    }
    if body.swap_partner_entry_id is not None:
        # partner 는 위의 swap 검증 블록에서 이미 fetch 되었습니다.
        # (partner 가 None 이면 위에서 404 raise 되므로 여기에는 항상 존재)
        _snap["partner"] = {
            "subject_id": partner.subject_id,
            "teacher_id": partner.teacher_id,
            "room_id":    partner.room_id,
        }

    req = TimetableChangeRequest(
        timetable_entry_id=body.timetable_entry_id,
        new_subject_id=body.new_subject_id,
        new_teacher_id=body.new_teacher_id,
        new_room_id=body.new_room_id,
        reason=body.reason,
        requested_by=current_user.username,
        requested_at=datetime.now(),
        current_step=current_step,
        affected_teacher_id=affected_teacher_id,
        consent_status=consent_status,
        swap_partner_entry_id=body.swap_partner_entry_id,
        # 신청 시점 슬롯 상태를 JSON 으로 직렬화하여 저장
        change_snapshot=json.dumps(_snap, ensure_ascii=False),
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # 피교사 동의가 필요하면 알림 생성 및 실시간 전송
    if consent_status == "pending" and affected_teacher_id is not None:
        affected_user = db.query(User).filter_by(teacher_id=affected_teacher_id).first()
        if affected_user is not None:
            message = (
                f"{current_user.username} 선생님이 수업 변경을 요청하셨습니다. "
                f"사유: {body.reason or '미작성'}"
            )
            background_tasks.add_task(
                _notify_user_async,
                affected_user.id,
                "consent_request",
                req.id,
                message,
            )

    wf = db.query(ApprovalWorkflow).filter_by(is_active=True).first()
    total_steps = len(wf.steps) if wf else 0
    return _enrich_response(req, total_steps)


@router.patch("/requests/{request_id}")
def review_request(
    request_id: int,
    body: ChangeRequestReview,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    변경 신청을 승인하거나 거절합니다. (동적 결재 워크플로우 + 교사 동의)

    2026-06-13 변경:
      - 피교사 동의(consent) 완료 전에는 일과계/교감이 승인할 수 없습니다.
      - 최종 승인 시 교환(swap)인 경우 상대 슬롯도 함께 변경합니다.
      - 승인/거절 결과를 신청자에게 실시간 알림으로 전송합니다.

    Body:
        action: "approve" | "reject"
        approved_by: 승인자/거절자 이름 (미입력 시 current_user.username 사용)
    """
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

    # ── 피교사 동의 상태 검증 ──────────────────────────────────────────────
    # 동의가 필요한 신청(consent_status=pending/rejected)은 관리자 결재 전에
    # 피교사의 동의를 먼저 받아야 합니다.
    if req.consent_status == "pending":
        raise HTTPException(
            400,
            "피교사의 동의 대기 중입니다. 동의 완료 후 관리자 승인이 가능합니다."
        )
    if req.consent_status == "rejected":
        raise HTTPException(
            400,
            "피교사가 동의를 거절하여 더 이상 승인할 수 없습니다."
        )

    # ── 거절 처리 ──────────────────────────────────────────────────────────
    if body.action == "reject":
        # 교사는 관리자 결재 단계에서 거절 권한이 없습니다.
        # (교사의 거절은 PATCH /requests/{id}/consent 로 처리)
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

        # 신청자에게 거절 알림 전송
        _notify_requester(background_tasks, db, req, "rejected", "변경 신청이 거절되었습니다.")

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
        db.commit()
        db.refresh(req)
        _notify_requester(background_tasks, db, req, "status_update",
                         f"변경 신청이 {cur + 1}단계로 전달되었습니다.")
        return _enrich_response(req, total_steps)

    # 마지막 단계: 최종 승인
    req.status = "approved"
    req.approved_by = actor_name
    req.approved_at = now

    # 실제 시간표 항목에 변경 내용을 적용합니다.
    _apply_request_changes(db, req)

    db.commit()
    db.refresh(req)

    # 신청자에게 최종 승인 알림 전송
    _notify_requester(background_tasks, db, req, "approved", "변경 신청이 최종 승인되어 시간표에 반영되었습니다.")

    return _enrich_response(req, total_steps)


@router.patch("/requests/{request_id}/consent")
def review_consent(
    request_id: int,
    body: ConsentReview,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    피교사가 변경 신청에 대한 동의(승인) 또는 거절을 처리합니다.

    2026-06-13 신규:
      - 피교사(로그인한 사용자의 teacher_id == affected_teacher_id)만 호출 가능.
      - 승인 시: consent_status=approved, current_step=1 로 설정하여
        일과계 결재 라인이 시작됩니다.
      - 거절 시: consent_status=rejected, status=rejected 로 최종 처리.
      - 결과는 신청자에게 실시간 알림으로 전송됩니다.

    Body:
        action: "approve" | "reject"
    """
    # ── 기본 검증 ──────────────────────────────────────────────────────────
    req = db.get(TimetableChangeRequest, request_id)
    if req is None:
        raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "action 은 'approve' 또는 'reject' 여야 합니다.")

    # 피교사 권한 검증
    if current_user.teacher_id is None or current_user.teacher_id != req.affected_teacher_id:
        raise HTTPException(403, "해당 변경 신청에 대한 동의/거절 권한이 없습니다.")

    if req.consent_status != "pending":
        raise HTTPException(400, f"동의 대기 중인 신청만 처리할 수 있습니다. 현재 상태: {req.consent_status}")

    if req.status in ("approved", "rejected"):
        raise HTTPException(400, "이미 최종 처리 완료된 신청입니다.")

    now = datetime.now()
    req.consent_by_user_id = current_user.id
    req.consent_at = now

    wf = db.query(ApprovalWorkflow).filter_by(is_active=True).first()
    total_steps = len(wf.steps) if wf else 0

    if body.action == "reject":
        req.consent_status = "rejected"
        req.status = "rejected"
        db.commit()
        db.refresh(req)
        _notify_requester(background_tasks, db, req, "consent_rejected",
                         f"{current_user.username} 선생님이 교체/변경 요청을 거절하셨습니다.")
        return _enrich_response(req, total_steps)

    # 승인
    req.consent_status = "approved"
    req.current_step = 1  # 일과계 결재 라인 시작
    db.commit()
    db.refresh(req)

    _notify_requester(background_tasks, db, req, "consent_approved",
                     f"{current_user.username} 선생님이 교체/변경 요청에 동의하셨습니다. 일과계 승인 대기 중입니다.")
    return _enrich_response(req, total_steps)


@router.get("/suggestions", response_model=SuggestionResponse)
def get_suggestions(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 시간표 슬롯에 대한 교체 가능한 대안을 제안합니다.

    2026-06-13 신규:
      - 현재 슬롯의 반·교시·교사·과목·교실 정보를 반환.
      - 과목/교사/교실별 대체 제안과, 다른 슬롯과의 교환(swap) 제안을 반환.
      - 모든 제안은 반 중복, 교사 중복, 교실 중복, 교사 불가 시간, 일일 최대 수업
        등의 충돌 검증을 통과해야 합니다.

    Query:
        entry_id: 대상 TimetableEntry.id
    """
    entry = db.get(TimetableEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "시간표 항목을 찾을 수 없습니다.")

    # 요청자가 해당 슬롯의 교사이거나, 관리자/교감/교무부장이면 조회 허용
    if current_user.role == "teacher" and current_user.teacher_id != entry.teacher_id:
        raise HTTPException(403, "본인의 수업 슬롯에 대한 제안만 조회할 수 있습니다.")

    return _build_suggestions(db, entry)


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


# ── 변경 적용 및 알림 헬퍼 ───────────────────────────────────────────────────

def _apply_request_changes(db: Session, req: TimetableChangeRequest) -> None:
    """
    최종 승인된 변경 신청을 실제 TimetableEntry 에 반영합니다.

    2026-06-13 개선:
      1. entry 가 None 이면 조용히 실패하지 않고 에러 로그를 남깁니다.
         (이전에는 return 만 하여 원인 추적이 불가능했습니다)
      2. 교환(swap) 신청인 경우, 신청 시점 스냅샷(change_snapshot)과 현재
         DB 상태를 비교합니다. 결재 기간 중 다른 변경이 상대 슬롯에 적용되었다면
         409 Conflict 를 반환합니다.
      3. partner(swap 상대 슬롯)도 None 체크 후 로그를 남기고 raise 합니다.
      4. 모든 변경은 TimetableChangeLog 에 before/after 로 기록됩니다.

    호출 위치: review_request() — DB 트랜잭션 안에서 호출됩니다.
    raise HTTPException 은 트랜잭션 롤백을 유발하므로 안전합니다.
    """
    from core.change_logger import log_entry_update

    # ── 1. 대상 슬롯 로드 및 존재 확인 ────────────────────────────────────
    entry = db.get(TimetableEntry, req.timetable_entry_id)
    if entry is None:
        # 승인 처리 중 시간표 항목이 삭제된 예외 상황.
        # 조용히 실패하지 않고 에러 로그를 남겨 나중에 원인을 추적할 수 있게 합니다.
        _logger.error(
            "변경 적용 실패 — TimetableEntry(id=%s) 를 찾을 수 없습니다. "
            "요청 ID: %s (신청자: %s). 항목이 삭제되었거나 DB 불일치가 발생했습니다.",
            req.timetable_entry_id, req.id, req.requested_by,
        )
        return

    # ── 2. 교환(swap) 신청: 상대 슬롯 검증 + 스냅샷 충돌 감지 ───────────
    # 교환이 아닌 경우(단순 과목·교사·교실 변경)는 이 블록을 건너뜁니다.
    partner = None
    if req.swap_partner_entry_id is not None:
        partner = db.get(TimetableEntry, req.swap_partner_entry_id)
        if partner is None:
            # 상대 슬롯이 결재 기간 중 삭제된 경우
            _logger.error(
                "교환 신청 적용 실패 — swap 상대 TimetableEntry(id=%s) 를 찾을 수 없습니다. "
                "요청 ID: %s",
                req.swap_partner_entry_id, req.id,
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"교환 상대 슬롯(entry_id={req.swap_partner_entry_id})이 "
                    "결재 기간 중 삭제되었습니다. 변경 신청을 취소하고 다시 신청해 주세요."
                ),
            )

        # 스냅샷 기반 충돌 감지 ─────────────────────────────────────────────
        # change_snapshot 이 없는 기존 레코드(스냅샷 추가 전에 생성됨)는
        # 검증 없이 통과합니다 (하위 호환성 유지).
        if req.change_snapshot:
            snap = json.loads(req.change_snapshot)
            partner_snap = snap.get("partner")  # swap 이 아닌 경우 None
            if partner_snap:
                # 스냅샷과 현재 DB 상태를 비교합니다.
                # 결재 기간 중 다른 신청이 상대 슬롯을 수정했다면 값이 달라집니다.
                current_partner_state = {
                    "subject_id": partner.subject_id,
                    "teacher_id": partner.teacher_id,
                    "room_id":    partner.room_id,
                }
                if current_partner_state != partner_snap:
                    _logger.warning(
                        "교환 신청 충돌 감지 — 요청 ID=%s, partner entry_id=%s. "
                        "신청 시점 스냅샷=%s, 현재 상태=%s",
                        req.id, req.swap_partner_entry_id,
                        partner_snap, current_partner_state,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"교환 상대 슬롯(entry_id={req.swap_partner_entry_id})이 "
                            "결재 기간 중 다른 변경으로 수정되었습니다. "
                            "변경 신청을 취소하고 최신 상태로 다시 신청해 주세요."
                        ),
                    )

    # ── 3. 단순 변경(과목/교사/교실) 적용 ─────────────────────────────────
    # 변경 전 상태를 before 에 기록합니다. 이후 log_entry_update() 가
    # before → after 를 TimetableChangeLog 에 저장합니다.
    before = {
        "subject_id": entry.subject_id,
        "teacher_id": entry.teacher_id,
        "room_id":    entry.room_id,
    }
    # new_* 필드가 None 이면 해당 속성은 변경하지 않습니다.
    if req.new_subject_id is not None:
        entry.subject_id = req.new_subject_id
    if req.new_teacher_id is not None:
        entry.teacher_id = req.new_teacher_id
    if req.new_room_id is not None:
        entry.room_id = req.new_room_id
    log_entry_update(db, entry, before)

    # ── 4. 교환(swap) 적용 ─────────────────────────────────────────────────
    # 교환 신청인 경우, entry 와 partner 의 과목/교사/교실을 서로 맞바꿉니다.
    # before(entry 원래 값) 와 partner_before(partner 원래 값) 를 서로 대입합니다.
    if partner is not None:
        partner_before = {
            "subject_id": partner.subject_id,
            "teacher_id": partner.teacher_id,
            "room_id":    partner.room_id,
        }
        # 교환: entry 에는 partner 의 원래 값을, partner 에는 entry 의 원래 값을 씁니다.
        entry.subject_id   = partner_before["subject_id"]
        entry.teacher_id   = partner_before["teacher_id"]
        entry.room_id      = partner_before["room_id"]
        partner.subject_id = before["subject_id"]
        partner.teacher_id = before["teacher_id"]
        partner.room_id    = before["room_id"]
        log_entry_update(db, partner, partner_before)


def _notify_requester(
    background_tasks: BackgroundTasks,
    db: Session,
    req: TimetableChangeRequest,
    notif_type: str,
    message: str,
) -> None:
    """
    변경 신청자(requested_by)에게 실시간 알림을 전송합니다.

    2026-06-13 신규:
      - requested_by username 으로 User 를 조회하여 알림을 생성.
      - 요청자가 오프라인이어도 DB 에 남아 재접속 시 확인 가능.
    """
    requester = db.query(User).filter_by(username=req.requested_by).first()
    if requester is None:
        return
    background_tasks.add_task(
        _notify_user_async,
        requester.id,
        notif_type,
        req.id,
        message,
    )


# ── 제안 알고리즘 헬퍼 ─────────────────────────────────────────────────────

def _day_name(day: int) -> str:
    """요일 번호(1=월)를 한글 요일명으로 변환합니다."""
    names = {1: "월", 2: "화", 3: "수", 4: "목", 5: "금"}
    return names.get(day, "?")


def _teacher_constraints_set(db: Session, teacher_ids: list[int]) -> set[tuple[int, int]]:
    """
    지정한 교사들의 '불가' 제약 슬롯을 {(day, period)} 집합으로 반환합니다.
    """
    from shared.models import TeacherConstraint
    rows = (
        db.query(TeacherConstraint)
        .filter(
            TeacherConstraint.teacher_id.in_(teacher_ids),
            TeacherConstraint.constraint_type == "unavailable",
        )
        .all()
    )
    return {(r.day_of_week, r.period) for r in rows}


def _entries_for_term(db: Session, term_id: int):
    """해당 학기의 모든 TimetableEntry 를 반환합니다."""
    return db.query(TimetableEntry).filter_by(term_id=term_id).all()


def _build_conflict_maps_from_list(
    entries: list,
    exclude_entry_id: Optional[int] = None,
) -> tuple[dict, dict, dict, dict]:
    """
    이미 로드된 TimetableEntry 리스트에서 충돌 검증용 맵을 계산합니다.
    DB 접근 없음 — O(N) 메모리 연산만 수행합니다.

    exclude_entry_id 가 지정된 경우 해당 항목의 슬롯은 맵에서 제외합니다.
    이를 이용해 "특정 슬롯이 비어있다고 가정했을 때"의 맵을 계산합니다.

    반환값:
      class_slots:   {class_id:   {(day, period)}}   — 반별 사용 중인 슬롯
      teacher_slots: {teacher_id: {(day, period)}}   — 교사별 사용 중인 슬롯
      room_slots:    {room_id:    {(day, period)}}   — 교실별 사용 중인 슬롯
      teacher_daily: {(teacher_id, day): count}       — 교사의 일별 수업 수
    """
    class_slots:   dict[int, set]             = {}
    teacher_slots: dict[int, set]             = {}
    room_slots:    dict[int, set]             = {}
    teacher_daily: dict[tuple[int, int], int] = {}

    for e in entries:
        if e.id == exclude_entry_id:
            continue  # 이 항목은 제외(비어있는 것으로 간주)
        slot = (e.day_of_week, e.period)
        class_slots.setdefault(e.school_class_id, set()).add(slot)
        teacher_slots.setdefault(e.teacher_id, set()).add(slot)
        if e.room_id is not None:
            room_slots.setdefault(e.room_id, set()).add(slot)
        teacher_daily[(e.teacher_id, e.day_of_week)] = (
            teacher_daily.get((e.teacher_id, e.day_of_week), 0) + 1
        )

    return class_slots, teacher_slots, room_slots, teacher_daily


def _build_conflict_maps(db: Session, term_id: int, exclude_entry_id: Optional[int]):
    """
    DB 에서 해당 학기 항목을 로드한 뒤 충돌 맵을 계산합니다.

    내부적으로 _build_conflict_maps_from_list 를 호출합니다.
    단일 호출 시에는 이 함수를 사용하고, 여러 번 반복 호출할 때는
    미리 로드한 entries 를 _build_conflict_maps_from_list 에 직접 넘겨
    불필요한 DB 왕복을 줄이세요.

    반환값:
      class_slots, teacher_slots, room_slots, teacher_daily (위와 동일)
    """
    entries = _entries_for_term(db, term_id)
    return _build_conflict_maps_from_list(entries, exclude_entry_id)


def _teacher_max_map(db: Session) -> dict[int, int]:
    """교사별 일 최대 수업 수를 반환합니다. 1 미만은 1로 보정합니다."""
    return {t.id: max(t.max_daily_classes, 1) for t in db.query(Teacher).all()}


def _can_place_teacher(
    teacher_id: int,
    day: int,
    period: int,
    teacher_slots: dict[int, set],
    teacher_daily: dict[tuple[int, int], int],
    teacher_max: dict[int, int],
    unavailable: set[tuple[int, int]],
    exclude_entry_id: Optional[int] = None,
) -> bool:
    """
    특정 교사를 (day, period)에 배치할 수 있는지 검증합니다.
    """
    slot = (day, period)
    if slot in unavailable:
        return False
    if slot in teacher_slots.get(teacher_id, set()):
        return False
    if teacher_daily.get((teacher_id, day), 0) >= teacher_max.get(teacher_id, 1):
        return False
    return True


def _can_place_class(
    class_id: int,
    day: int,
    period: int,
    class_slots: dict[int, set],
) -> bool:
    """특정 반을 (day, period)에 배치할 수 있는지 검증합니다."""
    return (day, period) not in class_slots.get(class_id, set())


def _can_place_room(
    room_id: Optional[int],
    day: int,
    period: int,
    room_slots: dict[int, set],
) -> bool:
    """특정 교실을 (day, period)에 배치할 수 있는지 검증합니다."""
    if room_id is None:
        return True
    return (day, period) not in room_slots.get(room_id, set())


def _build_suggestions(db: Session, entry: TimetableEntry) -> SuggestionResponse:
    """
    주어진 TimetableEntry 에 대한 교체/대체/교환 제안을 생성합니다.

    2026-06-13 신규:
      - 과목/교사/교실 대체 제안: 현재 슬롯의 반·교시에 배치 가능한 후보를 검색.
      - 교환 제안: 다른 슬롯과 서로 교사/과목을 맞바꿀 수 있는 경우를 검색.
      - 모든 제안은 반/교사/교실 중복, 불가 시간, 일일 최대 수업을 고려.

    2026-06-13 개선 (N+1 및 O(N²) 쿼리 해소):
      - 과목/교사/교실을 Dict 로 미리 로드하여 루프 안 db.get() 호출 제거.
      - 교환 제안 루프에서 _build_conflict_maps() 대신 이미 로드된 entries 로
        _build_conflict_maps_from_list() 를 사용. DB 쿼리 O(N) → O(1) 로 감소.
    """
    term_id   = entry.term_id
    day       = entry.day_of_week
    period    = entry.period
    class_id  = entry.school_class_id
    subject_id = entry.subject_id
    teacher_id = entry.teacher_id
    room_id    = entry.room_id

    # ── 마스터 데이터 일괄 로드 (N+1 방지) ─────────────────────────────────
    # 교사의 subject_assignments 도 함께 로드하여 "담당 과목 여부" 확인 시
    # 추가 쿼리가 발생하지 않도록 합니다.
    all_subjects_map: dict[int, Subject] = {
        s.id: s for s in db.query(Subject).all()
    }
    all_teachers_list: list[Teacher] = (
        db.query(Teacher)
        .options(joinedload(Teacher.subject_assignments))  # 배정 정보 즉시 로드
        .all()
    )
    all_teachers_map: dict[int, Teacher] = {t.id: t for t in all_teachers_list}
    all_rooms_map: dict[int, Room] = {
        r.id: r for r in db.query(Room).all()
    }

    # ── 현재 슬롯 표시 정보 ─────────────────────────────────────────────────
    subj = all_subjects_map.get(subject_id)
    tchr = all_teachers_map.get(teacher_id)
    room = all_rooms_map.get(room_id) if room_id else None
    cls  = db.get(SchoolClass, class_id)   # 반은 단일 조회 (1번)
    current = SuggestionCurrent(
        entry_id=entry.id,
        day_of_week=day,
        period=period,
        school_class_id=class_id,
        school_class_name=cls.display_name if cls else "",
        subject_id=subject_id,
        subject_name=subj.name if subj else "",
        teacher_id=teacher_id,
        teacher_name=tchr.name if tchr else "",
        room_id=room_id,
        room_name=room.name if room else None,
    )

    # ── 학기 전체 시간표를 한 번에 로드 (swap 루프에서 재사용) ───────────────
    # 이 리스트를 미리 로드해두면 이후 _build_conflict_maps_from_list() 가
    # DB 왕복 없이 메모리에서 계산할 수 있습니다.
    all_term_entries: list[TimetableEntry] = _entries_for_term(db, term_id)

    # 현재 슬롯을 제외한 충돌 맵 (이 슬롯이 빈 것으로 가정한 상태)
    class_slots, teacher_slots, room_slots, teacher_daily = (
        _build_conflict_maps_from_list(all_term_entries, entry.id)
    )

    # 교사 불가 시간 제약 및 일일 최대 수업 맵
    teacher_ids = list(all_teachers_map.keys())
    unavailable = _teacher_constraints_set(db, teacher_ids)
    teacher_max = {t.id: max(t.max_daily_classes, 1) for t in all_teachers_list}

    subjects: list[SuggestionOption] = []
    teachers: list[SuggestionOption] = []
    rooms:    list[SuggestionOption] = []

    # ── 과목 대체 제안 ──────────────────────────────────────────────────────
    # 같은 반·학기의 SubjectClassAssignment 중, 해당 교시에 배치 가능한 조합.
    assignments = (
        db.query(SubjectClassAssignment)
        .filter_by(school_class_id=class_id, term_id=term_id)
        .all()
    )
    seen_subject_teacher: set[tuple[int, int]] = set()
    for a in assignments:
        key = (a.subject_id, a.teacher_id)
        if key in seen_subject_teacher:
            continue  # 동일 조합 중복 건너뜀
        seen_subject_teacher.add(key)
        if a.subject_id == subject_id and a.teacher_id == teacher_id:
            continue  # 현재와 동일한 경우 제안 불필요
        if not _can_place_class(class_id, day, period, class_slots):
            continue
        if not _can_place_teacher(
            a.teacher_id, day, period, teacher_slots, teacher_daily, teacher_max, unavailable
        ):
            continue
        target_room_id = (
            a.preferred_room_id if a.preferred_room_id is not None else room_id
        )
        if not _can_place_room(target_room_id, day, period, room_slots):
            continue

        # 캐시된 dict 에서 가져오기 — 추가 쿼리 없음
        subj_obj = all_subjects_map.get(a.subject_id)
        tchr_obj = all_teachers_map.get(a.teacher_id)
        room_obj = all_rooms_map.get(target_room_id) if target_room_id else None
        label = f"{subj_obj.name}({tchr_obj.name})" if subj_obj and tchr_obj else "(알 수 없음)"
        if room_obj:
            label += f" — {room_obj.name}"
        subjects.append(SuggestionOption(
            subject_id=a.subject_id,
            teacher_id=a.teacher_id,
            room_id=target_room_id,
            label=label,
            reason=(
                f"{tchr_obj.name} 선생님이 해당 교시에 수업이 없으며 "
                "일일 최대 수업을 초과하지 않습니다."
            ) if tchr_obj else "",
        ))

    # ── 교사 대체 제안 ──────────────────────────────────────────────────────
    # 해당 교시에 배치 가능한 모든 교사 (이미 로드된 리스트를 순회).
    current_subject = all_subjects_map.get(subject_id)
    for t in all_teachers_list:
        if t.id == teacher_id:
            continue  # 현재 교사는 제외
        if not _can_place_teacher(
            t.id, day, period, teacher_slots, teacher_daily, teacher_max, unavailable
        ):
            continue
        # t.subject_assignments 는 joinedload 로 이미 로드됨 — 추가 쿼리 없음
        has_assignment = any(
            a.subject_id == subject_id
            and a.school_class_id == class_id
            and a.term_id == term_id
            for a in t.subject_assignments
        )
        if has_assignment and current_subject and cls:
            reason = (
                f"{t.name} 선생님이 {cls.display_name}의 "
                f"{current_subject.name} 담당 교사이며 해당 교시에 수업이 없습니다."
            )
        else:
            reason = f"{t.name} 선생님이 해당 교시에 수업이 없습니다."
        teachers.append(SuggestionOption(
            teacher_id=t.id,
            label=f"{t.name} 선생님",
            reason=reason,
        ))

    # ── 교실 대체 제안 ──────────────────────────────────────────────────────
    for r in all_rooms_map.values():
        if r.id == room_id:
            continue  # 현재 교실은 제외
        if not _can_place_room(r.id, day, period, room_slots):
            continue
        # 특별실이 필요한 과목이면 일반 교실은 제안하지 않음
        if current_subject and current_subject.needs_special_room and r.room_type == "일반":
            continue
        rooms.append(SuggestionOption(
            room_id=r.id,
            label=f"{r.name}({r.room_type})",
            reason=f"{r.name} 교실이 해당 교시에 비어 있습니다.",
        ))

    # ── 교환(swap) 제안 ─────────────────────────────────────────────────────
    # 이전 구현: 각 partner 마다 _build_conflict_maps(db, ...) 를 호출 → O(N²) DB 쿼리
    # 개선된 구현: 미리 로드된 all_term_entries 와 _build_conflict_maps_from_list 를 사용
    #   → O(N²) 메모리 연산 (DB 왕복 0회)
    #
    # N(시간표 항목 수)이 학교 규모 기준 수백 개라면 O(N²) 메모리 연산은 충분히 빠릅니다.
    # 수천 개 이상으로 늘어난다면 추가 최적화(인덱스, 이진 탐색 등)를 검토하세요.
    swaps: list[SuggestionOption] = []
    for p in all_term_entries:
        if p.id == entry.id:
            continue  # 자기 자신은 제외

        # partner p 를 제외한 충돌 맵 — DB 조회 없이 메모리에서 계산
        p_class_slots, p_teacher_slots, p_room_slots, p_teacher_daily = (
            _build_conflict_maps_from_list(all_term_entries, p.id)
        )

        # 교환 후 entry 의 교사(teacher_id)가 p 의 슬롯에 배치될 수 있는지 확인
        if not _can_place_class(class_id, p.day_of_week, p.period, p_class_slots):
            continue
        if not _can_place_teacher(
            teacher_id, p.day_of_week, p.period,
            p_teacher_slots, p_teacher_daily, teacher_max, unavailable
        ):
            continue
        if room_id is not None and not _can_place_room(
            room_id, p.day_of_week, p.period, p_room_slots
        ):
            continue

        # 교환 후 p 의 교사(p.teacher_id)가 entry 의 슬롯에 배치될 수 있는지 확인
        # (entry 를 제외한 맵 class_slots, teacher_slots, room_slots 재사용)
        if not _can_place_class(p.school_class_id, day, period, class_slots):
            continue
        if not _can_place_teacher(
            p.teacher_id, day, period,
            teacher_slots, teacher_daily, teacher_max, unavailable
        ):
            continue
        if p.room_id is not None and not _can_place_room(
            p.room_id, day, period, room_slots
        ):
            continue

        # 캐시된 dict 에서 가져오기 — 추가 쿼리 없음
        p_teacher = all_teachers_map.get(p.teacher_id)
        p_subject = all_subjects_map.get(p.subject_id)
        label = (
            f"{p_teacher.name if p_teacher else '?'} 선생님의 "
            f"{_day_name(p.day_of_week)}요일 {p.period}교시 "
            f"{p_subject.name if p_subject else '?'} 수업과 교환"
        )
        swaps.append(SuggestionOption(
            swap_partner_entry_id=p.id,
            label=label,
            reason="양쪽 교사 모두 상대 슬롯에 수업이 없고, 반/교실 충돌이 없습니다.",
        ))

    return SuggestionResponse(
        current=current,
        subjects=subjects,
        teachers=teachers,
        rooms=rooms,
        swaps=swaps,
    )
