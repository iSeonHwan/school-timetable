"""
채팅 API 테스트

server/api/chat.py 의 REST 엔드포인트와 joinedload 를 검증합니다.
  - 메시지 작성 (POST /chat/messages)
  - 메시지 목록 조회 (GET /chat/messages)
  - joinedload(ChatMessage.user) 덕분에 N+1 쿼리가 발생하지 않음
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import event

import database.connection as db_connection
from shared.models import ChatMessage


@contextmanager
def _capture_queries():
    """SQLAlchemy 엔진에 이벤트 리스너를 달아 실행된 SQL 문장 목록을 수집합니다."""
    queries = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    engine = db_connection._engine
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield queries
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


@pytest.fixture
def chat_users(auth_client):
    """채팅 테스트용 사용자 2명의 헤더를 생성합니다."""
    admin_headers = auth_client("admin", "adminpass", "admin")
    teacher_headers = auth_client("teacher", "teacherpass", "teacher")
    return admin_headers, teacher_headers


def test_post_and_list_chat_messages(client, chat_users):
    """메시지를 작성하고 조회하면 작성자 이름(username)이 포함되어야 합니다."""
    admin_headers, teacher_headers = chat_users

    r1 = client.post("/chat/messages", headers=admin_headers,
                     json={"content": "안녕하세요", "is_announcement": False})
    assert r1.status_code == 201
    assert r1.json()["content"] == "안녕하세요"

    r2 = client.post("/chat/messages", headers=teacher_headers,
                     json={"content": "반갑습니다", "is_announcement": False})
    assert r2.status_code == 201

    resp = client.get("/chat/messages", headers=admin_headers)
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    contents = [m["content"] for m in messages]
    assert "안녕하세요" in contents
    assert "반갑습니다" in contents

    usernames = {m["username"] for m in messages}
    assert "admin" in usernames
    assert "teacher" in usernames


def test_list_messages_uses_joinedload_no_n_plus_one(client, chat_users, db):
    """메시지 5개를 작성한 뒤 조회해도 사용자 조회 쿼리가 추가로 발생하지 않아야 합니다."""
    admin_headers, _ = chat_users

    for i in range(5):
        client.post("/chat/messages", headers=admin_headers,
                    json={"content": f"메시지{i}", "is_announcement": False})

    with _capture_queries() as queries:
        resp = client.get("/chat/messages", headers=admin_headers)
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 5
        # 모든 메시지의 username 이 채워져 있어야 joinedload 가 동작한 것입니다.
        assert all(m["username"] == "admin" for m in messages)

    # joinedload 로 User 를 한 번에 JOIN 하므로, 메시지 개수만큼 추가 User 쿼리가
    # 나가면 N+1 문제입니다. 정상이면 1~2개의 쿼리로 끝나야 합니다.
    assert len(queries) <= 2, f"쿼리가 {len(queries)}개 발생: {queries}"


def test_announcement_only_for_admin_or_vp(client, chat_users):
    """teacher 역할은 공지 메시지를 작성할 수 없어야 합니다."""
    _, teacher_headers = chat_users

    resp = client.post("/chat/messages", headers=teacher_headers,
                       json={"content": "공지", "is_announcement": True})
    assert resp.status_code == 403
