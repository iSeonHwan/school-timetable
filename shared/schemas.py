"""
Pydantic v2 API 입출력 스키마

FastAPI 의 요청(Request) / 응답(Response) 직렬화에 사용됩니다.
admin_app, teacher_app 의 API 클라이언트도 이 스키마를 참조합니다.

명명 규칙:
  XxxCreate  — POST 요청 바디 (생성)
  XxxUpdate  — PATCH 요청 바디 (수정, 필드 선택적)
  XxxOut     — 응답 바디 (DB → JSON 직렬화)
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, field_validator


# ── 인증 ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str        # "admin" | "vice_principal" | "teacher"
    user_id: int
    teacher_id: Optional[int] = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    teacher_id: Optional[int]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "teacher"
    teacher_id: Optional[int] = None


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    teacher_id: Optional[int] = None
    is_active: Optional[bool] = None


# ── 학기 ───────────────────────────────────────────────────────────────────

class AcademicTermOut(BaseModel):
    id: int
    year: int
    semester: int
    start_date: Optional[date]
    end_date: Optional[date]
    is_current: bool

    model_config = {"from_attributes": True}


class AcademicTermCreate(BaseModel):
    year: int
    semester: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: bool = False


# ── 학년 / 반 ──────────────────────────────────────────────────────────────

class GradeOut(BaseModel):
    id: int
    grade_number: int
    name: str

    model_config = {"from_attributes": True}


class GradeCreate(BaseModel):
    grade_number: int
    name: str


class SchoolClassOut(BaseModel):
    id: int
    grade_id: int
    class_number: int
    display_name: str
    homeroom_room_id: Optional[int]

    model_config = {"from_attributes": True}


class SchoolClassCreate(BaseModel):
    grade_id: int
    class_number: int
    display_name: str
    homeroom_room_id: Optional[int] = None


# ── 교실 ───────────────────────────────────────────────────────────────────

class RoomOut(BaseModel):
    id: int
    name: str
    room_type: str
    capacity: int
    floor: int
    notes: str

    model_config = {"from_attributes": True}


class RoomCreate(BaseModel):
    name: str
    room_type: str = "일반"
    capacity: int = 30
    floor: int = 1
    notes: str = ""


# ── 교과목 ─────────────────────────────────────────────────────────────────

class SubjectOut(BaseModel):
    id: int
    name: str
    short_name: str
    color_hex: str
    needs_special_room: bool

    model_config = {"from_attributes": True}


class SubjectCreate(BaseModel):
    name: str
    short_name: str
    color_hex: str = "#E3F2FD"
    needs_special_room: bool = False


# ── 교사 ───────────────────────────────────────────────────────────────────

class TeacherOut(BaseModel):
    id: int
    name: str
    employee_number: str
    is_homeroom: bool
    homeroom_class_id: Optional[int]
    max_daily_classes: int

    model_config = {"from_attributes": True}


class TeacherCreate(BaseModel):
    name: str
    employee_number: str = ""
    is_homeroom: bool = False
    homeroom_class_id: Optional[int] = None
    max_daily_classes: int = 5


class TeacherUpdate(BaseModel):
    name: Optional[str] = None
    employee_number: Optional[str] = None
    is_homeroom: Optional[bool] = None
    homeroom_class_id: Optional[int] = None
    max_daily_classes: Optional[int] = None


# ── 교사 제약 ──────────────────────────────────────────────────────────────

class TeacherConstraintOut(BaseModel):
    id: int
    teacher_id: int
    day_of_week: int
    period: int
    constraint_type: str

    model_config = {"from_attributes": True}


class TeacherConstraintCreate(BaseModel):
    day_of_week: int
    period: int
    constraint_type: str = "unavailable"


# ── 시수 배정 ──────────────────────────────────────────────────────────────

class AssignmentOut(BaseModel):
    id: int
    school_class_id: int
    subject_id: int
    teacher_id: int
    weekly_hours: int
    preferred_room_id: Optional[int]

    model_config = {"from_attributes": True}


class AssignmentCreate(BaseModel):
    school_class_id: int
    subject_id: int
    teacher_id: int
    weekly_hours: int = 1
    preferred_room_id: Optional[int] = None


# ── 시간표 항목 ────────────────────────────────────────────────────────────

class TimetableEntryOut(BaseModel):
    id: int
    term_id: int
    school_class_id: int
    subject_id: int
    teacher_id: int
    room_id: Optional[int]
    day_of_week: int
    period: int
    is_fixed: bool
    # 조회 편의를 위한 중첩 정보
    subject_name: Optional[str] = None
    subject_short: Optional[str] = None
    subject_color: Optional[str] = None
    teacher_name: Optional[str] = None
    room_name: Optional[str] = None

    model_config = {"from_attributes": True}


# ── 변경 신청 ──────────────────────────────────────────────────────────────

class ChangeRequestOut(BaseModel):
    id: int
    timetable_entry_id: int
    new_subject_id: Optional[int]
    new_teacher_id: Optional[int]
    new_room_id: Optional[int]
    status: str
    reason: str
    requested_by: str
    requested_at: datetime
    # 1차 승인: 일과계 선생님의 승인 정보
    scheduler_approved_by: str = ""
    scheduler_approved_at: Optional[datetime] = None
    # 최종 승인: 교감 선생님의 승인 정보
    approved_by: str = ""
    approved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChangeRequestCreate(BaseModel):
    timetable_entry_id: int
    new_subject_id: Optional[int] = None
    new_teacher_id: Optional[int] = None
    new_room_id: Optional[int] = None
    reason: str = ""


class ChangeRequestReview(BaseModel):
    """관리자가 신청을 승인/거절할 때 사용."""
    action: str   # "approve" | "reject"
    approved_by: str = ""


# ── 변경 이력 ──────────────────────────────────────────────────────────────

class ChangeLogOut(BaseModel):
    id: int
    timetable_entry_id: Optional[int]
    term_id: int
    school_class_id: int
    change_type: str
    details: str
    changed_at: datetime

    model_config = {"from_attributes": True}


# ── 학사일정 ───────────────────────────────────────────────────────────────

class SchoolEventOut(BaseModel):
    id: int
    term_id: int
    title: str
    event_type: str
    start_date: date
    end_date: date
    description: str
    color_hex: str

    model_config = {"from_attributes": True}


class SchoolEventCreate(BaseModel):
    term_id: int
    title: str
    event_type: str = "기타"
    start_date: date
    end_date: date
    description: str = ""
    color_hex: str = "#E3F2FD"


# ── 시간표 생성 요청 ───────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    term_id: int
    max_periods: int = 7
    max_retries: int = 30


# ── 채팅 ───────────────────────────────────────────────────────────────────

class ChatMessageOut(BaseModel):
    id: int
    user_id: int
    username: str           # User.username (조인해서 채워줌)
    content: str
    is_announcement: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    content: str
    is_announcement: bool = False

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("메시지 내용이 비어 있습니다.")
        return v.strip()


# ── WebSocket 이벤트 (채팅 실시간 전송용) ──────────────────────────────────

class WsEvent(BaseModel):
    """WebSocket 으로 주고받는 이벤트 봉투."""
    type: str          # "chat" | "ping" | "history"
    payload: dict = {}
