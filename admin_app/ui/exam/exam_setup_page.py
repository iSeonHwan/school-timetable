"""
시험 관리 화면 (2026-09-19 신규)

세 개의 섹션으로 구성됩니다:
  1. 시험 생성 폼 — 시험 기본 정보(이름·기간·교시 운영 규칙·감독 금지 규칙) 입력.
     저장 시 기간×교시 수만큼 ExamPeriod 가 자동 생성됩니다.
  2. 시험 목록 — 생성된 시험 조회·게시·삭제.
     게시(publish)하면 교사 앱에서 시험표·감독표가 조회 가능해집니다.
  3. 감독 불가 신청 승인 — 교사가 제출한 감독 불가 신청(pending)을
     승인/거절합니다. 승인된 신청은 다음 감독 자동 배정부터 하드 제약으로
     반영됩니다 (미승인 상태로 감독이 빠지는 사고 방지).

데이터 접근 방식:
  기존 관리자 앱 설정 페이지(ui/setup/*)와 동일하게 SQLAlchemy 로 DB 에
  직접 접근합니다. 게시 알림만 예외적으로 ApiClient 를 사용해 서버의
  POST /exams/{id}/publish 를 호출합니다 — 알림 발송 로직이 서버에만
  있기 때문입니다. 서버에 접속할 수 없으면 DB 상태만 변경합니다
  (알림은 채팅 공지로 보완).

교시 시각 계산 규칙(요구사항 4)은 core.exam_scheduler.rebuild_exam_periods
의 단일 구현을 재사용합니다 — 화면마다 계산식을 따로 두면 서버 API 와
시각이 어긋날 위험이 있기 때문입니다.
"""
import json
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem, QFrame, QMessageBox, QHeaderView,
    QComboBox, QDateEdit, QTimeEdit, QCheckBox,
)
from PyQt6.QtCore import QDate, QTime, Qt
from PyQt6.QtGui import QFont, QColor

from database.connection import get_session
from database.models import (
    AcademicTerm, Exam, ExamPeriod, InvigilationConstraint, Teacher,
)
from core.exam_scheduler import rebuild_exam_periods

# 공통 스타일 — 기존 설정 페이지(class_setup.py)와 동일한 톤을 유지합니다.
HEADER_STYLE = "background:#1B4F8A; color:white; font-weight:bold; padding:6px;"
BTN_PRIMARY  = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_SUCCESS  = "background:#27AE60; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER   = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"
BTN_WARN     = "background:#E67E22; color:white; border-radius:4px; padding:6px 14px;"

# 상태 표시 색 — 게시된 시험은 강조, 초안은 회색 표기
STATUS_COLORS = {"draft": QColor("#7F8C8D"), "published": QColor("#27AE60")}


