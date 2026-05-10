"""
교과목 관리 및 시수 배정 화면

두 섹션으로 구성됩니다:
  1. 교과목 추가: 교과명·약어·색상·특별실 필요 여부를 입력합니다.
  2. 반별 교과 시수 배정: 학반·교과·교사·주당 시수를 연결하는
     SubjectClassAssignment 레코드를 관리합니다.

데이터 의존성:
  이 페이지는 세 가지 선행 데이터에 의존합니다:
    - 학반 콤보박스(cb_class): ClassSetupWidget 에서 등록된 SchoolClass
    - 교과 콤보박스(cb_subject): 이 페이지의 상단 섹션에서 등록된 Subject
    - 교사 콤보박스(cb_teacher): TeacherSetupWidget 에서 등록된 Teacher

  페이지 전환 시 refresh() → _load_data() 가 호출되어 모든 콤보박스가
  최신 DB 데이터로 다시 채워집니다.

  즉, 편제 설정에서 학반을 추가한 뒤 이 페이지로 오면 새 학반이 cb_class 에,
  교사 관리에서 교사를 추가한 뒤 오면 새 교사가 cb_teacher 에 나타납니다.

색상 관리:
  PRESET_COLORS: 12색 파스텔 팔레트. _next_color() 로 순환하며 자동 할당.
  사용자가 색상 버튼을 클릭하면 QColorDialog 로 직접 선택 가능.

시수 배정 중복 처리:
  같은 (학반, 교과, 교사) 조합이 이미 존재하면 weekly_hours 만 업데이트합니다.
  이는 실수로 중복 배정되는 것을 방지하면서도 시수 수정은 허용하는 설계입니다.
"""
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
BTN_DANGER  = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"

# 교과목 자동 색상 팔레트 (파스텔 계열)
PRESET_COLORS = [
    "#FFE0B2", "#E3F2FD", "#E8F5E9", "#F3E5F5",
    "#FFF9C4", "#FFEBEE", "#E0F7FA", "#FCE4EC",
    "#F1F8E9", "#FBE9E7", "#EDE7F6", "#E0F2F1",
]
_color_idx = 0   # 모듈 수준 전역 인덱스 (앱 실행 중 계속 증가)


def _next_color() -> str:
    """PRESET_COLORS 를 순환하며 다음 색상을 반환합니다."""
    global _color_idx
    c = PRESET_COLORS[_color_idx % len(PRESET_COLORS)]
    _color_idx += 1
    return c


