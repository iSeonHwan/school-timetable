"""exam feature — 시험 시간표 + 시험 감독 시간표 스키마 변경 (2026-09-19)

Revision ID: 0002_exam_feature
Revises: 0001_baseline
Create Date: 2026-09-19 00:00:00 KST

이 revision 이 하는 일:
  1. 기존 컬럼 추가:
     - school_classes.student_count (시험 감독 2인 1조 판단 기준)
     - timetable_change_requests.request_type / invigilation_assignment_id /
       swap_partner_invigilation_id (감독 스왑 신청 지원)
     - change_request_steps.source_invigilation_id / target_invigilation_id
  2. NOT NULL 완화 (SQLite 는 ALTER COLUMN 을 지원하지 않으므로
     batch_alter_table 로 테이블을 재생성하는 방식 사용):
     - timetable_change_requests.timetable_entry_id  (감독 스왑 신청은 NULL)
     - change_request_steps.source_entry_id          (감독 단계는 NULL)
  3. 신규 테이블 생성: exams, exam_periods, exam_entries,
     invigilation_assignments, invigilation_constraints

왜 모든 연산이 존재 검사(inspector)로 보호되는가:
  이 프로젝트의 서버 부팅 순서는 init_db() 의 create_all() → _migrate_columns()
  → _ensure_alembic_state() 입니다. 즉 이 migration 이 실행되는 시점에
  스키마가 이미 create_all() 로 최신화되어 있을 수 있습니다 (신규 DB).
  또한 _migrate_columns() 가 컬럼 추가를 먼저 해두었을 수도 있습니다 (레거시 DB).
  두 경로 모두에서 안전하게 동작하도록 (멱등성) 각 연산 전에
  테이블/컬럼 존재 여부를 확인하고 누락된 것만 실행합니다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_exam_feature"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bind():
    """현재 마이그레이션 대상 DB 연결 객체 반환."""
    return op.get_bind()


def _has_table(name: str) -> bool:
    """테이블 존재 여부 — 멱등성 보장용 (이미 create_all() 이 만들었을 수 있음)."""
    return sa.inspect(_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    """컬럼 존재 여부 — _migrate_columns() 가 먼저 추가했을 수 있으므로 확인."""
    inspector = sa.inspect(_bind())
    if not inspector.has_table(table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _is_nullable(table: str, column: str) -> bool:
    """컬럼의 nullable 여부 — NOT NULL 완화가 이미 적용되었는지 판단."""
    inspector = sa.inspect(_bind())
    for col in inspector.get_columns(table):
        if col["name"] == column:
            return bool(col.get("nullable", True))
    return True


def upgrade() -> None:
    # ── 1. school_classes.student_count 추가 ────────────────────────────────
    # 시험 감독 조 구성(20명 이상 2인 1조)의 판단 기준 데이터입니다.
    # _has_table 가드: standalone alembic 실행처럼 create_all() 이 스키마를
    # 만들지 않은 경로에서 없는 테이블을 ALTER 하지 않도록 보호.
    if _has_table("school_classes") and not _has_column("school_classes", "student_count"):
        with op.batch_alter_table("school_classes") as batch:
            batch.add_column(sa.Column("student_count", sa.Integer(), nullable=True))

    # ── 2. timetable_change_requests 확장 (감독 스왑 신청 지원) ───────────────
    # 기존 수업 시간표 변경 신청과 동일한 결재 라인을 재사용하기 위해
    # 신청 유형 컬럼과 감독 배정 FK 를 추가하고, timetable_entry_id 를
    # nullable 로 완화합니다 (감독 스왑 신청은 시간표 슬롯이 없음).
    tcr_needs_alter = (
        not _has_column("timetable_change_requests", "request_type")
        or not _has_column("timetable_change_requests", "invigilation_assignment_id")
        or not _has_column("timetable_change_requests", "swap_partner_invigilation_id")
        or not _is_nullable("timetable_change_requests", "timetable_entry_id")
    )
    if tcr_needs_alter and _has_table("timetable_change_requests"):
        with op.batch_alter_table("timetable_change_requests") as batch:
            if not _has_column("timetable_change_requests", "request_type"):
                batch.add_column(sa.Column(
                    "request_type", sa.String(length=20),
                    nullable=False, server_default="timetable",
                ))
            if not _has_column("timetable_change_requests", "invigilation_assignment_id"):
                batch.add_column(sa.Column("invigilation_assignment_id", sa.Integer(), nullable=True))
            if not _has_column("timetable_change_requests", "swap_partner_invigilation_id"):
                batch.add_column(sa.Column("swap_partner_invigilation_id", sa.Integer(), nullable=True))
            if not _is_nullable("timetable_change_requests", "timetable_entry_id"):
                # SQLite 는 NOT NULL 해제가 불가하므로 batch 재생성으로 처리.
                batch.alter_column(
                    "timetable_entry_id", existing_type=sa.Integer(), nullable=True,
                )

    # ── 3. change_request_steps 확장 (연쇄 감독 스왑 확장 대비) ───────────────
    crs_needs_alter = (
        not _has_column("change_request_steps", "source_invigilation_id")
        or not _has_column("change_request_steps", "target_invigilation_id")
        or not _is_nullable("change_request_steps", "source_entry_id")
    )
    if crs_needs_alter and _has_table("change_request_steps"):
        with op.batch_alter_table("change_request_steps") as batch:
            if not _has_column("change_request_steps", "source_invigilation_id"):
                batch.add_column(sa.Column("source_invigilation_id", sa.Integer(), nullable=True))
            if not _has_column("change_request_steps", "target_invigilation_id"):
                batch.add_column(sa.Column("target_invigilation_id", sa.Integer(), nullable=True))
            if not _is_nullable("change_request_steps", "source_entry_id"):
                batch.alter_column(
                    "source_entry_id", existing_type=sa.Integer(), nullable=True,
                )

    # ── 4. 신규 테이블 생성 ─────────────────────────────────────────────────
    # create_all() 이 이미 만들었다면 건너뜁니다 (멱등성).
    if not _has_table("exams"):
        op.create_table(
            "exams",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("term_id", sa.Integer(), sa.ForeignKey("academic_terms.id"), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("exam_type", sa.String(length=20), nullable=False, server_default="midterm"),
            sa.Column("school_level", sa.String(length=10), nullable=False, server_default="high"),
            sa.Column("target_grade_ids", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("first_period_start", sa.Time(), nullable=False),
            sa.Column("periods_per_day", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("break_minutes", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("prep_minutes", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("exam_minutes", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("max_subjects_per_day", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("ban_homeroom_invigilation", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("ban_own_subject", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )

    if not _has_table("exam_periods"):
        op.create_table(
            "exam_periods",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=False),
            sa.Column("period", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.UniqueConstraint("exam_id", "exam_date", "period", name="uq_exam_period_slot"),
        )

    if not _has_table("exam_entries"):
        op.create_table(
            "exam_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("period_id", sa.Integer(), sa.ForeignKey("exam_periods.id"), nullable=False),
            sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=False),
            sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
            sa.Column("is_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
            sa.UniqueConstraint("exam_id", "period_id", "grade_id", name="uq_exam_entry_slot"),
        )

    if not _has_table("invigilation_assignments"):
        op.create_table(
            "invigilation_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("period_id", sa.Integer(), sa.ForeignKey("exam_periods.id"), nullable=False),
            sa.Column("school_class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=False),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=True),
            sa.Column("pair_index", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("period_id", "school_class_id", "pair_index", name="uq_invigilation_slot"),
        )

    if not _has_table("invigilation_constraints"):
        op.create_table(
            "invigilation_constraints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=False),
            sa.Column("period", sa.Integer(), nullable=True),
            sa.Column("reason", sa.Text()),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("requested_at", sa.DateTime()),
            sa.Column("reviewed_by", sa.String(length=30)),
            sa.Column("reviewed_at", sa.DateTime()),
        )


def downgrade() -> None:
    """
    시험 기능 스키마를 제거합니다 (baseline 상태로 복원).

    주의: NOT NULL 복원은 원래 제약 상태로 되돌리지만, 감독 스왑 신청
    데이터(request_type='invigilation')가 남아 있으면 NOT NULL 위반이
    발생할 수 있으므로 downgrade 전 해당 데이터를 정리해야 합니다.
    실제 운영에서는 downgrade 대신 백업 복구를 권장합니다.
    """
    for table in (
        "invigilation_constraints",
        "invigilation_assignments",
        "exam_entries",
        "exam_periods",
        "exams",
    ):
        if _has_table(table):
            op.drop_table(table)

    if _has_table("timetable_change_requests"):
        with op.batch_alter_table("timetable_change_requests") as batch:
            batch.alter_column("timetable_entry_id", existing_type=sa.Integer(), nullable=False)
            batch.drop_column("swap_partner_invigilation_id")
            batch.drop_column("invigilation_assignment_id")
            batch.drop_column("request_type")

    if _has_table("change_request_steps"):
        with op.batch_alter_table("change_request_steps") as batch:
            batch.alter_column("source_entry_id", existing_type=sa.Integer(), nullable=False)
            batch.drop_column("target_invigilation_id")
            batch.drop_column("source_invigilation_id")

    if _has_column("school_classes", "student_count"):
        with op.batch_alter_table("school_classes") as batch:
            batch.drop_column("student_count")