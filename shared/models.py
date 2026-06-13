"""
공통 SQLAlchemy ORM 모델 정의

server/, admin_app/, teacher_app/ 세 프로그램이 모두 이 파일을 참조합니다.
기존 database/models.py 의 모든 모델을 포함하며,
사용자 인증(User)과 채팅(ChatMessage) 테이블이 추가되었습니다.

테이블 목록:
  [기존]
  AcademicTerm          학년도/학기
  Grade                 학년
  SchoolClass           반
  Room                  교실·특별실
  Subject               교과목
  Teacher               교사
  SubjectClassAssignment  반·교과·교사·시수 연결
  TimetableEntry        시간표 단일 칸
  TeacherConstraint     교사 불가/선호/기피 시간
  SchoolEvent           학사일정
  TimetableChangeLog    시간표 변경 이력
  TimetableChangeRequest  당일 시간표 변경 신청

  [신규]
  User                  앱 로그인 계정 (관리자 / 교사)
  ChatMessage           전체 공개 채팅 메시지
  ApprovalWorkflow      설정 가능한 결재 워크플로우
  ApprovalStep          워크플로우의 개별 결재 단계
"""
import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey,
    Date, DateTime, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """모든 ORM 모델의 기반 클래스 — SQLAlchemy 2.0 선언형 스타일."""
    pass


# ── 학기 ───────────────────────────────────────────────────────────────────

class AcademicTerm(Base):
    """학년도·학기 정보. is_current=True 인 항목이 '현재 학기'로 간주됩니다."""
    __tablename__ = "academic_terms"

    id         = Column(Integer, primary_key=True)
    year       = Column(Integer, nullable=False)
    semester   = Column(Integer, nullable=False)
    start_date = Column(Date)
    end_date   = Column(Date)
    is_current = Column(Boolean, default=False)

    timetable_entries = relationship(
        "TimetableEntry", back_populates="term", cascade="all, delete-orphan"
    )
    school_events = relationship(
        "SchoolEvent", back_populates="term", cascade="all, delete-orphan"
    )

    def __str__(self):
        return f"{self.year}년 {self.semester}학기"


# ── 교실 ───────────────────────────────────────────────────────────────────

class Room(Base):
    """교실 및 특별실 정보."""
    __tablename__ = "rooms"

    id        = Column(Integer, primary_key=True)
    name      = Column(String(50), nullable=False)
    room_type = Column(String(20), default="일반")
    capacity  = Column(Integer, default=30)
    floor     = Column(Integer, default=1)
    notes     = Column(Text, default="")

    def __str__(self):
        return self.name


# ── 학년 / 반 ──────────────────────────────────────────────────────────────

class Grade(Base):
    """학년 정보 (1학년, 2학년, 3학년)."""
    __tablename__ = "grades"

    id           = Column(Integer, primary_key=True)
    grade_number = Column(Integer, nullable=False)
    name         = Column(String(20), nullable=False)

    classes = relationship("SchoolClass", back_populates="grade", cascade="all, delete-orphan")

    def __str__(self):
        return self.name


class SchoolClass(Base):
    """반 정보. 각 반은 하나의 학년에 속합니다."""
    __tablename__ = "school_classes"

    id               = Column(Integer, primary_key=True)
    grade_id         = Column(Integer, ForeignKey("grades.id"), nullable=False)
    class_number     = Column(Integer, nullable=False)
    display_name     = Column(String(20), nullable=False)
    homeroom_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)

    grade               = relationship("Grade", back_populates="classes")
    homeroom_room       = relationship("Room")
    subject_assignments = relationship(
        "SubjectClassAssignment", back_populates="school_class", cascade="all, delete-orphan"
    )
    timetable_entries   = relationship(
        "TimetableEntry", back_populates="school_class", cascade="all, delete-orphan"
    )

    def __str__(self):
        return self.display_name


# ── 교과목 ─────────────────────────────────────────────────────────────────

class Subject(Base):
    """교과목 정보."""
    __tablename__ = "subjects"

    id                 = Column(Integer, primary_key=True)
    name               = Column(String(50), nullable=False)
    short_name         = Column(String(20), nullable=False)
    color_hex          = Column(String(7), default="#E3F2FD")
    needs_special_room = Column(Boolean, default=False)

    assignments = relationship("SubjectClassAssignment", back_populates="subject")

    def __str__(self):
        return self.name


