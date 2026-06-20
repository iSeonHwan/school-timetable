"""
Alembic 마이그레이션 환경 설정

이 스크립트는 alembic CLI 가 마이그레이션을 실행할 때 호출됩니다.
DB 연결 URL 을 환경 변수 DB_URL (또는 config.get_db_url()) 에서 읽어오며,
shared/models.py 의 Base.metadata 를 target_metadata 로 사용합니다.

autogenerate 기능을 사용하면 모델 변경 사항을 자동으로 새 revision 으로
만들어줍니다:
    alembic revision --autogenerate -m "add teacher employee_number column"

주의:
  - autogenerate 가 모든 변경을 잡아주지는 않습니다 (예: NOT NULL 제약 변경,
    CHECK 제약, 일부 인덱스 등). 생성된 마이그레이션 파일은 반드시
    사람이 검토해야 합니다.
  - SQLite 는 ALTER COLUMN 을 지원하지 않아 일부 마이그레이션에서
    op.batch_alter_table (테이블 재생성 패턴) 사용이 필요합니다.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 프로젝트 루트를 sys.path 에 추가 — shared.models, config 임포트용.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.models import Base  # noqa: E402
from config import get_db_url   # noqa: E402

# Alembic 설정 객체 — alembic.ini 의 [alembic] 섹션을 읽어들입니다.
config = context.config

# 로깅 설정 — alembic.ini 의 [loggers] 섹션에 따라 콘솔에 로그 출력.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL 을 환경 변수 DB_URL 또는 config.get_db_url() 에서 가져와
# alembic 설정의 sqlalchemy.url 을 덮어씁니다.
# alembic.ini 의 sqlalchemy.url 은 단순 자리표시자입니다.
db_url = os.getenv("DB_URL") or get_db_url()
config.set_main_option("sqlalchemy.url", db_url)

# target_metadata — autogenerate 가 모델 변경을 비교할 기준 메타데이터.
# shared/models.py 의 Base.metadata 가 모든 ORM 모델의 테이블 정의를 포함.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    오프라인 모드 — 실제 DB 연결 없이 SQL 스크립트만 생성할 때 사용.
    예) alembic upgrade head --sql > migration.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite 에서 batch mode 기본 활성화 — ALTER COLUMN 한계 회피용.
        # PostgreSQL 등 다른 dialect 에서는 자동으로 일반 mode 사용.
        render_as_batch=db_url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    온라인 모드 — 실제 DB 에 연결해 마이그레이션을 실행.
    기본 모드 — alembic upgrade head / alembic stamp head 등이 이쪽으로.
    """
    # engine_from_config 가 connection 을 생성하고 마이그레이션 종료 후 닫습니다.
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite ALTER 한계 회피 — batch_alter_table() 호출 시 테이블 재생성.
            render_as_batch=db_url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()