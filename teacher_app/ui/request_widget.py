"""
교체 신청 위젯

교사가 당일 시간표 교체를 신청하고, 본인이 제출한 신청 목록을 확인합니다.

신청 흐름:
  교사가 날짜·교시·대체 교사/교과/교실 선택 → 신청 제출
  → 관리자(교감·일과계)가 관리 프로그램에서 승인/거절
  → 이 화면에서 결과 확인

동적 결재 워크플로우 지원:
  - 서버에서 current_step, total_steps, approval_history 를 제공
  - 상태 표시에 단계 진행 상황 포함
  - 결재 이력 컬럼으로 각 단계별 처리 내역 확인 가능
"""
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from shared.api_client import ApiClient, ApiError

ROLE_DISPLAY = {
    "admin": "일과계",
    "vice_principal": "교감",
    "department_head": "교무부장",
}


class _SubmitWorker(QThread):
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, body: dict):
        super().__init__()
        self._client = client
        self._body = body

    def run(self):
        try:
            result = self._client.post("/timetable/requests", self._body)
            self.done.emit(result)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class _LoadWorker(QThread):
    done = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client

    def run(self):
        try:
            requests = self._client.get("/timetable/requests")
            self.done.emit(requests)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class RequestWidget(QWidget):
    """당일 시간표 교체 신청 위젯."""

    def __init__(self, client: ApiClient):
        super().__init__()
        self._client = client
        self._entries: list[dict] = []
        self._worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("시간표 교체 신청")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(title)

        # ── 신청 폼 ──────────────────────────────────────────────────────
        form_box = QGroupBox("신청 정보 입력")
        form_layout = QVBoxLayout(form_box)

        # 신청 대상 시간표 선택
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("대상 시간표:"))
        self.cb_entry = QComboBox()
        self.cb_entry.setMinimumWidth(200)
        row1.addWidget(self.cb_entry)
        row1.addStretch()
        form_layout.addLayout(row1)

        # 사유 입력
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("변경 사유:"))
        self.edit_reason = QLineEdit()
        self.edit_reason.setPlaceholderText("예) 출장으로 인한 수업 교체 요청")
        row2.addWidget(self.edit_reason)
        form_layout.addLayout(row2)

        btn_submit = QPushButton("신청 제출")
        btn_submit.setStyleSheet(
            "background:#27AE60; color:white; border-radius:4px; padding:8px 20px; font-weight:bold;"
        )
        btn_submit.clicked.connect(self._submit)
        form_layout.addWidget(btn_submit, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(form_box)

        # ── 신청 목록 ────────────────────────────────────────────────────
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("내 신청 목록"))
        btn_refresh = QPushButton("새로고침")
        btn_refresh.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:4px 12px;"
        )
        btn_refresh.clicked.connect(self._load_requests)
        list_header.addWidget(btn_refresh)
        list_header.addStretch()
        layout.addLayout(list_header)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["신청일시", "대상", "사유", "상태", "동의", "결재 이력"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def refresh(self):
        """페이지 전환 시 내 시간표 목록과 신청 이력을 새로 불러옵니다."""
        self._load_my_entries()
        self._load_requests()

    def _load_my_entries(self):
        """본인이 담당하는 시간표 슬롯을 콤보박스에 채웁니다."""
        teacher_id = self._client.teacher_id
        if not teacher_id:
            return
        try:
            terms = self._client.get("/timetable/terms")
            current = next((t for t in terms if t.get("is_current")), None)
            if not current and terms:
                current = terms[0]
            if not current:
                return
            self._entries = self._client.get(
                "/timetable/entries",
                term_id=current["id"],
                teacher_id=teacher_id,
            )
            self.cb_entry.clear()
            day_names = {1: "월", 2: "화", 3: "수", 4: "목", 5: "금"}
            for e in self._entries:
                day = day_names.get(e["day_of_week"], "?")
                label = (
                    f"{day}요일 {e['period']}교시 — "
                    f"{e.get('subject_name', '?')} "
                    f"({e.get('teacher_name', '')})"
                )
                self.cb_entry.addItem(label, e["id"])
        except Exception as e:
            QMessageBox.warning(self, "조회 오류", str(e))

    def _load_requests(self):
        self._worker = _LoadWorker(self._client)
        self._worker.done.connect(self._populate_requests)
        self._worker.error.connect(lambda m: QMessageBox.warning(self, "오류", m))
        self._worker.start()

    def _populate_requests(self, requests: list):
        self.table.setRowCount(len(requests))
        status_colors = {
            "pending":  "#FFF9C4",
            "approved": "#E8F5E9",
            "rejected": "#FFEBEE",
        }
        consent_colors = {
            "not_required": "#FFFFFF",
            "pending":      "#FFF9C4",
            "approved":     "#E8F5E9",
            "rejected":     "#FFEBEE",
        }
        consent_labels = {
            "not_required": "불필요",
            "pending":      "대기 중",
            "approved":     "동의 완료",
            "rejected":     "동의 거절",
        }
        for row, req in enumerate(requests):
            at = str(req.get("requested_at", ""))[:16]
            status = req.get("status", "")
            current_step = req.get("current_step", 1)
            total_steps = req.get("total_steps", 0)
            consent_status = req.get("consent_status", "not_required")

            # 상태 텍스트 — pending 시 진행 단계 포함
            if status == "pending":
                total = total_steps or 1
                status_text = f"대기 중 ({current_step}/{total}단계)"
            elif status == "approved":
                status_text = "승인 완료"
            elif status == "rejected":
                status_text = "거절"
            else:
                status_text = status

            cells = [
                at,
                f"시간표#{req.get('timetable_entry_id', '')}",
                req.get("reason", ""),
                status_text,
                consent_labels.get(consent_status, consent_status),
                self._format_approval_history(req.get("approval_history", "[]")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 3:
                    item.setBackground(QColor(status_colors.get(status, "#FFFFFF")))
                elif col == 4:
                    item.setBackground(QColor(consent_colors.get(consent_status, "#FFFFFF")))
                self.table.setItem(row, col, item)

    @staticmethod
    def _format_approval_history(history_str: str) -> str:
        """
        서버에서 받은 approval_history JSON 문자열을 읽기 쉬운 여러 줄 텍스트로 변환합니다.

        서버는 ChangeRequestOut 에 total_steps 를 동적으로 주입하여 응답하므로,
        교사 앱은 별도의 워크플로우 조회 없이 API 응답만으로 진행 상황을 표시할 수 있습니다.

        JSON 구조 (서버에서 current_user.username 으로 by 필드를 채워 응답):
          [{"step": 1, "role": "admin", "action": "approve", "by": "admin", "at": "2024-03-15T14:30:00"}]

        출력 예:
          1단계 승인 (일과계, 03/15 14:30)
          2단계 거절 (교감, 03/15 15:00)
        """
        try:
            history = json.loads(history_str or "[]")
        except (json.JSONDecodeError, TypeError):
            return ""

        if not history:
            return ""

        lines = []
        for h in history:
            step = h.get("step", "?")
            role = h.get("role", "")
            role_label = ROLE_DISPLAY.get(role, role)
            action = h.get("action", "")
            action_text = "승인" if action == "approve" else "거절"
            at_str = ""
            if h.get("at"):
                try:
                    dt = datetime.fromisoformat(h["at"])
                    at_str = dt.strftime("%m/%d %H:%M")
                except (ValueError, TypeError):
                    pass
            lines.append(f"{step}단계 {action_text} ({role_label}{', ' + at_str if at_str else ''})")

        return "\n".join(lines)

    def _submit(self):
        entry_id = self.cb_entry.currentData()
        if entry_id is None:
            QMessageBox.warning(self, "입력 오류", "대상 시간표를 선택하세요.")
            return
        reason = self.edit_reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "입력 오류", "변경 사유를 입력하세요.")
            return

        self._worker = _SubmitWorker(
            self._client,
            {"timetable_entry_id": entry_id, "reason": reason},
        )
        self._worker.done.connect(self._on_submitted)
        self._worker.error.connect(lambda m: QMessageBox.critical(self, "신청 실패", m))
        self._worker.start()

    def _on_submitted(self, result: dict):
        QMessageBox.information(self, "신청 완료", "시간표 교체 신청이 접수되었습니다.\n관리자 승인 후 반영됩니다.")
        self.edit_reason.clear()
        self._load_requests()
