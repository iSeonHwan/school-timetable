"""
교사용 메인 창

레이아웃:
  왼쪽 사이드바 | 중앙 콘텐츠(시간표·신청) | 오른쪽 채팅 패널

콘텐츠 탭:
  1. 내 시간표    — 본인 teacher_id 로 필터된 TimetableEntryOut 그리드
  2. 학반 시간표  — 학반 선택 후 그리드
  3. 교체 신청   — 신청 제출 및 내 신청 목록
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFrame, QLabel, QPushButton, QStackedWidget,
    QDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from shared.api_client import ApiClient
from admin_app.ui.chat_panel import ChatPanel   # 채팅 패널은 공용으로 재활용
from teacher_app.ui.my_timetable import MyTimetableWidget
from teacher_app.ui.class_timetable import ClassTimetableWidget
from teacher_app.ui.request_widget import RequestWidget
from teacher_app.ui.notification_panel import NotificationPanel

SIDEBAR_W = 160
CHAT_W = 260


class _LoadUnreadCountWorker(QThread):
    """GET /notifications/unread-count 를 비동기로 조회하는 워커."""
    done = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client

    def run(self):
        try:
            result = self._client.get("/notifications/unread-count")
            self.done.emit(result.get("unread_count", 0))
        except Exception as e:
            self.error.emit(str(e))


class TeacherMainWindow(QMainWindow):
    """교사용 메인 창."""

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client
        self.setWindowTitle("시간표 확인 시스템 — 교사용")
        self.resize(1200, 780)
        self.setMinimumSize(900, 600)
        self._nav_buttons: list[QPushButton] = []
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 사이드바 ────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(SIDEBAR_W)
        sidebar.setStyleSheet("background:#1A6B3C;")
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        title = QLabel("📅 시간표")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        title.setStyleSheet("color:white; background:#145230; padding:16px 8px;")
        sb.addWidget(title)

        # ── 알림 버튼 ─────────────────────────────────────────────────────
        self.btn_notifications = QPushButton("🔔 알림 0")
        self.btn_notifications.setStyleSheet(
            "QPushButton { color:white; background:#1d7d47; border:none; "
            "padding:10px 16px; text-align:left; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background:#239a55; }"
        )
        self.btn_notifications.clicked.connect(self._show_notifications)
        sb.addWidget(self.btn_notifications)

        nav_items = [("내 시간표", 0), ("학반 시간표", 1), ("교체 신청", 2)]
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { color:white; background:transparent; border:none; "
                "padding:12px 16px; text-align:left; font-size:13px; }"
                "QPushButton:hover { background:#1d7d47; }"
                "QPushButton:checked { background:#239a55; font-weight:bold; }"
            )
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sb.addWidget(btn)
            self._nav_buttons.append(btn)

        sb.addStretch()

        btn_logout = QPushButton("로그아웃")
        btn_logout.setStyleSheet(
            "background:#C0392B; color:white; border:none; padding:10px; font-weight:bold;"
        )
        btn_logout.clicked.connect(self._logout)
        sb.addWidget(btn_logout)

        root.addWidget(sidebar)

        # ── 중앙 콘텐츠 ─────────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.page_my    = MyTimetableWidget(client=self._client)
        self.page_class = ClassTimetableWidget(client=self._client)
        self.page_req   = RequestWidget(client=self._client)

        for page in [self.page_my, self.page_class, self.page_req]:
            self.stack.addWidget(page)

        root.addWidget(self.stack, stretch=1)

        # ── 채팅 패널 ────────────────────────────────────────────────────
        # 일과계(admin) 또는 교감(vice_principal)은 공지 전송 가능
        is_admin = self._client.role in ("admin", "vice_principal")
        self._chat = ChatPanel(client=self._client, is_admin=is_admin)
        self._chat.setFixedWidth(CHAT_W)
        root.addWidget(self._chat)

        # WebSocket 실시간 알림 수신 시 읽지 않은 개수 갱신
        self._chat.notification_received.connect(self._on_notification_received)
        self._refresh_unread_count()

        self._switch_page(0)

    def _switch_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _show_notifications(self):
        """알림 패널을 다이얼로그로 표시합니다."""
        dlg = QDialog(self)
        dlg.setWindowTitle("알림")
        dlg.resize(420, 480)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        panel = NotificationPanel(client=self._client, parent=dlg)
        layout.addWidget(panel)

        # 다이얼로그가 닫히면 읽지 않은 개수를 다시 조회합니다.
        dlg.finished.connect(self._refresh_unread_count)
        dlg.exec()

    def _on_notification_received(self, payload: dict):
        """WebSocket 으로 실시간 알림 수신 시 벨 아이콘을 강조하고 개수를 갱신합니다."""
        self.btn_notifications.setStyleSheet(
            "QPushButton { color:white; background:#C0392B; border:none; "
            "padding:10px 16px; text-align:left; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background:#E74C3C; }"
        )
        self._refresh_unread_count()

    def _refresh_unread_count(self):
        """서버에서 읽지 않은 알림 개수를 조회해 벨 버튼에 표시합니다."""
        self._unread_worker = _LoadUnreadCountWorker(self._client)
        self._unread_worker.done.connect(self._update_badge)
        self._unread_worker.error.connect(lambda _: None)
        self._unread_worker.start()

    def _update_badge(self, count: int):
        """읽지 않은 알림 개수를 버튼 텍스트에 반영합니다."""
        self.btn_notifications.setText(f"🔔 알림 {count}")
        # 새 알림이 없으면 기본 색상으로 복원
        if count == 0:
            self.btn_notifications.setStyleSheet(
                "QPushButton { color:white; background:#1d7d47; border:none; "
                "padding:10px 16px; text-align:left; font-size:12px; font-weight:bold; }"
                "QPushButton:hover { background:#239a55; }"
            )

    def _logout(self):
        self._client.logout()
        self._chat.disconnect_ws()
        from teacher_app.ui.login_window import TeacherLoginWindow
        self._login = TeacherLoginWindow(server_url=self._client.base_url)
        self._login.show()
        self.close()