# ── 교사 ───────────────────────────────────────────────────────────────────

class Teacher(Base):
    """교사 정보."""
    __tablename__ = "teachers"

    id                = Column(Integer, primary_key=True)
    name              = Column(String(30), nullable=False)
    employee_number   = Column(String(20), default="")
    is_homeroom       = Column(Boolean, default=False)
    homeroom_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=True)
    max_daily_classes = Column(Integer, default=5)

    homeroom_class      = relationship("SchoolClass", foreign_keys=[homeroom_class_id])
    subject_assignments = relationship("SubjectClassAssignment", back_populates="teacher")
    constraints         = relationship(
        "TeacherConstraint", back_populates="teacher", cascade="all, delete-orphan"
    )
    # 이 교사에 연결된 앱 계정 (1:1, nullable — 계정 없는 교사도 허용)
    user = relationship("User", back_populates="teacher", uselist=False)

    def __str__(self):
        return self.name


# ── 교과·반·교사 배정 ──────────────────────────────────────────────────────

class SubjectClassAssignment(Base):
    """
    반·교과·교사·주당시수 연결 테이블. 시간표 자동 생성의 입력 데이터.

    2026-06-13 변경:
      - term_id 컬럼 추가. 학기별로 시수 배정을 분리하여, 2학기 데이터가
        1학기 생성에 섞이지 않도록 합니다.
      - term_id 는 모델상 nullable 로 유지하되, API/스키마에서 필수 입력을
        요구합니다. 이는 기존 SQLite DB에 컬럼을 추가할 때 NOT NULL 제약으로
        인한 마이그레이션 실패를 피하기 위함입니다.
    """
    __tablename__ = "subject_class_assignments"

    id                = Column(Integer, primary_key=True)
    school_class_id   = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id        = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id        = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    weekly_hours      = Column(Integer, nullable=False, default=1)
    preferred_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    # ── 학기 구분 (신규) ─────────────────────────────────────────────────
    # nullable=True 인 이유: 기존 DB 마이그레이션 시 NOT NULL 추가가 SQLite 에서
    # 까다로우므로, 애플리케이션 레벨에서 term_id 를 강제합니다.
    term_id           = Column(Integer, ForeignKey("academic_terms.id"), nullable=True)

    school_class   = relationship("SchoolClass", back_populates="subject_assignments")
    subject        = relationship("Subject", back_populates="assignments")
    teacher        = relationship("Teacher", back_populates="subject_assignments")
    preferred_room = relationship("Room")
    term           = relationship("AcademicTerm")


# ── 시간표 항목 ────────────────────────────────────────────────────────────

class TimetableEntry(Base):
    """시간표의 단일 칸(슬롯). day_of_week: 1=월 ~ 5=금, period: 1~7."""
    __tablename__ = "timetable_entries"

    id              = Column(Integer, primary_key=True)
    term_id         = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id      = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    room_id         = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    day_of_week     = Column(Integer, nullable=False)
    period          = Column(Integer, nullable=False)
    is_fixed        = Column(Boolean, default=False)
    # 함수 객체를 전달하면 SQLAlchemy 가 삽입(default) 및 수정(onupdate) 시점에 각각 호출합니다.
    created_at      = Column(DateTime, default=datetime.now)
    updated_at      = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    term         = relationship("AcademicTerm", back_populates="timetable_entries")
    school_class = relationship("SchoolClass", back_populates="timetable_entries")
    subject      = relationship("Subject")
    teacher      = relationship("Teacher")
    room         = relationship("Room")


# ── 교사 제약 조건 ─────────────────────────────────────────────────────────

class TeacherConstraint(Base):
    """교사별 시간 슬롯 제약. constraint_type: unavailable / preferred / avoid"""
    __tablename__ = "teacher_constraints"

    id              = Column(Integer, primary_key=True)
    teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    day_of_week     = Column(Integer, nullable=False)
    period          = Column(Integer, nullable=False)
    constraint_type = Column(String(20), nullable=False)

    teacher = relationship("Teacher", back_populates="constraints")


# ── 학사일정 ───────────────────────────────────────────────────────────────

