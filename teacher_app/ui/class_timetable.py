"""
학반 시간표 위젯 — 학반을 선택해 해당 반의 주간 시간표를 조회합니다.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from shared.api_client import ApiClient, ApiError

DAYS = ["월", "화", "수", "목", "금"]


class _LoadWorker(QThread):
    done = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, class_id: int, term_id: int):
        super().__init__()
        self._client = client
        self._class_id = class_id
        self._term_id = term_id

    def run(self):
        try:
            entries = self._client.get(
                "/timetable/entries",
                term_id=self._term_id,
                class_id=self._class_id,
            )
            self.done.emit(entries)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class ClassTimetableWidget(QWidget):
    """학반별 시간표 조회 위젯."""

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client
        self._worker = None
        self._term_id: int | None = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("학반별 시간표")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("학반:"))
        self.cb_class = QComboBox()
        self.cb_class.setMinimumWidth(120)
        row.addWidget(self.cb_class)

        btn = QPushButton("조회")
        btn.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px;"
        )
        btn.clicked.connect(self._load_timetable)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(52)
        layout.addWidget(self.table)

    def refresh(self):
        """페이지 전환 시 학반 목록과 현재 학기를 새로 불러옵니다."""
        try:
            classes = self._client.get("/setup/classes")
            terms = self._client.get("/timetable/terms")

            current = next((t for t in terms if t.get("is_current")), None)
            if not current and terms:
                current = terms[0]
            self._term_id = current["id"] if current else None

            self.cb_class.clear()
            for c in classes:
                self.cb_class.addItem(c["display_name"], c["id"])
        except Exception as e:
            QMessageBox.warning(self, "조회 오류", str(e))

    def _load_timetable(self):
        if self._term_id is None:
            QMessageBox.warning(self, "오류", "학기 정보를 불러오지 못했습니다.")
            return
        class_id = self.cb_class.currentData()
        if class_id is None:
            QMessageBox.warning(self, "오류", "학반을 선택하세요.")
            return
        self._worker = _LoadWorker(self._client, class_id, self._term_id)
        self._worker.done.connect(self._populate)
        self._worker.error.connect(lambda m: QMessageBox.warning(self, "조회 오류", m))
        self._worker.start()

    def _populate(self, entries: list):
        if not entries:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        max_period = max(e["period"] for e in entries)
        self.table.setRowCount(max_period)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(DAYS)
        self.table.setVerticalHeaderLabels([f"{i}교시" for i in range(1, max_period + 1)])

        for r in range(max_period):
            for c in range(5):
                self.table.setItem(r, c, QTableWidgetItem(""))

        for e in entries:
            row = e["period"] - 1
            col = e["day_of_week"] - 1
            subj = e.get("subject_short") or e.get("subject_name") or "?"
            teacher = e.get("teacher_name") or ""
            item = QTableWidgetItem(f"{subj}\n{teacher}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color = e.get("subject_color", "#E3F2FD")
            item.setBackground(QColor(color))
            self.table.setItem(row, col, item)
