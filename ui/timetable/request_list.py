"""
변경 신청 목록 및 승인/거절 화면 (동적 결재 워크플로우)

TimetableChangeRequest 레코드를 상태별로 필터링해 표시하고,
활성 ApprovalWorkflow 에 따라 승인·거절을 처리합니다.

이 파일은 Phase 5(동적 결재 UI)의 핵심으로, 하드코딩된 2단계 승인을
DB 기반 설정형 결재 워크플로우로 대체합니다.

아키텍처:
  - 서버 API 가 아닌 DB 직접 접근으로 승인·거절을 처리합니다.
    (다른 setup 페이지와 동일한 패턴 — admin_app 은 서버와 같은 머신에서
    직접 DB 에 연결하므로 API 왕복 없이 즉시 처리 가능)
  - refresh() 시점에 활성 ApprovalWorkflow 를 로드하여 self._workflow 에 저장하고,
    각 approve/reject 호출 시 이 워크플로우를 기준으로 역할 검증을 수행합니다.
  - 사용자 역할은 생성자 주입(self._role)으로 전달되며,
    AdminMainWindow 에서 client.role 값을 전달합니다.

동적 결재 흐름:
  1. 교사가 변경 신청 제출 → status = "pending", current_step = 1
  2. refresh() 시 활성 ApprovalWorkflow 로드 → self._total_steps 결정
  3. 사용자가 승인 버튼 클릭 → 현재 current_step 에 해당하는 ApprovalStep 조회
     → step.role_required 와 self._role 비교하여 권한 검증
     → 통과 시: approval_history JSON 배열에 기록 추가
       - 마지막 단계가 아니면 current_step += 1 (다음 단계로 진행)
       - 마지막 단계면 status = "approved", TimetableEntry 에 변경 적용 + 이력 기록

거절:
  - teacher 역할은 거절 불가 (승인자만 거절 권한 보유)
  - 현재 단계의 role_required 를 가진 사용자만 거절 가능
  - 거절 시 status = "rejected", approval_history 에 거절 기록 추가,
    TimetableEntry 는 변경되지 않음 (원상태 유지)

주의: 이 위젯은 서버 API 가 아닌 DB 직접 접근으로 동작하므로,
서버측 review_request 엔드포인트와 동일한 비즈니스 로직을
중복 구현하고 있습니다. 양쪽 로직을 변경할 때는 반드시 동기화하세요.
"""
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QBrush
from database.connection import get_session
from database.models import (
    TimetableChangeRequest, TimetableEntry, Teacher, Subject, Room,
    ApprovalWorkflow, ApprovalStep,
)
from core.change_logger import log_entry_update

DAYS_KR = ["월", "화", "수", "목", "금"]

# 역할 표시 매핑
ROLE_DISPLAY = {
    "admin": "일과계",
    "vice_principal": "교감",
    "department_head": "교무부장",
}


