"""교사별 시간표 조회 화면 (Mode A)"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame, QMessageBox
)
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import Teacher, TimetableEntry, AcademicTerm
from .neis_grid import TimetableGridA


class TeacherTimetableView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("교사별 시간표")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        filter_bar = QFrame()
        filter_bar.setStyleSheet("background:#F0F4FA; border-radius:6px;")
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(12, 8, 12, 8)

        fb.addWidget(QLabel("학기:"))
        self.cb_term = QComboBox()
        self.cb_term.setMinimumWidth(140)
        fb.addWidget(self.cb_term)

        fb.addSpacing(16)
        fb.addWidget(QLabel("교사:"))
        self.cb_teacher = QComboBox()
        self.cb_teacher.setMinimumWidth(120)
        fb.addWidget(self.cb_teacher)

        fb.addStretch()
        btn = QPushButton("조회")
        btn.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:6px 18px; font-weight:bold;"
        )
        btn.clicked.connect(self._load)
        fb.addWidget(btn)

        layout.addWidget(filter_bar)

        self.grid = TimetableGridA()
        layout.addWidget(self.grid)

        self._populate_combos()

    def _populate_combos(self):
        session = get_session()
        try:
            self.cb_term.clear()
            for t in session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all():
                self.cb_term.addItem(str(t), t.id)
            if self.cb_term.count() == 0:
                self.cb_term.addItem("(학기 없음)", None)

            self.cb_teacher.clear()
            for t in session.query(Teacher).order_by(Teacher.name).all():
                self.cb_teacher.addItem(t.name, t.id)
            if self.cb_teacher.count() == 0:
                self.cb_teacher.addItem("(교사 없음)", None)
        finally:
            session.close()

    def refresh(self):
        self._populate_combos()

    def _load(self):
        term_id = self.cb_term.currentData()
        teacher_id = self.cb_teacher.currentData()
        if not term_id or not teacher_id:
            QMessageBox.warning(self, "조회 오류", "학기와 교사를 선택해 주세요.")
            return

        session = get_session()
        try:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, teacher_id=teacher_id)
                .all()
            )
            data = []
            for e in entries:
                data.append({
                    "day": e.day_of_week,
                    "period": e.period,
                    "subject_name": e.subject.short_name if e.subject else "",
                    "teacher_name": e.school_class.display_name if e.school_class else "",
                    "color_hex": e.subject.color_hex if e.subject else "#FFFFFF",
                })
            self.grid.load(data)
        finally:
            session.close()