class SchoolEvent(Base):
    """학사일정 항목 (시험, 방학, 공휴일, 행사 등)."""
    __tablename__ = "school_events"

    id          = Column(Integer, primary_key=True)
    term_id     = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    title       = Column(String(100), nullable=False)
    event_type  = Column(String(20), nullable=False, default="기타")
    start_date  = Column(Date, nullable=False)
    end_date    = Column(Date, nullable=False)
    description = Column(Text, default="")
    color_hex   = Column(String(7), default="#E3F2FD")

    term = relationship("AcademicTerm", back_populates="school_events")

    def __str__(self):
        return self.title


# ── 변경 이력 ──────────────────────────────────────────────────────────────

class TimetableChangeLog(Base):
    """시간표 항목의 생성·수정·삭제 이력. details 컬럼에 JSON으로 변경 전후 데이터 저장."""
    __tablename__ = "timetable_change_logs"

    id                 = Column(Integer, primary_key=True)
    timetable_entry_id = Column(Integer, ForeignKey("timetable_entries.id"), nullable=True)
    term_id            = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    school_class_id    = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    change_type        = Column(String(20), nullable=False)  # created / modified / deleted
    details            = Column(Text, default="")            # JSON 문자열
    changed_at         = Column(DateTime, default=datetime.now)

    term            = relationship("AcademicTerm")
    school_class    = relationship("SchoolClass")
    timetable_entry = relationship("TimetableEntry")


# ── 변경 신청 ──────────────────────────────────────────────────────────────

