"""
채팅 API — REST + WebSocket

GET  /chat/messages        — 최근 메시지 목록 (REST, 접속 시 이력 로드용)
POST /chat/messages        — 메시지 전송 (REST fallback)
WS   /chat/ws?token=...    — 실시간 WebSocket 채팅

WebSocket 프로토콜:
  클라이언트 → 서버:
    {"type": "chat", "payload": {"content": "...", "is_announcement": false}}
    {"type": "ping"}

  서버 → 클라이언트:
    {"type": "history",  "payload": [ChatMessageOut, ...]}   # 접속 직후 최근 100개
    {"type": "chat",     "payload": ChatMessageOut}          # 새 메시지 브로드캐스트
    {"type": "pong"}
    {"type": "error",    "payload": {"detail": "..."}}
"""
from __future__ import annotations
import json
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, HTTPException
from sqlalchemy.orm import Session

from shared.models import ChatMessage, User
from shared.schemas import ChatMessageOut, ChatMessageCreate
from server.deps import get_db, get_current_user
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
    if body.is_announcement and current_user.role != "admin":
        raise HTTPException(403, "공지 메시지는 관리자만 전송할 수 있습니다.")
    msg = _save_message(db, current_user, body.content, body.is_announcement)
    return _to_out(msg, db)


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

            elif etype == "chat":
                p = event.get("payload", {})
                content = str(p.get("content", "")).strip()
                is_ann = bool(p.get("is_announcement", False))

                if not content:
                    await ws.send_text(json.dumps({"type": "error", "payload": {"detail": "빈 메시지"}}))
                    continue
                if is_ann and user.role != "admin":
                    await ws.send_text(json.dumps({"type": "error", "payload": {"detail": "공지는 관리자만 가능합니다."}}))
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
