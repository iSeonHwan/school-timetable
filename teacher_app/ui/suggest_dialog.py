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

2026-06-20 변경 (연쇄 교체 지원):
  - 교환 탭이 3개 서브모드로 확장되었습니다:
    1) 직접 교환: 기존 1:1 swap 제안 목록 (1단계)
    2) 경로 탐색: source 슬롯과 target 슬롯을 지정하면 서버가
       GET /timetable/swap-paths 로 연쇄 교체 경로들을 자동 탐색해 표시.
       각 경로는 단계별로 시각화("1단계: 월3 수학(김) ↔ 화2 영어(이)" 식).
    3) 수동 구성: 사용자가 단계를 직접 추가/편집.
  - 신청 시 선택한 경로/단계 정보를 steps 배열로 서버에 전달.
  - 서버는 각 단계의 관련 교사들에게 한 번에 동의 요청 알림 전송.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTabWidget, QWidget,
    QListWidget, QListWidgetItem, QMessageBox,
    QGroupBox, QTextEdit, QComboBox, QRadioButton, QButtonGroup,
    QScrollArea, QFrame, QSpinBox,
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


class _LoadSwapPathsWorker(QThread):
    """서버에서 연쇄 교체 경로를 비동기로 조회하는 워커 (2026-06-20 신규)."""
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client: ApiClient, source_entry_id: int, target_entry_id: int):
        super().__init__()
        self._client = client
        self._source_entry_id = source_entry_id
        self._target_entry_id = target_entry_id

    def run(self):
        try:
            data = self._client.get(
                "/timetable/swap-paths",
                source_entry_id=self._source_entry_id,
                target_entry_id=self._target_entry_id,
            )
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
                           단일 제안 선택 시 new_subject_id 등 단일 필드.
                           연쇄 교체 선택 시 steps 리스트.
        _all_entries     : 전체 시간표 슬롯 (경로 탐색 target 선택 콤보용)
        _manual_steps    : 수동 구성 모드에서 추가된 단계 목록
    """

    def __init__(self, client: ApiClient, entry_id: int, parent=None):
        super().__init__(parent)
        self._client = client
        self._entry_id = entry_id
        self._current: dict | None = None
        self._selected_payload: dict | None = None
        self._all_entries: list[dict] = []
        self._manual_steps: list[dict] = []  # 수동 구성 단계들
        self._paths_worker = None
        self.setWindowTitle("시간표 교체 제안")
        self.resize(620, 640)
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

        # ── 교환 탭 — 3개 서브모드 (직접/경로 탐색/수동 구성) ──────────────
        self.tab_swap = QWidget()
        swap_layout = QVBoxLayout(self.tab_swap)
        swap_layout.setContentsMargins(8, 8, 8, 8)
        swap_layout.setSpacing(8)

        # 서브모드 라디오 버튼 (직접 교환 / 경로 탐색 / 수동 구성)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("모드:"))
        self.rb_direct = QRadioButton("직접 교환 (1:1)")
        self.rb_paths = QRadioButton("경로 탐색 (연쇄)")
        self.rb_manual = QRadioButton("수동 구성")
        self.rb_direct.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.rb_direct, 0)
        self._mode_group.addButton(self.rb_paths, 1)
        self._mode_group.addButton(self.rb_manual, 2)
        self._mode_group.idClicked.connect(self._on_swap_mode_changed)
        mode_row.addWidget(self.rb_direct)
        mode_row.addWidget(self.rb_paths)
        mode_row.addWidget(self.rb_manual)
        mode_row.addStretch()
        swap_layout.addLayout(mode_row)

        # 스택 컨테이너 — 모드별 위젯을 담는 QFrame
        self.swap_container = QFrame()
        self.swap_container_layout = QVBoxLayout(self.swap_container)
        self.swap_container_layout.setContentsMargins(0, 0, 0, 0)
        self.swap_container_layout.setSpacing(6)
        swap_layout.addWidget(self.swap_container, stretch=1)

        # ── 모드 0: 직접 교환 — 기존 1:1 swap 목록 ──────────────────────
        self.direct_box = QGroupBox("교환 가능한 슬롯 (양쪽 교사 동의 필요)")
        direct_layout = QVBoxLayout(self.direct_box)
        self.list_swaps = QListWidget()
        self.list_swaps.itemClicked.connect(self._on_swap_selected)
        direct_layout.addWidget(self.list_swaps)
        self.swap_container_layout.addWidget(self.direct_box)

        # ── 모드 1: 경로 탐색 — source/target 선택 + 경로 카드 목록 ───────
        self.paths_box = QGroupBox("연쇄 교체 경로 탐색")
        paths_layout = QVBoxLayout(self.paths_box)

        # target 선택 행 — source 는 현재 슬롯으로 고정
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("목적지 슬롯:"))
        self.cb_target = QComboBox()
        self.cb_target.setMinimumWidth(280)
        target_row.addWidget(self.cb_target, stretch=1)
        self.btn_find_paths = QPushButton("경로 찾기")
        self.btn_find_paths.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:3px; padding:4px 12px;"
        )
        self.btn_find_paths.clicked.connect(self._find_paths)
        target_row.addWidget(self.btn_find_paths)
        paths_layout.addLayout(target_row)

        paths_layout.addWidget(QLabel("검색된 경로 (각 경로의 단계와 관련 교사가 표시됩니다):"))
        # 경로 목록을 스크롤 영역에 담음 — 경로가 길어질 수 있어 스크롤 지원
        self.list_paths = QListWidget()
        paths_layout.addWidget(self.list_paths, stretch=1)
        self.lbl_paths_note = QLabel("")
        self.lbl_paths_note.setWordWrap(True)
        self.lbl_paths_note.setStyleSheet("color:#7F8C8D; font-size:11px;")
        paths_layout.addWidget(self.lbl_paths_note)
        self.swap_container_layout.addWidget(self.paths_box)

        # ── 모드 2: 수동 구성 — 단계 추가/삭제 ──────────────────────────
        self.manual_box = QGroupBox("수동 단계 구성")
        manual_layout = QVBoxLayout(self.manual_box)

        manual_layout.addWidget(QLabel("각 단계에서 교환할 source/target 슬롯을 선택해 추가하세요."))
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("source 슬롯:"))
        self.cb_manual_source = QComboBox()
        self.cb_manual_source.setMinimumWidth(200)
        add_row.addWidget(self.cb_manual_source, stretch=1)
        add_row.addWidget(QLabel("target 슬롯:"))
        self.cb_manual_target = QComboBox()
        self.cb_manual_target.setMinimumWidth(200)
        add_row.addWidget(self.cb_manual_target, stretch=1)
        self.btn_add_step = QPushButton("단계 추가")
        self.btn_add_step.setStyleSheet(
            "background:#27AE60; color:white; border-radius:3px; padding:4px 12px;"
        )
        self.btn_add_step.clicked.connect(self._add_manual_step)
        add_row.addWidget(self.btn_add_step)
        manual_layout.addLayout(add_row)

        # 추가된 단계 표시
        self.list_manual_steps = QListWidget()
        manual_layout.addWidget(self.list_manual_steps, stretch=1)
        del_row = QHBoxLayout()
        self.btn_del_step = QPushButton("선택 단계 삭제")
        self.btn_del_step.setStyleSheet(
            "background:#E74C3C; color:white; border-radius:3px; padding:4px 12px;"
        )
        self.btn_del_step.clicked.connect(self._del_manual_step)
        del_row.addWidget(self.btn_del_step)
        del_row.addStretch()
        manual_layout.addLayout(del_row)
        self.swap_container_layout.addWidget(self.manual_box)

        self.tabs.addTab(self.tab_swap, "교환 제안")
        layout.addWidget(self.tabs, stretch=1)

        # 초기 모드 표시 — 직접 교환
        self._show_swap_mode(0)

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

    def _show_swap_mode(self, mode: int):
        """선택한 서브모드에 따라 해당 위젯만 표시하고 나머지는 숨김."""
        self.direct_box.setVisible(mode == 0)
        self.paths_box.setVisible(mode == 1)
        self.manual_box.setVisible(mode == 2)
        # 모드 전환 시 기존 선택 초기화
        self.list_swaps.clearSelection()
        self.list_paths.clearSelection()
        self._manual_steps.clear()
        self.list_manual_steps.clear()
        self._selected_payload = None
        self.lbl_summary.setText("위 제안 목록에서 하나를 선택하세요.")
        self.btn_submit.setEnabled(False)

    def _on_swap_mode_changed(self, mode_id: int):
        """서브모드 라디오 버튼 변경 시 호출."""
        self._show_swap_mode(mode_id)

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

        # ── 전체 시간표 슬롯 로드 (경로 탐색 target 콤보용) ────────────────
        # 본인 담당 슬롯이 아닌 모든 슬롯을 target 후보로 표시.
        # source 는 현재 슬롯(self._entry_id)으로 고정.
        self._load_all_entries_for_target_combo()

    def _load_all_entries_for_target_combo(self):
        """현재 학기의 모든 시간표 슬롯을 target 콤보박스에 채웁니다."""
        try:
            terms = self._client.get("/timetable/terms")
            current = next((t for t in terms if t.get("is_current")), None)
            if not current and terms:
                current = terms[0]
            if not current:
                return
            self._all_entries = self._client.get(
                "/timetable/entries", term_id=current["id"]
            )
            day_names = {1: "월", 2: "화", 3: "수", 4: "목", 5: "금"}
            self.cb_target.clear()
            self.cb_manual_source.clear()
            self.cb_manual_target.clear()
            for e in self._all_entries:
                # 현재 슬롯은 target 에서 제외
                if e["id"] == self._entry_id:
                    continue
                day = day_names.get(e["day_of_week"], "?")
                label = (
                    f"{day}요일 {e['period']}교시 — "
                    f"{e.get('subject_name', '?')} "
                    f"({e.get('teacher_name', '')}) "
                    f"[{e.get('school_class_name', '') or ''}]"
                )
                self.cb_target.addItem(label, e["id"])
                self.cb_manual_target.addItem(label, e["id"])
            # 수동 구성 source 는 현재 슬롯이 기본이지만 다른 슬롯도 가능
            self.cb_manual_source.addItem("(현재 슬롯)", self._entry_id)
            for e in self._all_entries:
                if e["id"] == self._entry_id:
                    continue
                day = day_names.get(e["day_of_week"], "?")
                label = (
                    f"{day}요일 {e['period']}교시 — "
                    f"{e.get('subject_name', '?')} "
                    f"({e.get('teacher_name', '')})"
                )
                self.cb_manual_source.addItem(label, e["id"])
        except Exception as e:
            QMessageBox.warning(self, "슬롯 목록 조회 오류", str(e))

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
        """대체 과목을 선택하면 교사/교실/교환 선택을 초기화하고 과목 ID만 저장합니다."""
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
        """직접 교환 모드에서 교환 상대 슬롯을 선택합니다."""
        opt = item.data(Qt.ItemDataRole.UserRole)
        self._selected_payload = {"swap_partner_entry_id": opt.get("swap_partner_entry_id")}
        self._update_summary(
            f"슬롯 교환: {opt.get('label', '')} — 양쪽 교사 동의 후 관리자 결재가 진행됩니다."
        )

    # ── 경로 탐색 모드 ──────────────────────────────────────────────────

    def _find_paths(self):
        """source(현재 슬롯)에서 target 으로 가는 연쇄 교체 경로를 서버에 조회합니다."""
        target_id = self.cb_target.currentData()
        if target_id is None:
            QMessageBox.warning(self, "선택 오류", "목적지 슬롯을 선택하세요.")
            return

        self.list_paths.clear()
        self.lbl_paths_note.setText("경로 탐색 중...")
        self.btn_find_paths.setEnabled(False)
        self.btn_find_paths.setText("탐색 중...")

        self._paths_worker = _LoadSwapPathsWorker(
            self._client, self._entry_id, target_id
        )
        self._paths_worker.done.connect(self._on_paths_loaded)
        self._paths_worker.error.connect(self._on_paths_error)
        self._paths_worker.start()

    def _on_paths_loaded(self, data: dict):
        """서버에서 받은 경로 목록을 UI에 표시합니다."""
        self.btn_find_paths.setEnabled(True)
        self.btn_find_paths.setText("경로 찾기")
        paths = data.get("paths", [])
        note = data.get("note", "")
        self.list_paths.clear()

        if not paths:
            self.lbl_paths_note.setText(
                note or "탐색된 경로가 없습니다. 수동 구성 모드를 이용해 보세요."
            )
            return

        self.lbl_paths_note.setText(note)

        for path in paths:
            # 각 경로를 카드 형태로 표시 — 단계별 라벨을 줄바꿈으로 묶음
            step_lines = []
            for s in path.get("steps", []):
                step_lines.append(f"  {s.get('step_order')}. {s.get('label', '')}")
            related_count = len(path.get("related_teacher_ids", []))
            text = (
                f"{path.get('summary', '')}\n"
                + "\n".join(step_lines)
                + f"\n  → 관련 교사 {related_count}명 동의 필요"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, path)
            # 항목 높이를 내용에 맞춰 확보
            item.setSizeHint(item.sizeHint())
            self.list_paths.addItem(item)

        self.list_paths.itemClicked.connect(self._on_path_selected)

    def _on_paths_error(self, message: str):
        """경로 탐색 실패 시 처리."""
        self.btn_find_paths.setEnabled(True)
        self.btn_find_paths.setText("경로 찾기")
        self.lbl_paths_note.setText("")
        QMessageBox.critical(self, "경로 탐색 실패", message)

    def _on_path_selected(self, item: QListWidgetItem):
        """경로 카드를 선택하면 steps 배열을 payload 로 저장."""
        path = item.data(Qt.ItemDataRole.UserRole)
        steps = path.get("steps", [])
        # 서버에 보낼 steps 형태로 변환 — step_type="swap", source/target
        steps_payload = []
        for s in steps:
            steps_payload.append({
                "step_type": "swap",
                "source_entry_id": s.get("source_entry_id"),
                "target_entry_id": s.get("target_entry_id"),
            })
        self._selected_payload = {"steps": steps_payload}
        summary_lines = [f"연쇄 교체 — {path.get('summary', '')}"]
        for s in steps:
            summary_lines.append(f"  {s.get('step_order')}. {s.get('label', '')}")
        related_count = len(path.get("related_teacher_ids", []))
        summary_lines.append(f"  → 관련 교사 {related_count}명에게 동의 요청 발송")
        self._update_summary("\n".join(summary_lines))

    # ── 수동 구성 모드 ──────────────────────────────────────────────────

    def _add_manual_step(self):
        """수동 구성 모드에서 단계를 추가합니다."""
        source_id = self.cb_manual_source.currentData()
        target_id = self.cb_manual_target.currentData()
        if source_id is None or target_id is None:
            QMessageBox.warning(self, "선택 오류", "source 와 target 슬롯을 모두 선택하세요.")
            return
        if source_id == target_id:
            QMessageBox.warning(self, "선택 오류", "source 와 target 은 달라야 합니다.")
            return
        # 이미 같은 슬롯이 참여한 단계가 있는지 중복 검사
        used_slots = set()
        for s in self._manual_steps:
            used_slots.add(s["source_entry_id"])
            used_slots.add(s["target_entry_id"])
        if source_id in used_slots or target_id in used_slots:
            QMessageBox.warning(
                self, "중복 슬롯",
                "이미 다른 단계에 참여한 슬롯입니다. 한 슬롯은 한 단계에만 참여할 수 있습니다."
            )
            return

        # 콤보 라벨에서 사용자 표시용 라벨 추출
        source_label = self.cb_manual_source.currentText()
        target_label = self.cb_manual_target.currentText()
        step = {
            "step_type": "swap",
            "source_entry_id": source_id,
            "target_entry_id": target_id,
            "source_label": source_label,
            "target_label": target_label,
        }
        self._manual_steps.append(step)
        self._refresh_manual_steps_list()

    def _del_manual_step(self):
        """선택한 수동 단계를 삭제합니다."""
        row = self.list_manual_steps.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "삭제할 단계를 선택하세요.")
            return
        del self._manual_steps[row]
        self._refresh_manual_steps_list()

    def _refresh_manual_steps_list(self):
        """수동 단계 목록을 다시 그립니다."""
        self.list_manual_steps.clear()
        for i, s in enumerate(self._manual_steps, start=1):
            text = (
                f"{i}단계: {s['source_label']}\n"
                f"      ↔ {s['target_label']}"
            )
            self.list_manual_steps.addItem(text)
        if self._manual_steps:
            # payload 갱신
            steps_payload = [
                {
                    "step_type": s["step_type"],
                    "source_entry_id": s["source_entry_id"],
                    "target_entry_id": s["target_entry_id"],
                }
                for s in self._manual_steps
            ]
            self._selected_payload = {"steps": steps_payload}
            lines = [f"수동 구성 — {len(self._manual_steps)}단계 연쇄 교체"]
            for i, s in enumerate(self._manual_steps, start=1):
                lines.append(f"  {i}. {s['source_label']} ↔ {s['target_label']}")
            lines.append(f"  → 관련 교사에게 동의 요청 발송")
            self._update_summary("\n".join(lines))
        else:
            self._selected_payload = None
            self.lbl_summary.setText("위 제안 목록에서 하나를 선택하세요.")
            self.btn_submit.setEnabled(False)

    def _clear_other_selections(self, source: QListWidget):
        """하나의 리스트에서 선택하면 다른 리스트의 선택을 해제합니다."""
        for widget in (self.list_subjects, self.list_teachers, self.list_rooms, self.list_swaps, self.list_paths):
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

        # 연쇄 교체 신청 시 최종 확인 다이얼로그 — 단계와 관련 교사 수 요약
        if "steps" in body and body["steps"]:
            step_count = len(body["steps"])
            ret = QMessageBox.question(
                self, "연쇄 교체 신청 확인",
                f"{step_count}단계 연쇄 교체를 신청합니다.\n"
                f"각 단계의 관련 교사들에게 동의 요청이 발송됩니다.\n"
                f"모든 교사가 동의해야 관리자 결재로 넘어갑니다.\n\n계속하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        self.btn_submit.setEnabled(False)
        self.btn_submit.setText("제출 중...")

        self._worker = _SubmitRequestWorker(self._client, body)
        self._worker.done.connect(self._on_submitted)
        self._worker.error.connect(self._on_submit_error)
        self._worker.start()

    def _on_submitted(self, result: dict):
        """신청 성공 시 사용자에게 안내하고 다이얼로그를 닫습니다."""
        consent_status = result.get("consent_status", "not_required")
        steps = result.get("steps", [])
        if steps:
            # 연쇄 교체 신청 — 다교사 동의 안내
            QMessageBox.information(
                self,
                "신청 접수 완료",
                f"{len(steps)}단계 연쇄 교체 신청이 접수되었습니다.\n"
                f"각 단계의 관련 교사들에게 동의 요청이 발송되었습니다.\n"
                f"모든 교사가 동의하면 일과계/교감 결재로 진행됩니다.",
            )
        elif consent_status == "pending":
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