"""exam room students — 혼합 시험실 수강 학생 명단(선택 입력) (2026-10-04)

Revision ID: 0005_exam_room_students
Revises: 0004_exam_rooms_corridor
Create Date: 2026-10-04 00:00:00 KST

배경: 시험 기간 중 "학생이 어떤 과목을 어디서 보는지" 안내하는 문서를
자동 생성하려면(ui/export/exam_export.py 의
export_room_assignment_notice_pdf/csv), 혼합 시험실(ExamRoom)에 실제로
누가 들어가는지 알아야 한다. ExamRoom.student_count(머릿수)만으로는
감독 배정(담임 제외·2인 1조 판단)에는 충분하지만 "누구"인지는 알 수
없어, 전부 선택 입력인 명단 테이블을 추가한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_exam_room_students"
down_revision: Union[str, Sequence[str], None] = "0004_exam_rooms_corridor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("exam_room_students"):
        op.create_table(
            "exam_room_students",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exam_room_id", sa.Integer(), sa.ForeignKey("exam_rooms.id"), nullable=False),
            sa.Column("student_number", sa.String(length=20), nullable=True),
            sa.Column("student_name", sa.String(length=30), nullable=True),
            sa.Column("source_class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=True),
        )


def downgrade() -> None:
    if _has_table("exam_room_students"):
        op.drop_table("exam_room_students")