class TimetableChangeRequest(Base):
    """
    당일 시간표 변경 신청.

    status 흐름 (동적 결재 워크플로우 + 교사 동의):
      교사 제출
        ↓
      [피교사 동의가 필요하면] consent_status=pending
        → affected_teacher_id 교사가 승인하면 consent_status=approved
        → 거절하면 consent_status=rejected, status=rejected (최종)
        ↓
      status=pending, current_step=1
        → [단계별 승인: current_step 진행] → approved (TimetableEntry 에 반영)
      어느 단계든 거절 가능 → rejected

    approval_history: JSON 배열로 모든 단계별 승인/거절 기록을 저장합니다.
    [
      {"step": 1, "role": "admin", "action": "approve", "by": "admin", "at": "2024-..."},
      {"step": 2, "role": "vice_principal", "action": "approve", "by": "vp", "at": "2024-..."}
    ]

    current_step: 현재 진행 중인 단계 번호 (1-based). approved 시에는 총 단계 수 + 1.
                  동의 대기 중일 때는 0으로 시작하여, 동의 완료 후 1로 전환됩니다.

    2026-06-13 변경:
      - affected_teacher_id / consent_status / consent_by_user_id / consent_at:
        교사 간 교체/대리 수업 시 피교사의 사전 동의를 기록합니다.
      - swap_partner_entry_id: 두 시간표 슬롯을 맞바꾸는 교환 신청 시 상대 슬롯을
        기록합니다. 이때 affected_teacher_id 는 상대 슬롯의 현재 교사가 됩니다.
    """
    __tablename__ = "timetable_change_requests"

    id                 = Column(Integer, primary_key=True)
    timetable_entry_id = Column(Integer, ForeignKey("timetable_entries.id"), nullable=False)
    new_subject_id     = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    new_teacher_id     = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    new_room_id        = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    status             = Column(String(20), nullable=False, default="pending")
    reason             = Column(Text, default="")
    requested_by       = Column(String(30), default="")
    requested_at       = Column(DateTime, default=datetime.now)
    # 동적 결재 워크플로우 필드
    # 동의 단계가 있을 때는 0으로 시작하여, 동의 완료 후 1로 설정됩니다.
    current_step       = Column(Integer, nullable=False, default=0)
    approval_history   = Column(Text, default="[]")  # JSON 배열

    # ── 교사 동의(consent) 관련 필드 (신규) ─────────────────────────────
    # 피교사 동의가 필요한 경우 affected_teacher_id 에 해당 교사의 ID 를 저장.
    affected_teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    # not_required: 동의 불필요 (예: 교실만 변경)
    # pending       : 피교사의 동의 대기 중
    # approved      : 피교사 동의 완료
    # rejected      : 피교사 거절 (status=rejected 로 최종 처리)
    consent_status      = Column(String(20), nullable=False, default="not_required")
    consent_by_user_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    consent_at          = Column(DateTime, nullable=True)
    # 교환(swap) 상대 슬롯. swap 은 두 TimetableEntry 의 교사/과목을 동시에 바꿉니다.
    swap_partner_entry_id = Column(Integer, ForeignKey("timetable_entries.id"), nullable=True)

    # ── 신청 시점 슬롯 스냅샷 (신규) ────────────────────────────────────────
    # 변경 신청이 접수될 때 대상 슬롯(entry)과 교환 상대 슬롯(partner)의 현재
    # 상태를 JSON 문자열로 저장합니다.
    #
    # 저장 형식:
    # {
    #   "entry":   {"subject_id": 1, "teacher_id": 2, "room_id": 3},
    #   "partner": {"subject_id": 4, "teacher_id": 5, "room_id": 6}  # swap인 경우만
    # }
    #
    # 용도:
    #   결재 기간이 길어지는 경우(예: 며칠 뒤 최종 승인), 그 사이에 다른 변경 신청이
    #   같은 슬롯을 수정했을 수 있습니다. 최종 승인 시 스냅샷과 현재 DB 상태를
    #   비교하여 이 같은 타이밍 충돌(race condition)을 감지합니다.
    #
    # nullable=True 인 이유:
    #   이 컬럼이 추가되기 전에 생성된 기존 레코드는 스냅샷이 없습니다.
    #   None 이면 검증을 건너뜁니다 (하위 호환성 유지).
    change_snapshot    = Column(Text, nullable=True)

    # ── [DEPRECATED] 하드코딩된 2단계 결재 필드 ──────────────────────────
    # approval_history 및 ApprovalWorkflow 로 대체되었습니다.
    # 기존 운영 데이터 보존을 위해 컬럼 자체는 유지하지만,
    # 신규 코드에서는 사용하지 않습니다.
    # TODO: 모든 운영 DB 마이그레이션 완료 후 다음 메이저 버전에서 제거 예정.
    scheduler_approved_by = Column(String(30), default="")
    scheduler_approved_at = Column(DateTime, nullable=True)
    approved_by        = Column(String(30), default="")
    approved_at        = Column(DateTime, nullable=True)
    vice_principal_approved_by = Column(String(30), default="")
    vice_principal_approved_at = Column(DateTime, nullable=True)

    timetable_entry     = relationship("TimetableEntry", foreign_keys=[timetable_entry_id])
    swap_partner_entry  = relationship("TimetableEntry", foreign_keys=[swap_partner_entry_id])
    new_subject         = relationship("Subject", foreign_keys=[new_subject_id])
    new_teacher         = relationship("Teacher", foreign_keys=[new_teacher_id])
    new_room            = relationship("Room", foreign_keys=[new_room_id])
    affected_teacher    = relationship("Teacher", foreign_keys=[affected_teacher_id])
    consent_by_user     = relationship("User", foreign_keys=[consent_by_user_id])


# ── 사용자 계정 (신규) ─────────────────────────────────────────────────────

