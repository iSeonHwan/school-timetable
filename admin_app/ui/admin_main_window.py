"""
관리자 메인 창

기존 MainWindow 의 레이아웃(사이드바 + QStackedWidget)을 유지하면서
우측에 채팅 패널(너비 280px)이 추가된 구조입니다.

편제·시간표 관련 위젯은 ui/ 폴더의 기존 PyQt6 위젯을 그대로 재활용하며,
SQLAlchemy 세션으로 DB에 직접 접근합니다.
채팅 패널만 ApiClient 를 통해 서버의 WebSocket 엔드포인트에 연결합니다.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFrame, QLabel, QPushButton, QStackedWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from shared.api_client import ApiClient
from admin_app.ui.chat_panel import ChatPanel

# 기존 설정 위젯 재활용
from ui.setup.class_setup import ClassSetupWidget
from ui.setup.teacher_setup import TeacherSetupWidget
from ui.setup.subject_setup import SubjectSetupWidget
from ui.setup.room_setup import RoomSetupWidget
from ui.timetable.class_view import ClassViewWidget
from ui.timetable.teacher_view import TeacherViewWidget
from ui.history.history_view import HistoryViewWidget

SIDEBAR_W = 180
CHAT_W = 280  # 채팅 패널 고정 너비


class AdminMainWindow(QMainWindow):
    """관리자용 메인 창. 기존 MainWindow 에 로그인·채팅이 추가된 버전."""

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client
        self.setWindowTitle("학교 시간표 관리 시스템 — 관리자")
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)
        self._worker = None
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
        sidebar.setStyleSheet("background:#1B4F8A;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        title_lbl = QLabel("📅 시간표 관리")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setFont(QFont("", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color:white; background:#153d6a; padding:16px 8px;")
        sb_layout.addWidget(title_lbl)

        self._nav_buttons: list[QPushButton] = []
        nav_items = [
            ("학년·반 관리", 0), ("교사 관리", 1), ("교과목·시수", 2),
            ("교실 관리", 3), ("학반별 시간표", 4),
            ("교사별 시간표", 5), ("변경 이력", 6),
        ]
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(self._nav_btn_style())
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sb_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sb_layout.addStretch()

        # 로그아웃 버튼
        btn_logout = QPushButton("로그아웃")
        btn_logout.setStyleSheet(
            "background:#C0392B; color:white; border:none; padding:10px; font-weight:bold;"
        )
        btn_logout.clicked.connect(self._logout)
        sb_layout.addWidget(btn_logout)

        root.addWidget(sidebar)

        # ── 메인 영역 (콘텐츠 + 채팅) ───────────────────────────────────
        main_area = QHBoxLayout()
        main_area.setSpacing(0)
        main_area.setContentsMargins(0, 0, 0, 0)

        # 콘텐츠 페이지
        self.stack = QStackedWidget()
        self.page_class_setup   = ClassSetupWidget()
        self.page_teacher_setup = TeacherSetupWidget()
        self.page_subject_setup = SubjectSetupWidget()
        self.page_room_setup    = RoomSetupWidget()
        self.page_class_view    = ClassViewWidget()
        self.page_teacher_view  = TeacherViewWidget()
        self.page_history       = HistoryViewWidget()

        for page in [
            self.page_class_setup, self.page_teacher_setup,
            self.page_subject_setup, self.page_room_setup,
            self.page_class_view, self.page_teacher_view,
            self.page_history,
        ]:
            self.stack.addWidget(page)

        main_area.addWidget(self.stack, stretch=1)

        # ── 채팅 패널 (우측 고정) ────────────────────────────────────────
        self._chat = ChatPanel(client=self._client, is_admin=True)
        self._chat.setFixedWidth(CHAT_W)
        main_area.addWidget(self._chat)

        root.addLayout(main_area)

        # 첫 페이지 활성화
        self._switch_page(0)

    def _switch_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
        # refresh() 가 있는 페이지는 전환 시 갱신합니다.
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _logout(self):
        self._client.logout()
        self._chat.disconnect_ws()
        from admin_app.ui.login_window import LoginWindow
        self._login = LoginWindow(server_url=self._client.base_url)
        self._login.show()
        self.close()

    @staticmethod
    def _nav_btn_style() -> str:
        return (
            "QPushButton { color:white; background:transparent; border:none; "
            "padding:12px 16px; text-align:left; font-size:13px; }"
            "QPushButton:hover { background:#1a5fa8; }"
            "QPushButton:checked { background:#2471c8; font-weight:bold; }"
        )
