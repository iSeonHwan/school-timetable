"""
감독 시간표 화면 (2026-09-19 신규)

선택 시험의 감독 배정(InvigilationAssignment)을 조회·편집합니다.

  - [자동 배정]: core.exam_scheduler.assign_invigilations 실행.
    하드 제약(수업 중 배제·담임 반 금지·담당 과목 금지·감독 불가·주간 제약)
    + 감독 횟수 균등 분배(요구사항 3)가 자동 적용됩니다.
  - 수동 배정: 교사 셀 더블클릭 → 교사 선택 → 동시간 중복 검사 후 저장.
    자동 배정으로 채워지지 않은 미배정 슬롯(후보 부족)을 채울 때 사용.
  - 횟수 분산 요약: 교사별 감독 횟수를 상단에 표시해 형평성 확인.
  - 내보내기: PDF(ui/export/exam_export.py) / CSV(Excel 호환).

데이터 접근: 기존 관리자 앱 페이지와 동일하게 SQLAlchemy 직접 접근.
"""
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QMessageBox,
    QHeaderView, QComboBox, QInputDialog, QFileDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from database.connection import get_session
from database.models import (
    Exam, ExamPeriod, InvigilationAssignment, SchoolClass,
    Teacher, ExamEntry, Subject,
)
from core.exam_scheduler import assign_invigilations
from ui.export.exam_export import export_invigilation_pdf, export_invigilation_csv

BTN_PRIMARY  = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_SECOND   = "background:#5D6D7E; color:white; border-radius:4px; padding:6px 14px;"


