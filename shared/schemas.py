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
from datetime import date, datetime, time
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
    # ── 반별 학생 수 (2026-09-19 추가) ─────────────────────────────────────
    # 시험 감독 2인 1조 판단 기준. 미입력(None)이면 감독 배정 알고리즘이
    # 기본값 30명을 가정합니다.
    student_count: Optional[int] = None

    model_config = {"from_attributes": True}


class SchoolClassCreate(BaseModel):
    grade_id: int
    class_number: int
    display_name: str
    homeroom_room_id: Optional[int] = None
    # ── 반별 학생 수 (2026-09-19 추가 — 시험 감독 조 구성 기준) ─────────────
    # 20명 이상 → 감독 2인 1조, 미만 → 1인. 선택 입력으로 두어 기존
    # 반 관리 흐름(학생 수 모름)도 그대로 동작하게 합니다.
    student_count: Optional[int] = Field(default=None, ge=1, le=200)


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
    # ── 신청 대상 (2026-09-19 변경: 감독 스왑 신청 지원) ─────────────────────
    # request_type="timetable"     → timetable_entry_id 필수 (기존 동작)
    # request_type="invigilation"  → timetable_entry_id=None, 감독 배정 ID 사용
    request_type: str = "timetable"
    timetable_entry_id: Optional[int]
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
    # ── 감독 스왑 대상 감독 배정 (2026-09-19 신규) ───────────────────────────
    # request_type="invigilation" 인 경우에만 값이 있습니다.
    # invigilation_assignment_id     : 신청자 본인의 감독 슬롯
    # swap_partner_invigilation_id   : 감독을 맞바꿀 상대의 감독 슬롯
    invigilation_assignment_id: Optional[int] = None
    swap_partner_invigilation_id: Optional[int] = None
    # [DEPRECATED] 하드코딩된 2단계 결재 필드 — 하위 호환용 유지
    scheduler_approved_by: str = ""
    scheduler_approved_at: Optional[datetime] = None
    approved_by: str = ""
    approved_at: Optional[datetime] = None

    # ── 연쇄 교체(chain swap) 단계 목록 (2026-06-20 신규) ───────────────────
    # 신규 연쇄 교체 신청의 경우 steps 가 채워집니다.
    # 기존 단일 swap/변경 신청은 steps 가 빈 리스트([]) 로 응답되며,
    # 클라이언트는 기존 필드(swap_partner_entry_id, new_*_id)를 그대로 사용합니다.
    # 서버가 응답 생성 시 자동으로 주입합니다(모델 컬럼 아님).
    steps: list["ChangeRequestStepOut"] = []

    model_config = {"from_attributes": True}


# ── 변경 신청 단계 (연쇄 교체 지원, 2026-06-20 신규) ───────────────────────

class ChangeRequestStepCreate(BaseModel):
    """
    변경 신청 단계 생성 요청.

    연쇄 교체 신청 시 클라이언트가 ChangeRequestCreate.steps 로 전달합니다.

    step_type 별 필수 필드:
      - "swap": target_entry_id 필수. new_*_id 는 모두 None.
      - "change": new_subject_id / new_teacher_id / new_room_id 중 최소 하나.
                  target_entry_id 는 None.

    affected_teacher_id:
      서버가 단계 유형에 따라 자동으로 설정합니다. 클라이언트가 명시적으로
      지정할 필요는 없지만(무시됨), 스키마 호환성을 위해 필드는 남겨둡니다.
    """
    step_type: str = "swap"            # "swap" | "change"
    source_entry_id: Optional[int] = None
    target_entry_id: Optional[int] = None
    new_subject_id: Optional[int] = None
    new_teacher_id: Optional[int] = None
    new_room_id: Optional[int] = None
    # ── 감독 연쇄 스왑 확장 필드 (2026-09-19 신규) ───────────────────────────
    # 감독 배정(InvigilationAssignment)을 대상으로 하는 단계에서 사용합니다.
    # 수업 시간표 단계에서는 None 입니다.
    source_invigilation_id: Optional[int] = None
    target_invigilation_id: Optional[int] = None


