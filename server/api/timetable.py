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
from server.deps import get_db, get_current_user, require_admin
from core.generator import generate_timetable

router = APIRouter(prefix="/timetable", tags=["시간표"])


# ── 학기 ───────────────────────────────────────────────────────────────────

@router.get("/terms", response_model=list[AcademicTermOut])
def list_terms(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(AcademicTerm).order_by(AcademicTerm.year.desc(), AcademicTerm.semester.desc()).all()


@router.post("/terms", response_model=AcademicTermOut, status_code=201)
def create_term(body: AcademicTermCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
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
    _: User = Depends(require_admin),
):
    """시간표를 자동 생성합니다. 관리자 전용."""
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
    _: User = Depends(require_admin),
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
    current_user: User = Depends(require_admin),
):
    """관리자가 변경 신청을 승인하거나 거절합니다."""
    from datetime import datetime
    req = db.get(TimetableChangeRequest, request_id)
    if req is None:
        raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")
    if req.status != "pending":
        raise HTTPException(400, "이미 처리된 신청입니다.")
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "action 은 'approve' 또는 'reject' 여야 합니다.")

    req.status = "approved" if body.action == "approve" else "rejected"
    req.approved_by = body.approved_by or current_user.username
    req.approved_at = datetime.now()

    if req.status == "approved":
        entry = db.get(TimetableEntry, req.timetable_entry_id)
        if entry:
            from core.change_logger import log_entry_update
            before = {
                "subject_id": entry.subject_id,
                "teacher_id": entry.teacher_id,
                "room_id": entry.room_id,
            }
            if req.new_subject_id:
                entry.subject_id = req.new_subject_id
            if req.new_teacher_id:
                entry.teacher_id = req.new_teacher_id
            if req.new_room_id:
                entry.room_id = req.new_room_id
            log_entry_update(session=db, entry=entry, before=before)

    db.commit()
    db.refresh(req)
    return req
