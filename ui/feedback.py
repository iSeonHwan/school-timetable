"""
피드백 수집 다이얼로그

사용자가 버그 신고·기능 제안·UI 개선 의견을 작성하면
프로젝트 루트의 feedback.json 파일에 JSON 배열로 누적 저장합니다.

저장 형식:
  [
    {
      "timestamp": "2025-09-01T14:30:00",
      "category": "버그 신고",
      "message": "..."
    },
    ...
  ]

파일이 없으면 새로 생성하고, 손상된 JSON 이면 초기화 후 저장합니다.
"""
import json
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QTextEdit,
    QComboBox, QDialogButtonBox, QMessageBox,
)
from PyQt6.QtGui import QFont

FEEDBACK_CATEGORIES = ["버그 신고", "기능 제안", "UI 개선", "기타"]

# feedback.json 의 기본 경로: 프로젝트 루트 (이 파일의 두 단계 상위)
DEFAULT_FEEDBACK_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "feedback.json"
)


class FeedbackDialog(QDialog):
    """
    피드백 입력 다이얼로그.

    Args:
        feedback_file: 저장할 JSON 파일 경로. 기본값은 프로젝트 루트의 feedback.json.
                       테스트 시 임시 경로를 주입할 수 있습니다.
    """

    def __init__(self, parent=None, feedback_file: str = DEFAULT_FEEDBACK_FILE):
        super().__init__(parent)
        self._feedback_file = feedback_file
        self.setWindowTitle("피드백 보내기")
        self.setMinimumWidth(420)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("피드백 / 의견 보내기")
        title.setFont(QFont("", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#1B4F8A;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        # 피드백 유형 선택
        self.cb_category = QComboBox()
        self.cb_category.addItems(FEEDBACK_CATEGORIES)
        form.addRow("유형:", self.cb_category)

        # 내용 입력
        self.text_message = QTextEdit()
        self.text_message.setPlaceholderText("내용을 입력해 주세요...")
        self.text_message.setMinimumHeight(120)
        form.addRow("내용:", self.text_message)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("제출")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        btns.accepted.connect(self._submit)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _submit(self):
        """
        내용을 검증하고 feedback.json 에 저장합니다.
        공백만 있는 내용은 거부합니다.
        """
        message = self.text_message.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "입력 오류", "내용을 입력해 주세요.")
            return

        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "category":  self.cb_category.currentText(),
            "message":   message,
        }
        self._save(entry)
        QMessageBox.information(self, "감사합니다", "피드백이 저장되었습니다. 감사합니다!")
        self.accept()

    def _save(self, entry: dict) -> None:
        """
        feedback.json 에 항목을 추가합니다.
        파일이 없으면 새로 생성하고, JSON 파싱 오류가 발생하면 배열을 초기화합니다.
        """
        entries = []
        if os.path.exists(self._feedback_file):
            with open(self._feedback_file, "r", encoding="utf-8") as f:
                try:
                    entries = json.load(f)
                except json.JSONDecodeError:
                    # 파일이 손상된 경우 기존 내용을 버리고 새로 시작합니다.
                    entries = []

        entries.append(entry)

        with open(self._feedback_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
