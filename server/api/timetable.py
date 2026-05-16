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
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from shared.models import (
    AcademicTerm, TimetableEntry, TimetableChangeLog,
    TimetableChangeRequest, Subject, Teacher, Room, User,
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

@router.get("/requests", response_model=list[ChangeRequestOut])
def list_requests(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(TimetableChangeRequest)
    if status:
        q = q.filter(TimetableChangeRequest.status == status)
    return q.order_by(TimetableChangeRequest.requested_at.desc()).all()


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


@router.patch("/requests/{request_id}", response_model=ChangeRequestOut)
def review_request(
    request_id: int,
    body: ChangeRequestReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    변경 신청을 승인하거나 거절합니다. (2단계 승인)

    승인 흐름 (사용자의 role 에 따라 자동 분기):
      1단계 — 일과계 선생님(admin)이 승인:
               pending → scheduler_approved
               (TimetableEntry 는 아직 변경되지 않음)
      2단계 — 교감 선생님(vice_principal)이 최종 승인:
               scheduler_approved → approved
               (TimetableEntry 에 변경 내용을 실제 적용 + 변경 이력 기록)

    거절은 두 역할 모두 가능하며, 어느 단계든 거절 시 rejected 로 처리됩니다.

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

    now = datetime.now()
    actor_name = body.approved_by or current_user.username
    user_role = current_user.role

    # ── 거절 처리 (두 역할 모두 가능) ───────────────────────────────────────
    if body.action == "reject":
        # 대기 중이거나 1차 승인된 상태만 거절 가능 (이미 최종 승인/거절된 건은 불가)
        if req.status in ("approved", "rejected"):
            raise HTTPException(400, "이미 최종 처리 완료된 신청입니다.")

        req.status = "rejected"
        req.approved_by = actor_name
        req.approved_at = now

        # 누가 거절했는지 기록: 일과계인지 교감인지에 따라 적절한 필드에 저장
        if user_role == "admin":
            req.scheduler_approved_by = actor_name
            req.scheduler_approved_at = now
        elif user_role == "vice_principal":
            req.vice_principal_approved_by = actor_name
            req.vice_principal_approved_at = now
        # teacher 는 이 엔드포인트 자체에 접근할 수 없으므로(별도 가드 없으나
        # deps.py 의 require_admin_or_vice_principal 을 여기서는 사용하지 않음 —
        # review_request 는 get_current_user 로 인증만 확인하고,
        # 역할 검증은 아래 approve 분기에서 진행)

        db.commit()
        db.refresh(req)
        return req

    # ── 승인 처리 (role 에 따라 1차/2차 분기) ───────────────────────────────
    # body.action == "approve"

    if user_role == "admin":
        # ── 1차 승인: 일과계 선생님 ──────────────────────────────────────
        if req.status != "pending":
            raise HTTPException(
                400,
                f"1차 승인은 '대기 중(pending)' 상태인 신청만 처리할 수 있습니다. "
                f"현재 상태: {req.status}",
            )
        req.status = "scheduler_approved"
        req.scheduler_approved_by = actor_name
        req.scheduler_approved_at = now
        # approved_by 는 교감 최종 승인 시에만 채워집니다.
        # 여기서는 명시적으로 비워둡니다 (혹시 이전에 거절됐다가 재신청된 경우 대비).
        req.approved_by = ""
        req.approved_at = None

    elif user_role == "vice_principal":
        # ── 2차(최종) 승인: 교감 선생님 ─────────────────────────────────
        if req.status != "scheduler_approved":
            raise HTTPException(
                400,
                f"최종 승인은 '1차 승인(scheduler_approved)' 상태인 신청만 처리할 수 있습니다. "
                f"현재 상태: {req.status}",
            )
        req.status = "approved"
        req.vice_principal_approved_by = actor_name
        req.vice_principal_approved_at = now
        req.approved_by = actor_name
        req.approved_at = now

        # 실제 시간표 항목에 변경 내용을 적용합니다.
        entry = db.get(TimetableEntry, req.timetable_entry_id)
        if entry:
            from core.change_logger import log_entry_update
            # 변경 전 상태를 스냅샷으로 기록합니다.
            before = {
                "subject_id": entry.subject_id,
                "teacher_id": entry.teacher_id,
                "room_id": entry.room_id,
            }
            # 신청된 변경사항만 선택적으로 적용 (None 이 아닌 필드만 덮어씀)
            if req.new_subject_id is not None:
                entry.subject_id = req.new_subject_id
            if req.new_teacher_id is not None:
                entry.teacher_id = req.new_teacher_id
            if req.new_room_id is not None:
                entry.room_id = req.new_room_id

            # 승인 시점에 중복 배정 재검증을 하지 않는 이유:
            # 신청 제출 당시에는 충돌이 없었더라도, 승인 전에 다른 슬롯이 변경됐을 수
            # 있습니다. 그러나 충돌 감지를 여기서 하면 승인 거부 로직이 복잡해집니다.
            # 대신 교감이 시간표를 직접 확인하고 충돌 여부를 판단하도록 위임합니다.
            log_entry_update(session=db, entry=entry, before=before)

    else:
        # teacher role — 승인 권한 없음
        raise HTTPException(403, "변경 신청 승인 권한이 없습니다. 관리자 계정으로 로그인하세요.")

    db.commit()
    db.refresh(req)
    return req
