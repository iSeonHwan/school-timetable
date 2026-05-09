"""변경 이력 조회 화면"""
from datetime import date, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QDateEdit, QTextEdit,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont, QColor, QBrush
from database.connection import get_session
from database.models import (
    TimetableChangeLog, SchoolClass, Grade, AcademicTerm,
)
import json


DAYS_KR = ["월", "화", "수", "목", "금"]
CHANGE_TYPES = {"created": "생성", "modified": "수정", "deleted": "삭제"}


class HistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("변경 이력")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # 필터
        filter_bar = QFrame()
        filter_bar.setStyleSheet("background:#F0F4FA; border-radius:6px;")
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(12, 8, 12, 8)

        fb.addWidget(QLabel("기간:"))
        self._dt_from = QDateEdit()
        self._dt_from.setCalendarPopup(True)
        self._dt_from.setDate(QDate.currentDate().addMonths(-1))
        fb.addWidget(self._dt_from)

        fb.addWidget(QLabel("~"))
        self._dt_to = QDateEdit()
        self._dt_to.setCalendarPopup(True)
        self._dt_to.setDate(QDate.currentDate())
        fb.addWidget(self._dt_to)

        fb.addSpacing(12)
        fb.addWidget(QLabel("학반:"))
        self._cb_class = QComboBox()
        self._cb_class.setMinimumWidth(100)
        fb.addWidget(self._cb_class)

        fb.addSpacing(12)
        fb.addWidget(QLabel("유형:"))
        self._cb_type = QComboBox()
        self._cb_type.addItem("전체", None)
        self._cb_type.addItem("생성", "created")
        self._cb_type.addItem("수정", "modified")
        self._cb_type.addItem("삭제", "deleted")
        fb.addWidget(self._cb_type)

        fb.addStretch()
        btn = QPushButton("조회")
        btn.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; "
            "padding:6px 18px; font-weight:bold;"
        )
        btn.clicked.connect(self.refresh)
        fb.addWidget(btn)

        layout.addWidget(filter_bar)

        # 테이블
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "일시", "학반", "변경 유형", "요일/교시", "상세 내용"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #1B4F8A; color: white;
                font-weight: bold; padding: 4px;
            }
        """)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # 상세 보기
        detail_label = QLabel("상세 내용:")
        detail_label.setFont(QFont("", 10, QFont.Weight.Bold))
        layout.addWidget(detail_label)

        self._txt_detail = QTextEdit()
        self._txt_detail.setReadOnly(True)
        self._txt_detail.setMaximumHeight(120)
        self._txt_detail.setStyleSheet("background:#F8F9FA; border:1px solid #CCC;")
        layout.addWidget(self._txt_detail)

        self._populate_class_combo()

    def _populate_class_combo(self):
        session = get_session()
        try:
            self._cb_class.clear()
            self._cb_class.addItem("전체", None)
            classes = (
                session.query(SchoolClass)
                .join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number)
                .all()
            )
            for c in classes:
                self._cb_class.addItem(c.display_name, c.id)
        finally:
            session.close()

    def refresh(self):
        session = get_session()
        try:
            q_from = self._dt_from.date()
            q_to = self._dt_to.date()
            dt_from = date(q_from.year(), q_from.month(), q_from.day())
            dt_to = date(q_to.year(), q_to.month(), q_to.day()) + timedelta(days=1)

            query = session.query(TimetableChangeLog).filter(
                TimetableChangeLog.changed_at >= dt_from,
                TimetableChangeLog.changed_at < dt_to,
            )

            class_id = self._cb_class.currentData()
            if class_id:
                query = query.filter_by(school_class_id=class_id)

            change_type = self._cb_type.currentData()
            if change_type:
                query = query.filter_by(change_type=change_type)

            logs = query.order_by(TimetableChangeLog.changed_at.desc()).limit(200).all()

            self.table.setRowCount(len(logs))
            for row, log in enumerate(logs):
                self.table.setItem(row, 0, self._item(
                    log.changed_at.strftime("%Y-%m-%d %H:%M") if log.changed_at else ""
                ))
                school_class = session.query(SchoolClass).get(log.school_class_id)
                self.table.setItem(row, 1, self._item(
                    school_class.display_name if school_class else ""
                ))
                type_text = CHANGE_TYPES.get(log.change_type, log.change_type)
                type_item = self._item(type_text)
                if log.change_type == "created":
                    type_item.setBackground(QBrush(QColor("#27AE60")))
                    type_item.setForeground(QBrush(QColor("white")))
                elif log.change_type == "modified":
                    type_item.setBackground(QBrush(QColor("#F39C12")))
                    type_item.setForeground(QBrush(QColor("white")))
                elif log.change_type == "deleted":
                    type_item.setBackground(QBrush(QColor("#E74C3C")))
                    type_item.setForeground(QBrush(QColor("white")))
                self.table.setItem(row, 2, type_item)

                slot_info = ""
                try:
                    d = json.loads(log.details) if log.details else {}
                    if log.change_type == "deleted":
                        info = d.get("deleted", {})
                    elif log.change_type == "modified":
                        info = d.get("after", {})
                    else:
                        info = d.get("after", {})
                    if info:
                        day = info.get("day", "")
                        period = info.get("period", "")
                        slot_info = f"{DAYS_KR[day - 1] if day else ''} {period}교시" if period else ""
                except (json.JSONDecodeError, KeyError):
                    pass
                self.table.setItem(row, 3, self._item(slot_info))
                self.table.setItem(row, 4, self._item(
                    self._format_details(log.details, log.change_type)
                ))
        finally:
            session.close()

    def _item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _format_details(self, details_str: str, change_type: str) -> str:
        try:
            d = json.loads(details_str) if details_str else {}
        except json.JSONDecodeError:
            return details_str[:80]

        if change_type == "created":
            after = d.get("after", {})
            return f"신규 생성 (과목ID:{after.get('subject_id')}, 교사ID:{after.get('teacher_id')})"
        elif change_type == "modified":
            before = d.get("before", {})
            after = d.get("after", {})
            parts = []
            if before.get("subject_id") != after.get("subject_id"):
                parts.append(f"과목:{before.get('subject_id')}→{after.get('subject_id')}")
            if before.get("teacher_id") != after.get("teacher_id"):
                parts.append(f"교사:{before.get('teacher_id')}→{after.get('teacher_id')}")
            if before.get("room_id") != after.get("room_id"):
                parts.append(f"교실:{before.get('room_id')}→{after.get('room_id')}")
            return ", ".join(parts) if parts else "변경 없음"
        elif change_type == "deleted":
            deleted = d.get("deleted", {})
            return f"삭제됨 (과목ID:{deleted.get('subject_id')}, 교사ID:{deleted.get('teacher_id')})"
        return ""

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            self._txt_detail.clear()
            return
        details = self.table.item(row, 4).text()
        self._txt_detail.setPlainText(details)
