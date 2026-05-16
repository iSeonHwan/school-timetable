"""
채팅 API — REST + WebSocket

GET    /chat/messages              — 최근 메시지 목록 (REST, 접속 시 이력 로드용)
POST   /chat/messages              — 메시지 전송 (REST fallback)
DELETE /chat/messages/{message_id} — 단일 메시지 삭제 (일과계·교감만 가능)
DELETE /chat/messages/cleanup      — 보관 기간 지난 메시지 일괄 삭제 (일과계만 가능)
WS     /chat/ws?token=...          — 실시간 WebSocket 채팅

WebSocket 프로토콜:
  클라이언트 → 서버:
    {"type": "chat", "payload": {"content": "...", "is_announcement": false}}
    {"type": "delete", "payload": {"message_id": 123}}
    {"type": "ping"}

  서버 → 클라이언트:
    {"type": "history",  "payload": [ChatMessageOut, ...]}   # 접속 직후 최근 100개
    {"type": "chat",     "payload": ChatMessageOut}          # 새 메시지 브로드캐스트
    {"type": "delete",   "payload": {"message_id": 123}}     # 메시지 삭제 브로드캐스트
    {"type": "pong"}
    {"type": "error",    "payload": {"detail": "..."}}

ConnectionManager 설계:
  - `manager` 는 모듈 레벨 싱글턴입니다. FastAPI 앱이 시작될 때 단 한 번 생성되어
    서버 프로세스가 종료될 때까지 유지됩니다.
  - 내부 `_connections` 리스트에는 (user_id, WebSocket) 쌍을 저장합니다.
    한 사용자가 여러 창에서 접속하면 동일한 user_id가 여러 번 들어갈 수 있습니다.
  - `broadcast()`는 연결이 끊긴 소켓에 send_text()가 실패하면 해당 소켓을
    자동으로 목록에서 제거합니다.
  - FastAPI는 각 WebSocket 연결을 별도의 asyncio 태스크로 처리하므로,
    같은 이벤트 루프 안에서 `_connections` 리스트에 동시 접근이 일어납니다.
    CPython의 GIL과 asyncio 단일 스레드 특성 덕분에 별도의 락 없이 안전합니다.
    단, 멀티프로세스(uvicorn workers > 1) 환경에서는 프로세스 간 연결 목록이
    공유되지 않으므로 Redis Pub/Sub 같은 별도 브로드캐스트 버스가 필요합니다.

채팅 메시지 자동 정리:
  - 서버 시작 시점부터 `CHAT_RETENTION_DAYS`(기본값 60일)보다 오래된 메시지는
    자동 삭제됩니다. lifespan 에서 백그라운드 asyncio 태스크로 주기적으로 실행되며,
    삭제된 메시지 ID 는 WebSocket 으로 브로드캐스트되어 모든 클라이언트의 UI 에서
    해당 메시지가 제거됩니다.
  - 환경 변수 CHAT_RETENTION_DAYS=0 이면 자동 정리를 비활성화합니다.
"""
from __future__ import annotations
import asyncio
import json
import os
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, HTTPException
from sqlalchemy.orm import Session

from shared.models import ChatMessage, User
from shared.schemas import ChatMessageOut, ChatMessageCreate
from server.deps import get_db, get_current_user, require_scheduler, require_admin_or_vice_principal
from server.auth_utils import decode_token
from database.connection import get_session

router = APIRouter(prefix="/chat", tags=["채팅"])


# ── 연결 관리자 ────────────────────────────────────────────────────────────

