"""교과목 및 주당 시수 입력 화면"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QFrame, QMessageBox, QHeaderView, QCheckBox, QColorDialog, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from database.connection import get_session
from database.models import Subject, SchoolClass, Grade, Teacher, SubjectClassAssignment

BTN_PRIMARY = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"

PRESET_COLORS = [
    "#FFE0B2", "#E3F2FD", "#E8F5E9", "#F3E5F5",
    "#FFF9C4", "#FFEBEE", "#E0F7FA", "#FCE4EC",
    "#F1F8E9", "#FBE9E7", "#EDE7F6", "#E0F2F1",
]
_color_idx = 0


def _next_color() -> str:
    global _color_idx
    c = PRESET_COLORS[_color_idx % len(PRESET_COLORS)]
    _color_idx += 1
    return c


class SubjectSetupWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_color = _next_color()
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("교과목 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 교과목 추가 ───────────────────────────────────────
        frame1 = QFrame()
        frame1.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f1_layout = QVBoxLayout(frame1)
        f1_layout.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("교과목 추가")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f1_layout.addWidget(lbl)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("교과명:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("예: 수학")
        self.edit_name.setFixedWidth(120)
        row1.addWidget(self.edit_name)

        row1.addSpacing(8)
        row1.addWidget(QLabel("약어:"))
        self.edit_short = QLineEdit()
        self.edit_short.setPlaceholderText("예: 수")
        self.edit_short.setFixedWidth(70)
        row1.addWidget(self.edit_short)

        row1.addSpacing(8)
        self.chk_special = QCheckBox("특별실 필요")
        row1.addWidget(self.chk_special)

        row1.addSpacing(8)
        row1.addWidget(QLabel("색상:"))
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(32, 24)
        self._refresh_color_btn()
        self.btn_color.clicked.connect(self._pick_color)
        row1.addWidget(self.btn_color)

        btn_add = QPushButton("교과목 추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_subject)
        row1.addWidget(btn_add)
        row1.addStretch()
        f1_layout.addLayout(row1)

        self.tbl_subjects = QTableWidget(0, 5)
        self.tbl_subjects.setHorizontalHeaderLabels(["ID", "교과명", "약어", "색상", "특별실"])
        self.tbl_subjects.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_subjects.setMaximumHeight(180)
        self.tbl_subjects.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_subjects.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_subjects.setStyleSheet("border:none;")
        f1_layout.addWidget(self.tbl_subjects)

        btn_del = QPushButton("선택 교과목 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._del_subject)
        f1_layout.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(frame1)

        # ── 시수 배정 ─────────────────────────────────────────
        frame2 = QFrame()
        frame2.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f2_layout = QVBoxLayout(frame2)
        f2_layout.setContentsMargins(12, 10, 12, 10)

        lbl2 = QLabel("반별 교과 시수 배정")
        lbl2.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl2.setStyleSheet("color:#1B4F8A; border:none;")
        f2_layout.addWidget(lbl2)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("학반:"))
        self.cb_class = QComboBox()
        self.cb_class.setMinimumWidth(100)
        row2.addWidget(self.cb_class)

        row2.addSpacing(8)
        row2.addWidget(QLabel("교과:"))
        self.cb_subject = QComboBox()
        self.cb_subject.setMinimumWidth(120)
        row2.addWidget(self.cb_subject)

        row2.addSpacing(8)
        row2.addWidget(QLabel("담당 교사:"))
        self.cb_teacher = QComboBox()
        self.cb_teacher.setMinimumWidth(120)
        row2.addWidget(self.cb_teacher)

        row2.addSpacing(8)
        row2.addWidget(QLabel("주당 시수:"))
        self.spin_hours = QSpinBox()
        self.spin_hours.setRange(1, 10)
        self.spin_hours.setValue(3)
        self.spin_hours.setFixedWidth(60)
        row2.addWidget(self.spin_hours)

        btn_assign = QPushButton("배정 추가")
        btn_assign.setStyleSheet(BTN_PRIMARY)
        btn_assign.clicked.connect(self._add_assignment)
        row2.addWidget(btn_assign)
        row2.addStretch()
        f2_layout.addLayout(row2)

        self.tbl_assignments = QTableWidget(0, 6)
        self.tbl_assignments.setHorizontalHeaderLabels(["ID", "학반", "교과", "교사", "주당시수", ""])
        self.tbl_assignments.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_assignments.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_assignments.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_assignments.setStyleSheet("border:none;")
        f2_layout.addWidget(self.tbl_assignments)

        btn_del_assign = QPushButton("선택 배정 삭제")
        btn_del_assign.setStyleSheet(BTN_DANGER)
        btn_del_assign.clicked.connect(self._del_assignment)
        f2_layout.addWidget(btn_del_assign, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(frame2)
        layout.addStretch()

    # ── helpers ──────────────────────────────────────────────

    def _refresh_color_btn(self):
        self.btn_color.setStyleSheet(
            f"background-color:{self._selected_color}; border:1px solid #999;"
        )

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self._selected_color), self, "색상 선택")
        if color.isValid():
            self._selected_color = color.name()
            self._refresh_color_btn()

    def _load_data(self):
        session = get_session()
        try:
            subjects = session.query(Subject).order_by(Subject.name).all()
            self.tbl_subjects.setRowCount(len(subjects))
            self.cb_subject.clear()
            for row, s in enumerate(subjects):
                self.tbl_subjects.setItem(row, 0, QTableWidgetItem(str(s.id)))
                self.tbl_subjects.setItem(row, 1, QTableWidgetItem(s.name))
                self.tbl_subjects.setItem(row, 2, QTableWidgetItem(s.short_name))
                color_item = QTableWidgetItem(s.color_hex)
                color_item.setBackground(QColor(s.color_hex))
                self.tbl_subjects.setItem(row, 3, color_item)
                self.tbl_subjects.setItem(row, 4, QTableWidgetItem("예" if s.needs_special_room else "아니오"))
                self.cb_subject.addItem(s.name, s.id)

            classes = (
                session.query(SchoolClass).join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number).all()
            )
            self.cb_class.clear()
            for c in classes:
                self.cb_class.addItem(c.display_name, c.id)

            teachers = session.query(Teacher).order_by(Teacher.name).all()
            self.cb_teacher.clear()
            for t in teachers:
                self.cb_teacher.addItem(t.name, t.id)

            assignments = (
                session.query(SubjectClassAssignment).all()
            )
            self.tbl_assignments.setRowCount(len(assignments))
            for row, a in enumerate(assignments):
                self.tbl_assignments.setItem(row, 0, QTableWidgetItem(str(a.id)))
                self.tbl_assignments.setItem(row, 1, QTableWidgetItem(a.school_class.display_name if a.school_class else ""))
                self.tbl_assignments.setItem(row, 2, QTableWidgetItem(a.subject.name if a.subject else ""))
                self.tbl_assignments.setItem(row, 3, QTableWidgetItem(a.teacher.name if a.teacher else ""))
                self.tbl_assignments.setItem(row, 4, QTableWidgetItem(str(a.weekly_hours)))
        finally:
            session.close()

    def refresh(self):
        self._load_data()

    def _add_subject(self):
        name = self.edit_name.text().strip()
        short = self.edit_short.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "교과명을 입력해 주세요.")
            return
        if not short:
            short = name[:2]
        session = get_session()
        try:
            s = Subject(
                name=name, short_name=short,
                color_hex=self._selected_color,
                needs_special_room=self.chk_special.isChecked(),
            )
            session.add(s)
            session.commit()
            self.edit_name.clear()
            self.edit_short.clear()
            self._selected_color = _next_color()
            self._refresh_color_btn()
            self._load_data()
        finally:
            session.close()

    def _del_subject(self):
        row = self.tbl_subjects.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 교과목을 선택해 주세요.")
            return
        sid = int(self.tbl_subjects.item(row, 0).text())
        session = get_session()
        try:
            session.query(Subject).filter_by(id=sid).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()

    def _add_assignment(self):
        class_id = self.cb_class.currentData()
        subject_id = self.cb_subject.currentData()
        teacher_id = self.cb_teacher.currentData()
        if not class_id or not subject_id or not teacher_id:
            QMessageBox.warning(self, "오류", "학반, 교과, 교사를 모두 선택해 주세요.")
            return
        hours = self.spin_hours.value()
        session = get_session()
        try:
            existing = session.query(SubjectClassAssignment).filter_by(
                school_class_id=class_id, subject_id=subject_id, teacher_id=teacher_id
            ).first()
            if existing:
                existing.weekly_hours = hours
            else:
                a = SubjectClassAssignment(
                    school_class_id=class_id, subject_id=subject_id,
                    teacher_id=teacher_id, weekly_hours=hours,
                )
                session.add(a)
            session.commit()
            self._load_data()
        finally:
            session.close()

    def _del_assignment(self):
        row = self.tbl_assignments.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 배정을 선택해 주세요.")
            return
        aid = int(self.tbl_assignments.item(row, 0).text())
        session = get_session()
        try:
            session.query(SubjectClassAssignment).filter_by(id=aid).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()
