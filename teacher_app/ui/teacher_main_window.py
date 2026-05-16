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
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from shared.api_client import ApiClient
from admin_app.ui.chat_panel import ChatPanel   # 채팅 패널은 공용으로 재활용
from teacher_app.ui.my_timetable import MyTimetableWidget
from teacher_app.ui.class_timetable import ClassTimetableWidget
from teacher_app.ui.request_widget import RequestWidget

SIDEBAR_W = 160
CHAT_W = 260


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

        self._switch_page(0)

    def _switch_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _logout(self):
        self._client.logout()
        self._chat.disconnect_ws()
        from teacher_app.ui.login_window import TeacherLoginWindow
        self._login = TeacherLoginWindow(server_url=self._client.base_url)
        self._login.show()
        self.close()
