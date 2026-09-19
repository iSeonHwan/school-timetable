"""
내 감독 시간표 위젯 (2026-09-19 신규, 교사 앱)

교사가 시험 기간에 본인과 관련된 감독 업무를 확인·신청하는 페이지입니다.

구성 (위에서 아래로 3개 섹션):
  1. 내 감독 시간표 — 게시된 시험 중 선택 → 본인 감독 배정 조회
     (GET /exams/my/invigilations?exam_id=)
  2. 감독 교체(스왑) 신청 — 감독일 변경이 필요할 때 상대 교사와 맞바꾸는
     신청. 기존 수업 시간표 교체와 동일한 승인 라인을 그대로 사용합니다:
       본인 신청 → 상대 교사 동의 → 일과계 1차 → 교감 최종 승인
     (POST /timetable/requests, request_type="invigilation")
  3. 감독 불가 신청 — 공결·출장·연수 등 특정 날짜(교시)에 감독이 불가한
     경우 사전 제출. 관리자(일과계) 승인 후 자동 배정에 반영됩니다.
     시험 게시 전(초안)에도 제출 가능 — 감독 배정은 게시 전에 이루어지기
     때문입니다. (POST /exams/{id}/constraints)

모든 서버 호출은 ApiClient 동기 메서드이므로 UI 스레드 블로킹을 막기 위해
QThread 워커(_GetWorker/_PostWorker)에서 실행합니다 (기존 페이지 패턴 동일).
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox,
    QDateEdit, QSpinBox, QCheckBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QFont, QColor

from shared.api_client import ApiClient, ApiError


class _GetWorker(QThread):
    """GET 요청을 비동기로 수행하는 워커 (조회 전용)."""
    done = pyqtSignal(object)   # 조회 결과 (list 또는 dict)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, path: str, params: dict | None = None):
        super().__init__()
        self._client = client
        self._path = path
        self._params = params or {}

    def run(self):
        try:
            # None 값 파라미터는 전송하지 않습니다 (exam_id 미지정 = 전체 조회).
            params = {k: v for k, v in self._params.items() if v is not None}
            result = self._client.get(self._path, **params)
            self.done.emit(result)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class _PostWorker(QThread):
    """POST 요청을 비동기로 수행하는 워커 (신청 제출용)."""
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, path: str, body: dict):
        super().__init__()
        self._client = client
        self._path = path
        self._body = body

    def run(self):
        try:
            result = self._client.post(self._path, self._body)
            self.done.emit(result)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


def _assignment_label(a: dict) -> str:
    """
    감독 배정 하나를 콤보박스 표기용 문자열로 만듭니다.

    서버(InvigilationAssignmentOut)가 조인해 준 이름 필드를 사용:
    "10/05 1교시 1-1 (1조) — 김교사"
    """
    date_str = str(a.get("exam_date") or "")
    try:
        date_str = datetime.fromisoformat(date_str).strftime("%m/%d")
    except ValueError:
        pass
    period = a.get("period_number", "?")
    cls = a.get("class_name") or f"반#{a.get('school_class_id')}"
    pair = a.get("pair_index", 1)
    teacher = a.get("teacher_name") or "미배정"
    return f"{date_str} {period}교시 {cls} ({pair}조) — {teacher}"


class MyInvigilationWidget(QWidget):
    """내 감독 시간표 + 감독 스왑 신청 + 감독 불가 신청 교사용 위젯."""

    def __init__(self, client: ApiClient, parent=None):
        super().__init__(parent)
        self._client = client
        # 서버 응답 캐시 — 스왑 신청 시 배정 ID 가 필요하므로 원본 저장
        self._exams: list[dict] = []            # 게시된 시험 (내 감독 조회용)
        self._exams_all: list[dict] = []         # 초안 포함 전체 (불가 신청용)
        self._my_invigilations: list[dict] = []  # 선택 시험의 내 감독 배정
        self._all_invigilations: list[dict] = [] # 선택 시험의 전체 감독표 (스왑 상대 선택용)
        self._my_constraints: list[dict] = []    # 선택 시험의 내 불가 신청 내역
        # QThread 참조 보관 — 파이썬 GC 가 실행 중 워커를 회수하지 못하게 함
        self._w_exams = None
        self._w_exams_all = None
        self._w_my = None
        self._w_all = None
        self._w_constraints = None
        self._w_submit = None
        self._init_ui()

    # ── UI 구성 ─────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("시험 감독")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color:#1A6B3C;")
        layout.addWidget(title)

        layout.addWidget(self._build_my_section())
        layout.addWidget(self._build_swap_section())
        layout.addWidget(self._build_constraint_section())
        layout.addStretch()

    def _build_my_section(self) -> QGroupBox:
        """섹션 1: 내 감독 시간표 — 게시된 시험 중 선택한 시험의 내 배정 조회."""
        box = QGroupBox("내 감독 시간표")
        v = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("시험 선택:"))
        self.cmb_exam = QComboBox()
        self.cmb_exam.setMinimumWidth(240)
        self.cmb_exam.currentIndexChanged.connect(self._on_exam_changed)
        row.addWidget(self.cmb_exam)
        row.addStretch()
        v.addLayout(row)

        self.tbl_my = QTableWidget()
        self.tbl_my.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_my.setColumnCount(5)
        self.tbl_my.setHorizontalHeaderLabels(["날짜", "교시", "시간", "반", "시험 과목"])
        self.tbl_my.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.tbl_my)

        hint = QLabel("게시된 시험의 내 감독 일정이 표시됩니다.")
        hint.setStyleSheet("color:#888; font-size:11px;")
        v.addWidget(hint)
        return box

    def _build_swap_section(self) -> QGroupBox:
        """
        섹션 2: 감독 교체(스왑) 신청.

        요구사항 8 — 기존 수업 시간표 교체의 승인 라인을 그대로 재사용:
        상대 교사 동의 → 일과계 1차 → 교감 최종 승인.
        """
        box = QGroupBox("감독 교체(스왑) 신청")
        v = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("내 감독:"))
        self.cmb_swap_mine = QComboBox()
        self.cmb_swap_mine.setMinimumWidth(260)
        row1.addWidget(self.cmb_swap_mine)
        row1.addStretch()
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("상대 감독:"))
        self.cmb_swap_partner = QComboBox()
        self.cmb_swap_partner.setMinimumWidth(260)
        row2.addWidget(self.cmb_swap_partner)
        row2.addStretch()
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("사유:"))
        self.edit_swap_reason = QLineEdit()
        self.edit_swap_reason.setPlaceholderText("예) 개인 일정으로 10/05 감독 어려움")
        row3.addWidget(self.edit_swap_reason)
        v.addLayout(row3)

        self.btn_swap = QPushButton("스왑 신청 제출")
        self.btn_swap.setStyleSheet(
            "background:#27AE60; color:white; border-radius:4px; "
            "padding:6px 16px; font-weight:bold;")
        self.btn_swap.clicked.connect(self._submit_swap)
        v.addWidget(self.btn_swap, alignment=Qt.AlignmentFlag.AlignRight)

        hint = QLabel(
            "상대 교사 동의 → 일과계 1차 → 교감 최종 승인 후 감독이 서로 맞바뀝니다. "
            "상대 감독은 게시된 감독표에서 선택합니다.")
        hint.setStyleSheet("color:#888; font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        return box

    def _build_constraint_section(self) -> QGroupBox:
        """섹션 3: 감독 불가 신청 (게시 전 초안 시험 포함)."""
        box = QGroupBox("감독 불가 신청")
        v = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("시험 선택:"))
        self.cmb_constraint_exam = QComboBox()
        self.cmb_constraint_exam.setMinimumWidth(240)
        self.cmb_constraint_exam.currentIndexChanged.connect(self._on_constraint_exam_changed)
        row1.addWidget(self.cmb_constraint_exam)
        row1.addStretch()
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("불가 날짜:"))
        self.date_constraint = QDateEdit(QDate.currentDate())
        self.date_constraint.setCalendarPopup(True)
        row2.addWidget(self.date_constraint)

        self.chk_all_periods = QCheckBox("하루 전체(전 교시)")
        self.chk_all_periods.toggled.connect(
            lambda checked: self.spin_c_period.setEnabled(not checked))
        row2.addWidget(self.chk_all_periods)

        row2.addWidget(QLabel("교시:"))
        self.spin_c_period = QSpinBox()
        self.spin_c_period.setRange(1, 10)
        row2.addWidget(self.spin_c_period)
        row2.addStretch()
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("사유:"))
        self.edit_c_reason = QLineEdit()
        self.edit_c_reason.setPlaceholderText("예) 출장, 공결, 연수 등")
        row3.addWidget(self.edit_c_reason)
        v.addLayout(row3)

        self.btn_constraint = QPushButton("불가 신청 제출")
        self.btn_constraint.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; "
            "padding:6px 16px; font-weight:bold;")
        self.btn_constraint.clicked.connect(self._submit_constraint)
        v.addWidget(self.btn_constraint, alignment=Qt.AlignmentFlag.AlignRight)

        # 내 신청 내역 — 승인 진행 상황(pending/approved/rejected) 확인용
        v.addWidget(QLabel("내 신청 내역"))
        self.tbl_constraints = QTableWidget()
        self.tbl_constraints.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_constraints.setColumnCount(4)
        self.tbl_constraints.setHorizontalHeaderLabels(["날짜", "교시", "사유", "상태"])
        self.tbl_constraints.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.tbl_constraints)

        hint = QLabel(
            "신청은 관리자 승인 후 자동 배정에 반영됩니다. "
            "시험 게시 전(초안)에도 제출할 수 있습니다.")
        hint.setStyleSheet("color:#888; font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        return box

    # ── 데이터 로딩 ─────────────────────────────────────────────────────

    def refresh(self):
        """페이지 진입 시 호출 — 시험 목록을 다시 불러옵니다."""
        # 내 감독 조회용: 게시된 시험만 (교사는 게시 전 시험표/감독표 접근 불가)
        self._w_exams = _GetWorker(self._client, "/exams")
        self._w_exams.done.connect(self._populate_exams)
        self._w_exams.error.connect(lambda m: QMessageBox.warning(self, "조회 오류", m))
        self._w_exams.start()

        # 불가 신청용: 초안 포함 전체 시험 — 실무 순서상 불가 신청은
        # 감독 배정(=게시) 전에 들어와야 하기 때문입니다.
        self._w_exams_all = _GetWorker(self._client, "/exams", {"include_draft": True})
        self._w_exams_all.done.connect(self._populate_constraint_exams)
        self._w_exams_all.error.connect(lambda m: None)
        self._w_exams_all.start()

    def _populate_exams(self, exams: list):
        """게시된 시험 콤보박스 갱신 + 첫 시험 선택 시 내 감독 로딩."""
        self._exams = exams
        self.cmb_exam.blockSignals(True)
        self.cmb_exam.clear()
        for ex in exams:
            self.cmb_exam.addItem(ex["name"], ex["id"])
        self.cmb_exam.blockSignals(False)
        self._load_my_invigilations()
        self._load_all_invigilations()

    def _populate_constraint_exams(self, exams: list):
        """불가 신청용 시험 콤보박스 갱신 (초안 포함)."""
        self._exams_all = exams
        self.cmb_constraint_exam.blockSignals(True)
        self.cmb_constraint_exam.clear()
        for ex in exams:
            state = " [게시됨]" if ex["status"] == "published" else " [준비 중]"
            self.cmb_constraint_exam.addItem(f"{ex['name']}{state}", ex["id"])
        self.cmb_constraint_exam.blockSignals(False)
        self._load_my_constraints()

    def _current_exam_id(self) -> int | None:
        return self.cmb_exam.currentData()

    def _on_exam_changed(self, *_):
        """내 감독 시험 선택 변경 시 감독 목록을 다시 불러옵니다."""
        self._load_my_invigilations()
        self._load_all_invigilations()

    def _on_constraint_exam_changed(self, *_):
        """불가 신청 대상 시험 변경 시 내역을 다시 불러옵니다."""
        self._load_my_constraints()

    def _load_my_invigilations(self):
        """선택 시험의 내 감독 배정 조회 (GET /exams/my/invigilations)."""
        exam_id = self._current_exam_id()
        if exam_id is None:
            self._my_invigilations = []
            self._render_my_invigilations()
            return
        self._w_my = _GetWorker(
            self._client, "/exams/my/invigilations", {"exam_id": exam_id})
        self._w_my.done.connect(self._render_my_invigilations)
        self._w_my.error.connect(lambda m: QMessageBox.warning(self, "조회 오류", m))
        self._w_my.start()

    def _load_all_invigilations(self):
        """
        선택 시험의 전체 감독표 조회 (GET /exams/{id}/invigilations).

        게시된 시험은 교사도 열람 가능합니다 (_check_teacher_visibility 참조).
        스왑 상대 슬롯 선택에 사용합니다.
        """
        exam_id = self._current_exam_id()
        if exam_id is None:
            self._all_invigilations = []
            self._populate_swap_combos()
            return
        self._w_all = _GetWorker(
            self._client, f"/exams/{exam_id}/invigilations")
        self._w_all.done.connect(self._on_all_invigilations)
        self._w_all.error.connect(lambda m: None)
        self._w_all.start()

    def _on_all_invigilations(self, rows: list):
        self._all_invigilations = rows
        self._populate_swap_combos()

    def _load_my_constraints(self):
        """선택한 불가 신청 시험의 내 신청 내역 조회."""
        exam_id = self.cmb_constraint_exam.currentData()
        if exam_id is None:
            self._my_constraints = []
            self._render_constraints()
            return
        self._w_constraints = _GetWorker(
            self._client, f"/exams/{exam_id}/constraints")
        self._w_constraints.done.connect(self._on_constraints)
        self._w_constraints.error.connect(lambda m: None)
        self._w_constraints.start()

    def _on_constraints(self, rows: list):
        """교사는 본인 신청만 서버가 필터해 반환 (다른 교사 사유 미노출)."""
        self._my_constraints = rows
        self._render_constraints()

    # ── 렌더링 ──────────────────────────────────────────────────────────

    def _render_my_invigilations(self, rows: list | None = None):
        """내 감독 테이블 + 스왑 신청 '내 감독' 콤보박스 렌더링."""
        if rows is not None:
            self._my_invigilations = rows
        rows = self._my_invigilations

        self.tbl_my.setRowCount(len(rows))
        for r, a in enumerate(rows):
            date_str = str(a.get("exam_date") or "")
            try:
                date_str = datetime.fromisoformat(date_str).strftime("%m/%d")
            except ValueError:
                pass
            start = str(a.get("start_time") or "")[:5]
            end = str(a.get("end_time") or "")[:5]
            cells = [
                date_str,
                f"{a.get('period_number', '?')}교시",
                f"{start}~{end}",
                a.get("class_name") or f"반#{a.get('school_class_id')}",
                a.get("subject_name") or "-",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl_my.setItem(r, c, item)

        # 스왑 '내 감독' 콤보 — 배정된 내 슬롯만 스왑 대상이 됩니다
        self.cmb_swap_mine.blockSignals(True)
        self.cmb_swap_mine.clear()
        for a in rows:
            self.cmb_swap_mine.addItem(_assignment_label(a), a["id"])
        self.cmb_swap_mine.blockSignals(False)
        self._populate_swap_combos()

    def _populate_swap_combos(self):
        """스왑 '상대 감독' 콤보 — 미배정 슬롯은 제외한 전체 감독표."""
        my_id = self.cmb_swap_mine.currentData()
        self.cmb_swap_partner.blockSignals(True)
        self.cmb_swap_partner.clear()
        for a in self._all_invigilations:
            # 스왑은 배정된 교사 간 맞바꾸기이므로 teacher_id 가 있는 슬롯만
            if a.get("teacher_id") is None:
                continue
            # 상대는 내 슬롯이 아니어야 함 (서버에서도 검증하지만 UX 차원 배제)
            if my_id is not None and a["id"] == my_id:
                continue
            self.cmb_swap_partner.addItem(_assignment_label(a), a["id"])
        self.cmb_swap_partner.blockSignals(False)

    def _render_constraints(self, rows: list | None = None):
        """감독 불가 신청 내역 테이블 렌더링."""
        if rows is not None:
            self._my_constraints = rows
        rows = self._my_constraints

        status_colors = {
            "pending": "#FFF9C4",
            "approved": "#E8F5E9",
            "rejected": "#FFEBEE",
        }
        status_labels = {"pending": "대기 중", "approved": "승인됨", "rejected": "거절됨"}
        self.tbl_constraints.setRowCount(len(rows))
        for r, c in enumerate(rows):
            date_str = str(c.get("exam_date") or "")
            period = c.get("period")
            period_text = "전 교시" if period is None else f"{period}교시"
            cells = [
                date_str, period_text,
                c.get("reason") or "",
                status_labels.get(c.get("status"), c.get("status", "")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 3:
                    item.setBackground(
                        QColor(status_colors.get(c.get("status"), "#FFFFFF")))
                self.tbl_constraints.setItem(r, col, item)

    # ── 신청 제출 ───────────────────────────────────────────────────────

    def _submit_swap(self):
        """감독 스왑 신청 제출 (기존 승인 라인 재사용 — 요구사항 8)."""
        mine_id = self.cmb_swap_mine.currentData()
        partner_id = self.cmb_swap_partner.currentData()
        if mine_id is None:
            QMessageBox.warning(self, "입력 오류", "내 감독을 선택하세요.")
            return
        if partner_id is None:
            QMessageBox.warning(self, "입력 오류", "상대 감독을 선택하세요.")
            return
        reason = self.edit_swap_reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "입력 오류", "사유를 입력하세요.")
            return

        # 서버(submit_request)가 request_type 으로 감독 스왑을 분기 처리합니다.
        self._w_submit = _PostWorker(self._client, "/timetable/requests", {
            "request_type": "invigilation",
            "invigilation_assignment_id": mine_id,
            "swap_partner_invigilation_id": partner_id,
            "reason": reason,
        })
        self._w_submit.done.connect(self._on_swap_submitted)
        self._w_submit.error.connect(
            lambda m: QMessageBox.critical(self, "신청 실패", m))
        self._w_submit.start()

    def _on_swap_submitted(self, result: dict):
        QMessageBox.information(
            self, "신청 완료",
            "감독 교체 신청이 접수되었습니다.\n"
            "상대 교사 동의 → 일과계 → 교감 승인 후 반영됩니다.")
        self.edit_swap_reason.clear()

    def _submit_constraint(self):
        """감독 불가 신청 제출 (관리자 승인 후 배정에 반영)."""
        exam_id = self.cmb_constraint_exam.currentData()
        if exam_id is None:
            QMessageBox.warning(self, "입력 오류", "시험을 선택하세요.")
            return
        reason = self.edit_c_reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "입력 오류", "사유를 입력하세요.")
            return

        body = {
            "exam_date": self.date_constraint.date().toString("yyyy-MM-dd"),
            # "하루 전체" 체크 시 period=None — 해당 날짜 전 교시가 대상
            "period": None if self.chk_all_periods.isChecked()
                      else self.spin_c_period.value(),
            "reason": reason,
        }
        self._w_submit = _PostWorker(
            self._client, f"/exams/{exam_id}/constraints", body)
        self._w_submit.done.connect(self._on_constraint_submitted)
        self._w_submit.error.connect(
            lambda m: QMessageBox.critical(self, "신청 실패", m))
        self._w_submit.start()

    def _on_constraint_submitted(self, result: dict):
        QMessageBox.information(
            self, "신청 완료",
            "감독 불가 신청이 접수되었습니다. 관리자 승인 후 반영됩니다.")
        self.edit_c_reason.clear()
        self._load_my_constraints()