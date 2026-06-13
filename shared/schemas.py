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
from pydantic import BaseModel, Field, field_validator


# ── 인증 ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """
    로그인 요청 바디.

    보안:
      - password: min_length=4 로 빈 비밀번호 전송을 1차 차단합니다.
        (실제 계정 비밀번호는 UserCreate 에서 최소 8자로 강제됩니다.)
      - username: max_length=50 으로 과도한 입력을 제한합니다.
    """
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=4)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str        # "admin" | "vice_principal" | "department_head" | "teacher"
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
    """
    사용자 계정 생성 요청.

    보안:
      - password: min_length=8 로 취약한 비밀번호 생성을 방지합니다.
      - role: 기본값 "teacher" — 명시적으로 지정하지 않으면 최소 권한으로 생성됩니다.
        서버 측에서도 role 필드를 검증하므로, API 를 통한 role escalation 공격이 차단됩니다.
    """
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8)
    role: str = "teacher"
    teacher_id: Optional[int] = None


class UserUpdate(BaseModel):
    """
    사용자 계정 수정 요청.

    보안:
      - role 필드가 제외되어 있습니다. API 호출로 권한 상승(role escalation)을
        시도하더라도 서버 측에서 role 을 허용 필드 목록에 포함하지 않으므로
        teacher → admin 같은 변경이 불가능합니다. role 변경은 DB 직접 조작만 가능.
      - password: 새 비밀번호 설정 시 min_length=8 적용.
    """
    password: Optional[str] = Field(None, min_length=8)
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
    grade_number: int = Field(..., ge=1, le=6)
    name: str = Field(..., min_length=1, max_length=20)


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
    """
    교실 생성 요청.

    필드 제약:
      - capacity: ge=1, le=500 — 비현실적이거나 악의적인 값 입력을 방지합니다.
      - floor: ge=1, le=20 — 층수 범위를 제한하여 데이터 무결성을 유지합니다.
    """
    name: str = Field(..., min_length=1, max_length=50)
    room_type: str = "일반"
    capacity: int = Field(default=30, ge=1, le=500)
    floor: int = Field(default=1, ge=1, le=20)
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
    name: str = Field(..., min_length=1, max_length=50)
    short_name: str = Field(..., min_length=1, max_length=20)
    color_hex: str = "#E3F2FD"
    needs_special_room: bool = False

    @field_validator("color_hex")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        if not v.startswith("#") or len(v) != 7:
            raise ValueError("색상은 #RRGGBB 형식이어야 합니다.")
        int(v[1:], 16)  # hex 파싱 가능 여부 확인
        return v


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
    """
    교사 생성 요청.

    2026-06-13 변경:
      - max_daily_classes 에 ge=1 검증 추가. 0 이하 값은 생성기에서
        무한 루프/오류를 유발할 수 있으므로 차단합니다.
    """
    name: str
    employee_number: str = ""
    is_homeroom: bool = False
    homeroom_class_id: Optional[int] = None
    max_daily_classes: int = Field(default=5, ge=1)


class TeacherUpdate(BaseModel):
    """
    교사 수정 요청.

    2026-06-13 변경:
      - max_daily_classes 에 ge=1 검증 추가.
    """
    name: Optional[str] = None
    employee_number: Optional[str] = None
    is_homeroom: Optional[bool] = None
    homeroom_class_id: Optional[int] = None
    max_daily_classes: Optional[int] = Field(None, ge=1)


# ── 교사 제약 ──────────────────────────────────────────────────────────────

class TeacherConstraintOut(BaseModel):
    id: int
    teacher_id: int
    day_of_week: int
    period: int
    constraint_type: str

    model_config = {"from_attributes": True}


class TeacherConstraintCreate(BaseModel):
    """
    교사 제약조건 생성 요청.

    필드 제약:
      - day_of_week: ge=1, le=5 (월~금) — 범위 밖 값을 차단합니다.
      - period: ge=1, le=7 (1~7교시) — 범위 밖 값을 차단합니다.
    """
    day_of_week: int = Field(..., ge=1, le=5)
    period: int = Field(..., ge=1, le=7)
    constraint_type: str = "unavailable"


# ── 시수 배정 ──────────────────────────────────────────────────────────────

class AssignmentOut(BaseModel):
    id: int
    school_class_id: int
    subject_id: int
    teacher_id: int
    weekly_hours: int
    preferred_room_id: Optional[int]
    term_id: Optional[int] = None

    model_config = {"from_attributes": True}


class AssignmentCreate(BaseModel):
    """
    시수 배정 생성/수정 요청.

    2026-06-13 변경:
      - term_id 추가. 학기별로 시수 배정을 구분하여 생성기가 해당 학기
        데이터만 사용하도록 합니다. 이 필드는 필수입니다.
    """
    school_class_id: int
    subject_id: int
    teacher_id: int
    weekly_hours: int = Field(default=1, ge=1, le=50)
    preferred_room_id: Optional[int] = None
    term_id: int


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
    """
    변경 신청 응답.

    동적 결재 워크플로우 + 교사 동의 지원:
      - current_step: 현재 진행 중인 단계 (1-based). 동의 대기 중일 때는 0.
      - total_steps: 활성 워크플로우의 총 단계 수 (DB 컬럼 아님, API 응답 시 주입)
      - approval_history: JSON 배열로 모든 단계별 승인/거절 기록
      - consent_status / affected_teacher_id: 피교사 동의 상태
      - swap_partner_entry_id: 교환 상대 슬롯
    """
    id: int
    timetable_entry_id: int
    new_subject_id: Optional[int]
    new_teacher_id: Optional[int]
    new_room_id: Optional[int]
    status: str
    reason: str
    requested_by: str
    requested_at: datetime
    # 동적 결재 정보
    current_step: int = 0
    total_steps: int = 0           # API 응답 시 서버가 주입
    approval_history: str = "[]"   # JSON 배열
    # 피교사 동의 정보 (신규)
    affected_teacher_id: Optional[int] = None
    consent_status: str = "not_required"
    consent_by_user_id: Optional[int] = None
    consent_at: Optional[datetime] = None
    swap_partner_entry_id: Optional[int] = None
    # [DEPRECATED] 하드코딩된 2단계 결재 필드 — 하위 호환용 유지
    scheduler_approved_by: str = ""
    scheduler_approved_at: Optional[datetime] = None
    approved_by: str = ""
    approved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChangeRequestCreate(BaseModel):
    """
    변경 신청 생성 요청.

    2026-06-13 변경:
      - swap_partner_entry_id 추가. 두 슬롯을 맞바꾸는 교환 신청에 사용.
    """
    timetable_entry_id: int
    new_subject_id: Optional[int] = None
    new_teacher_id: Optional[int] = None
    new_room_id: Optional[int] = None
    reason: str = ""
    swap_partner_entry_id: Optional[int] = None


class ChangeRequestReview(BaseModel):
    """
    변경 신청 승인/거절 요청.

    보안:
      - approved_by 필드는 서버가 무시하고 current_user.username 으로 덮어씁니다.
        클라이언트가 임의의 승인자 이름을 주입하는 것을 방지하여 감사 추적의
        무결성을 보장합니다. (actor impersonation 공격 방지)
    """
    action: str   # "approve" | "reject"
    approved_by: str = ""  # 서버가 무시하고 current_user.username 으로 덮어씁니다.


class ConsentReview(BaseModel):
    """
    피교사 동의(승인/거절) 요청.

    PATCH /timetable/requests/{id}/consent 의 요청 바디입니다.
    피교사(로그인한 사용자의 teacher_id == affected_teacher_id)만 호출할 수 있습니다.
    """
    action: str  # "approve" | "reject"


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
    title: str = Field(..., min_length=1, max_length=100)
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


# ── 시간표 교체 제안 ─────────────────────────────────────────────────────────

class SuggestionOption(BaseModel):
    """
    단일 제안 항목.

    변경 신청자가 선택하면, 이 항목에 해당하는 new_*_id / swap_partner_entry_id 를
    ChangeRequestCreate 에 담아 서버로 전송합니다.
    """
    subject_id: Optional[int] = None
    teacher_id: Optional[int] = None
    room_id: Optional[int] = None
    swap_partner_entry_id: Optional[int] = None
    label: str  # 화면에 표시할 설명 문구
    reason: str  # 왜 이 제안이 가능한지에 대한 짧은 설명


class SuggestionCurrent(BaseModel):
    """현재 선택한 시간표 슬롯의 요약 정보."""
    entry_id: int
    day_of_week: int
    period: int
    school_class_id: int
    school_class_name: str
    subject_id: int
    subject_name: str
    teacher_id: int
    teacher_name: str
    room_id: Optional[int]
    room_name: Optional[str]


class SuggestionResponse(BaseModel):
    """GET /timetable/suggestions 응답."""
    current: SuggestionCurrent
    subjects: list[SuggestionOption]
    teachers: list[SuggestionOption]
    rooms: list[SuggestionOption]
    swaps: list[SuggestionOption]


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
    """
    채팅 메시지 전송 요청.

    보안:
      - content: max_length=10000 으로 대용량 페이로드 공격을 방지합니다.
        (WebSocket 경로에서도 receive_text(max_size=4096) 으로 추가 제한)
      - is_announcement: 서버 측에서도 role 검증을 하므로, API 를 통한
        권한 없는 공지 발행을 차단합니다.
      - content_not_empty validator 로 공백만 있는 메시지도 거부합니다.
    """
    content: str = Field(..., min_length=1, max_length=10000)
    is_announcement: bool = False

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("메시지 내용이 비어 있습니다.")
        if len(stripped) > 10000:
            raise ValueError("메시지가 너무 깁니다. 10000자 이하로 입력하세요.")
        return stripped


# ── 알림 ────────────────────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    """알림 응답 스키마."""
    id: int
    user_id: int
    type: str
    change_request_id: Optional[int]
    message: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationReadRequest(BaseModel):
    """알림 읽음 처리 요청."""
    is_read: bool = True


# ── 결재 워크플로우 ─────────────────────────────────────────────────────────

class ApprovalStepCreate(BaseModel):
    """결재 단계 생성 요청."""
    step_order: int = Field(..., ge=1)
    role_required: str = Field(..., min_length=1, max_length=20)
    step_name: str = Field(..., min_length=1, max_length=50)


class ApprovalStepOut(BaseModel):
    id: int
    workflow_id: int
    step_order: int
    role_required: str
    step_name: str

    model_config = {"from_attributes": True}


class ApprovalWorkflowCreate(BaseModel):
    """
    결재 워크플로우 생성 요청.

    steps 의 step_order 는 1부터 시작하여 연속되어야 합니다.
    예) [1, 2, 3] — 정상, [1, 3] — 오류 (2가 누락됨)

    is_active=True 로 생성 시 기존 활성 워크플로우는 서버에서 자동 비활성화됩니다.
    한 번에 하나의 워크플로우만 활성 상태일 수 있습니다.

    보안:
      - role_required 는 자유 텍스트이지만, 서버의 role 검증 로직에서
        User.role 과 정확히 일치해야 승인 권한이 부여됩니다.
        알 수 없는 role 값은 사실상 승인 불가능한 단계가 되므로 주의하세요.
      - min_length=1 제약으로 빈 steps 배열 생성 방지 (최소 1단계 이상)
      - field_validator 로 step_order 연속성 검증
    """
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    steps: list[ApprovalStepCreate] = Field(..., min_length=1)
    is_active: bool = False

    @field_validator("steps")
    @classmethod
    def steps_must_be_sequential(cls, v: list) -> list:
        orders = [s.step_order for s in v]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("단계 순서는 1부터 시작하여 빠짐없이 연속되어야 합니다.")
        return v


class ApprovalWorkflowOut(BaseModel):
    id: int
    name: str
    description: str
    is_active: bool
    steps: list[ApprovalStepOut]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── WebSocket 이벤트 (채팅 실시간 전송용) ──────────────────────────────────

class WsEvent(BaseModel):
    """WebSocket 으로 주고받는 이벤트 봉투."""
    type: str          # "chat" | "ping" | "history"
    payload: dict = {}
