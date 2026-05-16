"""
내 시간표 위젯 — 로그인한 교사의 주간 시간표를 그리드로 표시합니다.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from shared.api_client import ApiClient, ApiError

DAYS = ["월", "화", "수", "목", "금"]


class _LoadWorker(QThread):
    done = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, teacher_id: int, term_id: int):
        super().__init__()
        self._client = client
        self._teacher_id = teacher_id
        self._term_id = term_id

    def run(self):
        try:
            entries = self._client.get(
                "/timetable/entries",
                term_id=self._term_id,
                teacher_id=self._teacher_id,
            )
            self.done.emit(entries)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class MyTimetableWidget(QWidget):
    """로그인한 교사의 주간 시간표."""

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

        self.lbl_title = QLabel("내 시간표")
        self.lbl_title.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(self.lbl_title)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(52)
        layout.addWidget(self.table)

    def refresh(self):
        teacher_id = self._client.teacher_id
        if not teacher_id:
            self.lbl_title.setText("내 시간표 (교사 계정이 연결되지 않음)")
            return
        # 현재 학기 조회
        try:
            terms = self._client.get("/timetable/terms")
            current = next((t for t in terms if t.get("is_current")), None)
            if not current:
                current = terms[0] if terms else None
            if not current:
                self.lbl_title.setText("내 시간표 (등록된 학기 없음)")
                return
            self._term_id = current["id"]
            self.lbl_title.setText(
                f"내 시간표 — {current['year']}년 {current['semester']}학기"
            )
        except Exception as e:
            QMessageBox.warning(self, "오류", str(e))
            return

        self._worker = _LoadWorker(self._client, teacher_id, self._term_id)
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

        # 빈 칸 초기화
        for r in range(max_period):
            for c in range(5):
                self.table.setItem(r, c, QTableWidgetItem(""))

        for e in entries:
            row = e["period"] - 1
            col = e["day_of_week"] - 1
            text = e.get("subject_short") or e.get("subject_name") or "?"
            class_name = ""  # 교사 시간표에서는 학반 정보도 표시하면 유용합니다
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color = e.get("subject_color", "#E3F2FD")
            item.setBackground(QColor(color))
            self.table.setItem(row, col, item)
