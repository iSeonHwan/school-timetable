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

  [2026-06-20 신규 — 연쇄 교체(chain swap) 지원]
  ChangeRequestStep     변경 신청의 개별 교체 단계 (1:N 자식 테이블)
                        — TimetableChangeRequest 1건이 여러 단계를 가질 수 있어
                          A↔C↔B 식의 연쇄 교체를 표현 가능
                        — 단계별로 별도의 affected_teacher_id/consent_status 를
                          가져 다교사 병렬 동의를 안전하게 처리

  [2026-09-19 신규 — 시험 시간표 + 시험 감독 시간표 지원]
  Exam                 시험 종류·기간 (중간/기말/모의고사, 교시 운영 규칙 포함)
  ExamPeriod           시험 날짜×교시 (시작/종료 시각 보관)
  ExamEntry            시험 시간표 한 칸 (날짜·교시·학년에 배치된 과목)
  InvigilationAssignment  감독 배정 (교시×반×조 슬롯에 배정된 교사)
  InvigilationConstraint  날짜 기반 감독 불가 신청 (기존 TeacherConstraint 는
                        요일+교시 기준이라 시험처럼 특정 날짜 기반 불가 신청을
                        담을 수 없어 별도 테이블로 추가)
"""
import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey,
    Date, DateTime, Text, Time, UniqueConstraint,
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
    # ── 반별 학생 수 (2026-09-19 신규 — 시험 감독 조 구성용) ────────────────
    # 시험 감독 배정에서 2인 1조 여부를 판단하는 기준 데이터입니다.
    #   - student_count >= 20 : 감독교사 2인 1조로 배정
    #   - student_count <  20 : 감독교사 1인 배정
    # nullable=True 인 이유: 기존 DB 마이그레이션 시 NOT NULL 추가 제약으로
    # 실패하지 않도록 애플리케이션 레벨에서 관리하며, 값이 없으면
    # 감독 배정 알고리즘이 기본값(30명)을 가정해 2인 1조로 처리합니다.
    student_count    = Column(Integer, nullable=True)

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
    # ── 낙관적 동시성 제어(optimistic locking) 버전 컬럼 (2026-06-20 신규) ──
    # 모든 TimetableEntry 수정 시 1씩 증가합니다.
    # 변경 신청 최종 승인 시점에 신청 저장 당시의 version 과 비교해
    # 결재 기간 중 다른 수정이 끼어들었는지 감지합니다.
    # 스냅샷(change_snapshot) 검증과 이중으로 보호하여 race condition 차단.
    # 기존 DB 마이그레이션은 server/main.py:_migrate_columns() 가 담당.
    version         = Column(Integer, nullable=False, default=1)

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
    # ── 신청 대상 식별 (2026-09-19 변경: nullable 로 완화) ────────────────────
    # 기존에는 수업 시간표 슬롯만 변경 대상이었으므로 NOT NULL 이었지만,
    # 시험 감독 스왑 신청(request_type="invigilation")은 시간표 슬롯이 아닌
    # 감독 배정(InvigilationAssignment)을 대상으로 하므로 NULL 이 됩니다.
    # 기존 수업 시간표 신청(request_type="timetable")은 여전히 필수 값이며,
    # API 레벨에서 유형별로 검증합니다 (DB 제약 완화는 Alembic 마이그레이션 담당).
    timetable_entry_id = Column(Integer, ForeignKey("timetable_entries.id"), nullable=True)
    # ── 신청 유형 (2026-09-19 신규) ─────────────────────────────────────────
    # "timetable"    : 기존 수업 시간표 변경 신청 (기본값 — 기존 데이터 하위 호환)
    # "invigilation": 시험 감독 스왑 신청 (대상은 invigilation_assignment_id)
    # 감독 스왑도 수업 시간표 변경과 동일한 결재 라인(피교사 동의 → 동적
    # 워크플로우 승인)을 재사용하므로 별도 신청 테이블을 만들지 않고
    # 유형 컬럼으로 분기합니다.
    request_type       = Column(String(20), nullable=False, default="timetable")
    # ── 감독 스왑 대상 감독 배정 (2026-09-19 신규) ───────────────────────────
    # request_type="invigilation" 인 경우에만 사용됩니다.
    # invigilation_assignment_id  : 신청자(본인)가 현재 맡고 있는 감독 슬롯
    # swap_partner_invigilation_id : 감독을 맞바꾸고자 하는 상대의 감독 슬롯
    invigilation_assignment_id = Column(Integer, ForeignKey("invigilation_assignments.id"), nullable=True)
    swap_partner_invigilation_id = Column(Integer, ForeignKey("invigilation_assignments.id"), nullable=True)
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
    # ── 감독 스왑 대상 관계 (2026-09-19 신규) ────────────────────────────────
    # 감독 스왑 신청(request_type="invigilation")에서 두 감독 배정을 조회하기
    # 위한 관계입니다. foreign_keys 를 명시하지 않으면 두 FK 컬럼 중 어느 것이
    # 어느 관계인지 SQLAlchemy 가 판단하지 못하므로 반드시 명시합니다.
    invigilation_assignment = relationship(
        "InvigilationAssignment", foreign_keys=[invigilation_assignment_id]
    )
    swap_partner_invigilation = relationship(
        "InvigilationAssignment", foreign_keys=[swap_partner_invigilation_id]
    )
    new_subject         = relationship("Subject", foreign_keys=[new_subject_id])
    new_teacher         = relationship("Teacher", foreign_keys=[new_teacher_id])
    new_room            = relationship("Room", foreign_keys=[new_room_id])
    affected_teacher    = relationship("Teacher", foreign_keys=[affected_teacher_id])
    consent_by_user     = relationship("User", foreign_keys=[consent_by_user_id])

    # ── 연쇄 교체(chain swap) 단계들 (2026-06-20 신규) ─────────────────────
    # 역참조 관계: 부모 신청 1건에 대해 여러 개의 단계(step)가 연결됨.
    # - 기존 단일 swap 신청(swap_partner_entry_id 사용)은 steps 가 비어 있음.
    # - 신규 연쇄 교체 신청은 steps 만 사용하여 다단계 교체를 표현.
    # cascade="all, delete-orphan": 부모 신청 삭제 시 자식 단계도 함께 삭제.
    steps = relationship(
        "ChangeRequestStep",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="ChangeRequestStep.step_order",
    )


# ── 변경 신청 단계 (연쇄 교체 지원, 2026-06-20 신규) ─────────────────────────

class ChangeRequestStep(Base):
    """
    변경 신청의 개별 교체 단계.

    TimetableChangeRequest 1건이 여러 개의 step 을 가질 수 있어,
    A↔C↔B 식의 연쇄 교체(chain swap)를 표현합니다.

    각 step 은 다음 정보를 가집니다:
      - step_order        : 1부터 시작하는 단계 순서 (UI 표시용)
      - step_type         : "swap" (두 슬롯 교환) | "change" (단일 슬롯의 과목/교사/교실 변경)
      - source_entry_id   : 이 단계에서 교체할 주체 슬롯
      - target_entry_id   : 이 단계에서 교체할 상대 슬롯 (step_type="swap" 인 경우만)
      - new_subject_id 등 : step_type="change" 인 경우 새 과목/교사/교실 지정
      - affected_teacher_id : 이 단계의 영향을 받는 교사 (동의 필요 시)
      - consent_status    : not_required | pending | approved | rejected
      - consent_by_user_id/consent_at : 동의 처리 사용자 및 시각
      - change_snapshot   : 단계 적용 시점의 source/target 슬롯 상태 스냅샷 (race 감지)

    부모 신청의 consent_status 는 파생값:
      - 모든 step 의 consent_status 가 "approved" → 부모 "approved"
      - 하나라도 "rejected" → 부모 "rejected"
      - 그 외 → "pending"
    서버가 응답 생성 시 자동으로 계산합니다(모델 컬럼이 아님).

    동시성:
      여러 교사가 동시에 본인 단계에 대해 동의/거절을 누를 수 있습니다.
      서버의 review_consent 핸들러는 SELECT ... FOR UPDATE 로 부모와 자식을
      잠근 후 갱신하여 lost update 를 방지합니다.
      SQLite 환경에서 FOR UPDATE 는 no-op 이므로, 운영 환경에서는
      PostgreSQL 사용을 권장합니다.
    """
    __tablename__ = "change_request_steps"

    id                 = Column(Integer, primary_key=True)
    request_id         = Column(Integer, ForeignKey("timetable_change_requests.id"), nullable=False)
    step_order         = Column(Integer, nullable=False)  # 1-based
    # "swap"  : source_entry_id 와 target_entry_id 의 과목/교사/교실을 맞바꿈
    # "change": source_entry_id 의 과목/교사/교실을 new_*_id 로 변경
    step_type          = Column(String(20), nullable=False, default="swap")
    # ── 주체/상대 슬롯 (2026-09-19 변경: source nullable 로 완화) ────────────
    # 기존에는 수업 시간표 슬롯만 대상이었으나, 감독 연쇄 스왑 확장을 대비해
    # 감독 배정(InvigilationAssignment)을 단계 대상으로 지정할 수 있게 됩니다.
    # 감독 단계의 경우 source_entry_id/target_entry_id 는 NULL 이고
    # source_invigilation_id/target_invigilation_id 가 대신 사용됩니다.
    # (현재 구현은 1:1 감독 스왑이므로 request 레벨 필드만 사용하지만,
    #  연쇄 감독 스왑 지원 시 이 컬럼들이 사용됩니다 — 확장 대비 설계)
    source_entry_id    = Column(Integer, ForeignKey("timetable_entries.id"), nullable=True)
    # 교환 상대 슬롯 (step_type="swap" 인 경우만, 그 외 None)
    target_entry_id    = Column(Integer, ForeignKey("timetable_entries.id"), nullable=True)
    # ── 감독 배정 기준 단계 대상 (2026-09-19 신규) ──────────────────────────
    # 감독 연쇄 스왑 단계에서 사용합니다. 수업 시간표 단계에서는 NULL 입니다.
    source_invigilation_id = Column(Integer, ForeignKey("invigilation_assignments.id"), nullable=True)
    target_invigilation_id = Column(Integer, ForeignKey("invigilation_assignments.id"), nullable=True)
    # 단일 슬롯 변경(step_type="change")인 경우의 새 값 (swap 에서는 미사용)
    new_subject_id     = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    new_teacher_id     = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    new_room_id        = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    # 이 단계의 영향을 받는 교사 — 동의가 필요한 경우 해당 교사의 User 로 알림 전송
    affected_teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    # 동의 상태: not_required(불필요) / pending(대기) / approved(동의) / rejected(거절)
    consent_status     = Column(String(20), nullable=False, default="not_required")
    consent_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    consent_at         = Column(DateTime, nullable=True)
    # 단계 적용 시점의 슬롯 상태 스냅샷 (race condition 감지용)
    # {"source": {"subject_id":..,"teacher_id":..,"room_id":..},
    #  "target": {...}}  (target 은 swap 인 경우만)
    change_snapshot    = Column(Text, nullable=True)

    # ── 관계 정의 ─────────────────────────────────────────────────────────
    request            = relationship("TimetableChangeRequest", back_populates="steps")
    source_entry       = relationship("TimetableEntry", foreign_keys=[source_entry_id])
    target_entry       = relationship("TimetableEntry", foreign_keys=[target_entry_id])
    # ── 감독 배정 단계 대상 관계 (2026-09-19 신규) ───────────────────────────
    # 감독 연쇄 스왑 단계에서 두 감독 배정을 조회하기 위한 관계입니다.
    source_invigilation = relationship(
        "InvigilationAssignment", foreign_keys=[source_invigilation_id]
    )
    target_invigilation = relationship(
        "InvigilationAssignment", foreign_keys=[target_invigilation_id]
    )
    new_subject        = relationship("Subject", foreign_keys=[new_subject_id])
    new_teacher        = relationship("Teacher", foreign_keys=[new_teacher_id])
    new_room           = relationship("Room", foreign_keys=[new_room_id])
    affected_teacher   = relationship("Teacher", foreign_keys=[affected_teacher_id])
    consent_by_user    = relationship("User", foreign_keys=[consent_by_user_id])


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


# ── 시험 시간표 + 시험 감독 시간표 (2026-09-19 신규) ─────────────────────────
#
# 이 섹션은 시험 기간 업무를 자동화하기 위해 추가되었습니다.
# 기존 수업 시간표(TimetableEntry)가 "요일×교시" 반복 구조인 반면,
# 시험 시간표는 "특정 날짜×시험 교시"의 1회성 구조라 별도 테이블이 필요합니다.
#
# 데이터 흐름:
#   1. 일과계가 Exam 생성 (기간·교시 운영 규칙 포함) → ExamPeriod 자동 생성
#   2. 시험 시간표(ExamEntry) 자동 배치 또는 수동 편집
#   3. 감독 배정(InvigilationAssignment) 자동 배정 또는 수동 조정
#   4. publish 시 교사 앱에서 조회 가능 + 전체 알림 발송
#   5. 교사는 감독 불가 신청(InvigilationConstraint) 또는 감독 스왑 신청 가능

class Exam(Base):
    """
    시험 종류·기간과 교시 운영 규칙.

    시험 한 번(예: "1학기 중간고사")을 나타냅니다. 시험 기간의 날짜별 교시는
    자식 테이블 ExamPeriod 로 관리하며, 시험 시간표 칸은 ExamEntry 로 관리합니다.

    주요 필드 설계 배경:
      - target_grade_ids: 전 학년이 아닌 일부 학년만 시험을 치르는 경우
        (예: 1·2학년 중간고사, 3학년 수업) 어떤 학년이 시험인지 명시합니다.
        JSON 배열(문자열)로 저장하며, 감독 배정 시 "시험 치르지 않는 학년의
        반은 그 교시에도 수업이 있다"는 검증(수업 병행 검증)의 기준이 됩니다.
      - first_period_start / break_minutes / prep_minutes / exam_minutes:
        시험기간 교시 운영 시간표는 일반 수업과 다르므로(쉬는시간 → 준비령 →
        5분 → 시험시간 → 종료령과 동시 종료) 사용자가 직접 입력할 수 있도록
        시험 단위로 보관합니다. 기본값은 요구사항 기준(08:30 시작, 10분 쉬는
        시간, 5분 준비, 50분 시험, 하루 3교시)입니다.
      - ban_homeroom_invigilation / ban_own_subject:
        감독 금지 규칙(담임 반 감독 금지 / 담당 과목 시험 감독 금지).
        기본값 True 이지만 학교 사정에 따라 관리자가 해제할 수 있습니다.
      - status: draft(작성 중, 관리자만 조회) → published(확정, 교사 앱 조회 가능).
        감독 배정이 진행 중인 미완성 시험표가 교사에게 조기 노출되는 것을
        방지하기 위해 2단계 상태를 둡니다.
    """
    __tablename__ = "exams"

    id         = Column(Integer, primary_key=True)
    term_id    = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    name       = Column(String(100), nullable=False)
    # 시험 유형 — 표기·분류용 (midterm=중간, final=기말, mock=모의고사 등)
    exam_type  = Column(String(20), nullable=False, default="midterm")
    # 학교급 모드 — 기본 고등학교("high"), 중학교 모드("middle").
    # 기능상 차이는 없고 표기·기본값 수준에서만 사용합니다 (요구사항 1).
    school_level = Column(String(10), nullable=False, default="high")
    # 시험 치르는 학년 ID 목록 — JSON 배열 문자열 (예: "[1, 2, 3]").
    # 빈 리스트 "[]" 면 해당 학기의 전체 학년이 시험 대상으로 간주됩니다.
    target_grade_ids = Column(Text, nullable=False, default="[]")
    # ── 시험 기간 (2026-09-19 추가) ────────────────────────────────────────
    # 기간의 날짜별 교시(ExamPeriod) 생성 근거가 됩니다. PATCH 로 기간이
    # 바뀌면 서버가 periods 를 재생성합니다.
    start_date = Column(Date, nullable=False)
    end_date   = Column(Date, nullable=False)
    # ── 교시 운영 규칙 (사용자 입력 가능, 기본값은 요구사항 4 기준) ───────────
    first_period_start = Column(Time, nullable=False)   # 1교시 시작 시각
    periods_per_day    = Column(Integer, nullable=False, default=3)  # 하루 교시 수
    break_minutes      = Column(Integer, nullable=False, default=10)  # 쉬는시간(분)
    prep_minutes       = Column(Integer, nullable=False, default=5)  # 준비령(분, 시험 종료 N분 전)
    exam_minutes       = Column(Integer, nullable=False, default=50)  # 시험 시간(분)
    # ── 시험 시간표 자동 배치 규칙 ─────────────────────────────────────────
    max_subjects_per_day = Column(Integer, nullable=False, default=3)  # 하루 최대 과목 수
    # ── 감독 금지 규칙 (기본 ON, 관리자 설정에서 해제 가능 — 요구사항 2) ─────
    ban_homeroom_invigilation = Column(Boolean, nullable=False, default=True)  # 담임 반 감독 금지
    ban_own_subject           = Column(Boolean, nullable=False, default=True)  # 담당 과목 시험 감독 금지
    # ── 게시 상태 ─────────────────────────────────────────────────────────
    status    = Column(String(20), nullable=False, default="draft")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    term = relationship("AcademicTerm")
    # 시험 기간의 날짜×교시들 — 시험 삭제 시 함께 삭제 (cascade)
    periods = relationship(
        "ExamPeriod", back_populates="exam", cascade="all, delete-orphan",
        order_by="ExamPeriod.exam_date, ExamPeriod.period",
    )
    # 시험 시간표 칸들 — 시험 삭제 시 함께 삭제 (cascade)
    entries = relationship(
        "ExamEntry", back_populates="exam", cascade="all, delete-orphan"
    )
    # 감독 배정들 — 시험 삭제 시 함께 삭제 (cascade).
    # 감독 배정은 시험 시간표(ExamEntry)와 독립적으로 존재할 수 있으므로
    # Exam 에 직접 연결합니다 (시험 치르는 모든 반이 감독 대상이며,
    # 시험 표에 과목이 아직 없는 교시에도 감독은 필요할 수 있음).
    invigilations = relationship(
        "InvigilationAssignment", back_populates="exam", cascade="all, delete-orphan"
    )
    # 감독 불가 신청들 — 시험 삭제 시 함께 삭제 (cascade)
    constraints = relationship(
        "InvigilationConstraint", back_populates="exam", cascade="all, delete-orphan"
    )

    def __str__(self):
        return self.name


class ExamPeriod(Base):
    """
    시험 날짜×교시 한 칸의 시간 정보.

    Exam 생성 시 기간(start_date~end_date)과 하루 교시 수(periods_per_day)에
    따라 자동으로 생성됩니다. 예: 10/20~10/22, 하루 3교시 → 9개의 ExamPeriod.

    시각 계산 규칙 (요구사항 4의 시험기간 운영 방식):
      - N교시 시작 = 1교시 시작 + (N-1) × (exam_minutes + break_minutes)
      - N교시 종료 = N교시 시작 + exam_minutes (종료령과 동시 종료)
      - 준비령 시각 = N교시 종료 - prep_minutes
        → 준비령은 파생값이라 DB 에 저장하지 않고 필요 시 계산합니다.
        (쉬는시간 → 준비령 → 5분 → 시험시간 → 종료령 순서로 진행)

    UniqueConstraint: 같은 시험에서 같은 날짜·같은 교시가 중복 생성되는 것을
    DB 레벨에서 차단합니다.
    """
    __tablename__ = "exam_periods"
    __table_args__ = (
        UniqueConstraint("exam_id", "exam_date", "period", name="uq_exam_period_slot"),
    )

    id         = Column(Integer, primary_key=True)
    exam_id    = Column(Integer, ForeignKey("exams.id"), nullable=False)
    exam_date  = Column(Date, nullable=False)   # 시험 날짜
    period     = Column(Integer, nullable=False)  # 교시 번호 (1 ~ periods_per_day)
    start_time = Column(Time, nullable=False)  # 시험 시작 시각
    end_time   = Column(Time, nullable=False)  # 시험 종료 시각 (= 시작 + exam_minutes)

    exam = relationship("Exam", back_populates="periods")
    # 이 교시에 배치된 시험 과목들 (학년별 1개씩) 과 감독 배정들
    entries = relationship("ExamEntry", back_populates="period", cascade="all, delete-orphan")
    invigilations = relationship(
        "InvigilationAssignment", back_populates="period", cascade="all, delete-orphan"
    )


class ExamEntry(Base):
    """
    시험 시간표의 한 칸: 특정 교시(ExamPeriod)에 특정 학년이 응시하는 과목.

    학년 단위로 배치하는 이유:
      시험은 같은 학년의 모든 반이 동시에 같은 과목을 응시하므로, 반 단위가
      아니라 학년 단위로 배치합니다. (예: 10/20 1교시 1학년 국어 — 1반~N반 전체)

    is_manual: 관리자가 더블클릭으로 수동 편집한 칸임을 표시합니다.
      자동 배치를 다시 실행하면 전체가 재배치되므로, 수동 편집 칸이 있었다는
      사실을 결과 메시지로 안내하는 근거로 사용합니다.

    UniqueConstraint: 같은 시험에서 같은 교시·같은 학년에 과목이 2개
    배치되는 것을 DB 레벨에서 차단합니다.
    """
    __tablename__ = "exam_entries"
    __table_args__ = (
        UniqueConstraint("exam_id", "period_id", "grade_id", name="uq_exam_entry_slot"),
    )

    id         = Column(Integer, primary_key=True)
    exam_id    = Column(Integer, ForeignKey("exams.id"), nullable=False)
    period_id  = Column(Integer, ForeignKey("exam_periods.id"), nullable=False)
    grade_id   = Column(Integer, ForeignKey("grades.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    is_manual  = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    exam    = relationship("Exam", back_populates="entries")
    period  = relationship("ExamPeriod", back_populates="entries")
    grade   = relationship("Grade")
    subject = relationship("Subject")


class InvigilationAssignment(Base):
    """
    감독 배정: 시험 교시×반×조 슬롯에 배정된 감독교사.

    감독 슬롯 생성 규칙 (요구사항 5 — 2인 1조 기준):
      시험 치르는 각 반의 학생 수(SchoolClass.student_count)를 기준으로
      해당 반×교시에 감독 슬롯을 몇 개 만들지 결정합니다.
        - 학생 20명 이상 → pair_index 1, 2 두 슬롯 (2인 1조)
        - 학생 20명 미만 → pair_index 1 한 슬롯 (1인 감독)
      student_count 가 미입력이면 기본 30명을 가정해 2인 1조로 처리합니다.

    teacher_id 가 nullable 인 이유:
      감독 후보가 부족한 소규모 학교에서 자동 배정이 슬롯을 전부 채우지
      못할 수 있습니다. 이때 슬롯 자체를 버리면 "미배정 감독 존재"라는
      사실이 사라지므로, teacher_id=NULL 로 슬롯을 남겨두고 관리자가
      수동 배정으로 채울 수 있게 합니다.

    UniqueConstraint: 같은 교시에 같은 반의 같은 조 번호가 중복되는 것을
    DB 레벨에서 차단합니다.
    """
    __tablename__ = "invigilation_assignments"
    __table_args__ = (
        UniqueConstraint("period_id", "school_class_id", "pair_index", name="uq_invigilation_slot"),
    )

    id              = Column(Integer, primary_key=True)
    exam_id         = Column(Integer, ForeignKey("exams.id"), nullable=False)
    period_id       = Column(Integer, ForeignKey("exam_periods.id"), nullable=False)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    # 감독교사 — NULL 이면 미배정 상태 (위 설명 참조)
    teacher_id      = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    # 조 번호: 1 = 단독 감독 또는 2인 1조의 첫 번째, 2 = 2인 1조의 두 번째
    pair_index      = Column(Integer, nullable=False, default=1)

    exam         = relationship("Exam", back_populates="invigilations")
    period       = relationship("ExamPeriod", back_populates="invigilations")
    school_class = relationship("SchoolClass")
    teacher      = relationship("Teacher")


class InvigilationConstraint(Base):
    """
    날짜 기반 감독 불가/제한 신청.

    기존 TeacherConstraint 가 "요일+교시" 기준(매주 반복)이라, 시험처럼
    특정 날짜에만 발생하는 불가(공결, 출장, 연수 등)를 표현할 수 없어
    별도 테이블로 추가했습니다.

    period 가 NULL 이면 "해당 날짜 전체 교시 불가"를 의미합니다.
      (교시를 지정하면 해당 교시만 불가)

    승인 워크플로우:
      교사가 신청(status=pending) → 일과계/교감이 승인(approved) 또는
      거절(rejected) 처리합니다. 감독 자동 배정 알고리즘은 approved 상태인
      신청만 하드 제약으로 반영합니다. pending/rejected 는 감독 배정에
      영향을 주지 않습니다 (미승인 상태로 감독이 빠지는 사고 방지).
    """
    __tablename__ = "invigilation_constraints"

    id           = Column(Integer, primary_key=True)
    exam_id      = Column(Integer, ForeignKey("exams.id"), nullable=False)
    teacher_id   = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    exam_date    = Column(Date, nullable=False)   # 불가 날짜
    period       = Column(Integer, nullable=True)  # 불가 교시 (None=전 교시)
    reason       = Column(Text, default="")
    status       = Column(String(20), nullable=False, default="pending")  # pending/approved/rejected
    requested_at = Column(DateTime, default=datetime.now)
    reviewed_by  = Column(String(30), default="")   # 승인/거절한 사용자명
    reviewed_at  = Column(DateTime, nullable=True)

    exam    = relationship("Exam", back_populates="constraints")
    teacher = relationship("Teacher")