class SubjectSetupWidget(QWidget):
    """교과목 CRUD 및 시수 배정 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_color = _next_color()   # 현재 선택된 색상 (#RRGGBB)
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

        # ── 교과목 추가 섹션 ──────────────────────────────────────────
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
        # 특별실(과학실, 음악실 등) 필요 여부
        self.chk_special = QCheckBox("특별실 필요")
        row1.addWidget(self.chk_special)

        row1.addSpacing(8)
        row1.addWidget(QLabel("색상:"))

        # 색상 버튼: 클릭 시 QColorDialog 를 엽니다.
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

        # 교과목 목록 테이블
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

        # ── 시수 배정 섹션 ────────────────────────────────────────────
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

        # 배정 목록 테이블
        self.tbl_assignments = QTableWidget(0, 5)
        self.tbl_assignments.setHorizontalHeaderLabels(["ID", "학반", "교과", "교사", "주당시수"])
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

    # ── 색상 버튼 헬퍼 ────────────────────────────────────────────────────

    def _refresh_color_btn(self):
        """색상 버튼의 배경색을 현재 선택 색상으로 갱신합니다."""
        self.btn_color.setStyleSheet(
            f"background-color:{self._selected_color}; border:1px solid #999;"
        )

    def _pick_color(self):
        """QColorDialog 를 열어 사용자가 색상을 직접 선택할 수 있게 합니다."""
        color = QColorDialog.getColor(QColor(self._selected_color), self, "색상 선택")
        if color.isValid():
            self._selected_color = color.name()   # "#RRGGBB" 형식으로 저장
            self._refresh_color_btn()

    # ── 데이터 로딩 ───────────────────────────────────────────────────────

    def _load_data(self):
        """DB 에서 교과목·학반·교사·배정 데이터를 읽어 UI 를 갱신합니다."""
        session = get_session()
        try:
            # 교과목 목록
            subjects = session.query(Subject).order_by(Subject.name).all()
            self.tbl_subjects.setRowCount(len(subjects))
            self.cb_subject.clear()
            for row, s in enumerate(subjects):
                self.tbl_subjects.setItem(row, 0, QTableWidgetItem(str(s.id)))
                self.tbl_subjects.setItem(row, 1, QTableWidgetItem(s.name))
                self.tbl_subjects.setItem(row, 2, QTableWidgetItem(s.short_name))
                color_item = QTableWidgetItem(s.color_hex)
                color_item.setBackground(QColor(s.color_hex))  # 셀 배경을 해당 색상으로 표시
                self.tbl_subjects.setItem(row, 3, color_item)
                self.tbl_subjects.setItem(row, 4, QTableWidgetItem("예" if s.needs_special_room else "아니오"))
                self.cb_subject.addItem(s.name, s.id)

            # 학반 목록
            classes = (
                session.query(SchoolClass).join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number).all()
            )
            self.cb_class.clear()
            for c in classes:
                self.cb_class.addItem(c.display_name, c.id)

            # 교사 목록
            teachers = session.query(Teacher).order_by(Teacher.name).all()
            self.cb_teacher.clear()
            for t in teachers:
                self.cb_teacher.addItem(t.name, t.id)

            # 배정 목록
            assignments = session.query(SubjectClassAssignment).all()
            self.tbl_assignments.setRowCount(len(assignments))
            for row, a in enumerate(assignments):
                self.tbl_assignments.setItem(row, 0, QTableWidgetItem(str(a.id)))
                self.tbl_assignments.setItem(row, 1, QTableWidgetItem(
                    a.school_class.display_name if a.school_class else ""
                ))
                self.tbl_assignments.setItem(row, 2, QTableWidgetItem(
                    a.subject.name if a.subject else ""
                ))
                self.tbl_assignments.setItem(row, 3, QTableWidgetItem(
                    a.teacher.name if a.teacher else ""
                ))
                self.tbl_assignments.setItem(row, 4, QTableWidgetItem(str(a.weekly_hours)))
        finally:
            session.close()

    def refresh(self):
        """외부에서 호출해 데이터를 갱신합니다."""
        self._load_data()

    # ── 교과목 CRUD ───────────────────────────────────────────────────────

    def _add_subject(self):
        """입력 폼으로 교과목을 DB 에 추가합니다."""
        name = self.edit_name.text().strip()
        short = self.edit_short.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "교과명을 입력해 주세요.")
            return
        if not short:
            short = name[:2]   # 약어 미입력 시 교과명 앞 2글자 사용

        session = get_session()
        try:
            s = Subject(
                name=name,
                short_name=short,
                color_hex=self._selected_color,
                needs_special_room=self.chk_special.isChecked(),
            )
            session.add(s)
            session.commit()
            self.edit_name.clear()
            self.edit_short.clear()
            # 다음 교과목 추가를 위해 색상을 자동으로 변경합니다.
            self._selected_color = _next_color()
            self._refresh_color_btn()
            self._load_data()
        finally:
            session.close()

    def _del_subject(self):
        """선택된 교과목을 삭제합니다."""
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

    # ── 시수 배정 CRUD ────────────────────────────────────────────────────

    def _add_assignment(self):
        """
        학반·교과·교사·시수 배정을 추가합니다.
        같은 (학반, 교과, 교사) 조합이 이미 있으면 시수만 업데이트합니다.
        """
        class_id   = self.cb_class.currentData()
        subject_id = self.cb_subject.currentData()
        teacher_id = self.cb_teacher.currentData()
        if not class_id or not subject_id or not teacher_id:
            QMessageBox.warning(self, "오류", "학반, 교과, 교사를 모두 선택해 주세요.")
            return

        hours = self.spin_hours.value()
        session = get_session()
        try:
            existing = session.query(SubjectClassAssignment).filter_by(
                school_class_id=class_id,
                subject_id=subject_id,
                teacher_id=teacher_id,
            ).first()

            if existing:
                # 이미 배정된 경우 시수만 업데이트합니다.
                existing.weekly_hours = hours
            else:
                a = SubjectClassAssignment(
                    school_class_id=class_id,
                    subject_id=subject_id,
                    teacher_id=teacher_id,
                    weekly_hours=hours,
                )
                session.add(a)

            session.commit()
            self._load_data()
        finally:
            session.close()

    def _del_assignment(self):
        """선택된 시수 배정을 삭제합니다."""
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