class ConnectionManager:
    """
    활성 WebSocket 연결 목록을 관리하고 브로드캐스트를 담당합니다.
    FastAPI 앱 수명 동안 단일 인스턴스로 동작합니다.
    """

    def __init__(self):
        # {user_id: WebSocket} — 동일 사용자가 여러 창을 열 수 있으므로 리스트 사용
        self._connections: list[tuple[int, WebSocket]] = []

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self._connections.append((user_id, ws))

    def disconnect(self, ws: WebSocket):
        self._connections = [(uid, w) for uid, w in self._connections if w is not ws]

    async def broadcast(self, message: dict):
        """연결된 모든 클라이언트에게 메시지를 전송합니다. 끊긴 연결은 자동 제거합니다."""
        dead = []
        for uid, ws in self._connections:
            try:
                await ws.send_text(json.dumps(message, ensure_ascii=False, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def online_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


# ── REST 엔드포인트 ────────────────────────────────────────────────────────

@router.get("/messages", response_model=list[ChatMessageOut])
def list_messages(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """최근 채팅 메시지를 반환합니다 (오래된 순 정렬)."""
    rows = (
        db.query(ChatMessage)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()  # 최신이 아래로 오도록 뒤집습니다.
    return [_to_out(msg, db) for msg in rows]


@router.post("/messages", response_model=ChatMessageOut, status_code=201)
def post_message(
    body: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """REST 방식으로 메시지를 전송합니다 (WebSocket fallback)."""
    if body.is_announcement and current_user.role not in ("admin", "vice_principal"):
        raise HTTPException(403, "공지 메시지는 관리자(일과계·교감)만 전송할 수 있습니다.")
    msg = _save_message(db, current_user, body.content, body.is_announcement)
    return _to_out(msg, db)


# ── 메시지 삭제 엔드포인트 ─────────────────────────────────────────────────────

@router.delete("/messages/{message_id}", status_code=200)
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_vice_principal),
):
    """
    단일 채팅 메시지를 삭제합니다. (일과계·교감 모두 가능)

    삭제된 메시지의 ID 를 WebSocket 으로 브로드캐스트하여
    모든 접속 클라이언트의 UI 에서 해당 메시지가 즉시 제거되도록 합니다.

    Args:
        message_id: 삭제할 메시지의 ID

    Returns:
        {"deleted": True, "message_id": <id>}

    Raises:
        404: 해당 ID 의 메시지가 존재하지 않음
    """
    msg = db.get(ChatMessage, message_id)
    if msg is None:
        raise HTTPException(404, "해당 메시지를 찾을 수 없습니다.")

    db.delete(msg)
    db.commit()

    # WebSocket 으로 삭제 이벤트를 브로드캐스트하여 모든 클라이언트가 UI 에서 제거하도록 함
    # asyncio.create_task 로 비동기 브로드캐스트 — 동기 핸들러 안에서 안전하게 실행
    async def _broadcast_delete():
        await manager.broadcast({
            "type": "delete",
            "payload": {"message_id": message_id},
        })

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_broadcast_delete())
    except RuntimeError:
        pass  # 이벤트 루프가 없는 환경 (테스트 등)에서는 브로드캐스트 생략

    return {"deleted": True, "message_id": message_id}


@router.delete("/messages", status_code=200)
def cleanup_old_messages(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scheduler),
):
    """
    보관 기간이 지난 오래된 채팅 메시지를 일괄 삭제합니다. (일과계 전용)

    CHAT_RETENTION_DAYS 환경 변수(기본값 60일)를 기준으로,
    created_at 이 그 기간보다 이전인 모든 메시지를 삭제합니다.
    CHAT_RETENTION_DAYS=0 으로 설정된 경우 보관 기간 제한 없이 모든 메시지가 유지됩니다.

    Returns:
        {"deleted_count": <삭제된 메시지 수>}
    """
    retention_days = int(os.getenv("CHAT_RETENTION_DAYS", "60"))
    if retention_days <= 0:
        return {"deleted_count": 0, "message": "자동 정리가 비활성화되어 있습니다 (CHAT_RETENTION_DAYS=0)."}

    cutoff = datetime.now() - timedelta(days=retention_days)
    old_messages = db.query(ChatMessage).filter(ChatMessage.created_at < cutoff).all()
    deleted_ids = [msg.id for msg in old_messages]
    count = len(deleted_ids)

    for msg in old_messages:
        db.delete(msg)
    db.commit()

    # 삭제된 모든 메시지 ID 를 WebSocket 으로 브로드캐스트
    async def _broadcast_cleanup():
        await manager.broadcast({
            "type": "cleanup",
            "payload": {"message_ids": deleted_ids},
        })

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_broadcast_cleanup())
    except RuntimeError:
        pass

    return {"deleted_count": count}


