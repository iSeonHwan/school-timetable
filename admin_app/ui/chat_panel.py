"""
채팅 패널 위젯 (관리자·교사 공용)

화면 오른쪽에 고정 너비로 배치되는 공동 채팅창입니다.
WebSocket 으로 실시간 메시지를 수신하고, QThread 안에서 run_forever 를 실행합니다.

기능:
  - 접속 시 최근 100개 메시지 이력 자동 로드
  - 실시간 새 메시지 수신
  - 메시지 입력·전송
  - 관리자(일과계·교감)는 '공지' 체크박스 활성화 → 🔔 강조 표시
  - 일과계(admin)는 메시지 삭제 가능 (개별 삭제 + 오래된 메시지 일괄 정리)
  - WebSocket 삭제 이벤트 수신 시 해당 메시지를 UI 에서 즉시 제거
  - 연결 끊김 시 자동 재연결 (5초 간격)

메시지 UI 구조:
  QScrollArea 안에 QVBoxLayout 으로 개별 MessageBubble(QFrame) 위젯을 쌓는 방식입니다.
  각 버블에는 message_id 가 할당되어 있어, 삭제 이벤트 수신 시 특정 버블만
  선택적으로 제거할 수 있습니다.
"""
from __future__ import annotations
import json
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QFrame, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor
from shared.api_client import ApiClient
import websocket


# ── WebSocket 백그라운드 스레드 ──────────────────────────────────────────────

class _WsThread(QThread):
    """
    WebSocket 연결을 백그라운드에서 유지하는 스레드.

    역할별 WebSocket 이벤트:
      - message_received : 서버로부터 수신한 모든 JSON 메시지 (history, chat, delete, cleanup)
      - connected        : WebSocket 연결 성공
      - disconnected     : WebSocket 연결 종료
    """
    message_received = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client
        self._ws_app: websocket.WebSocketApp | None = None
        self._running = True

    def run(self):
        while self._running:
            try:
                self._ws_app = self._client.connect_chat(
                    on_message=lambda ws, msg: self.message_received.emit(msg),
                    on_error=lambda ws, err: None,
                    on_close=lambda ws, c, m: self.disconnected.emit(),
                )
                self.connected.emit()
                self._ws_app.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                pass
            if self._running:
                # 연결 실패·종료 시 5초 후 재연결
                time.sleep(5)

    def send_json(self, payload: dict):
        """WebSocket 으로 임의의 JSON 이벤트를 전송합니다."""
        if self._ws_app:
            try:
                self._ws_app.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

    def stop(self):
        self._running = False
        if self._ws_app:
            self._ws_app.close()


# ── 메시지 버블 위젯 ─────────────────────────────────────────────────────────

