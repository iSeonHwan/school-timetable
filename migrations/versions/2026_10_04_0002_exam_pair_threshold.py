"""exam pair_threshold — 부감독(2인 1조) 배정 기준 학생 수 시험별 설정 (2026-10-04)

Revision ID: 0003_exam_pair_threshold
Revises: 0002_exam_feature
Create Date: 2026-10-04 00:00:00 KST

배경:
  core.exam_scheduler.PAIR_THRESHOLD 는 모듈 상수(20명)로 고정돼 있었다.
  실제 학교에서 쓰던 2학기 1회고사 시험감독표(엑셀 산출물)로 스케줄러를
  검증한 결과, 그 학교의 실제 운영 기준은 "한 시험실 24명 이상일 때만
  정·부 2명 배정"이었다 — 20명 기준을 적용하면 실제로는 단독 감독이던
  20~23명 교실에도 부감독이 추가로 배정되는 차이가 발견됐다.

  학교·학기마다 실제 기준이 다를 수 있으므로 상수 대신 시험(Exam) 단위
  컬럼으로 뽑아 관리자가 조정할 수 있게 한다. 기본값은 기존 동작과의
  하위 호환을 위해 20을 유지한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_exam_pair_threshold"
down_revision: Union[str, Sequence[str], None] = "0002_exam_feature"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("exams", "pair_threshold"):
        with op.batch_alter_table("exams") as batch:
            batch.add_column(sa.Column(
                "pair_threshold", sa.Integer(), nullable=False, server_default="20",
            ))


def downgrade() -> None:
    if _has_column("exams", "pair_threshold"):
        with op.batch_alter_table("exams") as batch:
            batch.drop_column("pair_threshold")
