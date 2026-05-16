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
"""
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
    """반·교과·교사·주당시수 연결 테이블. 시간표 자동 생성의 입력 데이터."""
    __tablename__ = "subject_class_assignments"

    id                = Column(Integer, primary_key=True)
    school_class_id   = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id        = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id        = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    weekly_hours      = Column(Integer, nullable=False, default=1)
    preferred_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)

    school_class   = relationship("SchoolClass", back_populates="subject_assignments")
    subject        = relationship("Subject", back_populates="assignments")
    teacher        = relationship("Teacher", back_populates="subject_assignments")
    preferred_room = relationship("Room")


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

    status 흐름 (2단계 승인):
      교사 제출 → pending → 일과계 1차 승인 → scheduler_approved
                           → 교감 최종 승인  → approved (TimetableEntry 에 반영)
      어느 단계든 거절 가능 → rejected

    approved_by / approved_at: 교감의 최종 승인 정보를 기록합니다.
    scheduler_approved_by / scheduler_approved_at: 일과계의 1차 승인 정보를 기록합니다.
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
    # 일과계 선생님의 1차 승인 정보
    scheduler_approved_by = Column(String(30), default="")
    scheduler_approved_at = Column(DateTime, nullable=True)
    # 교감 선생님의 최종 승인 정보
    approved_by        = Column(String(30), default="")
    approved_at        = Column(DateTime, nullable=True)

    timetable_entry = relationship("TimetableEntry")
    new_subject     = relationship("Subject", foreign_keys=[new_subject_id])
    new_teacher     = relationship("Teacher", foreign_keys=[new_teacher_id])
    new_room        = relationship("Room", foreign_keys=[new_room_id])


# ── 사용자 계정 (신규) ─────────────────────────────────────────────────────

class User(Base):
    """
    앱 로그인 계정.

    role:
      - "admin"            : 일과계 선생님 (scheduler) — 전체 관리 권한
                             편제·교사·교과·교실 CRUD, 계정 관리, 시간표 생성·수정,
                             변경 신청 1차 승인
      - "vice_principal"   : 교감 선생님 — 읽기 전용 + 변경 신청 최종 승인만 가능
                             시간표·편제 수정 불가, 계정 관리 불가
      - "teacher"          : 교사 — 시간표 조회, 변경 신청 제출

    teacher_id 가 설정된 경우 Teacher 레코드와 연결됩니다.
    관리자 계정은 teacher_id 가 없을 수 있습니다 (None).
    password_hash 에는 bcrypt 해시가 저장됩니다 (평문 저장 금지).
    """
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True)
    username      = Column(String(50), nullable=False, unique=True)  # 로그인 아이디
    password_hash = Column(String(128), nullable=False)              # bcrypt 해시
    role          = Column(String(20), nullable=False, default="teacher")  # admin / teacher
    teacher_id    = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    is_active     = Column(Boolean, default=True)                    # 비활성화 시 로그인 차단
    created_at    = Column(DateTime, default=datetime.now)

    teacher       = relationship("Teacher", back_populates="user")
    chat_messages = relationship("ChatMessage", back_populates="user")

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