class User(Base):
    """
    앱 로그인 계정.

    role:
      - "admin"            : 일과계 선생님 (scheduler) — 전체 관리 권한
                             편제·교사·교과·교실 CRUD, 계정 관리, 시간표 생성·수정,
                             변경 신청 승인 (워크플로우 설정에 따라 단계별로)
      - "vice_principal"   : 교감 선생님 — 읽기 전용 + 변경 신청 승인 (워크플로우 설정에 따름)
      - "department_head"  : 교무부장 — 읽기 전용 + 변경 신청 승인 (워크플로우 설정에 따름)
      - "teacher"          : 교사 — 시간표 조회, 변경 신청 제출

    teacher_id 가 설정된 경우 Teacher 레코드와 연결됩니다.
    관리자 계정은 teacher_id 가 없을 수 있습니다 (None).
    password_hash 에는 bcrypt 해시가 저장됩니다 (평문 저장 금지).
    """
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True)
    username      = Column(String(50), nullable=False, unique=True)  # 로그인 아이디
    password_hash = Column(String(128), nullable=False)              # bcrypt 해시
    role          = Column(String(20), nullable=False, default="teacher")  # admin / vice_principal / department_head / teacher
    teacher_id    = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    is_active     = Column(Boolean, default=True)                    # 비활성화 시 로그인 차단
    created_at    = Column(DateTime, default=datetime.now)

    teacher       = relationship("Teacher", back_populates="user")
    chat_messages = relationship("ChatMessage", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def __str__(self):
        return self.username


# ── 채팅 메시지 (신규) ─────────────────────────────────────────────────────

class ChatMessage(Base):
    """
    전체 공개 채팅 메시지.

    관리자(admin)가 올린 메시지는 is_announcement=True 로 표시해 강조합니다.
    일과계(admin)는 메시지를 삭제하거나 오래된 메시지를 일괄 정리할 수 있습니다.

    서버는 CHAT_RETENTION_DAYS(기본 60일)보다 오래된 메시지를 12시간 간격으로
    자동 삭제합니다. 0 으로 설정하면 무기한 보관합니다.
    """
    __tablename__ = "chat_messages"

    id              = Column(Integer, primary_key=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    content         = Column(Text, nullable=False)
    is_announcement = Column(Boolean, default=False)  # True 면 공지 메시지로 강조
    created_at      = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="chat_messages")


# ── 알림 (신규) ──────────────────────────────────────────────────────────────

class Notification(Base):
    """
    사용자별 알림 (시스템 알림).

    교사 간 수업 교체 동의 요청, 동의 결과, 최종 승인/거절 등의 이벤트를
    기록하고 실시간으로 전달합니다. WebSocket 으로 접속 중인 사용자에게는
    즉시 전송되며, 오프라인 사용자는 재접속 후 GET /notifications 로 조회할
    수 있습니다.

    type 값:
      - consent_request   : 피교사에게 동의를 요청하는 알림
      - consent_approved  : 피교사가 동의한 알림 (요청자에게 전송)
      - consent_rejected  : 피교사가 거절한 알림 (요청자에게 전송)
      - status_update     : 변경 신청 상태가 진행된 알림
      - approved          : 최종 승인된 알림
      - rejected          : 최종 거절된 알림
    """
    __tablename__ = "notifications"

    id                = Column(Integer, primary_key=True)
    user_id           = Column(Integer, ForeignKey("users.id"), nullable=False)
    type              = Column(String(30), nullable=False)
    change_request_id = Column(Integer, ForeignKey("timetable_change_requests.id"), nullable=True)
    message           = Column(Text, nullable=False)
    is_read           = Column(Boolean, default=False)
    created_at        = Column(DateTime, default=datetime.now)

    user          = relationship("User", back_populates="notifications")
    change_request = relationship("TimetableChangeRequest")


# ── 결재 워크플로우 (설정 가능) ──────────────────────────────────────────────

class ApprovalWorkflow(Base):
    """
    설정 가능한 결재 워크플로우 정의.

    한 번에 하나의 워크플로우만 is_active=True 일 수 있습니다.
    admin_app 의 '결재 라인 설정' 페이지에서 생성·수정·활성화할 수 있습니다.

    예시:
      1단계 — 일과계가 바로 최종 승인
      2단계 — 일과계 1차 승인 → 교감 최종 승인 (기본값)
      3단계 — 일과계 검토 → 교무부장 검토 → 교감 최종 승인
    """
    __tablename__ = "approval_workflows"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(100), nullable=False)
    description = Column(Text, default="")
    is_active   = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.now)

    steps = relationship(
        "ApprovalStep", back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ApprovalStep.step_order",
    )


class ApprovalStep(Base):
    """
    워크플로우의 개별 결재 단계.

    각 단계는 특정 role 을 가진 사용자만 승인할 수 있습니다.
    role_required: "admin" | "vice_principal" | "department_head" 등
    step_order: 1부터 시작하는 단계 순서
    """
    __tablename__ = "approval_steps"

    id            = Column(Integer, primary_key=True)
    workflow_id   = Column(Integer, ForeignKey("approval_workflows.id"), nullable=False)
    step_order    = Column(Integer, nullable=False)
    role_required = Column(String(20), nullable=False)
    step_name     = Column(String(50), nullable=False)

    workflow = relationship("ApprovalWorkflow", back_populates="steps")