class _MessageBubble(QFrame):
    """
    개별 채팅 메시지를 표시하는 위젯.

    일반 메시지: 파란색 사용자명 + 시간 + 내용
    공지 메시지: 노란 배경 + 왼쪽 주황 테두리 + 🔔 아이콘

    일과계(admin) 로그인 시 우측 상단에 삭제 버튼(✕)이 표시됩니다.
    """

    # 상위 ChatPanel 에서 연결할 시그널
    delete_requested = pyqtSignal(int)  # message_id 를 인자로 전달

    def __init__(self, msg: dict, can_delete: bool = False, parent=None):
        """
        Args:
            msg: ChatMessageOut 형식의 딕셔너리 (id, username, content, is_announcement, created_at)
            can_delete: True 이면 삭제 버튼(✕) 을 표시합니다 (일과계 전용).
        """
        super().__init__(parent)
        self._msg_id = msg.get("id", 0)
        self._set_style(msg, can_delete)

    @property
    def message_id(self) -> int:
        return self._msg_id

    def _set_style(self, msg: dict, can_delete: bool):
        """메시지 내용과 유형에 따라 버블 스타일을 설정합니다."""
        username = msg.get("username", "?")
        content = msg.get("content", "")
        is_ann = msg.get("is_announcement", False)
        created_at = msg.get("created_at", "")

        # 시각을 HH:MM 으로 짧게 표시
        time_str = str(created_at)[11:16] if len(str(created_at)) >= 16 else ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # ── 헤더 행: 사용자명 + 시간 + (삭제 버튼) ──
        header = QHBoxLayout()
        header.setSpacing(6)

        name_label = QLabel(f"<b style='color:#1B4F8A;'>{username}</b>")
        name_label.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(name_label)

        time_label = QLabel(f"<span style='color:#AAA; font-size:10px;'>{time_str}</span>")
        time_label.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(time_label)

        header.addStretch()

        # 일과계(admin) 에게만 삭제 버튼 표시
        if can_delete:
            btn_del = QPushButton("✕")
            btn_del.setFixedSize(18, 18)
            btn_del.setToolTip("이 메시지 삭제")
            btn_del.setStyleSheet(
                "QPushButton { color:#E74C3C; border:none; background:transparent; "
                "font-size:11px; font-weight:bold; padding:0; }"
                "QPushButton:hover { color:#C0392B; background:#FDEDEC; border-radius:3px; }"
            )
            btn_del.clicked.connect(lambda: self.delete_requested.emit(self._msg_id))
            header.addWidget(btn_del)

        layout.addLayout(header)

        # ── 내용 행 ──
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label.setStyleSheet("font-size:12px;")
        layout.addWidget(content_label)

        # ── 배경 스타일: 공지 vs 일반 ──
        if is_ann:
            self.setStyleSheet(
                "_MessageBubble {"
                "  background:#FFF3CD;"
                "  border-left: 3px solid #F39C12;"
                "  border-radius: 3px;"
                "  margin: 2px 0;"
                "}"
            )
        else:
            self.setStyleSheet(
                "_MessageBubble {"
                "  background: transparent;"
                "  border-bottom: 1px solid #EEE;"
                "  margin: 0;"
                "}"
            )


# ── 채팅 패널 ────────────────────────────────────────────────────────────────

