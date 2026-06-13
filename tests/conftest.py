import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

from database.connection import init_db, get_session
from server.main import app
import server.main as _server_main  # lifespan 의 init_db 를 무력화하기 위해 모듈 참조
from server.auth_utils import hash_password
from shared.models import User


@pytest.fixture(autouse=True)
def _setup_db(tmp_path):
    """
    각 테스트 전에 임시 파일 SQLite DB를 초기화합니다.

    FastAPI lifespan 이 init_db() 를 다시 호출하면서 기본 DB 로 엔진을
    덮어쓰는 것을 막기 위해, lifespan 내 init_db 호출은 no-op 으로 만듭니다.
    그러면 fixture 와 lifespan 이 같은 임시 파일 DB 엔진을 사용합니다.
    """
    original_lifespan_init = _server_main.init_db

    def _noop_init(db_url: str | None = None) -> None:
        """테스트 중 lifespan 의 DB 재초기화를 무시합니다."""
        pass

    _server_main.init_db = _noop_init
    db_path = tmp_path / "test.db"
    try:
        init_db(f"sqlite:///{db_path}")
        # lifespan 이 실행되지 않는 TestClient 환경에서도 결재 워크플로우를
        # 미리 생성해두어 시간표 변경 신청 테스트가 정상 동작하도록 합니다.
        _server_main._ensure_default_workflow()
        yield
    finally:
        _server_main.init_db = original_lifespan_init
        init_db(f"sqlite:///{tmp_path / 'clean.db'}")


@pytest.fixture
def db():
    """테스트용 SQLAlchemy 세션을 제공합니다."""
    s = get_session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    """FastAPI TestClient 를 제공합니다."""
    return TestClient(app)


@pytest.fixture
def auth_client(client, db):
    """
    로그인된 사용자의 Authorization 헤더를 생성하는 헬퍼를 제공합니다.

    사용 예:
        headers = auth_client("admin", "pass", "admin")
        resp = client.get("/setup/teachers", headers=headers)
    """
    def _login(username: str, password: str, role: str, teacher_id: int | None = None):
        # 이미 존재하는 사용자는 재생성하지 않고 바로 로그인합니다.
        # (테스트 파일 내부에서 직접 생성한 계정과 공유할 때 사용)
        user = db.query(User).filter_by(username=username).first()
        if user is None:
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                teacher_id=teacher_id,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        resp = client.post("/auth/login", json={"username": username, "password": password})
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _login