class ExamSetupWidget(QWidget):
    """
    시험 관리 화면 위젯.

    Args:
        api_client: 로그인된 ApiClient (게시 알림용). None 이면 게시 시
                    DB 상태만 변경합니다 — 서버 없이 구동하는 테스트·
                    오프라인 환경에서 동작하기 위한 폴백 경로입니다.
    """

    def __init__(self, api_client=None, parent=None):
        super().__init__(parent)
        self._client = api_client
        self._init_ui()
        self._load_data()

    # ── UI 구성 ─────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("시험 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        layout.addWidget(self._build_exam_form())
        layout.addWidget(self._build_exam_list(), stretch=1)
        layout.addWidget(self._build_constraint_panel(), stretch=1)

    def _build_exam_form(self) -> QFrame:
        """섹션 1: 시험 생성 폼."""
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("시험 추가")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        # ── 1행: 이름·유형·학급급·대상 학년 ────────────────────────────
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("시험명:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("예: 1학기 중간고사")
        self.edit_name.setFixedWidth(160)
        row1.addWidget(self.edit_name)

        row1.addSpacing(8)
        row1.addWidget(QLabel("유형:"))
        self.cmb_type = QComboBox()
        self.cmb_type.addItem("중간고사", "midterm")
        self.cmb_type.addItem("기말고사", "final")
        self.cmb_type.addItem("모의고사", "mock")
        row1.addWidget(self.cmb_type)

        row1.addSpacing(8)
        row1.addWidget(QLabel("학급:"))
        self.cmb_level = QComboBox()
        # 요구사항 1: 고등학교 기본, 설정으로 중학교 전환 (기능 차이 없음 — 표기용)
        self.cmb_level.addItem("고등학교", "high")
        self.cmb_level.addItem("중학교", "middle")
        row1.addWidget(self.cmb_level)

        row1.addSpacing(8)
        row1.addWidget(QLabel("대상 학년:"))
        self.edit_grades = QLineEdit()
        self.edit_grades.setPlaceholderText("예: 1,2 (비우면 전체)")
        self.edit_grades.setFixedWidth(130)
        self.edit_grades.setToolTip(
            "쉼표로 구분된 학년 번호. 시험을 치르는 학년만 감독 대상이 되고,\n"
            "시험 치르지 않는 학년의 수업 교사는 감독 후보에서 제외됩니다."
        )
        row1.addWidget(self.edit_grades)

        row1.addStretch()
        f.addLayout(row1)

        # ── 2행: 기간·교시 운영 규칙 (요구사항 4) ───────────────────────
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("시작일:"))
        self.date_start = QDateEdit(QDate.currentDate())
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        row2.addWidget(self.date_start)

        row2.addSpacing(8)
        row2.addWidget(QLabel("종료일:"))
        self.date_end = QDateEdit(QDate.currentDate().addDays(1))
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        row2.addWidget(self.date_end)

        row2.addSpacing(8)
        row2.addWidget(QLabel("1교시 시작:"))
        self.time_first = QTimeEdit(QTime(8, 30))   # 요구사항 기본값 08:30
        self.time_first.setDisplayFormat("HH:mm")
        row2.addWidget(self.time_first)

        row2.addSpacing(8)
        row2.addWidget(QLabel("하루 교시:"))
        self.spin_periods = QSpinBox(); self.spin_periods.setRange(1, 10); self.spin_periods.setValue(3)
        row2.addWidget(self.spin_periods)

        row2.addSpacing(8)
        row2.addWidget(QLabel("시험시간(분):"))
        self.spin_exam_min = QSpinBox(); self.spin_exam_min.setRange(10, 240); self.spin_exam_min.setValue(50)
        row2.addWidget(self.spin_exam_min)

        row2.addSpacing(8)
        row2.addWidget(QLabel("쉬는시간(분):"))
        self.spin_break = QSpinBox(); self.spin_break.setRange(0, 60); self.spin_break.setValue(10)
        row2.addWidget(self.spin_break)

        row2.addSpacing(8)
        row2.addWidget(QLabel("준비(분):"))
        self.spin_prep = QSpinBox(); self.spin_prep.setRange(0, 30); self.spin_prep.setValue(5)
        self.spin_prep.setToolTip("준비령 = 각 교시 종료 N 분 전. 파생값이라 저장하지 않고 표시에만 사용합니다.")
        row2.addWidget(self.spin_prep)
        row2.addStretch()
        f.addLayout(row2)

        # ── 3행: 하루 과목 상한 + 감독 금지 규칙 (요구사항 2·7) ──────────
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("하루 과목 수 상한:"))
        self.spin_max_subjects = QSpinBox(); self.spin_max_subjects.setRange(1, 10); self.spin_max_subjects.setValue(3)
        row3.addWidget(self.spin_max_subjects)

        row3.addSpacing(16)
        # 요구사항 2: 감독 금지 규칙 기본 ON, 필요 시 해제 가능
        self.chk_ban_homeroom = QCheckBox("담임 반 감독 금지")
        self.chk_ban_homeroom.setChecked(True)
        row3.addWidget(self.chk_ban_homeroom)
        self.chk_ban_own = QCheckBox("담당 과목 시험 감독 금지")
        self.chk_ban_own.setChecked(True)
        row3.addWidget(self.chk_ban_own)

        btn_add = QPushButton("시험 추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_exam)
        row3.addStretch()
        row3.addWidget(btn_add)
        f.addLayout(row3)

        return frame

    def _build_exam_list(self) -> QFrame:
        """섹션 2: 시험 목록 + 게시/삭제 버튼."""
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("시험 목록")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        self.tbl_exams = QTableWidget(0, 7)
        self.tbl_exams.setHorizontalHeaderLabels(
            ["ID", "시험명", "기간", "교시 운영", "대상 학년", "상태", "규칙"])
        self.tbl_exams.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_exams.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_exams.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_exams.setStyleSheet("border:none;")
        f.addWidget(self.tbl_exams)

        btn_row = QHBoxLayout()
        btn_publish = QPushButton("선택 시험 게시")
        btn_publish.setStyleSheet(BTN_SUCCESS)
        btn_publish.clicked.connect(self._publish_exam)
        btn_row.addWidget(btn_publish)

        btn_del = QPushButton("선택 시험 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._delete_exam)
        btn_row.addWidget(btn_del)

        btn_row.addWidget(QLabel(
            "게시하면 교사 앱에서 시험표·감독표가 보입니다. 게시 후에는 수정할 수 없습니다."))
        btn_row.addStretch()
        f.addLayout(btn_row)
        return frame

    def _build_constraint_panel(self) -> QFrame:
        """섹션 3: 감독 불가 신청 승인."""
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("감독 불가 신청 (승인하면 다음 자동 배정부터 반영)")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        self.tbl_constraints = QTableWidget(0, 6)
        self.tbl_constraints.setHorizontalHeaderLabels(
            ["ID", "시험", "교사", "날짜", "교시", "사유 / 상태"])
        self.tbl_constraints.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_constraints.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_constraints.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_constraints.setStyleSheet("border:none;")
        f.addWidget(self.tbl_constraints)

        btn_row = QHBoxLayout()
        btn_approve = QPushButton("승인")
        btn_approve.setStyleSheet(BTN_SUCCESS)
        btn_approve.clicked.connect(self._approve_constraint)
        btn_row.addWidget(btn_approve)

        btn_reject = QPushButton("거절")
        btn_reject.setStyleSheet(BTN_WARN)
        btn_reject.clicked.connect(self._reject_constraint)
        btn_row.addWidget(btn_reject)
        btn_row.addStretch()
        f.addLayout(btn_row)
        return frame

    # ── 데이터 로딩 ─────────────────────────────────────────────────────

    def _load_data(self):
        """시험 목록과 감독 불가 신청 목록을 DB 에서 읽어 갱신합니다."""
        self._load_exams()
        self._load_constraints()

    def refresh(self):
        """페이지 전환 시 main_window 에서 호출되는 갱신 진입점."""
        self._load_data()

    def _load_exams(self):
        session = get_session()
        try:
            exams = session.query(Exam).order_by(Exam.start_date.desc()).all()
            self.tbl_exams.setRowCount(len(exams))
            for row, ex in enumerate(exams):
                self.tbl_exams.setItem(row, 0, QTableWidgetItem(str(ex.id)))
                self.tbl_exams.setItem(row, 1, QTableWidgetItem(ex.name))
                self.tbl_exams.setItem(row, 2, QTableWidgetItem(
                    f"{ex.start_date:%m/%d}~{ex.end_date:%m/%d}"))
                self.tbl_exams.setItem(row, 3, QTableWidgetItem(
                    f"{ex.first_period_start:%H:%M} 시작 / 하루 {ex.periods_per_day}교시 / {ex.exam_minutes}분"))

                # 대상 학년 표기 — 저장값은 JSON 배열 문자열이므로 파싱해 표시
                try:
                    grade_ids = json.loads(ex.target_grade_ids or "[]")
                except (json.JSONDecodeError, TypeError):
                    grade_ids = []
                grade_text = ", ".join(str(g) for g in grade_ids) if grade_ids else "전체"
                self.tbl_exams.setItem(row, 4, QTableWidgetItem(grade_text))

                # 상태 — 색으로 구분 (초안 회색 / 게시 녹색)
                status_item = QTableWidgetItem(
                    "게시됨" if ex.status == "published" else "초안")
                status_item.setForeground(STATUS_COLORS.get(ex.status, QColor("black")))
                self.tbl_exams.setItem(row, 5, status_item)

                rules = []
                if ex.ban_homeroom_invigilation:
                    rules.append("담임금지")
                if ex.ban_own_subject:
                    rules.append("담당과목금지")
                self.tbl_exams.setItem(row, 6, QTableWidgetItem(
                    " / ".join(rules) if rules else "없음"))
        finally:
            session.close()

    def _load_constraints(self):
        session = get_session()
        try:
            rows = (
                session.query(InvigilationConstraint)
                .order_by(InvigilationConstraint.requested_at.desc())
                .all()
            )
            self.tbl_constraints.setRowCount(len(rows))
            for row, c in enumerate(rows):
                exam = session.get(Exam, c.exam_id)
                teacher = session.get(Teacher, c.teacher_id)
                self.tbl_constraints.setItem(row, 0, QTableWidgetItem(str(c.id)))
                self.tbl_constraints.setItem(row, 1, QTableWidgetItem(
                    exam.name if exam else f"#{c.exam_id}"))
                self.tbl_constraints.setItem(row, 2, QTableWidgetItem(
                    teacher.name if teacher else f"#{c.teacher_id}"))
                self.tbl_constraints.setItem(row, 3, QTableWidgetItem(
                    f"{c.exam_date:%m/%d}"))
                self.tbl_constraints.setItem(row, 4, QTableWidgetItem(
                    "전 교시" if c.period is None else f"{c.period}교시"))
                state_text = c.status
                if c.status == "approved" and c.reviewed_by:
                    state_text = f"승인({c.reviewed_by})"
                elif c.status == "rejected" and c.reviewed_by:
                    state_text = f"거절({c.reviewed_by})"
                item = QTableWidgetItem(f"{c.reason or '(사유 없음)'} — {state_text}")
                # pending 은 주황색으로 눈에 띄게 — 처리 대기 신청을 놓치지 않도록
                if c.status == "pending":
                    item.setForeground(QColor("#E67E22"))
                self.tbl_constraints.setItem(row, 5, item)
        finally:
            session.close()

    # ── 시험 생성·게시·삭제 ─────────────────────────────────────────────

    def _add_exam(self):
        """폼 입력값으로 시험을 생성하고 교시를 자동 생성합니다."""
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "시험명을 입력해 주세요.")
            return
        start = self.date_start.date().toPyDate()
        end = self.date_end.date().toPyDate()
        if end < start:
            QMessageBox.warning(self, "입력 오류", "종료일이 시작일보다 빠릅니다.")
            return

        # 대상 학년 파싱 — "1,2" → [1, 2]. 비어 있으면 전체 학년([]).
        grade_numbers = []
        for part in self.edit_grades.text().replace(" ", "").split(","):
            if part.isdigit():
                grade_numbers.append(int(part))

        session = get_session()
        try:
            term = (
                session.query(AcademicTerm)
                .filter_by(is_current=True)
                .order_by(AcademicTerm.id.desc())
                .first()
            )
            if term is None:
                QMessageBox.warning(
                    self, "학기 없음", "현재 학기가 없습니다. 먼저 학기를 등록해 주세요.")
                return

            # 학년 번호 → Grade id 매핑 (시험은 학년 id 를 JSON 으로 저장)
            if grade_numbers:
                from database.models import Grade
                grade_ids = [
                    g.id for g in session.query(Grade)
                    .filter(Grade.grade_number.in_(grade_numbers)).all()
                ]
                grade_ids_json = json.dumps(grade_ids)
            else:
                grade_ids_json = "[]"

            exam = Exam(
                term_id=term.id,
                name=name,
                exam_type=self.cmb_type.currentData(),
                school_level=self.cmb_level.currentData(),
                target_grade_ids=grade_ids_json,
                start_date=start,
                end_date=end,
                first_period_start=self.time_first.time().toPyTime(),
                periods_per_day=self.spin_periods.value(),
                break_minutes=self.spin_break.value(),
                prep_minutes=self.spin_prep.value(),
                exam_minutes=self.spin_exam_min.value(),
                max_subjects_per_day=self.spin_max_subjects.value(),
                ban_homeroom_invigilation=self.chk_ban_homeroom.isChecked(),
                ban_own_subject=self.chk_ban_own.isChecked(),
                status="draft",
            )
            session.add(exam)
            session.flush()
            # 기간·교시 규칙에 맞춰 ExamPeriod 자동 생성 (core 공통 구현 재사용)
            rebuild_exam_periods(session, exam)
            session.commit()
            self._load_data()
            QMessageBox.information(
                self, "완료", f"'{name}' 시험이 등록되었습니다.\n"
                "시험 시간표 / 감독 시간표 페이지에서 배치·배정을 진행하세요.")
        finally:
            session.close()

    def _selected_exam_id(self) -> int | None:
        """시험 목록에서 선택된 행의 시험 ID 반환."""
        row = self.tbl_exams.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "시험을 선택해 주세요.")
            return None
        return int(self.tbl_exams.item(row, 0).text())

    def _publish_exam(self):
        """
        선택 시험을 게시합니다.

        ApiClient 가 있으면 서버의 POST /exams/{id}/publish 를 호출해
        전 교사 알림(exam_published + 감독 배정 안내)까지 함께 발송합니다.
        서버에 접속할 수 없는 환경이면 DB 상태만 published 로 변경합니다.
        """
        exam_id = self._selected_exam_id()
        if exam_id is None:
            return

        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            if exam is None:
                return
            if exam.status == "published":
                QMessageBox.information(self, "안내", "이미 게시된 시험입니다.")
                return
            reply = QMessageBox.question(
                self, "게시 확인",
                f"'{exam.name}' 을(를) 게시할까요?\n"
                "게시 후에는 시험표·기간 수정이 불가하며, 전 교사에게 알림이 갑니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            name = exam.name

            # 경로 1 — 서버 API 경유(알림 발송 포함)
            if self._client is not None and self._client.is_logged_in:
                try:
                    self._client.post(f"/exams/{exam_id}/publish", {})
                    self._load_data()
                    QMessageBox.information(self, "게시 완료", f"'{name}' 이(가) 게시되었습니다.")
                    return
                except Exception:
                    # 서버 통신 실패 → DB 직접 경로로 폴백 (아래에서 처리)
                    pass

            # 경로 2 — DB 직접 변경 (서버 부재 시). 알림은 채팅 공지로 보완.
            exam.status = "published"
            session.commit()
            self._load_data()
            QMessageBox.information(
                self, "게시 완료",
                f"'{name}' 이(가) 게시되었습니다.\n"
                "(서버에 접속할 수 없어 알림은 발송되지 않았습니다 — 채팅 공지를 권장합니다.)")
        finally:
            session.close()

    def _delete_exam(self):
        """선택 시험을 삭제합니다. cascade 로 교시·시험표·감독 배정·불가 신청이 함께 삭제됩니다."""
        exam_id = self._selected_exam_id()
        if exam_id is None:
            return
        reply = QMessageBox.question(
            self, "삭제 확인",
            "시험과 딸린 교시·시험표·감독 배정·감독 불가 신청이 모두 삭제됩니다. 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            session.query(Exam).filter_by(id=exam_id).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()

    # ── 감독 불가 신청 승인/거절 ────────────────────────────────────────

    def _approve_constraint(self):
        """선택한 감독 불가 신청을 승인합니다. 승인 즉시 하드 제약으로 반영됩니다."""
        self._review_constraint("approved")

    def _reject_constraint(self):
        """선택한 감독 불가 신청을 거절합니다. 감독 배정에 반영되지 않습니다."""
        self._review_constraint("rejected")

    def _review_constraint(self, new_status: str):
        row = self.tbl_constraints.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "처리할 신청을 선택해 주세요.")
            return
        cid = int(self.tbl_constraints.item(row, 0).text())

        session = get_session()
        try:
            c = session.get(InvigilationConstraint, cid)
            if c is None:
                return
            if c.status != "pending":
                QMessageBox.information(self, "안내", "이미 처리된 신청입니다.")
                return
            c.status = new_status
            # 승인/거절자·시각 기록 — 누가 처리했는지 감사 추적용
            c.reviewed_by = "관리자앱"
            c.reviewed_at = datetime.now()
            session.commit()
            self._load_constraints()
        finally:
            session.close()