class ChatPanel(QWidget):
    """
    공동 채팅 패널 — 관리자·교사 모두 사용.

    사용자 역할에 따른 기능 차이:
      - teacher              : 메시지 열람·전송만 가능
      - vice_principal (교감): 메시지 열람·전송 + 공지 발송 가능
      - admin (일과계)      : 메시지 열람·전송 + 공지 발송 + 메시지 삭제 + 일괄 정리 가능
    """

    def __init__(self, client: ApiClient, is_admin: bool = False):
        """
        Args:
            client   : ApiClient 인스턴스 (로그인 완료된 상태)
            is_admin : True 이면 공지 전송 기능 활성화 (일과계·교감)
        """
        super().__init__()
        self._client = client
        self._is_admin = is_admin  # 공지 전송 가능 여부 (일과계·교감)

        # 일과계(admin role)만 메시지 삭제 가능
        self._can_delete = (client.role == "admin")

        self._ws_thread: _WsThread | None = None
        self._bubbles: list[_MessageBubble] = []  # 현재 표시 중인 버블 목록

        self._init_ui()
        self._start_ws()

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 헤더 ──────────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet("background:#2C3E50;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 8, 10, 8)

        title = QLabel("💬 전체 채팅")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:white;")
        h_layout.addWidget(title)

        self.lbl_status = QLabel("●")
        self.lbl_status.setStyleSheet("color:#E74C3C; font-size:10px;")
        self.lbl_status.setToolTip("서버 연결 상태")
        h_layout.addWidget(self.lbl_status)

        h_layout.addStretch()

        # 일과계 전용: 오래된 메시지 일괄 정리 버튼
        if self._can_delete:
            btn_cleanup = QPushButton("🗑 정리")
            btn_cleanup.setFixedHeight(24)
            btn_cleanup.setToolTip(
                f"보관 기간이 지난 오래된 메시지를 일괄 삭제합니다.\n"
                f"(CHAT_RETENTION_DAYS 환경 변수 기준)"
            )
            btn_cleanup.setStyleSheet(
                "QPushButton { color:#E74C3C; background:#34495E; border:none; "
                "border-radius:3px; padding:2px 8px; font-size:11px; font-weight:bold; }"
                "QPushButton:hover { background:#C0392B; color:white; }"
            )
            btn_cleanup.clicked.connect(self._cleanup_old_messages)
            h_layout.addWidget(btn_cleanup)

        layout.addWidget(header)

        # ── 스크롤 가능한 메시지 목록 ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background:#F8F9FA; border:none; }"
            "QScrollBar:vertical { width:6px; background:#EEE; }"
            "QScrollBar::handle:vertical { background:#CCC; border-radius:3px; }"
        )

        # 메시지 버블을 쌓을 컨테이너
        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(4, 4, 4, 4)
        self._msg_layout.setSpacing(0)
        self._msg_layout.addStretch()  # 하단 여백 — 새 메시지가 위로 쌓이도록

        scroll.setWidget(self._msg_container)
        layout.addWidget(scroll, stretch=1)

        # ── 구분선 ──────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#DDD;")
        layout.addWidget(sep)

        # ── 입력 영역 ──────────────────────────────────────────────────────
        input_frame = QFrame()
        input_frame.setStyleSheet("background:white; border-top:1px solid #DDD;")
        in_layout = QVBoxLayout(input_frame)
        in_layout.setContentsMargins(8, 6, 8, 6)
        in_layout.setSpacing(4)

        self.edit_msg = QLineEdit()
        self.edit_msg.setPlaceholderText("메시지를 입력하세요…")
        self.edit_msg.setStyleSheet("border:1px solid #CCC; border-radius:4px; padding:5px;")
        self.edit_msg.returnPressed.connect(self._send_message)
        in_layout.addWidget(self.edit_msg)

        btn_row = QHBoxLayout()

        # 공지 체크박스 — 일과계·교감만 보임
        self.chk_announce = QCheckBox("🔔 공지")
        self.chk_announce.setVisible(self._is_admin)
        self.chk_announce.setStyleSheet("font-size:11px;")
        btn_row.addWidget(self.chk_announce)

        btn_row.addStretch()

        self.btn_send = QPushButton("전송")
        self.btn_send.setFixedWidth(56)
        self.btn_send.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:5px; font-weight:bold;"
        )
        self.btn_send.clicked.connect(self._send_message)
        btn_row.addWidget(self.btn_send)

        in_layout.addLayout(btn_row)
        layout.addWidget(input_frame)

    # ── WebSocket ─────────────────────────────────────────────────────────────

    def _start_ws(self):
        self._ws_thread = _WsThread(self._client)
        self._ws_thread.message_received.connect(self._on_ws_message)
        self._ws_thread.connected.connect(self._on_connected)
        self._ws_thread.disconnected.connect(self._on_disconnected)
        self._ws_thread.start()

    def _on_connected(self):
        self.lbl_status.setStyleSheet("color:#2ECC71; font-size:10px;")
        self.lbl_status.setToolTip("서버에 연결됨")

    def _on_disconnected(self):
        self.lbl_status.setStyleSheet("color:#E74C3C; font-size:10px;")
        self.lbl_status.setToolTip("서버 연결 끊김 — 재연결 시도 중")

    def _on_ws_message(self, raw: str):
        """WebSocket 으로 수신한 JSON 을 파싱하여 이벤트 유형별로 처리합니다."""
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        etype = event.get("type")

        if etype == "history":
            # 접속 직후 서버가 보내는 메시지 이력 — 기존 버블을 모두 제거하고 다시 그림
            self._clear_all_bubbles()
            for msg in event.get("payload", []):
                self._add_bubble(msg)
            self._scroll_to_bottom()

        elif etype == "chat":
            # 새 메시지 수신
            self._add_bubble(event.get("payload", {}))
            self._scroll_to_bottom()

        elif etype == "delete":
            # 서버에서 특정 메시지가 삭제됨 → UI 에서 해당 버블 제거
            msg_id = event.get("payload", {}).get("message_id")
            if msg_id is not None:
                self._remove_bubble(msg_id)

        elif etype == "cleanup":
            # 서버에서 오래된 메시지 일괄 삭제 → UI 에서 여러 버블 제거
            msg_ids = event.get("payload", {}).get("message_ids", [])
            for mid in msg_ids:
                self._remove_bubble(mid)

    # ── 버블 추가/제거 ───────────────────────────────────────────────────────

    def _add_bubble(self, msg: dict):
        """
        메시지 버블 하나를 목록에 추가합니다.

        stretch 아이템 바로 위(메시지 목록의 끝)에 삽입하여
        최신 메시지가 항상 하단에 표시되도록 합니다.
        """
        bubble = _MessageBubble(
            msg,
            can_delete=self._can_delete,
            parent=self._msg_container,
        )
        bubble.delete_requested.connect(self._delete_message)
        # stretch 위에 삽입 (stretch 는 마지막 아이템)
        insert_idx = self._msg_layout.count() - 1
        self._msg_layout.insertWidget(insert_idx, bubble)
        self._bubbles.append(bubble)

    def _remove_bubble(self, msg_id: int):
        """
        특정 message_id 를 가진 버블을 UI 에서 찾아 제거합니다.

        이 메서드는 WebSocket delete/cleanup 이벤트 수신 시 호출되며,
        다른 클라이언트가 삭제한 메시지도 모든 접속자의 UI 에서 제거됩니다.
        """
        for bubble in self._bubbles:
            if bubble.message_id == msg_id:
                self._msg_layout.removeWidget(bubble)
                bubble.deleteLater()
                self._bubbles.remove(bubble)
                break

    def _clear_all_bubbles(self):
        """모든 메시지 버블을 제거합니다. (history 이벤트 수신 시 사용)"""
        for bubble in self._bubbles:
            self._msg_layout.removeWidget(bubble)
            bubble.deleteLater()
        self._bubbles.clear()

    def _scroll_to_bottom(self):
        """스크롤을 최하단으로 이동합니다. QTimer.singleShot 으로 레이아웃 갱신 후 처리."""
        def _scroll():
            sb = self.findChild(QScrollArea).verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())
        QTimer.singleShot(50, _scroll)

    # ── 메시지 전송 ───────────────────────────────────────────────────────────

    def _send_message(self):
        content = self.edit_msg.text().strip()
        if not content:
            return
        is_ann = self._is_admin and self.chk_announce.isChecked()
        if self._ws_thread:
            self._ws_thread.send_json({
                "type": "chat",
                "payload": {"content": content, "is_announcement": is_ann},
            })
        self.edit_msg.clear()
        self.chk_announce.setChecked(False)

    # ── 메시지 삭제 (일과계 전용) ─────────────────────────────────────────────

    def _delete_message(self, msg_id: int):
        """
        개별 메시지 삭제를 서버에 요청합니다.

        WebSocket 으로 delete 이벤트를 전송하면,
        서버가 DB 에서 삭제 후 모든 클라이언트에게 브로드캐스트합니다.
        자기 자신을 포함한 모든 클라이언트는 _on_ws_message → "delete" 경로로
        UI 에서 해당 버블을 제거합니다.
        """
        if self._ws_thread:
            self._ws_thread.send_json({
                "type": "delete",
                "payload": {"message_id": msg_id},
            })

    def _cleanup_old_messages(self):
        """
        오래된 메시지 일괄 정리를 서버에 요청합니다. (일과계 전용)

        REST API DELETE /chat/messages 를 호출하여
        CHAT_RETENTION_DAYS 기준보다 오래된 메시지를 모두 삭제합니다.
        서버가 삭제 후 cleanup 이벤트를 브로드캐스트하면 모든 클라이언트 UI 가 갱신됩니다.
        """
        try:
            # ApiClient 의 delete 는 동기 블로킹이므로 간단한 메시지에는 문제 없음
            from shared.api_client import ApiError
            result = self._client.delete("/chat/messages")
            count = result.get("deleted_count", 0)
            if count > 0:
                # 서버가 브로드캐스트하는 cleanup 이벤트로 UI 는 자동 갱신됨
                pass
        except Exception:
            # 오류는 무시 — 백그라운드 자동 정리 태스크가 알아서 처리함
            pass

    def disconnect_ws(self):
        """로그아웃 또는 창 닫기 시 WebSocket 연결을 종료합니다."""
        if self._ws_thread:
            self._ws_thread.stop()
            self._ws_thread.wait(3000)
