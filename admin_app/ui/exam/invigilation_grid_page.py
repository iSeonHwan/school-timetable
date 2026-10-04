"""
감독 시간표 화면 (2026-09-19 신규, 2026-10-04 혼합 시험실·복도감독 추가)

선택 시험의 감독 배정(InvigilationAssignment)을 조회·편집합니다.

  - [자동 배정]: core.exam_scheduler.assign_invigilations 실행.
    하드 제약(수업 중 배제·담임 반 금지·담당 과목 금지·감독 불가·주간 제약)
    + 감독 횟수 균등 분배(요구사항 3)가 자동 적용됩니다. 일반 반 슬롯뿐
    아니라 혼합 시험실(ExamRoom — 선택과목 등) 슬롯도 같은 그리드에
    "[혼합] 설명" 행으로 함께 표시됩니다.
  - [복도감독 자동 배정]: core.exam_scheduler.assign_corridor_duty 실행.
    학년×교시 단위로 별도 표에 표시됩니다(교실감독과 역할·후보군이 다름).
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
    QHeaderView, QComboBox, QInputDialog, QFileDialog, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from database.connection import get_session
from database.models import (
    Exam, ExamPeriod, InvigilationAssignment, SchoolClass,
    Teacher, ExamEntry, Subject, ExamRoom, CorridorDutyAssignment, Grade,
)
from core.exam_scheduler import assign_invigilations, assign_corridor_duty
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
        # _render_grid() 가 채우는 행 식별자 캐시 — _edit_cell() 이 더블클릭된
        # 행을 (period_id, kind, ref_id) 로 되짚어 찾을 때 재사용합니다.
        # (렌더링과 완전히 동일한 순서로 다시 계산하는 중복 로직을 없애
        # 둘이 어긋나는 사고를 방지합니다 — 혼합 시험실 추가로 더 중요해짐)
        self._row_keys: list[tuple] = []
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

        # 변경 최소화(요구사항 14) — 기본 ON. 재배정 시 지금도 유효한
        # 기존 배정은 그대로 두고 바뀐 자리만 다시 배정합니다. 실제
        # 운영에서는 "직전 배정을 최대한 유지"가 원칙이었습니다(특정 교사
        # 제외 등으로 몇 자리만 바뀌었을 때 전체가 뒤섞이면 혼란스러움).
        self.chk_preserve = QCheckBox("기존 배정 최대한 유지")
        self.chk_preserve.setChecked(True)
        self.chk_preserve.setToolTip(
            "체크 해제하면 기존 배정을 전부 무시하고 완전히 새로 배정합니다."
        )
        top.addWidget(self.chk_preserve)

        self.btn_pdf = QPushButton("PDF 내보내기")
        self.btn_pdf.setStyleSheet(BTN_SECOND)
        self.btn_pdf.clicked.connect(self._export_pdf)
        top.addWidget(self.btn_pdf)

        self.btn_csv = QPushButton("CSV 내보내기")
        self.btn_csv.setStyleSheet(BTN_SECOND)
        self.btn_csv.clicked.connect(self._export_csv)
        top.addWidget(self.btn_csv)
        top.addStretch()

        self.btn_corridor = QPushButton("복도감독 자동 배정")
        self.btn_corridor.setStyleSheet(BTN_SECOND)
        self.btn_corridor.clicked.connect(self._auto_assign_corridor)
        top.addWidget(self.btn_corridor)

        if self._read_only:
            # 교감용 읽기 전용 — 열람만 가능
            for b in (self.btn_assign, self.btn_pdf, self.btn_csv, self.chk_preserve, self.btn_corridor):
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
            "'[혼합]' 행은 여러 반이 섞이는 시험실입니다. "
            "빨간 '(미배정)' 칸은 후보 부족 등으로 자동 배정이 안 된 슬롯입니다.")
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)

        # ── 복도감독 표 (2026-10-04 추가) ──────────────────────────────────
        # 교실감독과 역할·후보군이 달라(학년×교시 단위, 1명) 별도 표로 둡니다.
        corridor_frame = QFrame()
        corridor_frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        cf = QVBoxLayout(corridor_frame)
        cf.setContentsMargins(8, 8, 8, 8)
        corridor_title = QLabel("복도감독 (학년×교시, 시험 과목 담당 교사 중 1명)")
        corridor_title.setStyleSheet("color:#1B4F8A; font-weight:bold; border:none;")
        cf.addWidget(corridor_title)
        self.tbl_corridor = QTableWidget()
        self.tbl_corridor.setColumnCount(4)
        self.tbl_corridor.setHorizontalHeaderLabels(["날짜", "교시", "학년", "담당 교사"])
        self.tbl_corridor.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_corridor.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_corridor.setStyleSheet("border:none;")
        self.tbl_corridor.setMaximumHeight(160)
        if not self._read_only:
            self.tbl_corridor.cellDoubleClicked.connect(self._edit_corridor_cell)
        cf.addWidget(self.tbl_corridor)
        layout.addWidget(corridor_frame)

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
        """선택 시험의 감독표(일반 반 + 혼합 시험실)를 렌더링하고 횟수 요약을 갱신합니다."""
        self.tbl.setRowCount(0)
        self.tbl.setColumnCount(0)
        self._row_keys = []
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            self.lbl_summary.setText("")
            self.tbl_corridor.setRowCount(0)
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
            room_map = {
                r.id: r for r in
                session.query(ExamRoom).filter_by(exam_id=exam.id).all()
            }

            # 시험 과목 표기용 맵 — 감독표에서 "국어 시험" 문맥을 보여줍니다.
            entries = session.query(ExamEntry).filter_by(exam_id=exam.id).all()
            subjects = {s.id: s for s in session.query(Subject).all()}
            entry_map = {(e.period_id, e.grade_id):
                         subjects.get(e.subject_id) for e in entries}

            # slot key = (period_id, kind, ref_id) — kind="class"면 ref_id는
            # school_class_id, kind="room"이면 ExamRoom.id. 혼합 시험실은
            # school_class_id가 없으므로 둘을 같은 네임스페이스로 섞으면
            # id 충돌 위험이 있어 kind 로 구분합니다.
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
                if a.exam_room_id is not None:
                    key = (a.period_id, "room", a.exam_room_id)
                else:
                    key = (a.period_id, "class", a.school_class_id)
                slots.setdefault(key, {})[a.pair_index] = a
                if a.teacher_id is not None:
                    duty_count[a.teacher_id] = duty_count.get(a.teacher_id, 0) + 1
                else:
                    unassigned += 1

            if not slots:
                self.lbl_summary.setText(
                    "감독 배정이 없습니다. [감독 자동 배정] 을 실행하세요.")
                self._render_corridor_table(session, exam)
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

            # ── 테이블: 행 = (교시 × 반/시험실), 열 = 날짜/교시/반/과목/1조/2조 ──
            self.tbl.setColumnCount(6)
            self.tbl.setHorizontalHeaderLabels(
                ["날짜", "교시(시간)", "반/시험실", "시험 과목", "1조", "2조"])

            row_keys = []
            for p in periods:
                # 같은 교시 안에서는 일반 반(class) → 혼합 시험실(room) 순,
                # 각각 id 순으로 정렬해 행 순서를 매 렌더링마다 안정적으로 유지.
                period_keys = sorted(
                    (k for k in slots if k[0] == p.id),
                    key=lambda k: (0 if k[1] == "class" else 1, k[2]),
                )
                for k in period_keys:
                    row_keys.append((p, k))
            self._row_keys = row_keys
            self.tbl.setRowCount(len(row_keys))

            for row, (p, key) in enumerate(row_keys):
                _, kind, ref_id = key
                self.tbl.setItem(row, 0, QTableWidgetItem(f"{p.exam_date:%m/%d}"))
                self.tbl.setItem(row, 1, QTableWidgetItem(
                    f"{p.period}교시 ({p.start_time:%H:%M}~{p.end_time:%H:%M})"))

                if kind == "class":
                    cls = class_map.get(ref_id)
                    self.tbl.setItem(row, 2, QTableWidgetItem(
                        cls.display_name if cls else f"반#{ref_id}"))
                    subj = entry_map.get((p.id, cls.grade_id)) if cls else None
                    self.tbl.setItem(row, 3, QTableWidgetItem(subj.name if subj else "-"))
                else:
                    room = room_map.get(ref_id)
                    label = room.label if room and room.label else f"시험실#{ref_id}"
                    self.tbl.setItem(row, 2, QTableWidgetItem(f"[혼합] {label}"))
                    subj_name = "-"
                    if room is not None and room.subject_id is not None:
                        subj = subjects.get(room.subject_id)
                        subj_name = subj.name if subj else "-"
                    self.tbl.setItem(row, 3, QTableWidgetItem(subj_name))

                pair_slots = slots[key]
                for pair_col, pair_idx in ((4, 1), (5, 2)):
                    a = pair_slots.get(pair_idx)
                    if a is None:
                        # 이 반/시험실에 해당 조 슬롯 자체가 없음 (1인 1조의 2조 열)
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

            self._render_corridor_table(session, exam)
        finally:
            session.close()

    def _render_corridor_table(self, session, exam: Exam):
        """
        복도감독 표를 렌더링합니다.

        session 을 _render_grid() 에서 열어둔 세션을 그대로 넘겨받아
        재사용합니다 — 매번 새 세션을 열면 교실감독 그리드를 그리는
        도중에 DB 에 반영된 변경(거의 없겠지만)과 복도감독 표 사이에
        미세한 시점 차이가 생길 수 있고, 불필요한 커넥션도 하나 더
        열리므로, 같은 한 번의 화면 갱신 안에서는 하나의 세션·하나의
        스냅샷으로 통일합니다.
        """
        rows = (
            session.query(CorridorDutyAssignment).filter_by(exam_id=exam.id)
            .order_by(CorridorDutyAssignment.period_id).all()
        )
        self.tbl_corridor.setRowCount(len(rows))
        for row, c in enumerate(rows):
            period = session.get(ExamPeriod, c.period_id)
            grade = session.get(Grade, c.grade_id)
            self.tbl_corridor.setItem(row, 0, QTableWidgetItem(
                f"{period.exam_date:%m/%d}" if period else "-"))
            self.tbl_corridor.setItem(row, 1, QTableWidgetItem(
                f"{period.period}교시" if period else "-"))
            self.tbl_corridor.setItem(row, 2, QTableWidgetItem(
                grade.name if grade else f"#{c.grade_id}"))
            t = self._teachers.get(c.teacher_id) if c.teacher_id else None
            item = QTableWidgetItem(t.name if t else "(미배정)")
            if c.teacher_id is None:
                item.setForeground(QColor("#C0392B"))
                item.setFont(QFont("", 9, QFont.Weight.Bold))
            self.tbl_corridor.setItem(row, 3, item)

    # ── 자동 배정·수동 배정 ─────────────────────────────────────────────

    def _auto_assign(self):
        """
        선택 시험의 감독을 자동 배정합니다.

        "기존 배정 최대한 유지" 체크 시(기본값) 지금도 유효한 기존
        배정은 그대로 두고 바뀐 자리만 다시 배정합니다(변경 최소화).
        체크 해제 시 기존 배정을 전부 지우고 완전히 새로 배정합니다.
        """
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            QMessageBox.information(self, "안내", "시험을 선택해 주세요.")
            return
        preserve = self.chk_preserve.isChecked()
        confirm_text = (
            "지금도 유효한 기존 감독 배정은 그대로 두고, 바뀐 자리만 다시 배정합니다.\n"
            if preserve else
            "기존 감독 배정을 전부 지우고 새로 배정합니다.\n"
        )
        reply = QMessageBox.question(
            self, "자동 배정 확인",
            confirm_text +
            "감독 불가 신청(승인)·수업 시간표가 반영됩니다. 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            # assign_invigilations 내부에서 commit 하므로 결과만 받습니다.
            # 부분 성공(False)이어도 미배정 슬롯을 남긴 채 저장됩니다.
            ok, msg = assign_invigilations(session, exam_id, preserve_existing=preserve)
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
        적용합니다: 같은 교시에 이미 다른 반/시험실을 감독 중인 교사는
        지정 불가. (관리자 앱은 DB 직접 접근이므로 검증을 여기서 수행)

        행 → 슬롯 매핑은 _render_grid() 가 채워둔 self._row_keys 를 그대로
        재사용합니다(렌더링과 별도로 다시 계산하면 둘이 어긋날 위험이 있고,
        혼합 시험실 추가로 그 위험이 더 커져 이번에 하나로 합쳤습니다).
        """
        if self._read_only or col not in (4, 5):
            return
        if row >= len(self._row_keys):
            return
        p, (period_id, kind, ref_id) = self._row_keys[row]
        pair_idx = 1 if col == 4 else 2

        session = get_session()
        try:
            query = session.query(InvigilationAssignment).filter_by(
                period_id=period_id, pair_index=pair_idx)
            if kind == "class":
                query = query.filter_by(school_class_id=ref_id)
            else:
                query = query.filter_by(exam_room_id=ref_id)
            target = query.first()
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
                # 동시간 중복 검사 — 한 교사가 같은 교시에 두 반/시험실 감독 불가
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
                        f"{teacher.name} 선생님은 이 교시에 이미 다른 반/시험실 감독이 배정되어 있습니다.")
                    return
                target.teacher_id = teacher.id
            session.commit()
        finally:
            session.close()
        self._render_grid()

    # ── 복도감독 ─────────────────────────────────────────────────────────

    def _auto_assign_corridor(self):
        """
        복도감독 자동 배정 (core.exam_scheduler.assign_corridor_duty).

        교실감독 자동 배정을 먼저 실행해야 그 결과를 바탕으로 겸임 배정을
        피할 수 있습니다 — 순서를 지키지 않아도 에러는 아니지만 안내합니다.
        """
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            QMessageBox.information(self, "안내", "시험을 선택해 주세요.")
            return
        reply = QMessageBox.question(
            self, "복도감독 자동 배정 확인",
            "학년×교시마다 시험 과목 담당 교사 중 1명을 복도감독으로 배정합니다.\n"
            "(교실감독 자동 배정을 먼저 실행해 두는 것을 권장합니다) 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            ok, msg = assign_corridor_duty(session, exam_id)
        finally:
            session.close()

        if ok:
            QMessageBox.information(self, "복도감독 배정 완료", msg)
        else:
            QMessageBox.warning(self, "복도감독 배정 완료(부분)", msg)
        self._render_grid()

    def _edit_corridor_cell(self, row: int, col: int):
        """복도감독 교사 셀 더블클릭 → 수동 지정·변경."""
        if self._read_only or col != 3:
            return
        exam_id = self.cmb_exam.currentData()
        if exam_id is None:
            return

        session = get_session()
        try:
            rows = (
                session.query(CorridorDutyAssignment).filter_by(exam_id=exam_id)
                .order_by(CorridorDutyAssignment.period_id).all()
            )
            if row >= len(rows):
                return
            target = rows[row]

            names = [t.name for t in self._teachers.values()]
            names.append("(미배정으로 비우기)")
            current = self.tbl_corridor.item(row, col)
            current_name = current.text() if current else ""
            default = names.index(current_name) if current_name in names else 0
            choice, ok = QInputDialog.getItem(
                self, "복도감독 교사 지정",
                "이 교시·학년의 복도감독 교사를 선택하세요:",
                names, default, editable=False)
            if not ok:
                return

            if choice == "(미배정으로 비우기)":
                target.teacher_id = None
            else:
                teacher = next(t for t in self._teachers.values() if t.name == choice)
                classroom_conflict = session.query(InvigilationAssignment).filter_by(
                    period_id=target.period_id, teacher_id=teacher.id).first()
                if classroom_conflict is not None:
                    QMessageBox.warning(
                        self, "배정 불가",
                        f"{teacher.name} 선생님은 이 교시에 이미 교실감독으로 배정되어 있습니다.")
                    return
                corridor_conflict = session.query(CorridorDutyAssignment).filter(
                    CorridorDutyAssignment.period_id == target.period_id,
                    CorridorDutyAssignment.teacher_id == teacher.id,
                    CorridorDutyAssignment.id != target.id,
                ).first()
                if corridor_conflict is not None:
                    QMessageBox.warning(
                        self, "배정 불가",
                        f"{teacher.name} 선생님은 이 교시에 이미 다른 학년 복도감독으로 배정되어 있습니다.")
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