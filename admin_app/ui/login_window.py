"""
관리자 로그인 창

아이디·비밀번호를 입력하고 FastAPI 서버에 인증합니다.
로그인 성공 시 AdminMainWindow 를 열고 이 창을 닫습니다.

허용 역할:
  - admin (일과계 선생님): 전체 관리 기능
  - vice_principal (교감 선생님): 변경 신청 최종 승인 + 시간표 열람
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from shared.api_client import ApiClient, ApiError


class _LoginWorker(QThread):
    """로그인 API 호출을 백그라운드 스레드에서 수행합니다."""
    success = pyqtSignal(dict)   # TokenResponse 딕셔너리
    failure = pyqtSignal(str)    # 오류 메시지

    def __init__(self, client: ApiClient, username: str, password: str):
        super().__init__()
        self._client = client
        self._username = username
        self._password = password

    def run(self):
        try:
            data = self._client.login(self._username, self._password)
            # 일과계(admin) 또는 교감(vice_principal)만 관리자 앱에 접근 가능
            if data.get("role") not in ("admin", "vice_principal"):
                self._client.logout()
                self.failure.emit("관리자 계정(일과계·교감)으로만 로그인할 수 있습니다.")
            else:
                self.success.emit(data)
        except ApiError as e:
            self.failure.emit(e.detail)
        except Exception as e:
            self.failure.emit(f"서버에 연결할 수 없습니다.\n({e})")


class LoginWindow(QWidget):
    """관리자 로그인 창."""

    def __init__(self, server_url: str):
        super().__init__()
        self._client = ApiClient(server_url)
        self._worker = None
        self.setWindowTitle("관리자 로그인")
        self.setFixedSize(360, 260)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(14)

        title = QLabel("학교 시간표 관리 시스템")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(title)

        sub = QLabel("관리자 로그인")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #555;")
        layout.addWidget(sub)

        layout.addSpacing(8)

        self.edit_id = QLineEdit()
        self.edit_id.setPlaceholderText("아이디")
        layout.addWidget(self.edit_id)

        self.edit_pw = QLineEdit()
        self.edit_pw.setPlaceholderText("비밀번호")
        self.edit_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_pw.returnPressed.connect(self._do_login)
        layout.addWidget(self.edit_pw)

        self.btn_login = QPushButton("로그인")
        self.btn_login.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:8px; font-weight:bold;"
        )
        self.btn_login.clicked.connect(self._do_login)
        layout.addWidget(self.btn_login)

    def _do_login(self):
        username = self.edit_id.text().strip()
        password = self.edit_pw.text()
        if not username or not password:
            QMessageBox.warning(self, "입력 오류", "아이디와 비밀번호를 입력하세요.")
            return

        self.btn_login.setEnabled(False)
        self.btn_login.setText("로그인 중...")

        self._worker = _LoginWorker(self._client, username, password)
        self._worker.success.connect(self._on_success)
        self._worker.failure.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, data: dict):
        from admin_app.ui.admin_main_window import AdminMainWindow
        self._main = AdminMainWindow(client=self._client)
        self._main.show()
        self.close()

    def _on_failure(self, msg: str):
        self.btn_login.setEnabled(True)
        self.btn_login.setText("로그인")
        QMessageBox.critical(self, "로그인 실패", msg)
