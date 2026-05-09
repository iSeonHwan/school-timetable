"""편제 설정 — 학년/반 입력"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QFrame, QMessageBox, QHeaderView, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import Grade, SchoolClass, Room

HEADER_STYLE = "background:#1B4F8A; color:white; font-weight:bold; padding:6px;"
BTN_PRIMARY = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"


class ClassSetupWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("편제 설정 (학년 / 반)")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 학년 섹션 ──────────────────────────────────────────
        grade_frame = QFrame()
        grade_frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        gf_layout = QVBoxLayout(grade_frame)
        gf_layout.setContentsMargins(12, 10, 12, 10)

        lbl_grade = QLabel("학년 관리")
        lbl_grade.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl_grade.setStyleSheet("color:#1B4F8A; border:none;")
        gf_layout.addWidget(lbl_grade)

        # 입력 폼
        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("학년 번호:"))
        self.spin_grade = QSpinBox()
        self.spin_grade.setRange(1, 6)
        self.spin_grade.setValue(1)
        self.spin_grade.setFixedWidth(70)
        form_row.addWidget(self.spin_grade)

        form_row.addSpacing(12)
        form_row.addWidget(QLabel("학년명:"))
        self.edit_grade_name = QLineEdit()
        self.edit_grade_name.setPlaceholderText("예: 1학년")
        self.edit_grade_name.setFixedWidth(120)
        form_row.addWidget(self.edit_grade_name)

        btn_add_grade = QPushButton("학년 추가")
        btn_add_grade.setStyleSheet(BTN_PRIMARY)
        btn_add_grade.clicked.connect(self._add_grade)
        form_row.addWidget(btn_add_grade)
        form_row.addStretch()
        gf_layout.addLayout(form_row)

        self.tbl_grades = QTableWidget(0, 3)
        self.tbl_grades.setHorizontalHeaderLabels(["ID", "학년 번호", "학년명"])
        self.tbl_grades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_grades.setMaximumHeight(160)
        self.tbl_grades.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_grades.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_grades.setStyleSheet("border:none;")
        gf_layout.addWidget(self.tbl_grades)

        btn_del_grade = QPushButton("선택 학년 삭제")
        btn_del_grade.setStyleSheet(BTN_DANGER)
        btn_del_grade.clicked.connect(self._del_grade)
        gf_layout.addWidget(btn_del_grade, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(grade_frame)

        # ── 학반 섹션 ──────────────────────────────────────────
        class_frame = QFrame()
        class_frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        cf_layout = QVBoxLayout(class_frame)
        cf_layout.setContentsMargins(12, 10, 12, 10)

        lbl_class = QLabel("반 관리")
        lbl_class.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl_class.setStyleSheet("color:#1B4F8A; border:none;")
        cf_layout.addWidget(lbl_class)

        class_row = QHBoxLayout()
        class_row.addWidget(QLabel("학년 선택:"))
        self.cb_grade = QComboBox()
        self.cb_grade.setMinimumWidth(100)
        class_row.addWidget(self.cb_grade)

        class_row.addSpacing(12)
        class_row.addWidget(QLabel("반 번호:"))
        self.spin_class = QSpinBox()
        self.spin_class.setRange(1, 30)
        self.spin_class.setValue(1)
        self.spin_class.setFixedWidth(70)
        class_row.addWidget(self.spin_class)

        class_row.addSpacing(12)
        class_row.addWidget(QLabel("표시명:"))
        self.edit_class_name = QLineEdit()
        self.edit_class_name.setPlaceholderText("예: 1-1")
        self.edit_class_name.setFixedWidth(100)
        class_row.addWidget(self.edit_class_name)

        btn_add_class = QPushButton("반 추가")
        btn_add_class.setStyleSheet(BTN_PRIMARY)
        btn_add_class.clicked.connect(self._add_class)
        class_row.addWidget(btn_add_class)
        class_row.addStretch()
        cf_layout.addLayout(class_row)

        self.tbl_classes = QTableWidget(0, 4)
        self.tbl_classes.setHorizontalHeaderLabels(["ID", "학년", "반 번호", "표시명"])
        self.tbl_classes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_classes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_classes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_classes.setStyleSheet("border:none;")
        cf_layout.addWidget(self.tbl_classes)

        btn_del_class = QPushButton("선택 반 삭제")
        btn_del_class.setStyleSheet(BTN_DANGER)
        btn_del_class.clicked.connect(self._del_class)
        cf_layout.addWidget(btn_del_class, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(class_frame)
        layout.addStretch()

    # ── 데이터 로딩 ──────────────────────────────────────────

    def _load_data(self):
        session = get_session()
        try:
            grades = session.query(Grade).order_by(Grade.grade_number).all()
            self.tbl_grades.setRowCount(len(grades))
            self.cb_grade.clear()
            for row, g in enumerate(grades):
                self.tbl_grades.setItem(row, 0, QTableWidgetItem(str(g.id)))
                self.tbl_grades.setItem(row, 1, QTableWidgetItem(str(g.grade_number)))
                self.tbl_grades.setItem(row, 2, QTableWidgetItem(g.name))
                self.cb_grade.addItem(g.name, g.id)

            classes = (
                session.query(SchoolClass)
                .join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number)
                .all()
            )
            self.tbl_classes.setRowCount(len(classes))
            for row, c in enumerate(classes):
                self.tbl_classes.setItem(row, 0, QTableWidgetItem(str(c.id)))
                self.tbl_classes.setItem(row, 1, QTableWidgetItem(c.grade.name))
                self.tbl_classes.setItem(row, 2, QTableWidgetItem(str(c.class_number)))
                self.tbl_classes.setItem(row, 3, QTableWidgetItem(c.display_name))
        finally:
            session.close()

    def refresh(self):
        self._load_data()

    # ── 학년 CRUD ────────────────────────────────────────────

    def _add_grade(self):
        gnum = self.spin_grade.value()
        gname = self.edit_grade_name.text().strip()
        if not gname:
            gname = f"{gnum}학년"
        session = get_session()
        try:
            exists = session.query(Grade).filter_by(grade_number=gnum).first()
            if exists:
                QMessageBox.warning(self, "중복", f"{gnum}학년이 이미 존재합니다.")
                return
            grade = Grade(grade_number=gnum, name=gname)
            session.add(grade)
            session.commit()
            self._load_data()
        finally:
            session.close()

    def _del_grade(self):
        row = self.tbl_grades.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 학년을 선택해 주세요.")
            return
        gid = int(self.tbl_grades.item(row, 0).text())
        reply = QMessageBox.question(
            self, "삭제 확인",
            "해당 학년과 소속 반 전체가 삭제됩니다. 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            session.query(Grade).filter_by(id=gid).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()

    # ── 학반 CRUD ────────────────────────────────────────────

    def _add_class(self):
        grade_id = self.cb_grade.currentData()
        if not grade_id:
            QMessageBox.warning(self, "오류", "학년을 먼저 추가해 주세요.")
            return
        cnum = self.spin_class.value()
        cname = self.edit_class_name.text().strip()

        session = get_session()
        try:
            grade = session.get(Grade, grade_id)
            if not cname:
                cname = f"{grade.grade_number}-{cnum}"
            exists = session.query(SchoolClass).filter_by(
                grade_id=grade_id, class_number=cnum
            ).first()
            if exists:
                QMessageBox.warning(self, "중복", f"{cname} 반이 이미 존재합니다.")
                return
            cls = SchoolClass(grade_id=grade_id, class_number=cnum, display_name=cname)
            session.add(cls)
            session.commit()
            self._load_data()
        finally:
            session.close()

    def _del_class(self):
        row = self.tbl_classes.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 반을 선택해 주세요.")
            return
        cid = int(self.tbl_classes.item(row, 0).text())
        reply = QMessageBox.question(
            self, "삭제 확인", "해당 반을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            session.query(SchoolClass).filter_by(id=cid).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()
