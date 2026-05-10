"""
교사별 시간표 조회 화면 (Mode A)

선택한 교사의 주간 시간표를 TimetableGridA 로 표시합니다.
반별 시간표와 달리, 교사 시간표에서는 '교사명' 대신 '학반명'이 셀 하단에
표시됩니다. (해당 교사가 어느 반을 가르치는지 한눈에 파악 가능)

데이터 의존성:
  - 학기 콤보박스(cb_term): TermDialog 로 등록된 AcademicTerm
  - 교사 콤보박스(cb_teacher): TeacherSetupWidget 에서 등록된 Teacher
  - 시간표 데이터: GenerateWorker 로 생성된 TimetableEntry
  - 페이지 전환 시 refresh() 로 콤보박스 최신 상태 유지

중요: _load() 에서 TimetableEntry.teacher_id 로 필터링할 때, 한 교사가
      여러 반에서 같은 교과를 가르치는 경우 모든 반의 수업이 표시됩니다.
      각 셀의 하단 텍스트(teacher_name 필드)에는 school_class.display_name 이
      들어가므로, 교사 입장에서 '지금 어느 반 수업인지'를 바로 알 수 있습니다.

편집 흐름은 ClassTimetableView 와 동일:
  셀 더블클릭 → EditDialog → 직접 수정 또는 변경 신청
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame, QMessageBox
)
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import Teacher, TimetableEntry, AcademicTerm
from .neis_grid import TimetableGridA
from .edit_dialog import EditDialog
from core.change_logger import log_entry_update


class TeacherTimetableView(QWidget):
    """교사별 시간표 조회 및 편집 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # (day, period) → TimetableEntry 매핑
        self._entries_by_slot: dict = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("교사별 시간표")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 필터 바 ───────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setStyleSheet("background:#F0F4FA; border-radius:6px;")
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(12, 8, 12, 8)

        fb.addWidget(QLabel("학기:"))
        self.cb_term = QComboBox()
        self.cb_term.setMinimumWidth(140)
        fb.addWidget(self.cb_term)

        fb.addSpacing(16)
        fb.addWidget(QLabel("교사:"))
        self.cb_teacher = QComboBox()
        self.cb_teacher.setMinimumWidth(120)
        fb.addWidget(self.cb_teacher)

        fb.addStretch()
        btn = QPushButton("조회")
        btn.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:6px 18px; font-weight:bold;"
        )
        btn.clicked.connect(self._load)
        fb.addWidget(btn)

        layout.addWidget(filter_bar)

        # ── 시간표 그리드 ─────────────────────────────────────────────
        self.grid = TimetableGridA()
        self.grid.slot_double_clicked.connect(self._on_slot_double_clicked)
        layout.addWidget(self.grid)

        self._populate_combos()

    def _populate_combos(self):
        """DB 에서 학기·교사 목록을 읽어 콤보박스를 채웁니다."""
        session = get_session()
        try:
            self.cb_term.clear()
            for t in session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all():
                self.cb_term.addItem(str(t), t.id)
            if self.cb_term.count() == 0:
                self.cb_term.addItem("(학기 없음)", None)

            self.cb_teacher.clear()
            for t in session.query(Teacher).order_by(Teacher.name).all():
                self.cb_teacher.addItem(t.name, t.id)
            if self.cb_teacher.count() == 0:
                self.cb_teacher.addItem("(교사 없음)", None)
        finally:
            session.close()

    def refresh(self):
        """메인 윈도우에서 페이지 전환 시 호출됩니다."""
        self._populate_combos()

    def _load(self):
        """'조회' 버튼 클릭 시 선택된 학기·교사의 시간표를 표시합니다."""
        term_id    = self.cb_term.currentData()
        teacher_id = self.cb_teacher.currentData()
        if not term_id or not teacher_id:
            QMessageBox.warning(self, "조회 오류", "학기와 교사를 선택해 주세요.")
            return

        session = get_session()
        try:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, teacher_id=teacher_id)
                .all()
            )
            self._entries_by_slot.clear()
            data = []
            for e in entries:
                self._entries_by_slot[(e.day_of_week, e.period)] = e
                data.append({
                    "day":          e.day_of_week,
                    "period":       e.period,
                    "subject_name": e.subject.short_name if e.subject else "",
                    # 교사 시간표에서는 교사명 대신 담당 학반명을 표시합니다.
                    "teacher_name": e.school_class.display_name if e.school_class else "",
                    "color_hex":    e.subject.color_hex if e.subject else "#FFFFFF",
                    "entry_id":     e.id,
                })
            self.grid.load(data)
        finally:
            session.close()

    def _on_slot_double_clicked(self, day: int, period: int):
        """
        셀 더블클릭 시 처리합니다.
        ClassTimetableView._on_slot_double_clicked 와 동일한 로직입니다.
        """
        entry = self._entries_by_slot.get((day, period))
        if entry is None:
            return

        dlg = EditDialog(entry, self)
        if dlg.exec() != EditDialog.DialogCode.Accepted:
            return

        changes = dlg.get_changes()
        if not any([changes["new_subject_id"], changes["new_teacher_id"], changes["new_room_id"]]):
            return

        session = get_session()
        try:
            # SQLAlchemy 2.0 방식: session.get(Model, pk)
            e = session.get(TimetableEntry, entry.id)
            if e is None:
                return

            old_data = {
                "day":        e.day_of_week,
                "period":     e.period,
                "subject_id": e.subject_id,
                "teacher_id": e.teacher_id,
                "room_id":    e.room_id,
            }

            if dlg.direct_edit:
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

            self._load()
        finally:
            session.close()
