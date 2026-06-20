"""baseline — 현재 스키마 상태 마커 (Alembic 도입 시점)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-20 00:00:00 KST

이 revision 은 빈 마커입니다. Alembic 도입 이전에 이미 운영되던 DB
(create_all() + _migrate_columns() 로 스키마를 관리하던 시스템)를
Alembic 관리 체계로 전환하기 위한 기준점 역할만 합니다.

동작 방식:
  1. 서버 시작 시 init_db() 의 Base.metadata.create_all() 이 새 테이블 생성
  2. server/main.py:_ensure_alembic_baseline() 가 alembic_version 테이블이
     없는 경우 stamp head 로 이 baseline 을 현재 상태로 마킹
  3. 이후 스키마 변경 시 새 revision 추가 → alembic upgrade head 로 적용

이 파일은 upgrade()/downgrade() 가 모두 pass 인 빈 마커입니다.
실제 테이블 생성은 create_all() 이 담당하므로 여기서 중복 CREATE 하지 않습니다.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    빈 마커 — 아무 연산도 수행하지 않습니다.
    스키마 생성은 init_db() 의 Base.metadata.create_all() 이 담당합니다.
    """
    pass


def downgrade() -> None:
    """
    빈 마커 — downgrade 도 아무 연산을 수행하지 않습니다.
    baseline 을 삭제하면 alembic 체인의 시작점이 사라지므로
    실제로는 호출되지 않습니다.
    """
    pass