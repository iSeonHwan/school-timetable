"""exam rooms + corridor duty + grade-date exclusions (2026-10-04)

Revision ID: 0004_exam_rooms_corridor
Revises: 0003_exam_pair_threshold
Create Date: 2026-10-04 00:00:00 KST

배경 — 실제 학교에서 쓰던 2학기 1회고사 시험감독표(엑셀)로 감독 자동
배정 스케줄러를 검증하는 과정에서 드러난 구조적 한계 3가지를 해소한다:

  1. 선택과목·공통고사처럼 여러 반 학생이 한 시험실에 섞이는 경우를
     표현할 길이 없었다 (감독 슬롯이 SchoolClass 1개 단위로만 존재).
     → exam_rooms 테이블 신설.
  2. 복도감독(학년별 1명, 시험 과목 담당 교사 중 배정, 감독 횟수 별도
     집계)이라는 역할 자체가 없었다.
     → corridor_duty_assignments 테이블 신설.
  3. 시험 기간 중 학년마다 시험에 들어가는 날짜가 다를 수 있는데
     (예: 첫날은 특정 학년만 정상수업) Exam.target_grade_ids 는 기간
     전체에 대해 한 번만 정해져 이를 표현할 수 없었다.
     → exam_grade_date_exclusions 테이블 신설(예외 날짜만 등록).

  부수 변경: invigilation_assignments.school_class_id 를 NOT NULL →
  nullable 로 완화하고 exam_room_id 컬럼을 추가해, "반 슬롯"과 "혼합
  시험실 슬롯"이 같은 테이블에 공존하도록 한다(둘 중 쓰지 않는 쪽은 NULL).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_exam_rooms_corridor"
down_revision: Union[str, Sequence[str], None] = "0003_exam_pair_threshold"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bind():
    return op.get_bind()


def _has_table(name: str) -> bool:
    return sa.inspect(_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(_bind())
    if not inspector.has_table(table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _is_nullable(table: str, column: str) -> bool:
    inspector = sa.inspect(_bind())
    for col in inspector.get_columns(table):
        if col["name"] == column:
            return bool(col.get("nullable", True))
    return True


def upgrade() -> None:
    # ── 1. exam_rooms ────────────────────────────────────────────────────
    if not _has_table("exam_rooms"):
        op.create_table(
            "exam_rooms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("period_id", sa.Integer(), sa.ForeignKey("exam_periods.id"), nullable=False),
            sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=False),
            sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=True),
            sa.Column("source_class_ids", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("student_count", sa.Integer(), nullable=True),
            sa.Column("label", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime()),
        )

    # ── 2. corridor_duty_assignments ────────────────────────────────────
    if not _has_table("corridor_duty_assignments"):
        op.create_table(
            "corridor_duty_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("period_id", sa.Integer(), sa.ForeignKey("exam_periods.id"), nullable=False),
            sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=False),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=True),
            sa.UniqueConstraint("period_id", "grade_id", name="uq_corridor_duty_slot"),
        )

    # ── 3. exam_grade_date_exclusions ───────────────────────────────────
    if not _has_table("exam_grade_date_exclusions"):
        op.create_table(
            "exam_grade_date_exclusions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_id", sa.Integer(), sa.ForeignKey("exams.id"), nullable=False),
            sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=False),
            sa.UniqueConstraint("exam_id", "grade_id", "exam_date", name="uq_grade_date_exclusion"),
        )

    # ── 4. invigilation_assignments 확장 ────────────────────────────────
    ia_needs_alter = (
        not _has_column("invigilation_assignments", "exam_room_id")
        or not _is_nullable("invigilation_assignments", "school_class_id")
    )
    if ia_needs_alter and _has_table("invigilation_assignments"):
        with op.batch_alter_table("invigilation_assignments") as batch:
            if not _has_column("invigilation_assignments", "exam_room_id"):
                batch.add_column(sa.Column(
                    "exam_room_id", sa.Integer(), sa.ForeignKey("exam_rooms.id"), nullable=True,
                ))
            if not _is_nullable("invigilation_assignments", "school_class_id"):
                batch.alter_column(
                    "school_class_id", existing_type=sa.Integer(), nullable=True,
                )
            # SQLite 는 batch_alter_table 로 테이블을 재생성하므로, 기존에
            # uq_invigilation_room_slot 이 없었다면 이 시점에 함께 추가한다.
            try:
                batch.create_unique_constraint(
                    "uq_invigilation_room_slot", ["period_id", "exam_room_id", "pair_index"],
                )
            except Exception:
                pass   # 이미 존재 — 멱등성 보장


def downgrade() -> None:
    if _has_table("invigilation_assignments"):
        with op.batch_alter_table("invigilation_assignments") as batch:
            try:
                batch.drop_constraint("uq_invigilation_room_slot", type_="unique")
            except Exception:
                pass
            if _has_column("invigilation_assignments", "exam_room_id"):
                batch.drop_column("exam_room_id")
            batch.alter_column("school_class_id", existing_type=sa.Integer(), nullable=False)

    for table in (
        "exam_grade_date_exclusions",
        "corridor_duty_assignments",
        "exam_rooms",
    ):
        if _has_table(table):
            op.drop_table(table)
