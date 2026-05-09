"""반별 시간표 조회 화면 (Mode A + Mode B 탭)"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTabWidget, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import (
    SchoolClass, Grade, TimetableEntry, AcademicTerm
)
from .neis_grid import TimetableGridA, TimetableGridB

DAYS_KR = ["월", "화", "수", "목", "금"]


class ClassTimetableView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 타이틀
        title = QLabel("시간표 조회")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # 필터 바
        filter_bar = QFrame()
        filter_bar.setStyleSheet("background:#F0F4FA; border-radius:6px; padding:4px;")
        fb_layout = QHBoxLayout(filter_bar)
        fb_layout.setContentsMargins(12, 8, 12, 8)

        fb_layout.addWidget(QLabel("학기:"))
        self.cb_term = QComboBox()
        self.cb_term.setMinimumWidth(140)
        fb_layout.addWidget(self.cb_term)

        fb_layout.addSpacing(16)
        fb_layout.addWidget(QLabel("학반:"))
        self.cb_class = QComboBox()
        self.cb_class.setMinimumWidth(100)
        fb_layout.addWidget(self.cb_class)

        fb_layout.addSpacing(16)
        fb_layout.addWidget(QLabel("요일(B모드):"))
        self.cb_day = QComboBox()
        for d in DAYS_KR:
            self.cb_day.addItem(d)
        self.cb_day.setMinimumWidth(80)
        fb_layout.addWidget(self.cb_day)

        fb_layout.addStretch()
        btn_load = QPushButton("조회")
        btn_load.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:6px 18px; font-weight:bold;"
        )
        btn_load.clicked.connect(self._load)
        fb_layout.addWidget(btn_load)

        layout.addWidget(filter_bar)

        # 탭
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { min-width:120px; padding:8px 12px; }
            QTabBar::tab:selected { background:#1B4F8A; color:white; font-weight:bold; }
        """)

        self.grid_a = TimetableGridA()
        self.tabs.addTab(self.grid_a, "모드 A  — 요일×교시 (학반별 주간)")

        self.grid_b = TimetableGridB()
        self.tabs.addTab(self.grid_b, "모드 B  — 교시×학반 (1일 전체)")

        layout.addWidget(self.tabs)

        self._populate_combos()

    def _populate_combos(self):
        session = get_session()
        try:
            # 학기
            self.cb_term.clear()
            terms = session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self.cb_term.addItem(str(t), t.id)
            if not terms:
                self.cb_term.addItem("(학기 없음)", None)

            # 학반
            self.cb_class.clear()
            classes = (
                session.query(SchoolClass)
                .join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number)
                .all()
            )
            for c in classes:
                self.cb_class.addItem(c.display_name, c.id)
            if not classes:
                self.cb_class.addItem("(학반 없음)", None)
        finally:
            session.close()

    def refresh(self):
        self._populate_combos()

    def _load(self):
        term_id = self.cb_term.currentData()
        class_id = self.cb_class.currentData()
        if not term_id or not class_id:
            QMessageBox.warning(self, "조회 오류", "학기와 학반을 선택해 주세요.")
            return

        session = get_session()
        try:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, school_class_id=class_id)
                .all()
            )
            self._load_mode_a(entries)
            self._load_mode_b(session, term_id)
        finally:
            session.close()

    def _load_mode_a(self, entries: list):
        data = []
        for e in entries:
            data.append({
                "day": e.day_of_week,
                "period": e.period,
                "subject_name": e.subject.short_name if e.subject else "",
                "teacher_name": e.teacher.name if e.teacher else "",
                "color_hex": e.subject.color_hex if e.subject else "#FFFFFF",
            })
        self.grid_a.load(data)

    def _load_mode_b(self, session, term_id: int):
        day_idx = self.cb_day.currentIndex() + 1   # 1~5

        classes = (
            session.query(SchoolClass)
            .join(Grade)
            .order_by(Grade.grade_number, SchoolClass.class_number)
            .all()
        )
        class_names = [c.display_name for c in classes]
        entries_by_class: dict[str, dict] = {}

        for cls in classes:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, school_class_id=cls.id, day_of_week=day_idx)
                .all()
            )
            period_map: dict[int, dict] = {}
            for e in entries:
                period_map[e.period] = {
                    "subject_name": e.subject.short_name if e.subject else "",
                    "teacher_name": e.teacher.name if e.teacher else "",
                    "color_hex": e.subject.color_hex if e.subject else "#FFFFFF",
                }
            entries_by_class[cls.display_name] = period_map

        self.grid_b.load(class_names, entries_by_class)
