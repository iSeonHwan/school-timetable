import json
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QTextEdit,
    QComboBox, QDialogButtonBox, QMessageBox,
)
from PyQt6.QtGui import QFont

FEEDBACK_CATEGORIES = ["버그 신고", "기능 제안", "UI 개선", "기타"]
DEFAULT_FEEDBACK_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "feedback.json")


class FeedbackDialog(QDialog):
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

        self.cb_category = QComboBox()
        self.cb_category.addItems(FEEDBACK_CATEGORIES)
        form.addRow("유형:", self.cb_category)

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
        message = self.text_message.toPlainText().strip()
        if not message:
            QMessageBox.warning(self, "입력 오류", "내용을 입력해 주세요.")
            return

        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "category": self.cb_category.currentText(),
            "message": message,
        }
        self._save(entry)
        QMessageBox.information(self, "감사합니다", "피드백이 저장되었습니다. 감사합니다!")
        self.accept()

    def _save(self, entry: dict) -> None:
        entries = []
        if os.path.exists(self._feedback_file):
            with open(self._feedback_file, "r", encoding="utf-8") as f:
                try:
                    entries = json.load(f)
                except json.JSONDecodeError:
                    entries = []
        entries.append(entry)
        with open(self._feedback_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
