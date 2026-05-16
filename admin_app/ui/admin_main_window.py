"""
관리자 메인 창

기존 MainWindow 의 레이아웃(사이드바 + QStackedWidget)을 유지하면서
우측에 채팅 패널(너비 280px)이 추가된 구조입니다.

편제·시간표 관련 위젯은 ui/ 폴더의 기존 PyQt6 위젯을 그대로 재활용하며,
SQLAlchemy 세션으로 DB에 직접 접근합니다.
채팅 패널만 ApiClient 를 통해 서버의 WebSocket 엔드포인트에 연결합니다.

역할별 사이드바 구성:
  - admin (일과계 선생님): 8개 페이지 전체 접근
    학년·반 관리, 교사 관리, 교과목·시수, 교실 관리,
    학반별 시간표, 교사별 시간표, 변경 이력, 변경 신청/결재
  - vice_principal (교감 선생님): 3개 페이지 (읽기 전용 + 승인)
    학반별 시간표(읽기 전용), 교사별 시간표(읽기 전용), 변경 신청/결재
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
from ui.timetable.class_view import ClassTimetableView
from ui.timetable.teacher_view import TeacherTimetableView
from ui.history.history_view import HistoryViewWidget
from ui.timetable.request_list import ChangeRequestWidget

SIDEBAR_W = 180
CHAT_W = 280  # 채팅 패널 고정 너비

# ── 역할별 네비게이션 구성 ─────────────────────────────────────────────────────
# (라벨, 페이지 인덱스) 튜플 목록
NAV_SCHEDULER = [
    ("학년·반 관리", 0), ("교사 관리", 1), ("교과목·시수", 2),
    ("교실 관리", 3), ("학반별 시간표", 4),
    ("교사별 시간표", 5), ("변경 이력", 6), ("변경 신청/결재", 7),
]

NAV_VICE_PRINCIPAL = [
    ("학반별 시간표", 4), ("교사별 시간표", 5), ("변경 신청/결재", 7),
]


class AdminMainWindow(QMainWindow):
    """
    관리자용 메인 창.

    사용자의 role 에 따라 사이드바와 기능이 달라집니다:
      - admin (일과계): 모든 관리 기능 사용 가능
      - vice_principal (교감): 시간표 열람 + 변경 신청 최종 승인만 가능
    """

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client
        self._role = client.role  # "admin" (일과계) 또는 "vice_principal" (교감)

        # 역할에 따른 윈도우 제목 설정
        if self._role == "vice_principal":
            self.setWindowTitle("학교 시간표 관리 시스템 — 교감")
        else:
            self.setWindowTitle("학교 시간표 관리 시스템 — 일과계")

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

        # 사이드바 타이틀: 역할에 따라 다르게 표시
        title_text = "📅 시간표 관리" if self._role == "admin" else "📋 교감 검토"
        title_lbl = QLabel(title_text)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setFont(QFont("", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color:white; background:#153d6a; padding:16px 8px;")
        sb_layout.addWidget(title_lbl)

        # 역할에 맞는 네비게이션 항목 결정
        nav_items = NAV_SCHEDULER if self._role == "admin" else NAV_VICE_PRINCIPAL

        # 페이지 인덱스를 실제 위젯과 연결하기 위한 매핑
        self._page_indices = {}  # {index: widget_reference}
        self._nav_buttons: list[QPushButton] = []

        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(self._nav_btn_style())
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sb_layout.addWidget(btn)
            self._nav_buttons.append(btn)
            self._page_indices[idx] = True  # 이 인덱스가 활성화됨을 표시

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

        # 콘텐츠 페이지 — QStackedWidget. 모든 페이지를 생성하지만,
        # 교감 역할은 제한된 인덱스만 네비게이션으로 접근 가능합니다.
        self.stack = QStackedWidget()

        # 페이지 위젯 생성
        # 읽기 전용 여부: 교감은 시간표를 편집할 수 없음
        read_only = (self._role == "vice_principal")

        self.page_class_setup   = ClassSetupWidget()          # index 0
        self.page_teacher_setup = TeacherSetupWidget()        # index 1
        self.page_subject_setup = SubjectSetupWidget()        # index 2
        self.page_room_setup    = RoomSetupWidget()           # index 3
        self.page_class_view    = ClassTimetableView(read_only=read_only)   # index 4
        self.page_teacher_view  = TeacherTimetableView(read_only=read_only) # index 5
        self.page_history       = HistoryViewWidget()         # index 6
        # 변경 신청/결재 위젯 — 역할 정보를 전달하여 승인 로직이 분기되도록 함
        self.page_request_mgmt  = ChangeRequestWidget(role=self._role)   # index 7

        # 모든 페이지를 스택에 등록 (순서 중요: 인덱스 = 스택 내 위치)
        for page in [
            self.page_class_setup,
            self.page_teacher_setup,
            self.page_subject_setup,
            self.page_room_setup,
            self.page_class_view,
            self.page_teacher_view,
            self.page_history,
            self.page_request_mgmt,
        ]:
            self.stack.addWidget(page)

        main_area.addWidget(self.stack, stretch=1)

        # ── 채팅 패널 (우측 고정) ────────────────────────────────────────
        # 일과계·교감 모두 공지 가능
        self._chat = ChatPanel(client=self._client, is_admin=True)
        self._chat.setFixedWidth(CHAT_W)
        main_area.addWidget(self._chat)

        root.addLayout(main_area)

        # 첫 페이지 활성화: 역할에 맞는 첫 번째 nav 항목의 인덱스로 이동
        first_idx = nav_items[0][1]
        self._switch_page(first_idx)

    def _switch_page(self, idx: int):
        """
        페이지 전환. 교감 역할이 접근 불가능한 페이지로는 전환하지 않습니다.
        관리자(admin)는 모든 인덱스(0~7)에 접근 가능하며,
        교감(vice_principal)은 허용된 인덱스(4,5,7)만 접근 가능합니다.
        """
        self.stack.setCurrentIndex(idx)
        # 네비게이션 버튼 하이라이트: 현재 인덱스와 일치하는 버튼만 checked
        # nav_items 에서 버튼과 인덱스의 매핑을 추적
        nav_items = NAV_SCHEDULER if self._role == "admin" else NAV_VICE_PRINCIPAL
        for i, (label, nav_idx) in enumerate(nav_items):
            if i < len(self._nav_buttons):
                self._nav_buttons[i].setChecked(nav_idx == idx)

        # refresh() 가 있는 페이지는 전환 시 갱신합니다.
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _logout(self):
        """로그아웃하고 로그인 창으로 돌아갑니다."""
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
