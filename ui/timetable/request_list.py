"""
변경 신청 목록 및 승인/거절 화면

TimetableChangeRequest 레코드를 상태별로 필터링해 표시하고,
관리자가 '승인' 또는 '거절'을 처리합니다.

승인 흐름:
  1. pending 상태인 신청을 선택합니다.
  2. '승인' 버튼 클릭 → TimetableEntry 에 즉시 반영 + 변경 이력 기록
  3. TimetableChangeRequest.status = "approved"

거절 흐름:
  1. pending 상태인 신청을 선택합니다.
  2. '거절' 버튼 클릭 → TimetableChangeRequest.status = "rejected"
     (TimetableEntry 는 변경하지 않습니다.)
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

DAYS_KR    = ["월", "화", "수", "목", "금"]
STATUS_MAP = {"pending": "대기", "approved": "승인", "rejected": "거절"}


class ChangeRequestWidget(QWidget):
    """변경 신청 목록 조회 및 승인/거절 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.cb_status.addItem("대기", "pending")
        self.cb_status.addItem("승인", "approved")
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
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "ID", "학반", "요일", "교시", "현재 과목/교사",
            "변경 과목/교사", "사유", "상태", "신청일",
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

        btn_approve = QPushButton("승인")
        btn_approve.setStyleSheet(
            "background:#27AE60; color:white; border-radius:4px; padding:8px 20px; font-weight:bold;"
        )
        btn_approve.clicked.connect(self._approve)
        btn_layout.addWidget(btn_approve)

        btn_reject = QPushButton("거절")
        btn_reject.setStyleSheet(
            "background:#E74C3C; color:white; border-radius:4px; padding:8px 20px; font-weight:bold;"
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
                entry       = req.timetable_entry
                school_class = entry.school_class if entry else None

                self.table.setItem(row, 0, self._item(str(req.id)))
                self.table.setItem(row, 1, self._item(
                    school_class.display_name if school_class else ""
                ))
                self.table.setItem(row, 2, self._item(
                    DAYS_KR[entry.day_of_week - 1] if entry else ""
                ))
                self.table.setItem(row, 3, self._item(str(entry.period) if entry else ""))

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
                self.table.setItem(row, 7, self._item(STATUS_MAP.get(req.status, req.status)))
                self.table.setItem(row, 8, self._item(
                    req.requested_at.strftime("%Y-%m-%d %H:%M") if req.requested_at else ""
                ))

                # 상태별 색상 표시
                status_item = self.table.item(row, 7)
                if req.status == "pending":
                    status_item.setBackground(QBrush(QColor("#F39C12")))   # 주황
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
        선택된 신청을 승인합니다.
        TimetableEntry 를 즉시 수정하고 변경 이력을 기록한 뒤
        신청 상태를 "approved" 로 변경합니다.
        """
        session = get_session()
        try:
            req_id = self._get_selected_request_id()
            if req_id is None:
                return

            req = session.get(TimetableChangeRequest, req_id)
            if req is None or req.status != "pending":
                QMessageBox.warning(self, "오류", "대기 상태인 신청만 승인할 수 있습니다.")
                return

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

            # 요청된 값이 있으면 반영하고, 없으면 기존 값 유지합니다.
            entry.subject_id = req.new_subject_id or entry.subject_id
            entry.teacher_id = req.new_teacher_id or entry.teacher_id
            entry.room_id    = req.new_room_id or entry.room_id

            log_entry_update(session, entry, old_data)

            req.status      = "approved"
            req.approved_at = datetime.now()   # 승인 일시 기록
            session.commit()

            QMessageBox.information(self, "승인 완료", "변경이 승인되어 시간표에 반영되었습니다.")
            self.refresh()
        finally:
            session.close()

    def _reject(self):
        """
        선택된 신청을 거절합니다.
        TimetableEntry 는 변경하지 않고 신청 상태만 "rejected" 로 변경합니다.
        """
        session = get_session()
        try:
            req_id = self._get_selected_request_id()
            if req_id is None:
                return

            req = session.get(TimetableChangeRequest, req_id)
            if req is None or req.status != "pending":
                QMessageBox.warning(self, "오류", "대기 상태인 신청만 거절할 수 있습니다.")
                return

            req.status = "rejected"
            session.commit()

            QMessageBox.information(self, "거절 완료", "변경 신청이 거절되었습니다.")
            self.refresh()
        finally:
            session.close()
