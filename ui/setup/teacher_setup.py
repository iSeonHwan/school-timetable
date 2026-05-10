"""
교사 관리 화면

두 섹션으로 구성됩니다:
  1. 교사 추가/편집: 이름·교원번호·일 최대 수업 수·담임 여부·담임 학반을 입력합니다.
  2. 교사 불가 시간 설정: 교사를 선택한 뒤 요일×교시 그리드에서 불가 슬롯을 체크합니다.

데이터 의존성:
  이 페이지는 ClassSetupWidget(편제 설정)에서 등록된 SchoolClass 데이터를
  '담임 학반' 콤보박스(cb_homeroom_class)에 표시합니다.
  페이지 전환 시 refresh() 가 호출되어 최신 학반 목록을 DB 에서 다시 읽어옵니다.

  또한 TeacherConstraint 테이블에 constraint_type="unavailable" 로 저장된
  불가 시간은 시간표 자동 생성 시 hard constraint(절대 위반 불가)로 작용합니다.

불가 시간 저장 전략:
  _save_constraints() 는 '전체 삭제 후 재삽입' 방식을 사용합니다.
  이는 업데이트 로직을 단순화하지만, constraint 레코드의 id 가 매번 변경됩니다.
  (히스토리 추적이 필요하다면 soft delete + upsert 방식으로 전환을 고려하세요.)
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QFrame, QMessageBox, QHeaderView, QCheckBox, QComboBox,
    QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import Teacher, SchoolClass, Grade, TeacherConstraint

BTN_PRIMARY = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER  = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"
BTN_ORANGE  = "background:#E67E22; color:white; border-radius:4px; padding:6px 14px;"

DAYS_KR = ["월", "화", "수", "목", "금"]
PERIODS  = list(range(1, 8))   # 1교시 ~ 7교시


class TeacherSetupWidget(QWidget):
    """교사 정보 입력 및 불가 시간 설정 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # (day, period) → QCheckBox 매핑. 불가 시간 그리드를 관리합니다.
        self._constraint_checkboxes: dict = {}
        # 현재 불가 시간 그리드에 표시 중인 교사 ID
        self._selected_teacher_id: int | None = None
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

        # ── 교사 추가 섹션 ────────────────────────────────────────────
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

        # 교사 목록 테이블
        self.tbl_teachers = QTableWidget(0, 5)
        self.tbl_teachers.setHorizontalHeaderLabels(["ID", "이름", "교원번호", "담임", "일최대"])
        self.tbl_teachers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_teachers.setMaximumHeight(200)
        self.tbl_teachers.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_teachers.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_teachers.setStyleSheet("border:none;")
        # 행 선택 시 불가 시간 그리드를 해당 교사 데이터로 갱신합니다.
        self.tbl_teachers.selectionModel().selectionChanged.connect(self._on_teacher_selected)
        f1.addWidget(self.tbl_teachers)

        btn_del = QPushButton("선택 교사 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._del_teacher)
        f1.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(frame1)

        # ── 불가 시간 설정 섹션 ───────────────────────────────────────
        frame2 = QFrame()
        frame2.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f2 = QVBoxLayout(frame2)
        f2.setContentsMargins(12, 10, 12, 10)

        lbl2 = QLabel("교사 불가 시간 설정")
        lbl2.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl2.setStyleSheet("color:#1B4F8A; border:none;")
        f2.addWidget(lbl2)

        # 현재 선택된 교사 이름을 표시하는 레이블
        self.lbl_selected_teacher = QLabel("(교사를 위에서 선택하세요)")
        self.lbl_selected_teacher.setStyleSheet("color:#888; border:none;")
        f2.addWidget(self.lbl_selected_teacher)

        # 요일(열) × 교시(행) 체크박스 그리드
        grid = QGridLayout()
        grid.setSpacing(4)

        # 첫 번째 행: 요일 헤더
        for col, day in enumerate(DAYS_KR):
            lbl_day = QLabel(day)
            lbl_day.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_day.setStyleSheet("font-weight:bold; color:#1B4F8A; border:none;")
            grid.addWidget(lbl_day, 0, col + 1)

        # 이후 행: 교시별 체크박스
        for row, period in enumerate(PERIODS):
            lbl_p = QLabel(f"{period}교시")
            lbl_p.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_p.setStyleSheet("border:none;")
            grid.addWidget(lbl_p, row + 1, 0)

            for col, _ in enumerate(DAYS_KR):
                day = col + 1  # 1(월) ~ 5(금)
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

    # ── 데이터 로딩 ───────────────────────────────────────────────────────

    def _load_data(self):
        """DB 에서 교사 목록과 학반 목록을 읽어 테이블·콤보박스를 갱신합니다."""
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

            # 담임 학반 콤보박스 갱신
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
        """외부에서 호출해 데이터를 갱신합니다."""
        self._load_data()

    def _on_teacher_selected(self):
        """
        교사 테이블에서 행을 선택하면 해당 교사의 불가 시간을 그리드에 반영합니다.
        """
        row = self.tbl_teachers.currentRow()
        if row < 0:
            return

        tid = int(self.tbl_teachers.item(row, 0).text())
        tname = self.tbl_teachers.item(row, 1).text()
        self._selected_teacher_id = tid
        self.lbl_selected_teacher.setText(f"선택된 교사: {tname}")

        # DB 에서 해당 교사의 불가 슬롯을 읽어 체크박스 상태를 설정합니다.
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

    # ── 교사 CRUD ─────────────────────────────────────────────────────────

    def _add_teacher(self):
        """입력 폼의 값으로 교사를 DB 에 추가합니다."""
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "이름을 입력해 주세요.")
            return

        homeroom_class_id = self.cb_homeroom_class.currentData()  # None 이면 미배정
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
        """선택된 교사를 삭제합니다. cascade 로 불가 시간 제약도 함께 삭제됩니다."""
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
        """
        현재 체크박스 상태를 DB 에 저장합니다.
        기존 불가 시간을 모두 삭제한 뒤 체크된 슬롯만 새로 추가합니다(덮어쓰기 방식).
        """
        if not self._selected_teacher_id:
            QMessageBox.information(self, "안내", "교사를 먼저 선택해 주세요.")
            return

        session = get_session()
        try:
            # 기존 불가 시간 전체 삭제
            session.query(TeacherConstraint).filter_by(
                teacher_id=self._selected_teacher_id,
                constraint_type="unavailable",
            ).delete()

            # 체크된 슬롯만 새로 삽입
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
