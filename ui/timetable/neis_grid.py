"""
NEIS 스타일 시간표 그리드 위젯

두 가지 표시 모드를 제공합니다:
  TimetableGridA (Mode A):
    열 = 요일(월~금), 행 = 교시(1~7)
    특정 반 또는 교사의 주간 시간표를 표시합니다.
    셀 더블클릭 시 slot_double_clicked 시그널을 방출합니다.

  TimetableGridB (Mode B):
    열 = 교시(1~7), 행 = 학반(1-1, 1-2 …)
    선택한 요일의 전체 학반 시간표를 한눈에 표시합니다.

각 셀은 _make_cell_widget() 으로 만든 컬러 프레임 위젯으로 표시됩니다.
빈 슬롯은 _make_empty_item() 으로 연한 회색 QTableWidgetItem 으로 채웁니다.
"""
from PyQt6.QtWidgets import (
    QWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QLabel, QFrame, QHeaderView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QBrush

DAYS_KR       = ["월", "화", "수", "목", "금"]
PERIOD_LABELS = [f"{i}교시" for i in range(1, 8)]

HEADER_BG    = "#1B4F8A"   # 헤더 배경색 (남색)
HEADER_FG    = "#FFFFFF"   # 헤더 글자색 (흰색)
EMPTY_BG     = "#F8F9FA"   # 빈 셀 배경색
BORDER_COLOR = "#CCCCCC"   # 그리드 테두리색

# 헤더·셀 공통 스타일시트 (QTableWidget 에 직접 적용)
_TABLE_STYLE = f"""
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
"""


def _make_header_item(text: str) -> QTableWidgetItem:
    """헤더 셀용 QTableWidgetItem 을 생성합니다 (남색 배경, 흰색 글자, 편집 불가)."""
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
    """
    교과명과 교사명을 세로로 배치한 컬러 셀 위젯을 생성합니다.
    color_hex: 교과목에 지정된 배경색 (#RRGGBB)
    """
    frame = QFrame()
    frame.setStyleSheet(f"background-color: {color_hex}; border: none;")

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(3, 3, 3, 3)
    layout.setSpacing(1)

    # 교과명 (굵은 글씨, 약어 표시)
    lbl_subject = QLabel(subject)
    lbl_subject.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_subject.setWordWrap(True)
    f1 = QFont()
    f1.setBold(True)
    f1.setPointSize(9)
    lbl_subject.setFont(f1)
    lbl_subject.setStyleSheet("color: #1a1a1a; background: transparent;")

    # 교사명 또는 학반명 (작은 글씨, 회색)
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
    """빈 슬롯용 QTableWidgetItem 을 생성합니다 (연한 회색 배경, 편집 불가)."""
    item = QTableWidgetItem("")
    item.setBackground(QBrush(QColor(EMPTY_BG)))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class TimetableGridA(QWidget):
    """
    Mode A: 요일(열) × 교시(행) 시간표 그리드.

    특정 학반 또는 교사의 주간 시간표를 표시합니다.
    셀 더블클릭 시 slot_double_clicked(day, period) 시그널을 방출해
    부모 위젯(ClassTimetableView, TeacherTimetableView)에서 편집 다이얼로그를 엽니다.
    """
    slot_double_clicked = pyqtSignal(int, int)   # (day: 1~5, period: 1~7)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._max_periods = 7
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(self._max_periods, 5)
        self.table.setHorizontalHeaderLabels(DAYS_KR)
        self.table.setVerticalHeaderLabels(PERIOD_LABELS[:self._max_periods])

        # 수직 헤더(교시) 스타일을 QSS 로 설정합니다.
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

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(70)  # 행 높이 고정
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        layout.addWidget(self.table)
        self._fill_empty()  # 초기 상태: 모든 셀을 빈 슬롯으로 채웁니다.

    def _on_cell_double_clicked(self, row: int, col: int):
        """QTableWidget 셀 더블클릭을 (day, period) 시그널로 변환해 방출합니다."""
        day    = col + 1   # 열 인덱스(0~4) → 요일(1~5)
        period = row + 1   # 행 인덱스(0~6) → 교시(1~7)
        self.slot_double_clicked.emit(day, period)

    def _fill_empty(self):
        """모든 셀을 빈 슬롯 아이템으로 초기화합니다."""
        for row in range(self._max_periods):
            for col in range(5):
                self.table.setItem(row, col, _make_empty_item())

    def load(self, entries: list[dict], max_periods: int = 7):
        """
        시간표 데이터를 받아 그리드를 채웁니다.

        Args:
            entries: 각 항목은 다음 키를 포함합니다.
                     day(1~5), period(1~N), subject_name, teacher_name, color_hex, entry_id
            max_periods: 표시할 최대 교시 수
        """
        self._max_periods = max_periods
        self.table.setRowCount(max_periods)
        self.table.setVerticalHeaderLabels(PERIOD_LABELS[:max_periods])
        self._fill_empty()  # 먼저 모든 셀을 빈 슬롯으로 초기화

        for e in entries:
            row = e["period"] - 1
            col = e["day"] - 1
            if 0 <= row < max_periods and 0 <= col < 5:
                widget = _make_cell_widget(
                    e.get("subject_name", ""),
                    e.get("teacher_name", ""),
                    e.get("color_hex", "#FFFFFF"),
                )
                # setCellWidget 으로 위젯을 배치하면 해당 셀의 QTableWidgetItem 이 무시됩니다.
                self.table.setCellWidget(row, col, widget)
                # 위젯이 있는 셀의 기존 아이템을 제거해 더블클릭 감지가 위젯과 충돌하지 않게 합니다.
                self.table.setItem(row, col, None)


class TimetableGridB(QWidget):
    """
    Mode B: 교시(열) × 학반(행) 시간표 그리드.

    특정 요일의 모든 학반 시간표를 동시에 표시합니다.
    (편집 기능 없음 — 더블클릭 시그널 미제공)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 초기에는 행·열이 없는 빈 테이블로 시작합니다.
        self.table = QTableWidget(0, 0)
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setStyleSheet(_TABLE_STYLE)
        layout.addWidget(self.table)

    def load(self, class_names: list[str], entries_by_class: dict[str, dict], max_periods: int = 7):
        """
        요일별 전체 학반 데이터를 받아 그리드를 채웁니다.

        Args:
            class_names    : 학반 이름 목록 (예: ["1-1", "1-2", ...])
            entries_by_class: {학반명: {교시번호: {subject_name, teacher_name, color_hex}}}
            max_periods    : 표시할 최대 교시 수
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