class ChangeRequestStepOut(BaseModel):
    """변경 신청 단계 응답."""
    id: int
    step_order: int
    step_type: str
    # 2026-09-19: 감독 연쇄 스왑 단계 지원을 위해 Optional 로 완화
    source_entry_id: Optional[int]
    target_entry_id: Optional[int]
    new_subject_id: Optional[int]
    new_teacher_id: Optional[int]
    new_room_id: Optional[int]
    # 감독 배정 대상 단계 확장 필드 (수업 시간표 단계에서는 None)
    source_invigilation_id: Optional[int] = None
    target_invigilation_id: Optional[int] = None
    affected_teacher_id: Optional[int]
    consent_status: str
    consent_by_user_id: Optional[int]
    consent_at: Optional[datetime]
    # 단계 표시용 라벨 (서버가 채움 — 예: "월3 수학(김) ↔ 화2 영어(이)")
    label: str = ""
    # 동의한 사용자 이름 (있으면 서버가 채움)
    consent_by_username: str = ""

    model_config = {"from_attributes": True}


class ChangeRequestCreate(BaseModel):
    """
    변경 신청 생성 요청.

    2026-06-13 변경:
      - swap_partner_entry_id 추가. 두 슬롯을 맞바꾸는 교환 신청에 사용.

    2026-06-20 변경:
      - steps 추가. 연쇄 교체(chain swap) 신청 시 여러 단계를 한 번에 제출.
      - steps 가 있으면 연쇄 교체로 처리되고, 없으면 기존 단일 신청 로직 유지.
        (하위 호환성 보장 — 기존 클라이언트 코드 수정 없이 동작)

    2026-09-19 변경:
      - request_type 추가. 기존 수업 시간표 변경("timetable", 기본값) 외에
        시험 감독 스왑 신청("invigilation")을 같은 엔드포인트로 제출합니다.
        감독 스왑은 timetable_entry_id 대신 invigilation_assignment_id 와
        swap_partner_invigilation_id 로 대상을 지정합니다.
    """
    request_type: str = "timetable"   # "timetable" | "invigilation"
    # timetable_entry_id: request_type="timetable" 인 경우 필수.
    # 감독 스왑 신청에서는 None 입니다 (서버에서 유형별 검증).
    timetable_entry_id: Optional[int] = None
    new_subject_id: Optional[int] = None
    new_teacher_id: Optional[int] = None
    new_room_id: Optional[int] = None
    reason: str = ""
    swap_partner_entry_id: Optional[int] = None
    # ── 감독 스왑 신청 필드 (2026-09-19 신규, request_type="invigilation") ──
    # invigilation_assignment_id   : 신청자 본인의 감독 슬롯 ID (필수)
    # swap_partner_invigilation_id : 감독을 맞바꿀 상대 감독 슬롯 ID (필수)
    invigilation_assignment_id: Optional[int] = None
    swap_partner_invigilation_id: Optional[int] = None
    # 연쇄 교체 단계들. 비어 있으면 단일 신청으로 취급.
    steps: Optional[list[ChangeRequestStepCreate]] = None


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

    2026-06-20 변경:
      - step_id 추가. 연쇄 교체 신청의 경우 각 단계마다 별도 동의가 필요하므로,
        어느 단계에 대한 동의인지 명시해야 합니다.
      - step_id 가 None 이면 기존 단일 동의 로직(부모의 affected_teacher_id 사용).
    """
    action: str  # "approve" | "reject"
    step_id: Optional[int] = None  # 연쇄 교체인 경우 처리할 단계 ID


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


# ── 연쇄 교체 경로 탐색 (2026-06-20 신규) ───────────────────────────────────

class SwapStepOut(BaseModel):
    """
    연쇄 교체 경로의 개별 단계.

    한 단계는 두 슬롯(source_entry_id ↔ target_entry_id) 간의 단순 swap 을 나타냅니다.
    연쇄 교체는 여러 단계의 시퀀스로 구성됩니다.
    """
    step_order: int                 # 1부터 시작하는 단계 순서
    source_entry_id: int
    target_entry_id: int
    # 사용자 표시용 라벨 — 예: "월3 수학(김선생) ↔ 화2 영어(이선생)"
    label: str
    # 이 단계에서 동의가 필요한 교사 ID 목록
    affected_teacher_ids: list[int] = []


class SwapPathOut(BaseModel):
    """
    연쇄 교체 경로 하나.

    source_entry_id 에서 target_entry_id 로 가는 검증된 단계들의 시퀀스입니다.
    시스템이 자동 탐색한 후보 경로를 사용자에게 제시할 때 사용됩니다.
    """
    steps: list[SwapStepOut]
    step_count: int                  # 단계 수 (len(steps) 와 동일하지만 UI 편의용)
    # 이 경로 전체에서 동의가 필요한 모든 교사 ID (중복 제거)
    related_teacher_ids: list[int] = []
    # 경로 요약 — 예: "3단계 연쇄 교체, 3명 동의 필요"
    summary: str


class SwapPathsResponse(BaseModel):
    """GET /timetable/swap-paths 응답."""
    source_entry_id: int
    target_entry_id: int
    paths: list[SwapPathOut]
    # 탐색 제한/성능 안내용 메시지
    note: str = ""


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


# ── 시험 시간표 + 시험 감독 시간표 (2026-09-19 신규) ──────────────────────────
#
# 시험 기능의 입출력 스키마입니다. 관리자 앱은 직접 DB 접근이라 이 스키마를
# 쓰지 않지만, 교사 앱(ApiClient)과 서버 간 직렬화에 사용됩니다.
# 학급(student_count)·변경 신청(request_type) 관련 확장은 위 각 섹션 참조.


class ExamOut(BaseModel):
    """
    시험 정보 응답.

    target_grade_ids 는 DB 에 JSON 문자열("[1, 2]")로 저장되어 있어
    그대로 전달합니다. 클라이언트에서 json.loads() 로 파싱해 사용합니다.
    (관리자 앱은 직접 DB 를 읽으므로 동일하게 취급)
    """
    id: int
    term_id: int
    name: str
    exam_type: str
    school_level: str
    target_grade_ids: str
    start_date: date
    end_date: date
    first_period_start: time
    periods_per_day: int
    break_minutes: int
    prep_minutes: int
    exam_minutes: int
    max_subjects_per_day: int
    ban_homeroom_invigilation: bool
    ban_own_subject: bool
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExamCreate(BaseModel):
    """
    시험 생성 요청.

    start_date ~ end_date 기간 동안 periods_per_day 만큼의 교시가 매일
    자동 생성됩니다 (ExamPeriod). 시각은 first_period_start 와
    exam_minutes / break_minutes 로 계산됩니다.

    필드 제약:
      - periods_per_day: ge=1, le=10 — 비현실적 교시 수 차단
      - exam_minutes: ge=10, le=240 — 시험 시간 상하한
      - target_grade_ids: 비어 있으면 전체 학년이 시험 대상
    """
    term_id: int
    name: str = Field(..., min_length=1, max_length=100)
    exam_type: str = "midterm"                       # midterm / final / mock
    school_level: str = "high"                       # high / middle
    start_date: date
    end_date: date
    target_grade_ids: list[int] = []                 # 비어 있으면 전체 학년
    first_period_start: time = time(8, 30)           # 요구사항 기본값: 08:30
    periods_per_day: int = Field(default=3, ge=1, le=10)
    break_minutes: int = Field(default=10, ge=0, le=60)
    prep_minutes: int = Field(default=5, ge=0, le=30)
    exam_minutes: int = Field(default=50, ge=10, le=240)
    max_subjects_per_day: int = Field(default=3, ge=1, le=10)
    ban_homeroom_invigilation: bool = True
    ban_own_subject: bool = True


class ExamUpdate(BaseModel):
    """
    시험 수정 요청 (부분 수정).

    기간(start_date/end_date)·시각·교시 수가 바뀌면 서버가 ExamPeriod 를
    재생성합니다. 이때 기존 감독 배정/시험 칸은 대상 교시가 사라지면 함께
    삭제되므로, 확정(published)된 시험은 수정을 거부합니다 (서버 측 검증).
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    exam_type: Optional[str] = None
    school_level: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    target_grade_ids: Optional[list[int]] = None
    first_period_start: Optional[time] = None
    periods_per_day: Optional[int] = Field(None, ge=1, le=10)
    break_minutes: Optional[int] = Field(None, ge=0, le=60)
    prep_minutes: Optional[int] = Field(None, ge=0, le=30)
    exam_minutes: Optional[int] = Field(None, ge=10, le=240)
    max_subjects_per_day: Optional[int] = Field(None, ge=1, le=10)
    ban_homeroom_invigilation: Optional[bool] = None
    ban_own_subject: Optional[bool] = None


