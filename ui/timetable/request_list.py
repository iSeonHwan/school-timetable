"""
변경 신청 목록 및 승인/거절 화면 (동적 결재 워크플로우 + 연쇄 교체 지원)

TimetableChangeRequest 레코드를 상태별로 필터링해 표시하고,
활성 ApprovalWorkflow 에 따라 승인·거절을 처리합니다.

이 파일은 Phase 5(동적 결재 UI)의 핵심으로, 하드코딩된 2단계 승인을
DB 기반 설정형 결재 워크플로우로 대체합니다.

2026-06-20 변경 (연쇄 교체 지원):
  - 신청 1건이 여러 단계(step)로 구성된 연쇄 교체 신청을 부모-자식 구조로 표시.
  - 메인 테이블: 부모 행(요약 — "연쇄 3단계, 2/3 동의")
  - 상세 패널: 선택된 신청의 단계별 시각화
    ("1단계: 월3 수학(김) ↔ 화2 영어(이) — 김선생님 동의 완료 03/15 14:30")
  - 승인 처리: 연쇄 교체는 모든 단계의 동의가 완료된 후 결재 라인 1회 통과 시
    시간표에 일괄 반영(원자성 보장 — 전체 단계를 한 트랜잭션으로 묶어 적용).

아키텍처:
  - 서버 API 가 아닌 DB 직접 접근으로 승인·거절을 처리합니다.
    (다른 setup 페이지와 동일한 패턴 — admin_app 은 서버와 같은 머신에서
    직접 DB 에 연결하므로 API 왕복 없이 즉시 처리 가능)
  - refresh() 시점에 활성 ApprovalWorkflow 를 로드하여 self._workflow 에 저장하고,
    각 approve/reject 호출 시 이 워크플로우를 기준으로 역할 검증을 수행합니다.
  - 사용자 역할은 생성자 주입(self._role)으로 전달되며,
    AdminMainWindow 에서 client.role 값을 전달합니다.

동적 결재 흐름:
  1. 교사가 변경 신청 제출 → status = "pending", current_step = 0 (동의 대기)
  2. 모든 단계 동의 완료 → current_step = 1 (결재 1단계 진입)
  3. refresh() 시 활성 ApprovalWorkflow 로드 → self._total_steps 결정
  4. 사용자가 승인 버튼 클릭 → 현재 current_step 에 해당하는 ApprovalStep 조회
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
    QGroupBox, QTextEdit,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QBrush
from database.connection import get_session
from database.models import (
    TimetableChangeRequest, TimetableEntry, Teacher, Subject, Room,
    ApprovalWorkflow, ApprovalStep, ChangeRequestStep, User,
)
from core.change_logger import log_entry_update

DAYS_KR = ["월", "화", "수", "목", "금"]

# 역할 표시 매핑
ROLE_DISPLAY = {
    "admin": "일과계",
    "vice_principal": "교감",
    "department_head": "교무부장",
}

# 단계 동의 상태 한글 라벨
CONSENT_LABELS = {
    "not_required": "동의 불필요",
    "pending":      "동의 대기",
    "approved":     "동의 완료",
    "rejected":     "동의 거절",
}


class ChangeRequestWidget(QWidget):
    """
    변경 신청 목록 조회 및 승인/거절 위젯.

    활성 ApprovalWorkflow 에 따라 동적으로 승인 단계를 결정합니다.
    role 파라미터는 현재 로그인한 사용자의 역할을 나타내며,
    각 단계의 role_required 와 일치할 때만 승인·거절이 가능합니다.

    2026-06-20: 연쇄 교체(chain swap) 지원
      - req.steps 가 비어 있지 않은 신청은 연쇄 교체로 취급.
      - 부모 행에 요약 표시 + 하단 상세 패널에 단계별 시각화.
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
        # 컬럼: ID, 유형, 학반, 요일, 교시, 현재 과목/교사,
        #       변경 내용(요약), 사유, 상태, 결재 이력, 신청일
        # "유형" 칼럼 추가: 단일 / 연쇄 N단계 구분 표시
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "ID", "유형", "학반", "요일", "교시", "현재 과목/교사",
            "변경 내용", "사유", "상태", "결재 이력", "신청일",
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
        # 행 선택 변경 시 상세 패널 갱신 + 승인 버튼 상태 갱신
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # ── 연쇄 교체 단계 상세 패널 ──────────────────────────────────
        # 선택된 신청이 연쇄 교체인 경우, 단계별 시각화를 표시합니다.
        # 단일 신청의 경우 패널을 숨김.
        self.detail_group = QGroupBox("연쇄 교체 단계 상세")
        detail_layout = QVBoxLayout(self.detail_group)
        detail_layout.setSpacing(6)

        self.detail_label = QLabel(
            "연쇄 교체 신청을 선택하면 각 단계의 교체 내용과 동의 상태가 표시됩니다."
        )
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color:#555;")
        detail_layout.addWidget(self.detail_label)

        # 단계별 상세 내용을 표시할 읽기 전용 텍스트 영역
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(120)
        self.detail_text.setStyleSheet("""
            QTextEdit {
                background: #FAFBFD;
                border: 1px solid #D0D7E2;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        detail_layout.addWidget(self.detail_text)

        self.detail_group.setVisible(False)
        layout.addWidget(self.detail_group)

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
                # req.steps 를 미리 로드(lazy load 1회 발생)
                steps = list(req.steps)
                is_chain = bool(steps)

                entry = req.timetable_entry
                school_class = entry.school_class if entry else None

                self.table.setItem(row, 0, self._item(str(req.id)))

                # ── 유형 표시 ──────────────────────────────────────────
                # 단일: 단순 과목/교사/교실 변경 또는 1:1 교환
                # 연쇄: N단계 연쇄 교체
                if is_chain:
                    type_text = f"연쇄 {len(steps)}단계"
                else:
                    type_text = "단일"
                type_item = self._item(type_text)
                if is_chain:
                    # 연쇄 교체는 배경색으로 구분 (연한 파란색)
                    type_item.setBackground(QBrush(QColor("#E3F2FD")))
                self.table.setItem(row, 1, type_item)

                self.table.setItem(row, 2, self._item(
                    school_class.display_name if school_class else ""
                ))
                self.table.setItem(row, 3, self._item(
                    DAYS_KR[entry.day_of_week - 1] if entry else ""
                ))
                self.table.setItem(row, 4, self._item(
                    str(entry.period) if entry else ""
                ))

                # 현재 과목/교사 정보 — 연쇄 교체인 경우 시작 슬롯 기준
                current_info = ""
                if entry:
                    subj = session.get(Subject, entry.subject_id)
                    tchr = session.get(Teacher, entry.teacher_id)
                    current_info = (
                        f"{subj.short_name if subj else ''} / "
                        f"{tchr.name if tchr else ''}"
                    )

                # 변경 요청된 과목/교사/교실 정보
                # - 단일 신청: new_*_id 또는 swap partner 표시
                # - 연쇄 신청: 단계 요약 표시 ("3단계, 2/3 동의" 등)
                if is_chain:
                    new_info = self._format_chain_summary(steps)
                else:
                    new_info = self._format_single_change(req, session)

                self.table.setItem(row, 5, self._item(current_info))
                self.table.setItem(row, 6, self._item(new_info))
                self.table.setItem(row, 7, self._item(req.reason[:50]))

                # 상태 표시 — 진행 단계 포함
                status_text = self._format_status(req, steps)
                self.table.setItem(row, 8, self._item(status_text))

                # 결재 이력 — approval_history JSON 파싱
                self.table.setItem(row, 9, self._item(self._format_history(req)))

                # 신청일
                self.table.setItem(row, 10, self._item(
                    req.requested_at.strftime("%Y-%m-%d %H:%M")
                    if req.requested_at else ""
                ))

                # ── 상태별 색상 표시 ────────────────────────────────────
                status_item = self.table.item(row, 8)
                if req.status == "pending":
                    status_item.setBackground(QBrush(QColor("#F39C12")))
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "approved":
                    status_item.setBackground(QBrush(QColor("#27AE60")))
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "rejected":
                    status_item.setBackground(QBrush(QColor("#E74C3C")))
                    status_item.setForeground(QBrush(QColor("white")))

            # 새로고침 후 선택 해제 상태로 상세 패널 초기화
            self._clear_detail_panel()
        finally:
            session.close()

    # ── 표시 헬퍼 ──────────────────────────────────────────────────────

    def _format_single_change(self, req: TimetableChangeRequest, session) -> str:
        """
        단일 신청의 변경 내용을 문자열로 포맷합니다.

        - swap_partner_entry_id 가 있으면 교환 신청 → 상대 슬롯 과목/교사 표시
        - new_*_id 가 있으면 단일 슬롯의 과목/교사/교실 변경
        - 모두 없으면 빈 문자열 (빈 신청 — 비정상 케이스)
        """
        # 교환 신청: 상대 슬롯의 현재 과목/교사 표시
        if req.swap_partner_entry_id:
            partner = session.get(TimetableEntry, req.swap_partner_entry_id)
            if partner:
                p_subj = session.get(Subject, partner.subject_id)
                p_tchr = session.get(Teacher, partner.teacher_id)
                return f"↔ 교환: {p_subj.short_name if p_subj else ''} / {p_tchr.name if p_tchr else ''}"
            return "↔ 교환 (상대 슬롯 없음)"

        # 단일 변경: new_*_id 조합
        parts = []
        if req.new_subject_id:
            ns = session.get(Subject, req.new_subject_id)
            if ns:
                parts.append(ns.short_name)
        if req.new_teacher_id:
            nt = session.get(Teacher, req.new_teacher_id)
            if nt:
                parts.append(nt.name)
        if req.new_room_id:
            nr = session.get(Room, req.new_room_id)
            if nr:
                parts.append(f"@{nr.name}")
        return " / ".join(parts) if parts else "(내용 없음)"

    def _format_chain_summary(self, steps: list) -> str:
        """
        연쇄 교체 단계들의 요약 문자열을 생성합니다.

        예) "3단계, 2/3 동의" — 3단계 중 2명이 동의 완료
        예) "2단계, 0/2 동의" — 아직 동의 없음
        rejected 단계가 있으면 "1명 거절" 표시 추가.
        """
        total = len(steps)
        approved = sum(1 for s in steps if s.consent_status == "approved")
        rejected = sum(1 for s in steps if s.consent_status == "rejected")
        # 동의 불필요 단계는 카운트에서 제외
        needs_consent = sum(1 for s in steps if s.consent_status != "not_required")

        parts = [f"{total}단계"]
        if needs_consent > 0:
            parts.append(f"{approved}/{needs_consent} 동의")
        if rejected > 0:
            parts.append(f"{rejected}명 거절")
        return ", ".join(parts)

    def _format_status(self, req: TimetableChangeRequest,
                       steps: list | None = None) -> str:
        """
        상태 문자열을 생성합니다.

        pending 상태일 때는 현재 결재 진행 상황과 피교사 동의 상태를 표시합니다:
          예) "대기 중 (1/3단계) — 동의 완료"
          예) "대기 중 (0/3단계) — 2/3 동의"  (연쇄 교체, 동의 진행 중)

        approved/rejected 는 최종 상태이므로 단계 정보 없이 표시합니다.
        """
        # 연쇄 교체인 경우 부모 consent_status 를 자식 단계들로부터 파생
        if steps:
            consent_text = self._derive_consent_status(steps)
        else:
            consent_text = CONSENT_LABELS.get(
                req.consent_status, req.consent_status
            )

        if req.status == "pending":
            total = self._total_steps or 1
            return f"대기 중 ({req.current_step}/{total}단계) — {consent_text}"
        if req.status == "approved":
            return "승인 완료"
        if req.status == "rejected":
            return "거절"
        return req.status

    def _derive_consent_status(self, steps: list) -> str:
        """
        자식 단계들의 consent_status 로부터 부모 상태를 파생합니다.

        규칙:
          - 하나라도 rejected → "동의 거절 (N/M)" — 전체 거절 처리
          - 모든 step approved (또는 not_required) → "동의 완료"
          - 그 외 → "N/M 동의 대기"
        """
        # 동의가 필요한 단계만 카운트 (not_required 제외)
        needs = [s for s in steps if s.consent_status != "not_required"]
        if not needs:
            return "동의 불필요"

        total = len(needs)
        approved = sum(1 for s in needs if s.consent_status == "approved")
        rejected = sum(1 for s in needs if s.consent_status == "rejected")

        if rejected > 0:
            return f"동의 거절 ({approved}/{total})"
        if approved == total:
            return "동의 완료"
        return f"{approved}/{total} 동의 대기"

    def _format_history(self, req: TimetableChangeRequest) -> str:
        """
        approval_history JSON 을 사람이 읽을 수 있는 여러 줄 문자열로 변환합니다.

        JSON 구조:
          [{"step": 1, "role": "admin", "action": "approve", "by": "일과계", "at": "2024-03-15T14:30:00"}]

        출력 예:
          1단계 승인 (일과계, 03/15 14:30)
          2단계 승인 (교감, 03/15 15:00)

        주의: 결재 라인(일과계 → 교감)의 이력만 여기에 표시되며,
        단계별 교사 동의는 별도 상세 패널에 표시됩니다.

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

    def _format_step_label(self, step: ChangeRequestStep, session) -> str:
        """
        단계를 표시용 라벨 문자열로 변환합니다.

        예) swap: "월3 수학(김) ↔ 화2 영어(이)"
        예) change: "월3 수학(김) → 과학(박) @과학실"

        과목/교사/교실 이름을 DB 에서 조회해 채웁니다.
        """
        source = session.get(TimetableEntry, step.source_entry_id)
        if source is None:
            return f"{step.step_order}단계: source 슬롯(id={step.source_entry_id}) 없음"

        src_subj = session.get(Subject, source.subject_id)
        src_tchr = session.get(Teacher, source.teacher_id)
        src_subj_name = src_subj.short_name if src_subj else "?"
        src_tchr_name = src_tchr.name if src_tchr else "?"
        src_label = f"{DAYS_KR[source.day_of_week - 1]}{source.period} {src_subj_name}({src_tchr_name})"

        if step.step_type == "swap":
            target = session.get(TimetableEntry, step.target_entry_id) if step.target_entry_id else None
            if target is None:
                return f"{step.step_order}단계: {src_label} ↔ (target 없음)"
            tgt_subj = session.get(Subject, target.subject_id)
            tgt_tchr = session.get(Teacher, target.teacher_id)
            tgt_subj_name = tgt_subj.short_name if tgt_subj else "?"
            tgt_tchr_name = tgt_tchr.name if tgt_tchr else "?"
            tgt_label = f"{DAYS_KR[target.day_of_week - 1]}{target.period} {tgt_subj_name}({tgt_tchr_name})"
            return f"{step.step_order}단계: {src_label} ↔ {tgt_label}"

        # step_type == "change"
        parts = []
        if step.new_subject_id:
            ns = session.get(Subject, step.new_subject_id)
            if ns:
                parts.append(ns.short_name)
        if step.new_teacher_id:
            nt = session.get(Teacher, step.new_teacher_id)
            if nt:
                parts.append(nt.name)
        if step.new_room_id:
            nr = session.get(Room, step.new_room_id)
            if nr:
                parts.append(f"@{nr.name}")
        new_label = " / ".join(parts) if parts else "(변경 없음)"
        return f"{step.step_order}단계: {src_label} → {new_label}"

    def _format_step_consent(self, step: ChangeRequestStep, session) -> str:
        """
        단계별 동의 상태를 표시용 문자열로 변환합니다.

        예) "동의 완료 (김선생님, 03/15 14:30)"
        예) "동의 대기 (박선생님)"
        예) "동의 불필요"
        예) "동의 거절 (이선생님, 03/15 15:00)"
        """
        status = step.consent_status or "not_required"
        if status == "not_required":
            return "동의 불필요"

        # 영향받는 교사 이름 조회
        tchr_name = "?"
        if step.affected_teacher_id:
            t = session.get(Teacher, step.affected_teacher_id)
            if t:
                tchr_name = t.name

        # 동의한 사용자 이름 조회 (User.username)
        approver = ""
        if step.consent_by_user_id:
            u = session.get(User, step.consent_by_user_id)
            if u:
                approver = u.username

        # 동의 시각
        at_str = ""
        if step.consent_at:
            try:
                at_str = step.consent_at.strftime("%m/%d %H:%M")
            except (ValueError, AttributeError):
                at_str = str(step.consent_at)[:16]

        if status == "approved":
            by = approver or tchr_name
            return f"동의 완료 ({by}{', ' + at_str if at_str else ''})"
        if status == "rejected":
            by = approver or tchr_name
            return f"동의 거절 ({by}{', ' + at_str if at_str else ''})"
        if status == "pending":
            return f"동의 대기 ({tchr_name})"
        return status

    def _item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    # ── 선택 변경 핸들러 ──────────────────────────────────────────────

    def _on_selection_changed(self):
        """
        테이블 행 선택 변경 시 호출됩니다.

        1. 선택된 신청이 연쇄 교체인 경우 상세 패널에 단계별 시각화 표시
        2. 단일 신청이거나 선택 없음 시 상세 패널 숨김
        3. 승인 버튼 활성화 상태 갱신
        """
        self._update_button_state()
        self._refresh_detail_panel()

    def _clear_detail_panel(self):
        """상세 패널을 초기화하고 숨깁니다."""
        self.detail_text.clear()
        self.detail_group.setVisible(False)

    def _refresh_detail_panel(self):
        """선택된 신청의 단계 상세를 갱신합니다. 연쇄 교체가 아니면 숨깁니다."""
        row = self.table.currentRow()
        if row < 0:
            self._clear_detail_panel()
            return

        try:
            req_id = int(self.table.item(row, 0).text())
        except (ValueError, AttributeError):
            self._clear_detail_panel()
            return

        session = get_session()
        try:
            req = session.get(TimetableChangeRequest, req_id)
            if req is None:
                self._clear_detail_panel()
                return

            steps = list(req.steps)
            if not steps:
                # 단일 신청 — 상세 패널 불필요
                self._clear_detail_panel()
                return

            # ── 단계별 상세 텍스트 생성 ──────────────────────────────
            lines = []
            for step in steps:
                label = self._format_step_label(step, session)
                consent = self._format_step_consent(step, session)
                lines.append(f"  • {label}")
                lines.append(f"      └ {consent}")
                # 스냅샷 존재 여부 표시 (race 감지용) — 디버그용이므로 간결하게
                if step.change_snapshot:
                    lines.append(f"      └ (스냅샷 보존됨)")
                lines.append("")  # 단계 구분 빈 줄

            # 부모 요약 헤더
            summary = self._format_chain_summary(steps)
            derived_status = self._derive_consent_status(steps)
            header = (
                f"연쇄 교체 신청 #{req.id} — {summary}\n"
                f"전체 동의 상태: {derived_status}\n"
                f"결재 단계: {req.current_step}/{self._total_steps or 1}단계\n"
                f"{'─' * 60}"
            )
            self.detail_text.setPlainText(header + "\n" + "\n".join(lines))
            self.detail_group.setVisible(True)
        finally:
            session.close()

    def _get_selected_request_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "처리할 신청을 선택해 주세요.")
            return None
        return int(self.table.item(row, 0).text())

    def _update_button_state(self):
        """
        테이블 선택 변경 시 승인/거절 버튼의 활성화 상태를 조정합니다.

        피교사 동의가 필요한 신청(consent_status=pending)은 아직 승인할 수 없으며,
        버튼에 툴팁으로 안내 메시지를 표시합니다.

        연쇄 교체의 경우 부모 consent_status 가 자식 단계들로부터 파생됩니다.
        """
        row = self.table.currentRow()
        if row < 0:
            self.btn_approve.setEnabled(True)
            self.btn_approve.setToolTip("")
            return

        req_id = int(self.table.item(row, 0).text())
        session = get_session()
        try:
            req = session.get(TimetableChangeRequest, req_id)
            if req is None:
                self.btn_approve.setEnabled(True)
                self.btn_approve.setToolTip("")
                return

            # 연쇄 교체: 파생 consent_status 계산
            steps = list(req.steps) if req.steps else []
            if steps:
                derived = self._derive_consent_status(steps)
                # "동의 완료" 또는 "동의 불필요" 가 아니면 승인 불가
                can_approve = derived in ("동의 완료", "동의 불필요")
                self.btn_approve.setEnabled(can_approve)
                self.btn_approve.setToolTip(
                    "" if can_approve
                    else f"모든 단계의 교사 동의가 완료된 후 승인할 수 있습니다. (현재: {derived})"
                )
            else:
                # 단일 신청: 기존 로직 유지
                if req.consent_status == "pending":
                    self.btn_approve.setEnabled(False)
                    self.btn_approve.setToolTip(
                        "피교사의 동의가 완료된 후에 승인할 수 있습니다."
                    )
                else:
                    self.btn_approve.setEnabled(True)
                    self.btn_approve.setToolTip("")
        finally:
            session.close()

    # ── 워크플로우 헬퍼 ──────────────────────────────────────────────

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

    # ── 승인 처리 ─────────────────────────────────────────────────────

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

        연쇄 교체 지원 (2026-06-20):
          - req.steps 가 있으면 최종 승인 시 _apply_chain_swap_changes 호출
          - 모든 단계를 한 트랜잭션으로 묶어 원자성 보장 (중간 실패 시 rollback)
          - 각 단계마다 change_snapshot 과 현재 DB 상태 비교 — 충돌 시 409

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

            # 연쇄 교체 동의 상태 검증
            steps = list(req.steps) if req.steps else []
            if steps:
                derived = self._derive_consent_status(steps)
                if derived not in ("동의 완료", "동의 불필요"):
                    QMessageBox.warning(
                        self, "동의 대기 중",
                        f"모든 단계의 교사 동의가 완료된 후 승인할 수 있습니다.\n"
                        f"현재 상태: {derived}"
                    )
                    return
            else:
                # 단일 신청: 기존 동의 검증
                if req.consent_status == "pending":
                    QMessageBox.warning(
                        self, "동의 대기 중",
                        "피교사의 동의가 완료된 후에 승인할 수 있습니다."
                    )
                    return

            # 활성 워크플로우가 없으면 결재 진행 불가능
            if not self._workflow:
                QMessageBox.warning(self, "오류",
                                    "활성화된 결재 워크플로우가 없습니다.\n"
                                    "관리자에게 문의하여 결재 라인을 설정해 주세요.")
                return

            # ── 현재 단계 확인 및 역할 검증 ─────────────────────────────
            current_step = req.current_step
            step_def = self._get_step_at(current_step)
            if step_def is None:
                QMessageBox.warning(self, "오류",
                                    f"워크플로우에 {current_step}단계가 정의되어 있지 않습니다.")
                return

            # 역할 기반 접근 제어
            if self._role != step_def.role_required:
                role_display = ROLE_DISPLAY.get(step_def.role_required, step_def.role_required)
                QMessageBox.warning(self, "권한 없음",
                                    f"현재 {current_step}단계는 {role_display} 선생님만 승인할 수 있습니다.")
                return

            # ── 승인 기록을 approval_history JSON 배열에 추가 ─────────────
            self._append_history(req, current_step, "approve")

            if current_step < self._total_steps:
                # ── 중간 단계 승인: 다음 단계로 진행 ────────────────────
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
                # 단일 신청과 연쇄 교체를 분기 처리
                try:
                    if steps:
                        # 연쇄 교체: 각 단계를 순회하며 TimetableEntry 반영
                        self._apply_chain_swap_changes(session, req, steps)
                        summary = self._format_chain_summary(steps)
                        success_msg = (
                            "연쇄 교체가 최종 승인되어 시간표에 반영되었습니다.\n"
                            f"적용 단계: {summary}"
                        )
                    else:
                        # 단일 신청: 기존 로직
                        entry = session.get(TimetableEntry, req.timetable_entry_id)
                        if entry is None:
                            QMessageBox.warning(self, "오류",
                                                "해당 시간표 항목이 존재하지 않습니다.")
                            return

                        # 변경 전 상태를 스냅샷으로 저장 (감사 추적용)
                        # old_data 는 entry 의 원래 과목/교사/교실 뿐 아니라 요일·교시도 포함하여
                        # log_entry_update 가 before/after 를 TimetableChangeLog 에 기록할 때 사용합니다.
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
                        log_entry_update(session, entry, old_data)

                        # 교환(swap) 신청: 상대 슬롯도 반영
                        # 교환인 경우 new_*_id 는 보통 None 이며, 단순히 두 슬롯의
                        # 과목/교사/교실을 맞바꿉니다.
                        # (new_*_id 가 같이 지정된 경우 swap 값이 우선 — 서버 로직과 동일)
                        if req.swap_partner_entry_id:
                            partner = session.get(TimetableEntry, req.swap_partner_entry_id)
                            if partner is None:
                                QMessageBox.warning(
                                    self, "오류",
                                    "교환 상대 슬롯이 존재하지 않아 변경을 적용할 수 없습니다.",
                                )
                                return
                            partner_before = {
                                "subject_id": partner.subject_id,
                                "teacher_id": partner.teacher_id,
                                "room_id":    partner.room_id,
                            }
                            # 교환: entry 에는 partner 의 원래 값을, partner 에는 entry 의 원래 값을
                            entry.subject_id   = partner_before["subject_id"]
                            entry.teacher_id   = partner_before["teacher_id"]
                            entry.room_id      = partner_before["room_id"]
                            partner.subject_id = old_data["subject_id"]
                            partner.teacher_id = old_data["teacher_id"]
                            partner.room_id    = old_data["room_id"]
                            log_entry_update(session, partner, partner_before)

                        success_msg = "변경이 최종 승인되어 시간표에 반영되었습니다."

                    req.status = "approved"
                    role_label = ROLE_DISPLAY.get(self._role, self._role)
                    req.approved_by = role_label
                    req.approved_at = datetime.now()

                    session.commit()
                    QMessageBox.information(self, "최종 승인 완료", success_msg)
                except Exception as e:
                    # 트랜잭션 롤백 — 충돌이나 검증 실패 시 원자성 보장
                    session.rollback()
                    QMessageBox.warning(
                        self, "적용 실패",
                        f"시간표 반영 중 오류가 발생했습니다.\n{e}\n"
                        "변경 신청이 취소되었습니다. 최신 상태로 다시 신청해 주세요.",
                    )
                    return

            self.refresh()
        finally:
            session.close()

    def _apply_chain_swap_changes(self, session, req: TimetableChangeRequest,
                                   steps: list) -> None:
        """
        연쇄 교체 신청의 모든 단계를 TimetableEntry 에 반영합니다.

        각 단계를 step_order 순서대로 순회하며:
          - step_type="swap": source 와 target 슬롯의 과목/교사/교실을 맞바꿈
          - step_type="change": source 슬롯의 과목/교사/교실을 new_*_id 로 변경

        각 단계마다 change_snapshot 과 현재 DB 상태를 비교해 충돌을 감지합니다.
        결재 기간 중 다른 변경 신청이 같은 슬롯을 수정했다면 ValueError 를 raise 하여
        트랜잭션을 롤백합니다 (원자성 보장 — 일부 단계만 적용되는 일 없음).

        연쇄 교체 chain link 처리:
          - 한 슬롯이 step N 의 target 이자 step N+1 의 source 로 참여할 수 있음.
          - step N 적용 후 해당 슬롯의 상태는 당연히 바뀌므로, step N+1 의 snapshot
            검증은 "이전 단계에서 이미 수정한 슬롯"에 대해서는 건너뜁니다.
          - 단, 외부(다른 신청)에서 수정한 경우는 여전히 ValueError 로 차단.

        서버의 _apply_chain_swap_changes 와 동일한 로직입니다 (DB 직접 접근 버전).
        """
        ordered = sorted(steps, key=lambda s: s.step_order)

        # 이전 단계에서 이미 수정한 슬롯 ID 집합 — chain link 슬롯은
        # snapshot 검증을 건너뜀 (자신이 방금 수정한 결과이므로 당연히 다름).
        modified_in_this_tx: set[int] = set()

        for step in ordered:
            # source 슬롯 로드
            source = session.get(TimetableEntry, step.source_entry_id)
            if source is None:
                raise ValueError(
                    f"{step.step_order}단계: source 슬롯(id={step.source_entry_id})이 "
                    "결재 기간 중 삭제되었습니다."
                )

            # 이 단계의 스냅샷을 한 번 로드 — source/target 검증 모두 이 변수 사용
            snap: dict = {}
            if step.change_snapshot:
                try:
                    snap = json.loads(step.change_snapshot)
                except json.JSONDecodeError:
                    snap = {}

            # 스냅샷 충돌 감지 (source) — chain link 슬롯은 건너뜀
            if step.source_entry_id not in modified_in_this_tx:
                source_snap = snap.get("source")
                if source_snap:
                    current = {
                        "subject_id": source.subject_id,
                        "teacher_id": source.teacher_id,
                        "room_id":    source.room_id,
                    }
                    if current != source_snap:
                        raise ValueError(
                            f"{step.step_order}단계: source 슬롯(id={step.source_entry_id})이 "
                            "결재 기간 중 다른 변경으로 수정되었습니다."
                        )

            if step.step_type == "swap":
                target = session.get(TimetableEntry, step.target_entry_id) if step.target_entry_id else None
                if target is None:
                    raise ValueError(
                        f"{step.step_order}단계: target 슬롯(id={step.target_entry_id})이 "
                        "결재 기간 중 삭제되었습니다."
                    )

                # 스냅샷 충돌 감지 (target) — chain link 슬롯은 건너뜀
                if step.target_entry_id not in modified_in_this_tx:
                    target_snap = snap.get("target")
                    if target_snap:
                        current = {
                            "subject_id": target.subject_id,
                            "teacher_id": target.teacher_id,
                            "room_id":    target.room_id,
                        }
                        if current != target_snap:
                            raise ValueError(
                                f"{step.step_order}단계: target 슬롯(id={step.target_entry_id})이 "
                                "결재 기간 중 다른 변경으로 수정되었습니다."
                            )

                # 교환 적용 — before/after 로그 기록
                source_before = {
                    "subject_id": source.subject_id,
                    "teacher_id": source.teacher_id,
                    "room_id":    source.room_id,
                }
                target_before = {
                    "subject_id": target.subject_id,
                    "teacher_id": target.teacher_id,
                    "room_id":    target.room_id,
                }
                # 교환: 양쪽 값을 맞바꿈
                source.subject_id = target_before["subject_id"]
                source.teacher_id = target_before["teacher_id"]
                source.room_id    = target_before["room_id"]
                target.subject_id = source_before["subject_id"]
                target.teacher_id = source_before["teacher_id"]
                target.room_id    = source_before["room_id"]
                log_entry_update(session, source, source_before)
                log_entry_update(session, target, target_before)
                # 두 슬롯 모두 이번 트랜잭션에서 수정됨
                modified_in_this_tx.add(source.id)
                modified_in_this_tx.add(target.id)

            elif step.step_type == "change":
                # 단일 슬롯 변경
                before = {
                    "subject_id": source.subject_id,
                    "teacher_id": source.teacher_id,
                    "room_id":    source.room_id,
                }
                if step.new_subject_id is not None:
                    source.subject_id = step.new_subject_id
                if step.new_teacher_id is not None:
                    source.teacher_id = step.new_teacher_id
                if step.new_room_id is not None:
                    source.room_id = step.new_room_id
                log_entry_update(session, source, before)
                modified_in_this_tx.add(source.id)

            else:
                raise ValueError(
                    f"{step.step_order}단계: 알 수 없는 step_type={step.step_type}"
                )

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
          - 연쇄 교체의 경우에도 부모 신청이 rejected 로 종료되면
            자식 단계의 동의 여부와 무관하게 전체 신청이 취소됩니다.
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
            if self._role == "teacher":
                QMessageBox.warning(self, "권한 없음", "교사는 변경 신청을 거절할 수 없습니다.")
                return

            # 현재 단계의 role_required 와 사용자 role 비교
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