class InvigilationGridWidget(QWidget):
    """
    감독 시간표 화면 위젯.

    Args:
        read_only: True 이면 자동 배정·수동 편집·내보내기가 비활성화됩니다.
                   교감은 감독표를 열람만 합니다 (최종 승인은 변경 신청
                   결재 라인에서 처리).
    """

    def __init__(self, read_only: bool = False, parent=None):
        super().__init__(parent)
        self._read_only = read_only
        self._teachers: dict[int, Teacher] = {}
        self._init_ui()
        self._load_data()

    # ── UI 구성 ─────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("시험 감독 시간표")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 상단: 시험 선택 + 자동 배정 + 내보내기 ────────────────────────
        top = QHBoxLayout()
        top.addWidget(QLabel("시험 선택:"))
        self.cmb_exam = QComboBox()
        self.cmb_exam.setMinimumWidth(220)
        self.cmb_exam.currentIndexChanged.connect(self._render_grid)
        top.addWidget(self.cmb_exam)

        self.btn_assign = QPushButton("감독 자동 배정")
        self.btn_assign.setStyleSheet(BTN_PRIMARY)
        self.btn_assign.clicked.connect(self._auto_assign)
        top.addWidget(self.btn_assign)

        self.btn_pdf = QPushButton("PDF 내보내기")
        self.btn_pdf.setStyleSheet(BTN_SECOND)
        self.btn_pdf.clicked.connect(self._export_pdf)
        top.addWidget(self.btn_pdf)

        self.btn_csv = QPushButton("CSV 내보내기")
        self.btn_csv.setStyleSheet(BTN_SECOND)
        self.btn_csv.clicked.connect(self._export_csv)
        top.addWidget(self.btn_csv)
        top.addStretch()

        if self._read_only:
            # 교감용 읽기 전용 — 열람만 가능
            for b in (self.btn_assign, self.btn_pdf, self.btn_csv):
                b.setEnabled(False)
        layout.addLayout(top)

        # 감독 횟수 분산 요약 — 요구사항 3(균등 분배) 결과를 한눈에 확인
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(
            "color:#1B4F8A; background:#EDF2F9; border-radius:4px; padding:6px 10px;")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        # ── 감독표 그리드 ────────────────────────────────────────────────
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(8, 8, 8, 8)

        self.tbl = QTableWidget()
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setStyleSheet("border:none;")
        if not self._read_only:
            # 수동 배정 진입점 — 교사 셀 더블클릭으로 교체 다이얼로그 열기
            self.tbl.cellDoubleClicked.connect(self._edit_cell)
        f.addWidget(self.tbl)
        layout.addWidget(frame, stretch=1)

        hint = QLabel(
            "교사 셀을 더블클릭하면 감독교사를 수동으로 지정·변경할 수 있습니다. "
            "빨간 '(미배정)' 칸은 후보 부족 등으로 자동 배정이 안 된 슬롯입니다.")
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

    # ── 데이터 로딩 ─────────────────────────────────────────────────────

    def _load_data(self):
        """시험 콤보박스와 교사 캐시를 갱신합니다."""
        session = get_session()
        try:
            self._teachers = {t.id: t for t in session.query(Teacher).order_by(Teacher.name).all()}
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

    def _render_grid(self):
        """선택 시험의 감독표를 렌더링하고 횟수 요약을 갱신합니다."""
        self.tbl.setRowCount(0)
        self.tbl.setColumnCount(0)
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            self.lbl_summary.setText("")
            return

        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            if exam is None:
                return

            periods = (
                session.query(ExamPeriod).filter_by(exam_id=exam.id)
                .order_by(ExamPeriod.exam_date, ExamPeriod.period)
                .all()
            )
            # 반은 감독표 행 순서가 안정적이도록 id 순으로 정렬해 둡니다.
            class_map = {
                c.id: c for c in
                session.query(SchoolClass).order_by(SchoolClass.id).all()
            }

            # 시험 과목 표기용 맵 — 감독표에서 "국어 시험" 문맥을 보여줍니다.
            entries = session.query(ExamEntry).filter_by(exam_id=exam.id).all()
            subjects = {s.id: s for s in session.query(Subject).all()}
            entry_map = {(e.period_id, e.grade_id):
                         subjects.get(e.subject_id) for e in entries}

            # (period_id, class_id) → {pair_index: assignment}
            slots: dict = {}
            duty_count: dict = {}
            unassigned = 0
            for a in (
                session.query(InvigilationAssignment)
                .filter_by(exam_id=exam.id)
                .order_by(InvigilationAssignment.period_id,
                          InvigilationAssignment.pair_index)
                .all()
            ):
                slots.setdefault((a.period_id, a.school_class_id), {})[a.pair_index] = a
                if a.teacher_id is not None:
                    duty_count[a.teacher_id] = duty_count.get(a.teacher_id, 0) + 1
                else:
                    unassigned += 1

            if not slots:
                self.lbl_summary.setText(
                    "감독 배정이 없습니다. [감독 자동 배정] 을 실행하세요.")
                return

            # ── 요약 라벨 — 형평성 지표 ────────────────────────────────────
            if duty_count:
                counts = sorted(duty_count.values())
                parts = []
                for tid, cnt in sorted(duty_count.items()):
                    t = self._teachers.get(tid)
                    parts.append(f"{t.name if t else tid} {cnt}회" if t else f"{tid} {cnt}회")
                self.lbl_summary.setText(
                    f"총 배정 {sum(counts)}건 · 교사 {len(counts)}명 · "
                    f"최소 {counts[0]}회~최대 {counts[-1]}회   |   " + ", ".join(parts)
                    + (f"   |   미배정 {unassigned}칸" if unassigned else ""))
            else:
                self.lbl_summary.setText(f"미배정 {unassigned}칸 — 수동 배정이 필요합니다.")

            # ── 테이블: 행 = (교시 × 반), 열 = 날짜/교시/반/과목/1조/2조 ──
            self.tbl.setColumnCount(6)
            self.tbl.setHorizontalHeaderLabels(
                ["날짜", "교시(시간)", "반", "시험 과목", "1조", "2조"])

            rows = []
            for p in periods:
                for cid in sorted({cid for (pid, cid) in slots if pid == p.id}):
                    rows.append((p, cid))
            self.tbl.setRowCount(len(rows))

            for row, (p, cid) in enumerate(rows):
                cls = class_map.get(cid)
                self.tbl.setItem(row, 0, QTableWidgetItem(f"{p.exam_date:%m/%d}"))
                self.tbl.setItem(row, 1, QTableWidgetItem(
                    f"{p.period}교시 ({p.start_time:%H:%M}~{p.end_time:%H:%M})"))
                self.tbl.setItem(row, 2, QTableWidgetItem(
                    cls.display_name if cls else f"반#{cid}"))
                subj = entry_map.get((p.id, cls.grade_id)) if cls else None
                self.tbl.setItem(row, 3, QTableWidgetItem(
                    subj.name if subj else "-"))

                pair_slots = slots[(p.id, cid)]
                for pair_col, pair_idx in ((4, 1), (5, 2)):
                    a = pair_slots.get(pair_idx)
                    if a is None:
                        # 이 반에 해당 조 슬롯 자체가 없음 (1인 1조 반의 2조 열)
                        item = QTableWidgetItem("")
                    else:
                        t = self._teachers.get(a.teacher_id) if a.teacher_id else None
                        text = t.name if t else "(미배정)"
                        item = QTableWidgetItem(text)
                        if a.teacher_id is None:
                            # 미배정 슬롯은 빨간색 — 즉시 눈에 들어오게
                            item.setForeground(QColor("#C0392B"))
                            item.setFont(QFont("", 9, QFont.Weight.Bold))
                    self.tbl.setItem(row, pair_col, item)
        finally:
            session.close()

    # ── 자동 배정·수동 배정 ─────────────────────────────────────────────

    def _auto_assign(self):
        """선택 시험의 감독을 자동 배정합니다 (기존 배정은 새로 덮어씁니다)."""
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            QMessageBox.information(self, "안내", "시험을 선택해 주세요.")
            return
        reply = QMessageBox.question(
            self, "자동 배정 확인",
            "기존 감독 배정을 지우고 새로 배정합니다.\n"
            "감독 불가 신청(승인)·수업 시간표가 반영됩니다. 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            # assign_invigilations 내부에서 commit 하므로 결과만 받습니다.
            # 부분 성공(False)이어도 미배정 슬롯을 남긴 채 저장됩니다.
            ok, msg = assign_invigilations(session, exam_id)
        finally:
            session.close()

        if ok:
            QMessageBox.information(self, "자동 배정 완료", msg)
        else:
            QMessageBox.warning(self, "자동 배정 완료(부분)", msg)
        self._render_grid()

    def _edit_cell(self, row: int, col: int):
        """
        교사 셀 더블클릭 → 감독교사 수동 지정·변경.

        서버 API(PUT /exams/invigilations/{id})와 동일한 규칙을 로컬에서
        적용합니다: 같은 교시에 이미 다른 반을 감독 중인 교사는 지정 불가.
        (관리자 앱은 DB 직접 접근이므로 검증을 여기서 수행)
        """
        if self._read_only or col not in (4, 5):
            return
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            return

        session = get_session()
        try:
            # 행 → (period_id, class_id, pair_index) 복원 — 렌더링과 동일한
            # 정렬(periods 순 × class id 순)로 다시 계산합니다.
            exam = session.get(Exam, exam_id)
            if exam is None:
                return
            periods = (
                session.query(ExamPeriod).filter_by(exam_id=exam.id)
                .order_by(ExamPeriod.exam_date, ExamPeriod.period).all()
            )
            slots = (
                session.query(InvigilationAssignment).filter_by(exam_id=exam.id)
                .order_by(InvigilationAssignment.period_id,
                          InvigilationAssignment.pair_index).all()
            )
            keys = []
            for p in periods:
                for cid in sorted({s.school_class_id for s in slots if s.period_id == p.id}):
                    for pair in (1, 2):
                        if any(s.period_id == p.id and s.school_class_id == cid
                               and s.pair_index == pair for s in slots):
                            keys.append((p.id, cid, pair))
            if row >= len(keys):
                return
            period_id, class_id, pair_idx = keys[row]

            target = next(
                (s for s in slots if s.period_id == period_id
                 and s.school_class_id == class_id and s.pair_index == pair_idx),
                None)
            if target is None:
                return

            # 교사 선택 다이얼로그 — 미배정 해제 옵션도 제공
            names = [t.name for t in self._teachers.values()]
            names.append("(미배정으로 비우기)")
            current = self.tbl.item(row, col)
            current_name = current.text() if current else ""
            default = names.index(current_name) if current_name in names else 0
            choice, ok = QInputDialog.getItem(
                self, "감독교사 지정",
                f"이 슬롯의 감독교사를 선택하세요 ({pair_idx}조):",
                names, default, editable=False)
            if not ok:
                return

            if choice == "(미배정으로 비우기)":
                target.teacher_id = None
            else:
                teacher = next(t for t in self._teachers.values() if t.name == choice)
                # 동시간 중복 검사 — 한 교사가 같은 교시에 두 반 감독 불가
                conflict = (
                    session.query(InvigilationAssignment)
                    .filter(
                        InvigilationAssignment.period_id == period_id,
                        InvigilationAssignment.teacher_id == teacher.id,
                        InvigilationAssignment.id != target.id,
                    ).first())
                if conflict is not None:
                    QMessageBox.warning(
                        self, "배정 불가",
                        f"{teacher.name} 선생님은 이 교시에 이미 다른 반 감독이 배정되어 있습니다.")
                    return
                target.teacher_id = teacher.id
            session.commit()
        finally:
            session.close()
        self._render_grid()

    # ── 내보내기 ─────────────────────────────────────────────────────────

    def _export_pdf(self):
        """감독표를 PDF 로 저장합니다 (ui/export/exam_export.py 재사용)."""
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "감독표 PDF 저장", "invigilation.pdf", "PDF Files (*.pdf)")
        if not path:
            return
        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            export_invigilation_pdf(session, exam, path)
        finally:
            session.close()
        QMessageBox.information(self, "저장 완료", f"PDF가 저장되었습니다:\n{path}")

    def _export_csv(self):
        """감독배정을 CSV 로 저장합니다 (Excel 에서 바로 열립니다)."""
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "감독표 CSV 저장", "invigilation.csv", "CSV Files (*.csv)")
        if not path:
            return
        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            export_invigilation_csv(session, exam, path)
        finally:
            session.close()
        QMessageBox.information(self, "저장 완료", f"CSV가 저장되었습니다:\n{path}")