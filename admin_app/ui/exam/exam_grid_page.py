"""
시험 시간표 화면 (2026-09-19 신규, 요구사항 7)

시험 선택 → (날짜×교시) × (대상 학년) 그리드에 시험 과목을 표시합니다.

  - [자동 배치]: core.exam_scheduler.generate_exam_entries 실행.
    규칙 — 과목당 1회, 하루 과목 수 상한, 학년별 독립 배치.
  - 수동 편집: 셀 더블클릭 → 과목 선택 다이얼로그 → 즉시 저장(is_manual 표시).
    자동 배치와 수동 편집을 병행할 수 있습니다 (요구사항 7).
  - 게시된 시험은 읽기 전용 — 시험지·안내가 이미 배포된 상태에서
    과목이 바뀌는 사고를 막기 위함입니다.

데이터 접근: 기존 관리자 앱 페이지와 동일하게 SQLAlchemy 직접 접근.
교사 앱은 서버 API 를 통해 같은 데이터를 조회합니다.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QMessageBox,
    QHeaderView, QComboBox, QInputDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from database.connection import get_session
from database.models import (
    Exam, ExamPeriod, ExamEntry, Subject, Grade,
)
from core.exam_scheduler import generate_exam_entries

HEADER_STYLE = "background:#1B4F8A; color:white; font-weight:bold; padding:6px;"
BTN_PRIMARY  = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"


class ExamGridWidget(QWidget):
    """
    시험 시간표(과목 배치) 화면 위젯.

    Args:
        read_only: True 이면 자동 배치 버튼·셀 편집이 비활성화됩니다.
                   교감은 시험표를 열람만 할 수 있어야 하므로 이 플래그를 사용합니다.
    """

    def __init__(self, read_only: bool = False, parent=None):
        super().__init__(parent)
        self._read_only = read_only
        self._subjects: dict[int, Subject] = {}   # 과목 선택 다이얼로그용 캐시
        self._init_ui()
        self._load_data()

    # ── UI 구성 ─────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("시험 시간표 (과목 배치)")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 상단 컨트롤 행: 시험 선택 + 자동 배치 ────────────────────────
        top = QHBoxLayout()
        top.addWidget(QLabel("시험 선택:"))
        self.cmb_exam = QComboBox()
        self.cmb_exam.setMinimumWidth(220)
        self.cmb_exam.currentIndexChanged.connect(self._render_grid)
        top.addWidget(self.cmb_exam)

        self.btn_auto = QPushButton("자동 배치")
        self.btn_auto.setStyleSheet(BTN_PRIMARY)
        self.btn_auto.clicked.connect(self._auto_generate)
        if self._read_only:
            self.btn_auto.setEnabled(False)
        top.addWidget(self.btn_auto)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color:#666;")
        top.addWidget(self.lbl_info)
        top.addStretch()
        layout.addLayout(top)

        # ── 그리드 ──────────────────────────────────────────────────────
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(8, 8, 8, 8)

        self.tbl = QTableWidget()
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setStyleSheet("border:none;")
        if not self._read_only:
            # 수동 편집 진입점 — 더블클릭으로 과목 선택 다이얼로그를 엽니다.
            self.tbl.cellDoubleClicked.connect(self._edit_cell)
        f.addWidget(self.tbl)
        layout.addWidget(frame, stretch=1)

        hint = QLabel("셀을 더블클릭하면 과목을 수동으로 변경할 수 있습니다. (게시된 시험은 편집 불가)")
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

    # ── 데이터 로딩 ─────────────────────────────────────────────────────

    def _load_data(self):
        """시험 콤보박스와 과목 캐시를 갱신합니다."""
        session = get_session()
        try:
            self._subjects = {s.id: s for s in session.query(Subject).order_by(Subject.name).all()}

            self.cmb_exam.blockSignals(True)
            self.cmb_exam.clear()
            exams = session.query(Exam).order_by(Exam.start_date.desc()).all()
            for ex in exams:
                state = " [게시됨]" if ex.status == "published" else ""
                self.cmb_exam.addItem(f"{ex.name}{state}", ex.id)
            self.cmb_exam.blockSignals(False)
        finally:
            session.close()
        self._render_grid()

    def refresh(self):
        """페이지 전환 시 main_window 에서 호출되는 갱신 진입점."""
        self._load_data()

    # ── 그리드 렌더링 ────────────────────────────────────────────────────

    def _current_exam(self) -> Exam | None:
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            return None
        session = get_session()
        try:
            return session.get(Exam, exam_id)
        finally:
            session.close()

    def _render_grid(self):
        """
        선택 시험의 시험표를 그리드로 렌더링합니다.

        구조: 행 = 날짜×교시(시간 표기), 열 = 대상 학년.
        셀 텍스트 = 과목명(약어). 수동 편집 칸은 배경색으로 구분합니다.
        """
        self.tbl.setRowCount(0)
        self.tbl.setColumnCount(0)
        exam = self._current_exam()
        if exam is None:
            self.lbl_info.setText("")
            return

        session = get_session()
        try:
            exam = session.get(Exam, exam.id)   # 이 세션에 attach
            periods = (
                session.query(ExamPeriod).filter_by(exam_id=exam.id)
                .order_by(ExamPeriod.exam_date, ExamPeriod.period)
                .all()
            )
            if not periods:
                self.lbl_info.setText("교시가 없습니다. 시험 관리에서 기간을 확인하세요.")
                return

            # 대상 학년 열 구성 — target_grade_ids 가 비어 있으면 전체 학년
            grades = session.query(Grade).order_by(Grade.grade_number).all()
            if exam.target_grade_ids and exam.target_grade_ids not in ("[]", ""):
                import json
                target_ids = json.loads(exam.target_grade_ids)
                grades = [g for g in grades if g.id in target_ids]
            if not grades:
                self.lbl_info.setText("대상 학년이 없습니다.")
                return

            # 시험표 조회: {(period_id, grade_id): entry}
            entries = session.query(ExamEntry).filter_by(exam_id=exam.id).all()
            entry_map = {(e.period_id, e.grade_id): e for e in entries}

            # 헤더: 첫 열 = 교시 정보, 이후 = 학년별 열
            self.tbl.setColumnCount(1 + len(grades))
            self.tbl.setHorizontalHeaderLabels(
                ["교시"] + [g.name for g in grades])
            self.tbl.setRowCount(len(periods))

            state_text = "게시됨(편집 불가)" if exam.status == "published" else "초안"
            self.lbl_info.setText(
                f"{exam.start_date:%m/%d}~{exam.end_date:%m/%d} · "
                f"1교시 {exam.first_period_start:%H:%M} · 하루 {exam.periods_per_day}교시 · {state_text}")

            for row, p in enumerate(periods):
                # 교시 행 라벨 — 날짜·교시·시각 (준비령은 표기하지 않음)
                period_item = QTableWidgetItem(
                    f"{p.exam_date:%m/%d}\n{p.period}교시\n{p.start_time:%H:%M}~{p.end_time:%H:%M}")
                period_item.setForeground(QColor("#1B4F8A"))
                self.tbl.setItem(row, 0, period_item)

                for col, g in enumerate(grades, start=1):
                    entry = entry_map.get((p.id, g.id))
                    if entry is not None:
                        subj = self._subjects.get(entry.subject_id)
                        cell = QTableWidgetItem(
                            subj.name if subj else f"과목#{entry.subject_id}")
                        if entry.is_manual:
                            # 수동 편집 칸은 연한 노랑 배경 — 자동 배치 결과와 구분
                            cell.setBackground(QColor("#FFF9C4"))
                        if subj is not None and subj.color_hex:
                            # 과목 색상이 지정되어 있으면 셀 텍스트에도 반영
                            cell.setForeground(QColor(subj.color_hex))
                    else:
                        cell = QTableWidgetItem("—")
                        cell.setForeground(QColor("#CCCCCC"))
                    self.tbl.setItem(row, col, cell)
        finally:
            session.close()

    # ── 자동 배치·수동 편집 ─────────────────────────────────────────────

    def _auto_generate(self):
        """선택 시험의 시험표를 자동 배치합니다 (기존 칸은 새로 덮어씁니다)."""
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            QMessageBox.information(self, "안내", "시험을 선택해 주세요.")
            return
        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            if exam is not None and exam.status == "published":
                QMessageBox.warning(self, "불가", "게시된 시험은 재배치할 수 없습니다.")
                return
        finally:
            session.close()

        session = get_session()
        try:
            # generate_exam_entries 내부에서 commit/rollback 하므로
            # 여기서는 결과 메시지만 받아 표시합니다.
            ok, msg = generate_exam_entries(session, exam_id)
        finally:
            session.close()

        if ok:
            QMessageBox.information(self, "자동 배치 완료", msg)
        else:
            QMessageBox.warning(self, "자동 배치 실패", msg)
        self._render_grid()

    def _edit_cell(self, row: int, col: int):
        """
        셀 더블클릭 → 과목 선택 다이얼로그 → 수동 저장.

        대상 칸 식별: 표시된 periods/grades 순서가 행/열 순서와 같으므로
        다시 같은 정렬로 조회해 period_id·grade_id 를 구합니다.
        """
        if self._read_only:
            return
        if col == 0:
            return   # 교시 라벨 열은 편집 대상 아님
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            return

        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            if exam is None:
                return
            if exam.status == "published":
                QMessageBox.warning(self, "불가", "게시된 시험표는 수정할 수 없습니다.")
                return

            # 행 → ExamPeriod, 열 → Grade 재조회 (렌더링과 동일한 정렬 보장)
            periods = (
                session.query(ExamPeriod).filter_by(exam_id=exam.id)
                .order_by(ExamPeriod.exam_date, ExamPeriod.period)
                .all()
            )
            if row >= len(periods):
                return
            period = periods[row]

            grades = session.query(Grade).order_by(Grade.grade_number).all()
            if exam.target_grade_ids and exam.target_grade_ids not in ("[]", ""):
                import json
                target_ids = json.loads(exam.target_grade_ids)
                grades = [g for g in grades if g.id in target_ids]
            if col - 1 >= len(grades):
                return
            grade = grades[col - 1]

            # 과목 선택 다이얼로그 — 기존 과목이 선택된 상태로 시작
            names = [s.name for s in self._subjects.values()]
            if not names:
                QMessageBox.information(self, "안내", "등록된 과목이 없습니다.")
                return
            current = self.tbl.item(row, col)
            current_name = current.text() if current else ""
            choice, ok = QInputDialog.getItem(
                self, "과목 변경",
                f"{period.exam_date:%m/%d} {period.period}교시 — {grade.name} 시험 과목 선택:",
                names, names.index(current_name) if current_name in names else 0,
                editable=False)
            if not ok:
                return
            subject = next(s for s in self._subjects.values() if s.name == choice)

            # 해당 칸 upsert — UniqueConstraint(exam, period, grade) 가 기준
            entry = session.query(ExamEntry).filter_by(
                exam_id=exam.id, period_id=period.id, grade_id=grade.id
            ).first()
            if entry is None:
                entry = ExamEntry(exam_id=exam.id, period_id=period.id,
                                  grade_id=grade.id, subject_id=subject.id,
                                  is_manual=True)
                session.add(entry)
            else:
                entry.subject_id = subject.id
                entry.is_manual = True   # 수동 편집 표시 — 이후 자동 배치 안내의 근거
            session.commit()
        finally:
            session.close()
        self._render_grid()