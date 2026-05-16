"""
교사 로그인 창

teacher role 계정으로만 로그인할 수 있습니다.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from shared.api_client import ApiClient, ApiError


class _LoginWorker(QThread):
    success = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, client: ApiClient, username: str, password: str):
        super().__init__()
        self._client = client
        self._username = username
        self._password = password

    def run(self):
        try:
            data = self._client.login(self._username, self._password)
            # admin 도 교사 프로그램 로그인을 허용합니다 (시간표 확인 목적).
            self.success.emit(data)
        except ApiError as e:
            self.failure.emit(e.detail)
        except Exception as e:
            self.failure.emit(f"서버에 연결할 수 없습니다.\n({e})")


class TeacherLoginWindow(QWidget):
    """교사용 로그인 창."""

    def __init__(self, server_url: str):
        super().__init__()
        self._client = ApiClient(server_url)
        self._worker = None
        self.setWindowTitle("교사 로그인")
        self.setFixedSize(340, 240)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(12)

        title = QLabel("시간표 확인 시스템")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("", 13, QFont.Weight.Bold))
        layout.addWidget(title)

        sub = QLabel("교사 로그인")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#666;")
        layout.addWidget(sub)

        layout.addSpacing(6)

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
            "background:#27AE60; color:white; border-radius:4px; padding:8px; font-weight:bold;"
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
        from teacher_app.ui.teacher_main_window import TeacherMainWindow
        self._main = TeacherMainWindow(client=self._client)
        self._main.show()
        self.close()

    def _on_failure(self, msg: str):
        self.btn_login.setEnabled(True)
        self.btn_login.setText("로그인")
        QMessageBox.critical(self, "로그인 실패", msg)
