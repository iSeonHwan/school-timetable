"""변경 신청 목록 및 승인/거절 화면"""
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
import json


DAYS_KR = ["월", "화", "수", "목", "금"]
STATUS_MAP = {"pending": "대기", "approved": "승인", "rejected": "거절"}


class ChangeRequestWidget(QWidget):
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

        # 필터
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

        # 테이블
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

        # 액션 버튼
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
                self.table.setItem(row, 3, self._item(str(entry.period) if entry else ""))

                current_info = ""
                if entry:
                    subj = session.query(Subject).get(entry.subject_id)
                    tchr = session.query(Teacher).get(entry.teacher_id)
                    current_info = f"{subj.short_name if subj else ''} / {tchr.name if tchr else ''}"

                new_info_parts = []
                if req.new_subject_id:
                    ns = session.query(Subject).get(req.new_subject_id)
                    if ns:
                        new_info_parts.append(ns.short_name)
                if req.new_teacher_id:
                    nt = session.query(Teacher).get(req.new_teacher_id)
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

                # Status coloring
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

    def _item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _get_selected_request(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "처리할 신청을 선택해 주세요.")
            return None
        req_id = int(self.table.item(row, 0).text())
        session = get_session()
        try:
            return session.query(TimetableChangeRequest).get(req_id)
        finally:
            session.close()

    def _approve(self):
        session = get_session()
        try:
            req_id = self._get_selected_request_id()
            if req_id is None:
                return
            req = session.query(TimetableChangeRequest).get(req_id)
            if req is None or req.status != "pending":
                QMessageBox.warning(self, "오류", "대기 상태인 신청만 승인할 수 있습니다.")
                return

            entry = session.query(TimetableEntry).get(req.timetable_entry_id)
            if entry is None:
                QMessageBox.warning(self, "오류", "해당 시간표 항목이 존재하지 않습니다.")
                return

            old_data = {
                "day": entry.day_of_week,
                "period": entry.period,
                "subject_id": entry.subject_id,
                "teacher_id": entry.teacher_id,
                "room_id": entry.room_id,
            }

            entry.subject_id = req.new_subject_id or entry.subject_id
            entry.teacher_id = req.new_teacher_id or entry.teacher_id
            entry.room_id = req.new_room_id or entry.room_id

            log_entry_update(session, entry, old_data)

            req.status = "approved"
            req.approved_at = __import__("datetime").datetime.now()
            session.commit()

            QMessageBox.information(self, "승인 완료", "변경이 승인되어 시간표에 반영되었습니다.")
            self.refresh()
        finally:
            session.close()

    def _reject(self):
        session = get_session()
        try:
            req_id = self._get_selected_request_id()
            if req_id is None:
                return
            req = session.query(TimetableChangeRequest).get(req_id)
            if req is None or req.status != "pending":
                QMessageBox.warning(self, "오류", "대기 상태인 신청만 거절할 수 있습니다.")
                return

            req.status = "rejected"
            session.commit()

            QMessageBox.information(self, "거절 완료", "변경 신청이 거절되었습니다.")
            self.refresh()
        finally:
            session.close()

    def _get_selected_request_id(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "처리할 신청을 선택해 주세요.")
            return None
        return int(self.table.item(row, 0).text())
