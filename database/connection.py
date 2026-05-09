"""
SQLAlchemy 데이터베이스 연결 관리 모듈

모듈 수준 싱글턴 패턴으로 엔진(_engine)과 세션 팩토리(_SessionLocal)를 유지합니다.

사용법:
  1. 앱 시작 시 init_db(url) 를 한 번만 호출합니다.
  2. DB 가 필요한 곳에서 session = get_session() 으로 새 세션을 받습니다.
  3. 작업 완료 후 반드시 session.close() 를 호출해 연결을 반환합니다.
     (try/finally 블록을 활용해 예외 시에도 반드시 닫히도록 합니다.)

주의: 전역 세션을 공유하지 않습니다. 각 요청/작업마다 새 세션을 열고 닫습니다.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base
from config import get_db_url

# 모듈 수준 싱글턴 — init_db() 이후에만 유효합니다.
_engine = None
_SessionLocal = None


def init_db(db_url: str | None = None) -> None:
    """
    SQLAlchemy 엔진을 초기화하고 테이블을 생성합니다.

    db_url 이 None 이면 config.get_db_url() 로 자동 결정합니다.
    SQLite 의 경우 멀티스레드 접근을 허용하기 위해 check_same_thread=False 를 설정합니다.
    Base.metadata.create_all() 은 이미 존재하는 테이블은 건드리지 않습니다.
    """
    global _engine, _SessionLocal

    url = db_url or get_db_url()

    # SQLite 는 기본적으로 동일 스레드에서만 연결을 허용합니다.
    # QThread 에서 DB 작업을 수행하기 때문에 이 제한을 해제합니다.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}

    _engine = create_engine(url, connect_args=connect_args, echo=False)

    # ORM 모델에 선언된 테이블을 DB에 CREATE TABLE IF NOT EXISTS 로 생성합니다.
    Base.metadata.create_all(_engine)

    # autocommit=False: 명시적으로 session.commit() 을 호출해야 변경이 반영됩니다.
    # autoflush=False : 쿼리 전 자동 flush 를 하지 않아 의도치 않은 INSERT/UPDATE 를 방지합니다.
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    """
    새 SQLAlchemy 세션을 생성해 반환합니다.
    init_db() 를 먼저 호출하지 않으면 RuntimeError 를 발생시킵니다.
    반환된 세션은 사용 후 반드시 .close() 해야 합니다.
    """
    if _SessionLocal is None:
        raise RuntimeError("DB가 초기화되지 않았습니다. init_db()를 먼저 호출하세요.")
    return _SessionLocal()