class ExamPeriodOut(BaseModel):
    """시험 교시(날짜×교시) 응답. 준비령 시각은 end_time - prep_minutes 로 파생."""
    id: int
    exam_id: int
    exam_date: date
    period: int
    start_time: time
    end_time: time

    model_config = {"from_attributes": True}


class ExamEntryOut(BaseModel):
    """시험 시간표 칸 응답 (조회 편의용 이름 필드는 서버가 주입)."""
    id: int
    exam_id: int
    period_id: int
    grade_id: int
    subject_id: int
    is_manual: bool
    subject_name: Optional[str] = None    # 서버가 주입 (Subject.name)
    subject_short: Optional[str] = None   # 서버가 주입 (Subject.short_name)
    subject_color: Optional[str] = None   # 서버가 주입 (Subject.color_hex)

    model_config = {"from_attributes": True}


class ExamEntryUpdate(BaseModel):
    """
    시험 시간표 칸 수동 편집 요청.

    관리자가 그리드에서 칸을 더블클릭해 과목을 바꿀 때 사용합니다.
    is_manual=True 로 표시되어, 이후 자동 배치 재실행 시 안내 메시지의
    근거가 됩니다.
    """
    subject_id: int


class InvigilationAssignmentOut(BaseModel):
    """감독 배정 응답 (교시·반·교사 이름은 서버가 조인해 주입)."""
    id: int
    exam_id: int
    period_id: int
    school_class_id: int
    teacher_id: Optional[int]
    pair_index: int
    # 조회 편의용 — 서버가 조인 결과로 채웁니다
    exam_date: Optional[date] = None
    period_number: Optional[int] = None      # ExamPeriod.period
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    class_name: Optional[str] = None         # SchoolClass.display_name
    class_grade_id: Optional[int] = None     # SchoolClass.grade_id
    teacher_name: Optional[str] = None       # Teacher.name (미배정이면 None)
    subject_name: Optional[str] = None       # 그 교시 시험 과목명 (표시용)

    model_config = {"from_attributes": True}


