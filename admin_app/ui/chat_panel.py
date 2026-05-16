"""
채팅 패널 위젯 (관리자·교사 공용)

화면 오른쪽에 고정 너비로 배치되는 공동 채팅창입니다.
WebSocket 으로 실시간 메시지를 수신하고, QThread 안에서 run_forever 를 실행합니다.

기능:
  - 접속 시 최근 100개 메시지 이력 자동 로드
  - 실시간 새 메시지 수신
  - 메시지 입력·전송
  - 관리자는 '공지' 체크박스 활성화 → 🔔 강조 표시
  - 연결 끊김 시 자동 재연결 (5초 간격)
"""
from __future__ import annotations
import json
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QLineEdit, QPushButton, QCheckBox, QFrame, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from shared.api_client import ApiClient
import websocket


class _WsThread(QThread):
    """
    WebSocket 연결을 백그라운드에서 유지하는 스레드.
    메시지 수신 시 message_received 시그널을 발생시킵니다.
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

    def send(self, content: str, is_announcement: bool = False):
        if self._ws_app:
            try:
                payload = json.dumps({
                    "type": "chat",
                    "payload": {"content": content, "is_announcement": is_announcement},
                })
                self._ws_app.send(payload)
            except Exception:
                pass

    def stop(self):
        self._running = False
        if self._ws_app:
            self._ws_app.close()


class ChatPanel(QWidget):
    """공동 채팅 패널 — 관리자·교사 모두 사용."""

    def __init__(self, client: ApiClient, is_admin: bool = False):
        super().__init__()
        self._client = client
        self._is_admin = is_admin
        self._ws_thread: _WsThread | None = None
        self._init_ui()
        self._start_ws()

    # ── UI 구성 ───────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 헤더
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

        layout.addWidget(header)

        # 메시지 표시 영역
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setStyleSheet(
            "background:#F8F9FA; border:none; font-size:12px; padding:4px;"
        )
        layout.addWidget(self.chat_area, stretch=1)

        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#DDD;")
        layout.addWidget(sep)

        # 입력 영역
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

        # 공지 체크박스 — 관리자만 보임
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

    # ── WebSocket ─────────────────────────────────────────────────────────

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
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        etype = event.get("type")

        if etype == "history":
            self.chat_area.clear()
            for msg in event.get("payload", []):
                self._append_message(msg)

        elif etype == "chat":
            self._append_message(event.get("payload", {}))

    def _append_message(self, msg: dict):
        username = msg.get("username", "?")
        content = msg.get("content", "")
        is_ann = msg.get("is_announcement", False)
        created_at = msg.get("created_at", "")

        # 시각을 HH:MM 으로 짧게 표시합니다.
        time_str = str(created_at)[11:16] if len(str(created_at)) >= 16 else ""

        if is_ann:
            html = (
                f'<div style="background:#FFF3CD; border-left:3px solid #F39C12; '
                f'margin:4px 0; padding:4px 8px; border-radius:3px;">'
                f'<b>🔔 [공지] {username}</b> <span style="color:#888;font-size:10px;">{time_str}</span><br>'
                f'{content}</div>'
            )
        else:
            html = (
                f'<div style="margin:3px 0;">'
                f'<b style="color:#1B4F8A;">{username}</b> '
                f'<span style="color:#AAA;font-size:10px;">{time_str}</span><br>'
                f'{content}</div>'
            )

        self.chat_area.append(html)
        # 스크롤을 항상 최하단으로 이동합니다.
        sb = self.chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── 메시지 전송 ───────────────────────────────────────────────────────

    def _send_message(self):
        content = self.edit_msg.text().strip()
        if not content:
            return
        is_ann = self._is_admin and self.chk_announce.isChecked()
        if self._ws_thread:
            self._ws_thread.send(content, is_ann)
        self.edit_msg.clear()
        self.chk_announce.setChecked(False)

    def disconnect_ws(self):
        """로그아웃 또는 창 닫기 시 WebSocket 연결을 종료합니다."""
        if self._ws_thread:
            self._ws_thread.stop()
            self._ws_thread.wait(3000)
