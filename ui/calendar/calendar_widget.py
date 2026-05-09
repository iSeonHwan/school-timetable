"""학사일정 관리 화면"""
from datetime import date
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
    QCalendarWidget, QSplitter, QDateEdit, QLineEdit,
    QTextEdit, QGroupBox, QFormLayout, QDialog,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont, QColor, QBrush
from database.connection import get_session
from database.models import SchoolEvent, AcademicTerm


EVENT_TYPES = ["개교기념일", "시험", "축제", "방학", "공휴일", "행사", "기타"]
TYPE_COLORS = {
    "개교기념일": "#E74C3C",
    "시험": "#F39C12",
    "축제": "#2ECC71",
    "방학": "#3498DB",
    "공휴일": "#E74C3C",
    "행사": "#9B59B6",
    "기타": "#95A5A6",
}


class CalendarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = get_session()
        self._events: list[SchoolEvent] = []
        self._init_ui()
        self._populate_terms()
        self._load_events()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("학사일정 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # 학기 선택
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("학기:"))
        self.cb_term = QComboBox()
        self.cb_term.setMinimumWidth(160)
        self.cb_term.currentIndexChanged.connect(self._load_events)
        top_bar.addWidget(self.cb_term)

        top_bar.addStretch()
        btn_add = QPushButton("+ 일정 추가")
        btn_add.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; "
            "padding:8px 18px; font-weight:bold;"
        )
        btn_add.clicked.connect(self._add_event)
        top_bar.addWidget(btn_add)
        layout.addLayout(top_bar)

        # 캘린더 + 이벤트 목록
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.clicked.connect(self._on_date_selected)
        splitter.addWidget(self.calendar)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self._lbl_month = QLabel("")
        self._lbl_month.setFont(QFont("", 11, QFont.Weight.Bold))
        right_layout.addWidget(self._lbl_month)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["날짜", "제목", "유형", "설명"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #1B4F8A; color: white;
                font-weight: bold; padding: 4px;
            }
        """)
        right_layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_edit = QPushButton("수정")
        btn_edit.clicked.connect(self._edit_event)
        btn_edit.setStyleSheet(
            "background:#F39C12; color:white; border-radius:4px; padding:6px 14px;"
        )
        btn_layout.addWidget(btn_edit)

        btn_delete = QPushButton("삭제")
        btn_delete.clicked.connect(self._delete_event)
        btn_delete.setStyleSheet(
            "background:#E74C3C; color:white; border-radius:4px; padding:6px 14px;"
        )
        btn_layout.addWidget(btn_delete)

        btn_layout.addStretch()
        right_layout.addLayout(btn_layout)

        splitter.addWidget(right_panel)
        splitter.setSizes([400, 500])
        layout.addWidget(splitter)

    def _populate_terms(self):
        try:
            self.cb_term.clear()
            terms = self._session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self.cb_term.addItem(str(t), t.id)
            if not terms:
                self.cb_term.addItem("(학기 없음)", None)
        except Exception:
            self.cb_term.addItem("(학기 없음)", None)

    def refresh(self):
        self._session.close()
        self._session = get_session()
        self._populate_terms()
        self._load_events()

    def _load_events(self):
        term_id = self.cb_term.currentData()
        if not term_id:
            self._events = []
        else:
            self._events = (
                self._session.query(SchoolEvent)
                .filter_by(term_id=term_id)
                .order_by(SchoolEvent.start_date)
                .all()
            )
        self._on_date_selected(self.calendar.selectedDate())

    def _on_date_selected(self, qdate: QDate):
        selected = date(qdate.year(), qdate.month(), qdate.day())
        month_start = date(selected.year, selected.month, 1)
        if selected.month == 12:
            month_end = date(selected.year + 1, 1, 1)
        else:
            month_end = date(selected.year, selected.month + 1, 1)

        self._lbl_month.setText(f"{selected.year}년 {selected.month}월 일정")

        month_events = [
            e for e in self._events
            if e.start_date < month_end and e.end_date >= month_start
        ]

        self.table.setRowCount(len(month_events))
        for row, event in enumerate(month_events):
            date_str = (
                f"{event.start_date.strftime('%m/%d')}"
                if event.start_date == event.end_date
                else f"{event.start_date.strftime('%m/%d')}~{event.end_date.strftime('%m/%d')}"
            )
            self.table.setItem(row, 0, self._item(date_str))
            self.table.setItem(row, 1, self._item(event.title))
            type_item = self._item(event.event_type)
            color = TYPE_COLORS.get(event.event_type, "#95A5A6")
            type_item.setBackground(QBrush(QColor(color)))
            type_item.setForeground(QBrush(QColor("white")))
            self.table.setItem(row, 2, type_item)
            self.table.setItem(row, 3, self._item(
                (event.description or "")[:60]
            ))

    def _item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _get_selected_event(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        # Find matching event by title + date in the current month view
        title = self.table.item(row, 1).text()
        date_str = self.table.item(row, 0).text()
        for e in self._events:
            if e.title == title and date_str in str(e.start_date):
                return e
        return None

    def _add_event(self):
        dlg = EventDialog(self._session, self.cb_term.currentData(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            session = get_session()
            try:
                data = dlg.get_data()
                event = SchoolEvent(
                    term_id=self.cb_term.currentData(),
                    title=data["title"],
                    event_type=data["event_type"],
                    start_date=data["start_date"],
                    end_date=data["end_date"],
                    description=data["description"],
                )
                session.add(event)
                session.commit()
            finally:
                session.close()
            self._load_events()

    def _edit_event(self):
        event = self._get_selected_event()
        if event is None:
            QMessageBox.warning(self, "선택 오류", "수정할 일정을 선택해 주세요.")
            return
        dlg = EventDialog(
            self._session, self.cb_term.currentData(), self,
            title=event.title, event_type=event.event_type,
            start_date=event.start_date, end_date=event.end_date,
            description=event.description,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            session = get_session()
            try:
                data = dlg.get_data()
                e = session.query(SchoolEvent).get(event.id)
                if e:
                    e.title = data["title"]
                    e.event_type = data["event_type"]
                    e.start_date = data["start_date"]
                    e.end_date = data["end_date"]
                    e.description = data["description"]
                    session.commit()
            finally:
                session.close()
            self._load_events()

    def _delete_event(self):
        event = self._get_selected_event()
        if event is None:
            QMessageBox.warning(self, "선택 오류", "삭제할 일정을 선택해 주세요.")
            return
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{event.title}' 일정을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            session = get_session()
            try:
                e = session.query(SchoolEvent).get(event.id)
                if e:
                    session.delete(e)
                    session.commit()
            finally:
                session.close()
            self._load_events()


class EventDialog(QDialog):
    def __init__(self, session, term_id, parent=None, **kwargs):
        super().__init__(parent)
        self.setWindowTitle("일정 추가" if not kwargs else "일정 수정")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)

        self._txt_title = QLineEdit(kwargs.get("title", ""))
        self._txt_title.setPlaceholderText("일정 제목")
        layout.addRow("제목:", self._txt_title)

        self._cmb_type = QComboBox()
        for et in EVENT_TYPES:
            self._cmb_type.addItem(et)
        if "event_type" in kwargs:
            idx = EVENT_TYPES.index(kwargs["event_type"]) if kwargs["event_type"] in EVENT_TYPES else 6
            self._cmb_type.setCurrentIndex(idx)
        layout.addRow("유형:", self._cmb_type)

        self._dt_start = QDateEdit()
        self._dt_start.setCalendarPopup(True)
        if "start_date" in kwargs:
            self._dt_start.setDate(QDate(kwargs["start_date"]))
        else:
            self._dt_start.setDate(QDate.currentDate())
        layout.addRow("시작일:", self._dt_start)

        self._dt_end = QDateEdit()
        self._dt_end.setCalendarPopup(True)
        if "end_date" in kwargs:
            self._dt_end.setDate(QDate(kwargs["end_date"]))
        else:
            self._dt_end.setDate(QDate.currentDate())
        layout.addRow("종료일:", self._dt_end)

        self._txt_desc = QTextEdit()
        self._txt_desc.setMaximumHeight(80)
        self._txt_desc.setPlaceholderText("설명 (선택사항)")
        if "description" in kwargs:
            self._txt_desc.setPlainText(kwargs["description"] or "")
        layout.addRow("설명:", self._txt_desc)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _validate(self):
        if not self._txt_title.text().strip():
            QMessageBox.warning(self, "입력 오류", "제목을 입력해 주세요.")
            return
        self.accept()

    def get_data(self) -> dict:
        qs = self._dt_start.date()
        qe = self._dt_end.date()
        return {
            "title": self._txt_title.text().strip(),
            "event_type": self._cmb_type.currentText(),
            "start_date": date(qs.year(), qs.month(), qs.day()),
            "end_date": date(qe.year(), qe.month(), qe.day()),
            "description": self._txt_desc.toPlainText().strip(),
        }