class InvigilationUpdate(BaseModel):
    """
    감독 배정 수동 변경 요청.

    관리자가 감독표에서 미배정/배정된 슬롯의 감독교사를 직접 바꿀 때
    사용합니다. teacher_id=None 으로 미배정 상태로 되돌릴 수 있습니다.
    """
    teacher_id: Optional[int] = None


class InvigilationConstraintCreate(BaseModel):
    """
    감독 불가 신청 생성 요청 (교사 제출).

    period=None 이면 해당 날짜의 전 교시가 불가 대상입니다.
    신청 즉시 감독 배정에 반영되지 않고 관리자 승인(approved) 후에만
    하드 제약으로 반영됩니다 (미승인 상태로 감독이 빠지는 사고 방지).
    exam_id 는 경로 파라미터(/exams/{exam_id}/constraints)에서 오므로
    본문 스키마에는 포함하지 않습니다 — 두 곳에 두면 불일치 검증이 필요합니다.
    """
    exam_date: date
    period: Optional[int] = Field(None, ge=1, le=10)  # None = 전 교시
    reason: str = Field(default="", max_length=500)


class InvigilationConstraintOut(BaseModel):
    """감독 불가 신청 응답 (교사 이름은 서버가 주입)."""
    id: int
    exam_id: int
    teacher_id: int
    exam_date: date
    period: Optional[int]
    reason: str
    status: str
    requested_at: datetime
    reviewed_by: str
    reviewed_at: Optional[datetime]
    teacher_name: Optional[str] = None    # 서버가 주입

    model_config = {"from_attributes": True}


class InvigilationConstraintReview(BaseModel):
    """
    감독 불가 신청 승인/거절 요청 (일과계/교감).

    approved_by 는 서버가 무시하고 현재 로그인 사용자명으로 덮어씁니다
    (ChangeRequestReview 와 동일한 actor impersonation 방지 정책).
    """
    action: str            # "approve" | "reject"
    reviewed_by: str = ""  # 서버가 무시하고 current_user.username 사용
