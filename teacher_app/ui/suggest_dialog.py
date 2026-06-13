"""
시간표 교체 제안 다이얼로그

교사가 시간표 슬롯을 더블클릭하면 열리는 창입니다.
서버의 GET /timetable/suggestions?entry_id=X 를 조회해
충돌 검증을 통과한 대체 제안(과목/교사/교실)과 교환(swap) 제안을 보여줍니다.

제안을 선택하고 사유를 입력한 뒤 '신청 제출' 버튼을 누르면
POST /timetable/requests 로 변경 신청이 접수됩니다.

동의가 필요한 경우(예: 다른 교사로 교체, 교환):
  - 서버가 피교사에게 알림(Notification)을 보냅니다.
  - 피교사가 동의(approve)해야 일과계의 결재 단계(current_step=1)로 넘어갑니다.
  - 동의가 없으면 관리자가 승인할 수 없습니다.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTabWidget, QWidget,
    QListWidget, QListWidgetItem, QMessageBox,
    QGroupBox, QTextEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from shared.api_client import ApiClient, ApiError


class _LoadSuggestionsWorker(QThread):
    """서버에서 제안 목록을 비동기로 조회하는 워커."""
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, entry_id: int):
        super().__init__()
        self._client = client
        self._entry_id = entry_id

    def run(self):
        try:
            data = self._client.get("/timetable/suggestions", entry_id=self._entry_id)
            self.done.emit(data)
        except ApiError as e:
            self.error.emit(e.detail)
        except Exception as e:
            self.error.emit(str(e))


class _SubmitRequestWorker(QThread):
    """변경 신청을 비동기로 제출하는 워커."""
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


class SuggestDialog(QDialog):
    """
    시간표 교체 제안 다이얼로그.

    Attributes:
        _client          : ApiClient (로그인된 상태)
        _entry_id        : 더블클릭한 시간표 항목 ID
        _current         : 현재 슬롯 정보 (SuggestionCurrent)
        _selected_payload: 사용자가 선택한 제안의 식별자 딕셔너리
    """

    def __init__(self, client: ApiClient, entry_id: int, parent=None):
        super().__init__(parent)
        self._client = client
        self._entry_id = entry_id
        self._current: dict | None = None
        self._selected_payload: dict | None = None
        self.setWindowTitle("시간표 교체 제안")
        self.resize(520, 520)
        self._init_ui()
        self._load_suggestions()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 현재 슬롯 정보 표시 ─────────────────────────────────────────────
        self.lbl_current = QLabel("현재 슬롯 정보를 불러오는 중...")
        self.lbl_current.setFont(QFont("", 11, QFont.Weight.Bold))
        self.lbl_current.setStyleSheet("color:#1A5276;")
        layout.addWidget(self.lbl_current)

        # ── 탭 위젯: 대체 제안 / 교환 제안 ──────────────────────────────────
        self.tabs = QTabWidget()

        # 대체 제안 탭
        self.tab_replace = QWidget()
        replace_layout = QVBoxLayout(self.tab_replace)
        replace_layout.setContentsMargins(8, 8, 8, 8)
        replace_layout.setSpacing(10)

        self.list_subjects = QListWidget()
        self.list_subjects.setMaximumHeight(120)
        self.list_subjects.itemClicked.connect(self._on_subject_selected)
        replace_layout.addWidget(QLabel("대체 과목"))
        replace_layout.addWidget(self.list_subjects)

        self.list_teachers = QListWidget()
        self.list_teachers.setMaximumHeight(120)
        self.list_teachers.itemClicked.connect(self._on_teacher_selected)
        replace_layout.addWidget(QLabel("대체 교사 (선택 시 피교사 동의 필요)"))
        replace_layout.addWidget(self.list_teachers)

        self.list_rooms = QListWidget()
        self.list_rooms.setMaximumHeight(100)
        self.list_rooms.itemClicked.connect(self._on_room_selected)
        replace_layout.addWidget(QLabel("대체 교실"))
        replace_layout.addWidget(self.list_rooms)

        self.tabs.addTab(self.tab_replace, "대체 제안")

        # 교환 제안 탭
        self.tab_swap = QWidget()
        swap_layout = QVBoxLayout(self.tab_swap)
        swap_layout.setContentsMargins(8, 8, 8, 8)
        swap_layout.setSpacing(8)
        swap_layout.addWidget(QLabel("현재 슬롯과 교환할 수 있는 다른 슬롯입니다. (양쪽 교사 동의 필요)"))
        self.list_swaps = QListWidget()
        self.list_swaps.itemClicked.connect(self._on_swap_selected)
        swap_layout.addWidget(self.list_swaps)
        self.tabs.addTab(self.tab_swap, "교환 제안")

        layout.addWidget(self.tabs, stretch=1)

        # ── 선택 요약 및 사유 입력 ──────────────────────────────────────────
        summary_box = QGroupBox("선택 내용")
        summary_layout = QVBoxLayout(summary_box)

        self.lbl_summary = QLabel("위 제안 목록에서 하나를 선택하세요.")
        self.lbl_summary.setWordWrap(True)
        summary_layout.addWidget(self.lbl_summary)

        reason_layout = QHBoxLayout()
        reason_layout.addWidget(QLabel("변경 사유:"))
        self.edit_reason = QLineEdit()
        self.edit_reason.setPlaceholderText("예) 회의로 인한 수업 대체 요청")
        reason_layout.addWidget(self.edit_reason)
        summary_layout.addLayout(reason_layout)

        layout.addWidget(summary_box)

        # ── 버튼 ───────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("취소")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        self.btn_submit = QPushButton("신청 제출")
        self.btn_submit.setStyleSheet(
            "background:#27AE60; color:white; border-radius:4px; padding:8px 20px; font-weight:bold;"
        )
        self.btn_submit.clicked.connect(self._submit)
        self.btn_submit.setEnabled(False)
        btn_layout.addWidget(self.btn_submit)

        layout.addLayout(btn_layout)

    def _load_suggestions(self):
        """서버에서 제안 목록을 조회합니다."""
        self._worker = _LoadSuggestionsWorker(self._client, self._entry_id)
        self._worker.done.connect(self._populate)
        self._worker.error.connect(self._on_load_error)
        self._worker.start()

    def _on_load_error(self, message: str):
        QMessageBox.critical(self, "제안 조회 실패", message)
        self.reject()

    def _populate(self, data: dict):
        """서버 응답을 UI에 채웁니다."""
        self._current = data.get("current", {})
        current = self._current
        day_names = {1: "월", 2: "화", 3: "수", 4: "목", 5: "금"}
        day = day_names.get(current.get("day_of_week", 0), "?")
        self.lbl_current.setText(
            f"{current.get('school_class_name', '?')} — {day}요일 {current.get('period', '?')}교시\n"
            f"과목: {current.get('subject_name', '?')} | 교사: {current.get('teacher_name', '?')} | "
            f"교실: {current.get('room_name') or '미배정'}"
        )

        self._fill_list(self.list_subjects, data.get("subjects", []))
        self._fill_list(self.list_teachers, data.get("teachers", []))
        self._fill_list(self.list_rooms, data.get("rooms", []))
        self._fill_list(self.list_swaps, data.get("swaps", []))

    @staticmethod
    def _fill_list(widget: QListWidget, items: list):
        """SuggestionOption 리스트를 QListWidget에 채웁니다."""
        widget.clear()
        for opt in items:
            label = opt.get("label", "")
            reason = opt.get("reason", "")
            text = f"{label}\n  → {reason}" if reason else label
            item = QListWidgetItem(text)
            # 선택 시 꺼낼 데이터를 item 데이터로 저장
            item.setData(Qt.ItemDataRole.UserRole, opt)
            widget.addItem(item)

    def _on_subject_selected(self, item: QListWidgetItem):
        """대체 과목을 선택하면 교사/교실 선택을 초기화하고 과목 ID만 저장합니다."""
        self._clear_other_selections(self.list_subjects)
        opt = item.data(Qt.ItemDataRole.UserRole)
        self._selected_payload = {"new_subject_id": opt.get("subject_id")}
        self._update_summary(f"과목 변경: {opt.get('label', '')}")

    def _on_teacher_selected(self, item: QListWidgetItem):
        """대체 교사를 선택하면 피교사 동의가 필요함을 표시합니다."""
        self._clear_other_selections(self.list_teachers)
        opt = item.data(Qt.ItemDataRole.UserRole)
        self._selected_payload = {"new_teacher_id": opt.get("teacher_id")}
        self._update_summary(
            f"교사 변경: {opt.get('label', '')} — 피교사 동의 후 관리자 결재가 진행됩니다."
        )

    def _on_room_selected(self, item: QListWidgetItem):
        """대체 교실을 선택합니다. 동의는 필요 없습니다."""
        self._clear_other_selections(self.list_rooms)
        opt = item.data(Qt.ItemDataRole.UserRole)
        self._selected_payload = {"new_room_id": opt.get("room_id")}
        self._update_summary(f"교실 변경: {opt.get('label', '')}")

    def _on_swap_selected(self, item: QListWidgetItem):
        """교환 상대 슬롯을 선택하면 양쪽 교사 동의가 필요함을 표시합니다."""
        opt = item.data(Qt.ItemDataRole.UserRole)
        self._selected_payload = {"swap_partner_entry_id": opt.get("swap_partner_entry_id")}
        self._update_summary(
            f"슬롯 교환: {opt.get('label', '')} — 양쪽 교사 동의 후 관리자 결재가 진행됩니다."
        )

    def _clear_other_selections(self, source: QListWidget):
        """하나의 리스트에서 선택하면 다른 리스트의 선택을 해제합니다."""
        for widget in (self.list_subjects, self.list_teachers, self.list_rooms, self.list_swaps):
            if widget is not source:
                widget.clearSelection()

    def _update_summary(self, text: str):
        """선택 요약 라벨을 갱신하고 제출 버튼을 활성화합니다."""
        self.lbl_summary.setText(text)
        self.btn_submit.setEnabled(True)

    def _submit(self):
        """선택한 제안과 사유를 담아 변경 신청을 제출합니다."""
        if not self._selected_payload:
            QMessageBox.warning(self, "입력 오류", "제안 목록에서 하나를 선택하세요.")
            return
        reason = self.edit_reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "입력 오류", "변경 사유를 입력하세요.")
            return

        body = {
            "timetable_entry_id": self._entry_id,
            "reason": reason,
            **self._selected_payload,
        }
        self.btn_submit.setEnabled(False)
        self.btn_submit.setText("제출 중...")

        self._worker = _SubmitRequestWorker(self._client, body)
        self._worker.done.connect(self._on_submitted)
        self._worker.error.connect(self._on_submit_error)
        self._worker.start()

    def _on_submitted(self, result: dict):
        """신청 성공 시 사용자에게 안내하고 다이얼로그를 닫습니다."""
        consent_status = result.get("consent_status", "not_required")
        if consent_status == "pending":
            QMessageBox.information(
                self,
                "신청 접수 완료",
                "변경 신청이 접수되었습니다.\n"
                "피교사의 동의와 관리자 결재를 순차적으로 거친 후 반영됩니다.",
            )
        else:
            QMessageBox.information(
                self,
                "신청 접수 완료",
                "변경 신청이 접수되었습니다.\n관리자 결재 후 반영됩니다.",
            )
        self.accept()

    def _on_submit_error(self, message: str):
        """신청 실패 시 버튼을 복원하고 오류를 표시합니다."""
        self.btn_submit.setEnabled(True)
        self.btn_submit.setText("신청 제출")
        QMessageBox.critical(self, "신청 실패", message)