# ── WebSocket 엔드포인트 ───────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_chat(ws: WebSocket, token: str = Query(...)):
    """
    WebSocket 채팅 엔드포인트.
    URL 파라미터로 JWT 토큰을 전달합니다: /chat/ws?token=<JWT>
    """
    # 토큰 검증
    payload = decode_token(token)
    if payload is None:
        await ws.close(code=4001)
        return

    user_id: int = payload["sub"]
    db = get_session()
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            await ws.close(code=4001)
            return

        await manager.connect(user_id, ws)

        # 접속 직후 최근 100개 이력 전송
        rows = (
            db.query(ChatMessage)
            .order_by(ChatMessage.created_at.desc())
            .limit(100)
            .all()
        )
        rows.reverse()
        history = [_to_out(m, db).model_dump() for m in rows]
        await ws.send_text(json.dumps(
            {"type": "history", "payload": history},
            ensure_ascii=False, default=str,
        ))

        # 메시지 수신 루프
        while True:
            raw = await ws.receive_text()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "payload": {"detail": "JSON 형식 오류"}}))
                continue

            etype = event.get("type")

            if etype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            elif etype == "delete":
                # ── 메시지 삭제 요청 (WebSocket 경로, 일과계·교감만 가능) ──
                if user.role not in ("admin", "vice_principal"):
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "payload": {"detail": "메시지 삭제는 관리자(일과계·교감)만 가능합니다."},
                    }))
                    continue
                p = event.get("payload", {})
                msg_id = p.get("message_id")
                if msg_id is None:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "payload": {"detail": "message_id 가 필요합니다."},
                    }))
                    continue
                target = db.get(ChatMessage, msg_id)
                if target is None:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "payload": {"detail": "해당 메시지를 찾을 수 없습니다."},
                    }))
                    continue
                db.delete(target)
                db.commit()
                await manager.broadcast({
                    "type": "delete",
                    "payload": {"message_id": msg_id},
                })

            elif etype == "chat":
                p = event.get("payload", {})
                content = str(p.get("content", "")).strip()
                is_ann = bool(p.get("is_announcement", False))

                if not content:
                    await ws.send_text(json.dumps({"type": "error", "payload": {"detail": "빈 메시지"}}))
                    continue
                if is_ann and user.role not in ("admin", "vice_principal"):
                    await ws.send_text(json.dumps({"type": "error", "payload": {"detail": "공지는 관리자(일과계·교감)만 가능합니다."}}))
                    continue

                msg = _save_message(db, user, content, is_ann)
                out = _to_out(msg, db).model_dump()
                # 모든 접속자에게 브로드캐스트
                await manager.broadcast({"type": "chat", "payload": out})

            else:
                await ws.send_text(json.dumps({"type": "error", "payload": {"detail": f"알 수 없는 이벤트: {etype}"}}))

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
        db.close()


# ── 내부 유틸 ─────────────────────────────────────────────────────────────

def _save_message(db: Session, user: User, content: str, is_announcement: bool) -> ChatMessage:
    msg = ChatMessage(user_id=user.id, content=content, is_announcement=is_announcement)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _to_out(msg: ChatMessage, db: Session) -> ChatMessageOut:
    user = db.get(User, msg.user_id)
    return ChatMessageOut(
        id=msg.id,
        user_id=msg.user_id,
        username=user.username if user else "(알 수 없음)",
        content=msg.content,
        is_announcement=msg.is_announcement,
        created_at=msg.created_at,
    )


# ── 백그라운드 자동 정리 태스크 ────────────────────────────────────────────────

async def _auto_cleanup_loop():
    """
    주기적으로 오래된 채팅 메시지를 자동 삭제하는 백그라운드 태스크입니다.

    동작 방식:
      1. 서버 시작 후 최초 5분 대기 (초기 연결이 안정화될 때까지)
      2. CHAT_RETENTION_DAYS 환경 변수(기본값 60일) 기준으로 오래된 메시지 삭제
      3. 삭제된 메시지 ID 들을 WebSocket 으로 브로드캐스트하여 모든 클라이언트 UI 갱신
      4. 12시간 간격으로 반복 실행

    CHAT_RETENTION_DAYS=0 으로 설정 시 자동 정리가 비활성화됩니다.
    이 태스크는 FastAPI lifespan 을 통해 시작되며, 서버 종료 시 함께 종료됩니다.
    """
    try:
        # 서버 시작 직후에는 연결이 안정화될 때까지 잠시 대기
        await asyncio.sleep(300)  # 5분 대기
    except asyncio.CancelledError:
        return

    while True:
        try:
            retention_days = int(os.getenv("CHAT_RETENTION_DAYS", "60"))
            if retention_days > 0:
                db = get_session()
                try:
                    cutoff = datetime.now() - timedelta(days=retention_days)
                    old_messages = (
                        db.query(ChatMessage)
                        .filter(ChatMessage.created_at < cutoff)
                        .all()
                    )
                    if old_messages:
                        deleted_ids = [msg.id for msg in old_messages]
                        for msg in old_messages:
                            db.delete(msg)
                        db.commit()

                        # 삭제된 메시지 ID 브로드캐스트
                        await manager.broadcast({
                            "type": "cleanup",
                            "payload": {"message_ids": deleted_ids},
                        })
                        print(f"[채팅 정리] {len(deleted_ids)}개의 오래된 메시지 삭제 완료 "
                              f"(보관 기간: {retention_days}일)")
                finally:
                    db.close()
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[채팅 정리] 오류 발생: {e}")

        # 12시간 대기 후 다음 정리 주기 실행
        try:
            await asyncio.sleep(43200)  # 12시간 = 12 * 60 * 60
        except asyncio.CancelledError:
            return


def start_cleanup_task():
    """
    FastAPI lifespan 에서 호출하여 백그라운드 자동 정리 태스크를 시작합니다.

    Returns:
        asyncio.Task — 서버 종료 시 cancel() 할 수 있는 태스크 핸들
    """
    loop = asyncio.get_event_loop()
    return loop.create_task(_auto_cleanup_loop())
