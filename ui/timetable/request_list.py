"""
변경 신청 목록 및 승인/거절 화면 (2단계 승인)

TimetableChangeRequest 레코드를 상태별로 필터링해 표시하고,
사용자의 역할(일과계/교감)에 따라 승인·거절을 처리합니다.

2단계 승인 흐름:
  1. 교사가 변경 신청 제출 → status = "pending"
  2. 일과계 선생님(admin)이 1차 승인 → status = "scheduler_approved"
     (TimetableEntry 는 아직 변경되지 않음)
  3. 교감 선생님(vice_principal)이 최종 승인 → status = "approved"
     (TimetableEntry 에 변경 내용 적용 + 변경 이력 기록)

거절:
  - 일과계·교감 모두 어느 단계든 거절 가능 → status = "rejected"
  - 누가 거절했는지 scheduler_approved_by 또는 vice_principal_approved_by 에 기록
"""
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
)
from core.change_logger import log_entry_update

DAYS_KR = ["월", "화", "수", "목", "금"]
# 상태 표시용 한글 매핑 — scheduler_approved 추가
STATUS_MAP = {
    "pending": "대기 중",
    "scheduler_approved": "1차 승인",
    "approved": "최종 승인",
    "rejected": "거절",
}


class ChangeRequestWidget(QWidget):
    """
    변경 신청 목록 조회 및 승인/거절 위젯.

    role 파라미터에 따라 승인 동작이 달라집니다:
      - "admin" (일과계): pending → scheduler_approved (1차 승인)
      - "vice_principal" (교감): scheduler_approved → approved (최종 승인 + 시간표 반영)
    """

    def __init__(self, parent=None, role: str = "admin"):
        super().__init__(parent)
        # role: "admin" (일과계) 또는 "vice_principal" (교감)
        self._role = role
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 역할에 따른 타이틀
        title_text = "변경 신청 관리" if self._role == "admin" else "변경 신청 최종 승인 (교감)"
        title = QLabel(title_text)
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
        self.cb_status.addItem("1차 승인", "scheduler_approved")
        self.cb_status.addItem("최종 승인", "approved")
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
        #       사유, 상태, 1차 승인자, 최종 승인자, 신청일
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "ID", "학반", "요일", "교시", "현재 과목/교사",
            "변경 과목/교사", "사유", "상태", "1차 승인자", "최종 승인자", "신청일",
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

        # 승인 버튼 라벨: 역할에 따라 다르게 표시
        approve_label = "1차 승인" if self._role == "admin" else "최종 승인"
        btn_approve = QPushButton(approve_label)
        btn_approve.setStyleSheet(
            "background:#27AE60; color:white; border-radius:4px; "
            "padding:8px 20px; font-weight:bold;"
        )
        btn_approve.clicked.connect(self._approve)
        btn_layout.addWidget(btn_approve)

        btn_reject = QPushButton("거절")
        btn_reject.setStyleSheet(
            "background:#E74C3C; color:white; border-radius:4px; "
            "padding:8px 20px; font-weight:bold;"
        )
        btn_reject.clicked.connect(self._reject)
        btn_layout.addWidget(btn_reject)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def refresh(self):
        """DB 에서 변경 신청 목록을 읽어 테이블을 갱신합니다."""
        session = get_session()
        try:
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

                # 상태 표시
                status_text = STATUS_MAP.get(req.status, req.status)
                self.table.setItem(row, 7, self._item(status_text))

                # 1차 승인자 (일과계)
                sched_info = ""
                if req.scheduler_approved_by:
                    sched_info = req.scheduler_approved_by
                    if req.scheduler_approved_at:
                        sched_info += f"\n{req.scheduler_approved_at.strftime('%m/%d %H:%M')}"
                self.table.setItem(row, 8, self._item(sched_info))

                # 최종 승인자 (교감)
                vp_info = ""
                if req.vice_principal_approved_by:
                    vp_info = req.vice_principal_approved_by
                    if req.vice_principal_approved_at:
                        vp_info += f"\n{req.vice_principal_approved_at.strftime('%m/%d %H:%M')}"
                self.table.setItem(row, 9, self._item(vp_info))

                # 신청일
                self.table.setItem(row, 10, self._item(
                    req.requested_at.strftime("%Y-%m-%d %H:%M")
                    if req.requested_at else ""
                ))

                # ── 상태별 색상 표시 ────────────────────────────────────
                status_item = self.table.item(row, 7)
                if req.status == "pending":
                    status_item.setBackground(QBrush(QColor("#F39C12")))   # 주황
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "scheduler_approved":
                    status_item.setBackground(QBrush(QColor("#2980B9")))   # 파랑
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "approved":
                    status_item.setBackground(QBrush(QColor("#27AE60")))   # 초록
                    status_item.setForeground(QBrush(QColor("white")))
                elif req.status == "rejected":
                    status_item.setBackground(QBrush(QColor("#E74C3C")))   # 빨강
                    status_item.setForeground(QBrush(QColor("white")))
        finally:
            session.close()

    def _item(self, text: str) -> QTableWidgetItem:
        """가운데 정렬된 QTableWidgetItem 을 생성하는 헬퍼 메서드입니다."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _get_selected_request_id(self) -> int | None:
        """
        테이블에서 선택된 행의 신청 ID 를 반환합니다.
        선택된 행이 없으면 경고를 표시하고 None 을 반환합니다.
        """
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "처리할 신청을 선택해 주세요.")
            return None
        return int(self.table.item(row, 0).text())

    def _approve(self):
        """
        선택된 신청을 승인합니다. (역할에 따라 1차 또는 최종 승인)

        일과계 선생님(admin):
          pending → scheduler_approved (1차 승인, TimetableEntry 변경 없음)

        교감 선생님(vice_principal):
          scheduler_approved → approved (최종 승인, TimetableEntry 즉시 수정 + 이력 기록)
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

            now = datetime.now()

            if self._role == "admin":
                # ── 1차 승인: 일과계 선생님 ──────────────────────────
                if req.status != "pending":
                    QMessageBox.warning(
                        self, "오류",
                        f"1차 승인은 '대기 중' 상태인 신청만 처리할 수 있습니다.\n"
                        f"현재 상태: {STATUS_MAP.get(req.status, req.status)}",
                    )
                    return
                req.status = "scheduler_approved"
                req.scheduler_approved_by = "일과계"
                req.scheduler_approved_at = now
                # approved_by 는 교감 최종 승인 시 채워지므로 명시적으로 초기화
                req.approved_by = ""
                req.approved_at = None
                session.commit()
                QMessageBox.information(
                    self, "1차 승인 완료",
                    "변경 신청이 1차 승인되었습니다.\n교감 선생님의 최종 승인이 필요합니다.",
                )

            elif self._role == "vice_principal":
                # ── 2차(최종) 승인: 교감 선생님 ───────────────────────
                if req.status != "scheduler_approved":
                    QMessageBox.warning(
                        self, "오류",
                        f"최종 승인은 '1차 승인' 상태인 신청만 처리할 수 있습니다.\n"
                        f"현재 상태: {STATUS_MAP.get(req.status, req.status)}",
                    )
                    return

                # 실제 시간표 항목에 변경 적용
                entry = session.get(TimetableEntry, req.timetable_entry_id)
                if entry is None:
                    QMessageBox.warning(self, "오류", "해당 시간표 항목이 존재하지 않습니다.")
                    return

                # 변경 전 스냅샷 저장 (이력 기록용)
                old_data = {
                    "day":        entry.day_of_week,
                    "period":     entry.period,
                    "subject_id": entry.subject_id,
                    "teacher_id": entry.teacher_id,
                    "room_id":    entry.room_id,
                }

                # 요청된 값이 있으면 반영, 없으면 기존 값 유지
                entry.subject_id = req.new_subject_id or entry.subject_id
                entry.teacher_id = req.new_teacher_id or entry.teacher_id
                entry.room_id    = req.new_room_id or entry.room_id

                log_entry_update(session, entry, old_data)

                req.status = "approved"
                req.vice_principal_approved_by = "교감"
                req.vice_principal_approved_at = now
                req.approved_by = "교감"
                req.approved_at = now

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
        선택된 신청을 거절합니다. (일과계·교감 모두 가능)

        어느 단계든 거절 가능하며, TimetableEntry 는 변경하지 않습니다.
        누가 거절했는지 역할에 맞는 필드(scheduler_approved_by/vice_principal_approved_by)에 기록됩니다.
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

            # 이미 최종 처리된 건(approved/rejected)은 거절 불가
            if req.status in ("approved", "rejected"):
                QMessageBox.warning(
                    self, "오류",
                    "이미 최종 처리 완료된 신청입니다.",
                )
                return

            now = datetime.now()
            req.status = "rejected"
            req.approved_by = "일과계" if self._role == "admin" else "교감"
            req.approved_at = now

            # 누가 거절했는지 역할에 맞는 필드에 기록
            if self._role == "admin":
                req.scheduler_approved_by = "일과계(거절)"
                req.scheduler_approved_at = now
            elif self._role == "vice_principal":
                req.vice_principal_approved_by = "교감(거절)"
                req.vice_principal_approved_at = now

            session.commit()
            QMessageBox.information(self, "거절 완료", "변경 신청이 거절되었습니다.")
            self.refresh()
        finally:
            session.close()
