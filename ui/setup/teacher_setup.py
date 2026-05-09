"""교사 정보 입력 화면"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QFrame, QMessageBox, QHeaderView, QCheckBox, QComboBox,
    QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import Teacher, SchoolClass, Grade, TeacherConstraint

BTN_PRIMARY = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"
BTN_ORANGE = "background:#E67E22; color:white; border-radius:4px; padding:6px 14px;"

DAYS_KR = ["월", "화", "수", "목", "금"]
PERIODS = list(range(1, 8))


class TeacherSetupWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._constraint_checkboxes: dict = {}   # (day, period) -> QCheckBox
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("교사 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 교사 추가 ─────────────────────────────────────────
        frame1 = QFrame()
        frame1.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f1 = QVBoxLayout(frame1)
        f1.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("교사 추가/편집")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f1.addWidget(lbl)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("이름:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("홍길동")
        self.edit_name.setFixedWidth(100)
        row1.addWidget(self.edit_name)

        row1.addSpacing(8)
        row1.addWidget(QLabel("교원번호:"))
        self.edit_empno = QLineEdit()
        self.edit_empno.setPlaceholderText("선택입력")
        self.edit_empno.setFixedWidth(100)
        row1.addWidget(self.edit_empno)

        row1.addSpacing(8)
        row1.addWidget(QLabel("일 최대 수업:"))
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 10)
        self.spin_max.setValue(5)
        self.spin_max.setFixedWidth(60)
        row1.addWidget(self.spin_max)

        row1.addSpacing(8)
        self.chk_homeroom = QCheckBox("담임")
        row1.addWidget(self.chk_homeroom)

        row1.addSpacing(8)
        row1.addWidget(QLabel("담임 학반:"))
        self.cb_homeroom_class = QComboBox()
        self.cb_homeroom_class.setMinimumWidth(90)
        row1.addWidget(self.cb_homeroom_class)

        btn_add = QPushButton("교사 추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_teacher)
        row1.addWidget(btn_add)
        row1.addStretch()
        f1.addLayout(row1)

        self.tbl_teachers = QTableWidget(0, 5)
        self.tbl_teachers.setHorizontalHeaderLabels(["ID", "이름", "교원번호", "담임", "일최대"])
        self.tbl_teachers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_teachers.setMaximumHeight(200)
        self.tbl_teachers.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_teachers.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_teachers.setStyleSheet("border:none;")
        self.tbl_teachers.selectionModel().selectionChanged.connect(self._on_teacher_selected)
        f1.addWidget(self.tbl_teachers)

        btn_del = QPushButton("선택 교사 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._del_teacher)
        f1.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(frame1)

        # ── 교사 불가 시간 설정 ───────────────────────────────
        frame2 = QFrame()
        frame2.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f2 = QVBoxLayout(frame2)
        f2.setContentsMargins(12, 10, 12, 10)

        lbl2 = QLabel("교사 불가 시간 설정")
        lbl2.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl2.setStyleSheet("color:#1B4F8A; border:none;")
        f2.addWidget(lbl2)

        self.lbl_selected_teacher = QLabel("(교사를 위에서 선택하세요)")
        self.lbl_selected_teacher.setStyleSheet("color:#888; border:none;")
        f2.addWidget(self.lbl_selected_teacher)

        grid = QGridLayout()
        grid.setSpacing(4)
        # 헤더 행
        for col, day in enumerate(DAYS_KR):
            lbl_day = QLabel(day)
            lbl_day.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_day.setStyleSheet("font-weight:bold; color:#1B4F8A; border:none;")
            grid.addWidget(lbl_day, 0, col + 1)

        for row, period in enumerate(PERIODS):
            lbl_p = QLabel(f"{period}교시")
            lbl_p.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_p.setStyleSheet("border:none;")
            grid.addWidget(lbl_p, row + 1, 0)
            for col, _ in enumerate(DAYS_KR):
                day = col + 1
                chk = QCheckBox()
                chk.setStyleSheet("border:none;")
                grid.addWidget(chk, row + 1, col + 1, alignment=Qt.AlignmentFlag.AlignCenter)
                self._constraint_checkboxes[(day, period)] = chk

        f2.addLayout(grid)

        btn_save_constraints = QPushButton("불가 시간 저장")
        btn_save_constraints.setStyleSheet(BTN_ORANGE)
        btn_save_constraints.clicked.connect(self._save_constraints)
        f2.addWidget(btn_save_constraints, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(frame2)
        layout.addStretch()

        self._selected_teacher_id: int | None = None

    # ── 데이터 ───────────────────────────────────────────────

    def _load_data(self):
        session = get_session()
        try:
            teachers = session.query(Teacher).order_by(Teacher.name).all()
            self.tbl_teachers.setRowCount(len(teachers))
            for row, t in enumerate(teachers):
                self.tbl_teachers.setItem(row, 0, QTableWidgetItem(str(t.id)))
                self.tbl_teachers.setItem(row, 1, QTableWidgetItem(t.name))
                self.tbl_teachers.setItem(row, 2, QTableWidgetItem(t.employee_number or ""))
                self.tbl_teachers.setItem(row, 3, QTableWidgetItem("예" if t.is_homeroom else ""))
                self.tbl_teachers.setItem(row, 4, QTableWidgetItem(str(t.max_daily_classes)))

            classes = (
                session.query(SchoolClass).join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number).all()
            )
            self.cb_homeroom_class.clear()
            self.cb_homeroom_class.addItem("(없음)", None)
            for c in classes:
                self.cb_homeroom_class.addItem(c.display_name, c.id)
        finally:
            session.close()

    def refresh(self):
        self._load_data()

    def _on_teacher_selected(self):
        row = self.tbl_teachers.currentRow()
        if row < 0:
            return
        tid = int(self.tbl_teachers.item(row, 0).text())
        tname = self.tbl_teachers.item(row, 1).text()
        self._selected_teacher_id = tid
        self.lbl_selected_teacher.setText(f"선택된 교사: {tname}")

        # 불가 시간 체크박스 업데이트
        session = get_session()
        try:
            constraints = session.query(TeacherConstraint).filter_by(
                teacher_id=tid, constraint_type="unavailable"
            ).all()
            unavail = {(c.day_of_week, c.period) for c in constraints}
            for (day, period), chk in self._constraint_checkboxes.items():
                chk.setChecked((day, period) in unavail)
        finally:
            session.close()

    def _add_teacher(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "이름을 입력해 주세요.")
            return
        homeroom_class_id = self.cb_homeroom_class.currentData()
        session = get_session()
        try:
            t = Teacher(
                name=name,
                employee_number=self.edit_empno.text().strip(),
                is_homeroom=self.chk_homeroom.isChecked(),
                homeroom_class_id=homeroom_class_id,
                max_daily_classes=self.spin_max.value(),
            )
            session.add(t)
            session.commit()
            self.edit_name.clear()
            self.edit_empno.clear()
            self._load_data()
        finally:
            session.close()

    def _del_teacher(self):
        row = self.tbl_teachers.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 교사를 선택해 주세요.")
            return
        tid = int(self.tbl_teachers.item(row, 0).text())
        reply = QMessageBox.question(
            self, "삭제 확인", "해당 교사를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            session.query(Teacher).filter_by(id=tid).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()

    def _save_constraints(self):
        if not self._selected_teacher_id:
            QMessageBox.information(self, "안내", "교사를 먼저 선택해 주세요.")
            return
        session = get_session()
        try:
            session.query(TeacherConstraint).filter_by(
                teacher_id=self._selected_teacher_id, constraint_type="unavailable"
            ).delete()
            for (day, period), chk in self._constraint_checkboxes.items():
                if chk.isChecked():
                    c = TeacherConstraint(
                        teacher_id=self._selected_teacher_id,
                        day_of_week=day,
                        period=period,
                        constraint_type="unavailable",
                    )
                    session.add(c)
            session.commit()
            QMessageBox.information(self, "저장 완료", "불가 시간이 저장되었습니다.")
        finally:
            session.close()
