"""
NEIS 스타일 시간표 그리드 위젯 (두 가지 모드)
- Mode A: 요일(열) × 교시(행) — 학반별 주간 시간표
- Mode B: 교시(열) × 학반(행) — 1일차 전체 학반 시간표
"""
from PyQt6.QtWidgets import (
    QWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QLabel, QFrame, QHBoxLayout, QHeaderView, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QBrush

DAYS_KR = ["월", "화", "수", "목", "금"]
PERIOD_LABELS = [f"{i}교시" for i in range(1, 8)]

HEADER_BG = "#1B4F8A"
HEADER_FG = "#FFFFFF"
EMPTY_BG = "#F8F9FA"
BORDER_COLOR = "#CCCCCC"


def _make_header_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setBackground(QBrush(QColor(HEADER_BG)))
    item.setForeground(QBrush(QColor(HEADER_FG)))
    font = QFont()
    font.setBold(True)
    font.setPointSize(9)
    item.setFont(font)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _make_cell_widget(subject: str, teacher: str, color_hex: str) -> QWidget:
    frame = QFrame()
    frame.setStyleSheet(
        f"background-color: {color_hex}; border: none;"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(3, 3, 3, 3)
    layout.setSpacing(1)

    lbl_subject = QLabel(subject)
    lbl_subject.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_subject.setWordWrap(True)
    f1 = QFont()
    f1.setBold(True)
    f1.setPointSize(9)
    lbl_subject.setFont(f1)
    lbl_subject.setStyleSheet("color: #1a1a1a; background: transparent;")

    lbl_teacher = QLabel(teacher)
    lbl_teacher.setAlignment(Qt.AlignmentFlag.AlignCenter)
    f2 = QFont()
    f2.setPointSize(8)
    lbl_teacher.setFont(f2)
    lbl_teacher.setStyleSheet("color: #555555; background: transparent;")

    layout.addWidget(lbl_subject)
    layout.addWidget(lbl_teacher)
    return frame


def _make_empty_item() -> QTableWidgetItem:
    item = QTableWidgetItem("")
    item.setBackground(QBrush(QColor(EMPTY_BG)))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class TimetableGridA(QWidget):
    """Mode A: 요일(열) × 교시(행) — 특정 학반의 주간 시간표"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: dict = {}   # (day, period) -> {subject, teacher, color}
        self._max_periods = 7
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(self._max_periods, 5)
        self.table.setHorizontalHeaderLabels(DAYS_KR)
        self.table.setVerticalHeaderLabels(PERIOD_LABELS[:self._max_periods])

        # 헤더 스타일
        self._style_headers()

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(70)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {BORDER_COLOR};
                border: 1px solid {BORDER_COLOR};
                font-size: 9pt;
            }}
            QHeaderView::section {{
                background-color: {HEADER_BG};
                color: {HEADER_FG};
                font-weight: bold;
                font-size: 9pt;
                border: 1px solid #153a6a;
                padding: 4px;
            }}
        """)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        layout.addWidget(self.table)
        self._fill_empty()

    def _style_headers(self):
        vh = self.table.verticalHeader()
        vh.setStyleSheet(f"""
            QHeaderView::section {{
                background-color: {HEADER_BG};
                color: {HEADER_FG};
                font-weight: bold;
                font-size: 9pt;
                border: 1px solid #153a6a;
                padding: 4px;
            }}
        """)

    def _fill_empty(self):
        for row in range(self._max_periods):
            for col in range(5):
                self.table.setItem(row, col, _make_empty_item())

    def load(self, entries: list[dict], max_periods: int = 7):
        """
        entries: list of {day(1~5), period(1~N), subject_name, teacher_name, color_hex}
        """
        self._max_periods = max_periods
        self.table.setRowCount(max_periods)
        self.table.setVerticalHeaderLabels(PERIOD_LABELS[:max_periods])
        self._fill_empty()

        for e in entries:
            row = e["period"] - 1
            col = e["day"] - 1
            if 0 <= row < max_periods and 0 <= col < 5:
                widget = _make_cell_widget(
                    e.get("subject_name", ""),
                    e.get("teacher_name", ""),
                    e.get("color_hex", "#FFFFFF"),
                )
                self.table.setCellWidget(row, col, widget)
                self.table.setItem(row, col, None)


class TimetableGridB(QWidget):
    """Mode B: 교시(열) × 학반(행) — 1일차 전체 학반 시간표"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 0)
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {BORDER_COLOR};
                border: 1px solid {BORDER_COLOR};
                font-size: 9pt;
            }}
            QHeaderView::section {{
                background-color: {HEADER_BG};
                color: {HEADER_FG};
                font-weight: bold;
                font-size: 9pt;
                border: 1px solid #153a6a;
                padding: 4px;
            }}
        """)
        layout.addWidget(self.table)

    def load(self, class_names: list[str], entries_by_class: dict[str, dict], max_periods: int = 7):
        """
        class_names: ["1-1", "1-2", ...]
        entries_by_class: {"1-1": {period: {subject_name, teacher_name, color_hex}, ...}, ...}
        """
        n_rows = len(class_names)
        n_cols = max_periods

        self.table.setRowCount(n_rows)
        self.table.setColumnCount(n_cols)
        self.table.setHorizontalHeaderLabels(PERIOD_LABELS[:max_periods])
        self.table.setVerticalHeaderLabels(class_names)

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(70)
        self.table.verticalHeader().setStyleSheet(f"""
            QHeaderView::section {{
                background-color: {HEADER_BG};
                color: {HEADER_FG};
                font-weight: bold;
                font-size: 9pt;
                border: 1px solid #153a6a;
                padding: 4px;
            }}
        """)

        for row, cls_name in enumerate(class_names):
            periods = entries_by_class.get(cls_name, {})
            for col in range(max_periods):
                period = col + 1
                if period in periods:
                    e = periods[period]
                    widget = _make_cell_widget(
                        e.get("subject_name", ""),
                        e.get("teacher_name", ""),
                        e.get("color_hex", "#FFFFFF"),
                    )
                    self.table.setCellWidget(row, col, widget)
                else:
                    self.table.setItem(row, col, _make_empty_item())