class ChangeRequestWidget(QWidget):
    """
    변경 신청 목록 조회 및 승인/거절 위젯.

    활성 ApprovalWorkflow 에 따라 동적으로 승인 단계를 결정합니다.
    role 파라미터는 현재 로그인한 사용자의 역할을 나타내며,
    각 단계의 role_required 와 일치할 때만 승인·거절이 가능합니다.
    """

    def __init__(self, parent=None, role: str = "admin"):
        super().__init__(parent)
        self._role = role
        self._workflow = None  # 활성 ApprovalWorkflow (refresh 시 로드)
        self._total_steps = 0
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("변경 신청 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 필터 바 ───────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setStyleSheet("background:#F0F4FA; border-radius:6px;")
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(12, 8, 12, 8)

        fb.addWidget(QLabel("상태:"))
        self.cb_status = QComboBox()
        self.cb_status.addItem("전체", None)
        self.cb_status.addItem("대기 중", "pending")
        self.cb_status.addItem("승인 완료", "approved")
        self.cb_status.addItem("거절", "rejected")
        fb.addWidget(self.cb_status)

        fb.addStretch()
        btn_refresh = QPushButton("새로고침")
        btn_refresh.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; padding:6px 18px; font-weight:bold;"
        )
        btn_refresh.clicked.connect(self.refresh)
        fb.addWidget(btn_refresh)

        layout.addWidget(filter_bar)

        # ── 신청 목록 테이블 ──────────────────────────────────────────
        # 컬럼: ID, 학반, 요일, 교시, 현재 과목/교사, 변경 과목/교사,
        #       사유, 상태, 결재 이력, 신청일
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "ID", "학반", "요일", "교시", "현재 과목/교사",
            "변경 과목/교사", "사유", "상태", "결재 이력", "신청일",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #1B4F8A; color: white;
                font-weight: bold; padding: 4px;
            }
        """)
        layout.addWidget(self.table)

        # ── 승인/거절 버튼 ────────────────────────────────────────────
        btn_layout = QHBoxLayout()

        self.btn_approve = QPushButton("승인")
        self.btn_approve.setStyleSheet(
            "background:#27AE60; color:white; border-radius:4px; "
            "padding:8px 20px; font-weight:bold;"
        )
        self.btn_approve.clicked.connect(self._approve)
        btn_layout.addWidget(self.btn_approve)

        self.btn_reject = QPushButton("거절")
        self.btn_reject.setStyleSheet(
            "background:#E74C3C; color:white; border-radius:4px; "
            "padding:8px 20px; font-weight:bold;"
        )
        self.btn_reject.clicked.connect(self._reject)
        btn_layout.addWidget(self.btn_reject)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def refresh(self):
        """DB 에서 변경 신청 목록과 활성 워크플로우를 읽어 테이블을 갱신합니다."""
        session = get_session()
        try:
            # 활성 워크플로우 로드
            self._workflow = session.query(ApprovalWorkflow).filter_by(is_active=True).first()
            if self._workflow:
                # steps relationship 을 미리 로드
                _ = self._workflow.steps
                self._total_steps = len(self._workflow.steps)
            else:
                self._total_steps = 0

            status_filter = self.cb_status.currentData()
            query = session.query(TimetableChangeRequest).order_by(
                TimetableChangeRequest.requested_at.desc()
            )
            if status_filter:
                query = query.filter_by(status=status_filter)

            requests = query.all()
            self.table.setRowCount(len(requests))

            for row, req in enumerate(requests):
                entry = req.timetable_entry
                school_class = entry.school_class if entry else None

                self.table.setItem(row, 0, self._item(str(req.id)))
                self.table.setItem(row, 1, self._item(
                    school_class.display_name if school_class else ""
                ))
                self.table.setItem(row, 2, self._item(
                    DAYS_KR[entry.day_of_week - 1] if entry else ""
                ))
                self.table.setItem(row, 3, self._item(
                    str(entry.period) if entry else ""
                ))

                # 현재 과목/교사 정보
                current_info = ""
                if entry:
                    subj = session.get(Subject, entry.subject_id)
                    tchr = session.get(Teacher, entry.teacher_id)
                    current_info = (
                        f"{subj.short_name if subj else ''} / "
                        f"{tchr.name if tchr else ''}"
                    )

                # 변경 요청된 과목/교사 정보
                new_info_parts = []
                if req.new_subject_id:
                    ns = session.get(Subject, req.new_subject_id)
                    if ns:
                        new_info_parts.append(ns.short_name)
                if req.new_teacher_id:
                    nt = session.get(Teacher, req.new_teacher_id)
                    if nt:
                        new_info_parts.append(nt.name)
                new_info = " / ".join(new_info_parts) if new_info_parts else current_info

                self.table.setItem(row, 4, self._item(current_info))
                self.table.setItem(row, 5, self._item(new_info))
                self.table.setItem(row, 6, self._item(req.reason[:50]))

                # 상태 표시 — 진행 단계 포함
                status_text = self._format_status(req)
                self.table.setItem(row, 7, self._item(status_text))

                # 결재 이력 — approval_history JSON 파싱
                self.table.setItem(row, 8, self._item(self._format_history(req)))

                # 신청일
                self.table.setItem(row, 9, self._item(
                    req.requested_at.strftime("%Y-%m-%d %H:%M")
                    if req.requested_at else ""
                ))

                # ── 상태별 색상 표시 ────────────────────────────────────
                status_item = self.table.item(row, 7)
                if req.status == "pending":
                    status_item.setBackground(QBrush(QColor("#F39C12")))
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "approved":
                    status_item.setBackground(QBrush(QColor("#27AE60")))
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "rejected":
                    status_item.setBackground(QBrush(QColor("#E74C3C")))
                    status_item.setForeground(QBrush(QColor("white")))
        finally:
            session.close()

    def _format_status(self, req: TimetableChangeRequest) -> str:
        """
        상태 문자열을 생성합니다.

        pending 상태일 때는 현재 결재 진행 상황을 표시합니다:
          예) "대기 중 (1/3단계)" — 3단계 중 1단계 대기 중
          예) "대기 중 (3/3단계)" — 마지막 단계 승인만 남음

        approved/rejected 는 최종 상태이므로 단계 정보 없이 표시합니다.
        """
        if req.status == "pending":
            total = self._total_steps or 1
            return f"대기 중 ({req.current_step}/{total}단계)"
        if req.status == "approved":
            return "승인 완료"
        if req.status == "rejected":
            return "거절"
        return req.status

    def _format_history(self, req: TimetableChangeRequest) -> str:
        """
        approval_history JSON 을 사람이 읽을 수 있는 여러 줄 문자열로 변환합니다.

        JSON 구조:
          [{"step": 1, "role": "admin", "action": "approve", "by": "일과계", "at": "2024-03-15T14:30:00"}]

        출력 예:
          1단계 승인 (일과계, 03/15 14:30)
          2단계 승인 (교감, 03/15 15:00)

        JSON 파싱 오류 시 빈 문자열을 반환하여 UI 가 깨지지 않도록 합니다.
        """
        try:
            history = json.loads(req.approval_history or "[]")
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
                    at_str = str(h["at"])[:16]
            lines.append(f"{step}단계 {action_text} ({role_label}{', ' + at_str if at_str else ''})")

        return "\n".join(lines)

    def _item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _get_selected_request_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "처리할 신청을 선택해 주세요.")
            return None
        return int(self.table.item(row, 0).text())

    def _get_step_at(self, step_number: int):
        """워크플로우에서 지정된 단계의 ApprovalStep 을 반환합니다."""
        if not self._workflow:
            return None
        for step in self._workflow.steps:
            if step.step_order == step_number:
                return step
        return None

    def _append_history(self, req: TimetableChangeRequest, step_num: int,
                        action: str):
        """
        approval_history JSON 배열에 새 승인/거절 항목을 추가합니다.

        각 항목은 다음 필드를 포함합니다:
          - step: 결재 단계 번호 (1-based, current_step 과 동일)
          - role: 승인/거절자의 role 값 (admin / vice_principal / department_head)
          - action: "approve" 또는 "reject"
          - by: 승인/거절자 표시 이름 (ROLE_DISPLAY 한글명)
          - at: ISO 8601 형식의 처리 시각 (datetime.now().isoformat())

        ensure_ascii=False 로 저장하여 한글 role 이름이 유니코드로 정상 보존됩니다.
        """
        try:
            history = json.loads(req.approval_history or "[]")
        except (json.JSONDecodeError, TypeError):
            history = []

        role_label = ROLE_DISPLAY.get(self._role, self._role)
        history.append({
            "step": step_num,
            "role": self._role,
            "action": action,
            "by": role_label,
            "at": datetime.now().isoformat(),
        })
        req.approval_history = json.dumps(history, ensure_ascii=False)

    def _approve(self):
        """
        선택된 신청을 승인합니다.

        동적 워크플로우에 따른 승인 처리 절차:
          1. 신청의 current_step 에 해당하는 ApprovalStep 을 워크플로우에서 조회
          2. step.role_required 와 현재 사용자 역할(self._role) 비교 → 불일치 시 차단
          3. approval_history JSON 배열에 {step, role, action, by, at} 기록 추가
          4. 분기:
             - 마지막 단계가 아니면: current_step += 1 (다음 승인자에게 전달)
             - 마지막 단계이면: status = "approved" + TimetableEntry 변경 확정 + 변경 이력 기록

        역할 검증 실패 시 다른 역할의 사용자가 승인을 시도하는 것을 차단합니다.
        이는 서버측 review_request 엔드포인트와 동일한 검증 로직입니다.
        """
        session = get_session()
        try:
            req_id = self._get_selected_request_id()
            if req_id is None:
                return

            req = session.get(TimetableChangeRequest, req_id)
            if req is None:
                QMessageBox.warning(self, "오류", "해당 신청을 찾을 수 없습니다.")
                return

            # 이미 최종 처리된 신청은 승인 불가 (이중 승인 방지)
            if req.status == "approved":
                QMessageBox.warning(self, "오류", "이미 최종 승인된 신청입니다.")
                return
            if req.status == "rejected":
                QMessageBox.warning(self, "오류", "이미 거절된 신청입니다.")
                return

            # 활성 워크플로우가 없으면 결재 진행 불가능
            # (서버 시작 시 기본 워크플로우가 자동 생성되므로 정상 상황에서는 발생하지 않음)
            if not self._workflow:
                QMessageBox.warning(self, "오류",
                                    "활성화된 결재 워크플로우가 없습니다.\n"
                                    "관리자에게 문의하여 결재 라인을 설정해 주세요.")
                return

            # ── 현재 단계 확인 및 역할 검증 ─────────────────────────────
            # current_step 은 1-based: 1 = 첫 번째 단계, 2 = 두 번째 단계, ...
            current_step = req.current_step
            step_def = self._get_step_at(current_step)
            if step_def is None:
                QMessageBox.warning(self, "오류",
                                    f"워크플로우에 {current_step}단계가 정의되어 있지 않습니다.")
                return

            # 역할 기반 접근 제어: 현재 단계에 지정된 role_required 와
            # 로그인한 사용자의 role 이 일치해야만 승인 가능
            if self._role != step_def.role_required:
                role_display = ROLE_DISPLAY.get(step_def.role_required, step_def.role_required)
                QMessageBox.warning(self, "권한 없음",
                                    f"현재 {current_step}단계는 {role_display} 선생님만 승인할 수 있습니다.")
                return

            # ── 승인 기록을 approval_history JSON 배열에 추가 ─────────────
            # 각 항목은 {step, role, action, by, at} 형식으로 저장되어 감사 추적 가능
            self._append_history(req, current_step, "approve")

            if current_step < self._total_steps:
                # ── 중간 단계 승인: 다음 단계로 진행 ────────────────────
                # TimetableEntry 는 아직 변경하지 않고, current_step 만 증가시켜
                # 다음 role 의 승인자에게 승인 권한을 넘깁니다.
                req.current_step = current_step + 1
                session.commit()
                next_step = self._get_step_at(current_step + 1)
                next_role = ROLE_DISPLAY.get(
                    next_step.role_required, next_step.role_required
                ) if next_step else "?"
                QMessageBox.information(
                    self, "승인 완료",
                    f"{current_step}단계 승인이 완료되었습니다.\n"
                    f"다음 단계: {next_role} 선생님의 승인이 필요합니다.",
                )
            else:
                # ── 마지막 단계 승인: 시간표에 변경 확정 적용 ────────────
                # 모든 결재 단계를 통과했으므로 변경 내용을 TimetableEntry 에
                # 실제로 반영하고, 변경 이력(TimetableChangeLog)을 기록합니다.
                entry = session.get(TimetableEntry, req.timetable_entry_id)
                if entry is None:
                    QMessageBox.warning(self, "오류", "해당 시간표 항목이 존재하지 않습니다.")
                    return

                # 변경 전 상태를 스냅샷으로 저장 (감사 추적용)
                old_data = {
                    "day":        entry.day_of_week,
                    "period":     entry.period,
                    "subject_id": entry.subject_id,
                    "teacher_id": entry.teacher_id,
                    "room_id":    entry.room_id,
                }

                # 요청된 값이 있으면 반영, null 이면 기존 값 유지
                entry.subject_id = req.new_subject_id or entry.subject_id
                entry.teacher_id = req.new_teacher_id or entry.teacher_id
                entry.room_id    = req.new_room_id or entry.room_id

                # 변경 이력 자동 기록 (감사 추적)
                log_entry_update(session, entry, old_data)

                req.status = "approved"
                role_label = ROLE_DISPLAY.get(self._role, self._role)
                req.approved_by = role_label
                req.approved_at = datetime.now()

                session.commit()
                QMessageBox.information(
                    self, "최종 승인 완료",
                    "변경이 최종 승인되어 시간표에 반영되었습니다.",
                )

            self.refresh()
        finally:
            session.close()

    def _reject(self):
        """
        선택된 신청을 거절합니다.

        거절 권한 검증:
          - teacher 역할은 거절 불가 (승인 권한이 있는 역할만 거절 가능)
          - 현재 단계의 role_required 와 일치하는 사용자만 거절 가능
            (다른 역할의 사용자가 임의로 거절하는 것을 방지)

        거절 시:
          - status = "rejected" 로 변경
          - approval_history 에 거절 기록 추가 (action: "reject")
          - TimetableEntry 는 변경되지 않음 (원상태 유지)
        """
        session = get_session()
        try:
            req_id = self._get_selected_request_id()
            if req_id is None:
                return

            req = session.get(TimetableChangeRequest, req_id)
            if req is None:
                QMessageBox.warning(self, "오류", "해당 신청을 찾을 수 없습니다.")
                return

            # 이미 최종 처리된 신청은 거절 불가 (이중 처리 방지)
            if req.status in ("approved", "rejected"):
                QMessageBox.warning(self, "오류", "이미 최종 처리 완료된 신청입니다.")
                return

            if not self._workflow:
                QMessageBox.warning(self, "오류",
                                    "활성화된 결재 워크플로우가 없습니다.")
                return

            # 교사(teacher)는 승인 권한이 없으므로 거절 권한도 없음
            # 승인자(admin, vice_principal, department_head)만 거절 가능
            if self._role == "teacher":
                QMessageBox.warning(self, "권한 없음", "교사는 변경 신청을 거절할 수 없습니다.")
                return

            # 현재 단계의 role_required 와 사용자 role 비교
            # 예: 2단계가 "vice_principal" 이면 교감만 거절 가능, 일과계는 거절 불가
            current_step = req.current_step
            step_def = self._get_step_at(current_step)
            if step_def and self._role != step_def.role_required:
                role_display = ROLE_DISPLAY.get(step_def.role_required, step_def.role_required)
                QMessageBox.warning(self, "권한 없음",
                                    f"현재 {current_step}단계는 {role_display} 선생님만 거절할 수 있습니다.")
                return

            # 거절 기록을 approval_history 에 추가 (감사 추적)
            self._append_history(req, current_step, "reject")

            req.status = "rejected"
            role_label = ROLE_DISPLAY.get(self._role, self._role)
            req.approved_by = role_label
            req.approved_at = datetime.now()

            session.commit()
            QMessageBox.information(self, "거절 완료", "변경 신청이 거절되었습니다.")
            self.refresh()
        finally:
            session.close()
