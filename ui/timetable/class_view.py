"""
반별 시간표 조회 화면

두 개의 탭으로 구성됩니다:
  Mode A — 요일×교시 (TimetableGridA):
    선택한 반의 주간 시간표를 5열(요일) × N행(교시) 그리드로 표시합니다.
    셀 더블클릭 시 EditDialog 를 열어 직접 수정 또는 변경 신청을 처리합니다.

  Mode B — 교시×학반 (TimetableGridB):
    선택한 요일의 모든 반 시간표를 교시별로 비교할 수 있습니다.
    특정 요일에 학년 전체가 어떤 수업을 듣는지 한눈에 파악 가능합니다.
    (조회 전용, 편집 기능 없음)

데이터 의존성:
  - 학기 콤보박스(cb_term): TermDialog(학기 추가) 또는 main_window._add_term()
  - 학반 콤보박스(cb_class): ClassSetupWidget(편제 설정)에서 등록된 SchoolClass
  - 시간표 그리드 데이터: GenerateWorker 로 생성된 TimetableEntry
  - 페이지 전환 시 refresh() 로 콤보박스 최신 상태 유지

편집 처리 흐름:
  1. 셀 더블클릭 → EditDialog 표시 (현재 과목·교사·교실 정보 포함)
  2. '직접 수정' 선택 → TimetableEntry 즉시 업데이트 + TimetableChangeLog 기록
     (승인 절차 없이 즉시 반영. 담당자 권한 필요)
  3. '변경 신청' 선택 → TimetableChangeRequest 생성 (status=pending)
     (승인자에 의한 approve/reject 이후 반영)

  직접 수정/변경 신청 모두 core/change_logger.py 의 log_entry_update() 로
  변경 이력을 TimetableChangeLog 테이블에 기록합니다.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTabWidget, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import (
    SchoolClass, Grade, TimetableEntry, AcademicTerm,
)
from .neis_grid import TimetableGridA, TimetableGridB
from .edit_dialog import EditDialog
from core.change_logger import log_entry_update

DAYS_KR = ["월", "화", "수", "목", "금"]


class ClassTimetableView(QWidget):
    """반별 시간표 조회 및 편집 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # (day, period) → TimetableEntry 매핑. 더블클릭 시 빠른 조회에 사용합니다.
        self._entries_by_slot: dict = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("시간표 조회")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 필터 바 ───────────────────────────────────────────────────
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

        # ── 탭 위젯 ───────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { min-width:120px; padding:8px 12px; }
            QTabBar::tab:selected { background:#1B4F8A; color:white; font-weight:bold; }
        """)

        # Mode A: 요일×교시 그리드 (편집 가능)
        self.grid_a = TimetableGridA()
        self.grid_a.slot_double_clicked.connect(self._on_slot_double_clicked)
        self.tabs.addTab(self.grid_a, "모드 A  — 요일×교시 (학반별 주간)")

        # Mode B: 교시×학반 그리드 (조회 전용)
        self.grid_b = TimetableGridB()
        self.tabs.addTab(self.grid_b, "모드 B  — 교시×학반 (1일 전체)")

        layout.addWidget(self.tabs)

        self._populate_combos()

    def _populate_combos(self):
        """DB 에서 학기·학반 목록을 읽어 콤보박스를 채웁니다."""
        session = get_session()
        try:
            self.cb_term.clear()
            terms = session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self.cb_term.addItem(str(t), t.id)
            if not terms:
                self.cb_term.addItem("(학기 없음)", None)

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
        """메인 윈도우에서 페이지 전환 시 호출됩니다. 콤보박스를 최신 데이터로 갱신합니다."""
        self._populate_combos()

    def _load(self):
        """'조회' 버튼 클릭 시 선택된 학기·학반의 시간표를 두 탭 모두에 표시합니다."""
        term_id  = self.cb_term.currentData()
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
        """
        Mode A 그리드에 데이터를 로드합니다.
        동시에 _entries_by_slot 딕셔너리를 갱신해 더블클릭 시 빠른 조회를 지원합니다.
        """
        self._entries_by_slot.clear()
        data = []
        for e in entries:
            self._entries_by_slot[(e.day_of_week, e.period)] = e
            data.append({
                "day":          e.day_of_week,
                "period":       e.period,
                "subject_name": e.subject.short_name if e.subject else "",
                "teacher_name": e.teacher.name if e.teacher else "",
                "color_hex":    e.subject.color_hex if e.subject else "#FFFFFF",
                "entry_id":     e.id,
            })
        self.grid_a.load(data)

    def _load_mode_b(self, session, term_id: int):
        """
        Mode B 그리드에 선택 요일의 전체 학반 데이터를 로드합니다.
        cb_day 콤보박스의 선택 인덱스(0~4)를 요일(1~5)로 변환합니다.
        """
        day_idx = self.cb_day.currentIndex() + 1   # 0-indexed → 1-indexed

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
                    "color_hex":    e.subject.color_hex if e.subject else "#FFFFFF",
                }
            entries_by_class[cls.display_name] = period_map

        self.grid_b.load(class_names, entries_by_class)

    def _on_slot_double_clicked(self, day: int, period: int):
        """
        Mode A 셀 더블클릭 시 처리합니다.
        EditDialog 에서 직접 수정 또는 변경 신청 중 하나를 선택합니다.
        """
        entry = self._entries_by_slot.get((day, period))
        if entry is None:
            return  # 빈 슬롯은 편집하지 않습니다.

        dlg = EditDialog(entry, self)
        if dlg.exec() != EditDialog.DialogCode.Accepted:
            return

        changes = dlg.get_changes()
        # 아무 항목도 변경하지 않았으면 처리하지 않습니다.
        if not any([changes["new_subject_id"], changes["new_teacher_id"], changes["new_room_id"]]):
            return

        session = get_session()
        try:
            # SQLAlchemy 2.0 방식: session.get(Model, pk)
            e = session.get(TimetableEntry, entry.id)
            if e is None:
                return

            # 변경 전 스냅샷을 이력 기록용으로 저장합니다.
            old_data = {
                "day":        e.day_of_week,
                "period":     e.period,
                "subject_id": e.subject_id,
                "teacher_id": e.teacher_id,
                "room_id":    e.room_id,
            }

            if dlg.direct_edit:
                # 직접 수정: 선택된 변경 항목만 즉시 반영합니다.
                if changes["new_subject_id"] is not None:
                    e.subject_id = changes["new_subject_id"]
                if changes["new_teacher_id"] is not None:
                    e.teacher_id = changes["new_teacher_id"]
                if changes["new_room_id"] is not None:
                    e.room_id = changes["new_room_id"]

                log_entry_update(session, e, old_data)
                session.commit()
                QMessageBox.information(self, "수정 완료", "시간표가 수정되었습니다.")
            else:
                # 변경 신청: TimetableChangeRequest 를 생성합니다.
                # new_*_id 가 None 이면 현재 값을 유지합니다.
                from database.models import TimetableChangeRequest
                req = TimetableChangeRequest(
                    timetable_entry_id=e.id,
                    new_subject_id=changes["new_subject_id"] or e.subject_id,
                    new_teacher_id=changes["new_teacher_id"] or e.teacher_id,
                    new_room_id=changes["new_room_id"] or e.room_id,
                    reason=changes["reason"],
                    requested_by="",
                )
                session.add(req)
                session.commit()
                QMessageBox.information(self, "신청 완료", "변경이 신청되었습니다. 승인 후 반영됩니다.")

            self._load()  # 화면을 최신 상태로 갱신합니다.
        finally:
            session.close()
