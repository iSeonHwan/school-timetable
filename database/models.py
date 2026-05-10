"""
SQLAlchemy ORM 모델 정의

데이터 입력 순서와 의존 관계 (Data Dependency Graph):
  앱에서 데이터를 입력해야 하는 순서는 아래 관계 화살표를 따릅니다.
  화살표 방향 = "먼저 입력되어야 함":

    ① AcademicTerm (학기)  ──→  TimetableEntry (시간표)
    ② Grade (학년)         ──→  SchoolClass (반)
    ③ SchoolClass (반)     ──→  Teacher.homeroom_class_id (담임 학반)
                            ──→  SubjectClassAssignment (시수 배정)
                            ──→  TimetableEntry (시간표)
    ④ Room (교실)          ──→  SchoolClass.homeroom_room_id (담임 교실)
                            ──→  SubjectClassAssignment.preferred_room_id
                            ──→  TimetableEntry.room_id
    ⑤ Subject (교과목)     ──→  SubjectClassAssignment (시수 배정)
    ⑥ Teacher (교사)       ──→  SubjectClassAssignment (시수 배정)
                            ──→  TeacherConstraint (불가 시간)

  즉, 권장 입력 순서:
    학기 추가 → 학년/반 등록 → 교실 등록 → 교과목 등록 → 교사 등록 → 시수 배정 → 시간표 생성

테이블 구조 요약:
  AcademicTerm          학년도/학기 (예: 2025년 1학기)
  Grade                 학년 (1학년, 2학년, 3학년)
  SchoolClass           반 (1-1, 1-2 …)  Grade 에 속함
  Room                  교실·특별실
  Subject               교과목 (수학, 과학 …)
  Teacher               교사
  SubjectClassAssignment  "어떤 반의 어떤 과목을 누가 주당 몇 시간 가르치나" 연결 테이블
  TimetableEntry        실제 시간표 한 칸 (학기·반·교과·교사·교실·요일·교시)
  TeacherConstraint     교사 불가/선호/기피 시간 슬롯
  SchoolEvent           학사일정 (시험, 방학, 공휴일 …)
  TimetableChangeLog    시간표 변경 이력 (생성/수정/삭제)
  TimetableChangeRequest  당일 시간표 변경 신청 (pending → approved/rejected)

ER 관계 다이어그램:
  Grade 1─* SchoolClass 1─* SubjectClassAssignment *─1 Subject
                                                    *─1 Teacher
  AcademicTerm 1─* TimetableEntry *─1 SchoolClass
                                  *─1 Subject
                                  *─1 Teacher
                                  *─1 Room (nullable)
  Teacher 1─* TeacherConstraint

Cascade 삭제 흐름:
  Grade 삭제 → SchoolClass 삭제 → SubjectClassAssignment 삭제, TimetableEntry 삭제
  AcademicTerm 삭제 → TimetableEntry 삭제, SchoolEvent 삭제
  Teacher 삭제 → TeacherConstraint 삭제
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
    year       = Column(Integer, nullable=False)           # 연도 (예: 2025)
    semester   = Column(Integer, nullable=False)           # 학기: 1 또는 2
    start_date = Column(Date)                              # 학기 시작일
    end_date   = Column(Date)                              # 학기 종료일
    is_current = Column(Boolean, default=False)            # 현재 학기 여부

    # cascade="all, delete-orphan": 학기 삭제 시 연결된 시간표·일정도 함께 삭제됩니다.
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
    room_type = Column(String(20), default="일반")   # 일반 / 과학실 / 음악실 등
    capacity  = Column(Integer, default=30)           # 수용 인원
    floor     = Column(Integer, default=1)            # 층
    notes     = Column(Text, default="")              # 비고

    def __str__(self):
        return self.name


# ── 학년 / 반 ──────────────────────────────────────────────────────────────

class Grade(Base):
    """학년 정보 (1학년, 2학년, 3학년)."""
    __tablename__ = "grades"

    id           = Column(Integer, primary_key=True)
    grade_number = Column(Integer, nullable=False)    # 학년 번호 (1, 2, 3)
    name         = Column(String(20), nullable=False) # 표시명 (예: "1학년")

    # cascade: 학년 삭제 시 소속 반도 함께 삭제됩니다.
    classes = relationship("SchoolClass", back_populates="grade", cascade="all, delete-orphan")

    def __str__(self):
        return self.name


class SchoolClass(Base):
    """반 정보. 각 반은 하나의 학년에 속합니다."""
    __tablename__ = "school_classes"

    id               = Column(Integer, primary_key=True)
    grade_id         = Column(Integer, ForeignKey("grades.id"), nullable=False)
    class_number     = Column(Integer, nullable=False)     # 반 번호 (1, 2, 3 …)
    display_name     = Column(String(20), nullable=False)  # 화면 표시명 (예: "1-1")
    homeroom_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)  # 담임 교실

    grade              = relationship("Grade", back_populates="classes")
    homeroom_room      = relationship("Room")
    subject_assignments = relationship(
        "SubjectClassAssignment", back_populates="school_class", cascade="all, delete-orphan"
    )
    timetable_entries  = relationship(
        "TimetableEntry", back_populates="school_class", cascade="all, delete-orphan"
    )

    def __str__(self):
        return self.display_name


# ── 교과목 ─────────────────────────────────────────────────────────────────

class Subject(Base):
    """교과목 정보. 시간표 셀 색상과 특별실 필요 여부를 포함합니다."""
    __tablename__ = "subjects"

    id                = Column(Integer, primary_key=True)
    name              = Column(String(50), nullable=False)   # 전체 교과명 (예: 수학)
    short_name        = Column(String(20), nullable=False)   # 약어 (예: 수)
    color_hex         = Column(String(7), default="#E3F2FD") # 셀 배경색 (#RRGGBB)
    needs_special_room = Column(Boolean, default=False)      # 특별실(과학실 등) 필요 여부

    assignments = relationship("SubjectClassAssignment", back_populates="subject")

    def __str__(self):
        return self.name


# ── 교사 ───────────────────────────────────────────────────────────────────

class Teacher(Base):
    """교사 정보. 담임 여부와 일 최대 수업 수를 관리합니다."""
    __tablename__ = "teachers"

    id                 = Column(Integer, primary_key=True)
    name               = Column(String(30), nullable=False)
    employee_number    = Column(String(20), default="")     # 교원번호 (선택)
    is_homeroom        = Column(Boolean, default=False)     # 담임 여부
    homeroom_class_id  = Column(Integer, ForeignKey("school_classes.id"), nullable=True)
    max_daily_classes  = Column(Integer, default=5)         # 하루 최대 수업 가능 교시 수

    homeroom_class    = relationship("SchoolClass", foreign_keys=[homeroom_class_id])
    subject_assignments = relationship("SubjectClassAssignment", back_populates="teacher")
    # cascade: 교사 삭제 시 해당 교사의 불가 시간 제약도 삭제됩니다.
    constraints       = relationship(
        "TeacherConstraint", back_populates="teacher", cascade="all, delete-orphan"
    )

    def __str__(self):
        return self.name


# ── 교과·반·교사 배정 ──────────────────────────────────────────────────────

class SubjectClassAssignment(Base):
    """
    '어떤 반(school_class)이 어떤 교과(subject)를 누가(teacher) 주당 몇 시간 가르치나'를
    나타내는 연결 테이블입니다. 시간표 자동 생성 알고리즘의 입력 데이터가 됩니다.
    """
    __tablename__ = "subject_class_assignments"

    id              = Column(Integer, primary_key=True)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id      = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    weekly_hours    = Column(Integer, nullable=False, default=1)  # 주당 시수
    preferred_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)  # 선호 교실

    school_class   = relationship("SchoolClass", back_populates="subject_assignments")
    subject        = relationship("Subject", back_populates="assignments")
    teacher        = relationship("Teacher", back_populates="subject_assignments")
    preferred_room = relationship("Room")


# ── 시간표 항목 ────────────────────────────────────────────────────────────

class TimetableEntry(Base):
    """
    시간표의 단일 칸(슬롯)을 나타냅니다.
    day_of_week: 1=월요일 … 5=금요일
    period     : 1=1교시 … 7=7교시 (최대 교시 수는 생성 시 설정)
    is_fixed   : True 면 자동 생성 시 해당 칸을 덮어쓰지 않습니다 (미래 확장용).
    """
    __tablename__ = "timetable_entries"

    id              = Column(Integer, primary_key=True)
    term_id         = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id      = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    room_id         = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    day_of_week     = Column(Integer, nullable=False)   # 1(월) ~ 5(금)
    period          = Column(Integer, nullable=False)   # 1 ~ max_periods
    is_fixed        = Column(Boolean, default=False)    # 고정 슬롯 여부
    # default 에 함수 객체(datetime.now)를 전달하면 SQLAlchemy 가 삽입 시점에 호출합니다.
    created_at      = Column(DateTime, default=datetime.now)
    updated_at      = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    term         = relationship("AcademicTerm", back_populates="timetable_entries")
    school_class = relationship("SchoolClass", back_populates="timetable_entries")
    subject      = relationship("Subject")
    teacher      = relationship("Teacher")
    room         = relationship("Room")


# ── 교사 제약 조건 ─────────────────────────────────────────────────────────

class TeacherConstraint(Base):
    """
    교사별 시간 슬롯 제약 조건입니다.
    constraint_type:
      - "unavailable" : 절대 불가 (하드 제약, 시간표 생성 시 해당 슬롯에 배치하지 않음)
      - "preferred"   : 선호 (소프트 제약, 미래 확장 예정)
      - "avoid"       : 기피 (소프트 제약, 미래 확장 예정)
    """
    __tablename__ = "teacher_constraints"

    id              = Column(Integer, primary_key=True)
    teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    day_of_week     = Column(Integer, nullable=False)      # 1(월) ~ 5(금)
    period          = Column(Integer, nullable=False)      # 1 ~ max_periods
    constraint_type = Column(String(20), nullable=False)   # unavailable / preferred / avoid

    teacher = relationship("Teacher", back_populates="constraints")


# ── 학사일정 ───────────────────────────────────────────────────────────────

class SchoolEvent(Base):
    """
    학사일정 항목 (개교기념일, 시험기간, 방학, 공휴일, 축제, 행사 등).
    start_date ~ end_date 범위로 지정하며, 단일 날짜는 start_date == end_date.
    """
    __tablename__ = "school_events"

    id          = Column(Integer, primary_key=True)
    term_id     = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    title       = Column(String(100), nullable=False)
    event_type  = Column(String(20), nullable=False, default="기타")
    # 지원 유형: 개교기념일, 시험, 축제, 방학, 공휴일, 행사, 기타
    start_date  = Column(Date, nullable=False)
    end_date    = Column(Date, nullable=False)
    description = Column(Text, default="")
    color_hex   = Column(String(7), default="#E3F2FD")  # 캘린더 표시 색상

    term = relationship("AcademicTerm", back_populates="school_events")

    def __str__(self):
        return self.title


# ── 변경 이력 ──────────────────────────────────────────────────────────────

class TimetableChangeLog(Base):
    """
    시간표 항목의 생성·수정·삭제 이력을 기록합니다.
    details 컬럼에 JSON 형태로 변경 전후 데이터를 저장합니다.
      생성: {"after": {...}}
      수정: {"before": {...}, "after": {...}}
      삭제: {"deleted": {...}}
    """
    __tablename__ = "timetable_change_logs"

    id                 = Column(Integer, primary_key=True)
    # 삭제된 항목은 timetable_entries 에서 제거되므로 nullable=True 로 설정합니다.
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
    당일 시간표 변경 신청 워크플로 테이블입니다.
    신청 → 관리자 승인(approved) 또는 거절(rejected) 흐름을 지원합니다.

    status 값:
      - "pending"  : 승인 대기 중
      - "approved" : 승인 완료 (TimetableEntry 에 즉시 반영됨)
      - "rejected" : 거절됨
    """
    __tablename__ = "timetable_change_requests"

    id                  = Column(Integer, primary_key=True)
    timetable_entry_id  = Column(Integer, ForeignKey("timetable_entries.id"), nullable=False)
    new_subject_id      = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    new_teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    new_room_id         = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    status              = Column(String(20), nullable=False, default="pending")
    reason              = Column(Text, default="")           # 변경 사유
    requested_by        = Column(String(30), default="")     # 신청자 이름 (미래 로그인 기능 대비)
    requested_at        = Column(DateTime, default=datetime.now)
    approved_by         = Column(String(30), default="")     # 승인자 이름
    approved_at         = Column(DateTime, nullable=True)    # 승인/거절 일시

    timetable_entry = relationship("TimetableEntry")
    new_subject     = relationship("Subject", foreign_keys=[new_subject_id])
    new_teacher     = relationship("Teacher", foreign_keys=[new_teacher_id])
    new_room        = relationship("Room", foreign_keys=[new_room_id])
