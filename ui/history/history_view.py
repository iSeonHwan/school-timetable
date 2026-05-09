"""
시간표 변경 이력 조회 화면

TimetableChangeLog 테이블을 날짜·학반·변경 유형으로 필터링해 표시합니다.
최대 200건까지 최신순으로 조회하며, 행을 선택하면 하단 상세 영역에 내용이 표시됩니다.

이력 데이터 구조 (details JSON):
  생성: {"after":   {"day", "period", "subject_id", "teacher_id", "room_id"}}
  수정: {"before":  {...}, "after": {...}}
  삭제: {"deleted": {...}}

표시 형식:
  요일/교시 열: "화 3교시"
  상세 내용 열: "과목:3→5, 교사:2→7" (수정) / "신규 생성" (생성) / "삭제됨" (삭제)
"""
import json
from datetime import date, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QDateEdit, QTextEdit,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont, QColor, QBrush
from database.connection import get_session
from database.models import (
    TimetableChangeLog, SchoolClass, Grade, AcademicTerm,
)

DAYS_KR      = ["월", "화", "수", "목", "금"]
CHANGE_TYPES = {"created": "생성", "modified": "수정", "deleted": "삭제"}


class HistoryWidget(QWidget):
    """시간표 변경 이력 조회 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("변경 이력")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        # ── 필터 바 ───────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setStyleSheet("background:#F0F4FA; border-radius:6px;")
        fb = QHBoxLayout(filter_bar)
        fb.setContentsMargins(12, 8, 12, 8)

        fb.addWidget(QLabel("기간:"))

        # 시작 날짜: 기본값 1개월 전
        self._dt_from = QDateEdit()
        self._dt_from.setCalendarPopup(True)
        self._dt_from.setDate(QDate.currentDate().addMonths(-1))
        fb.addWidget(self._dt_from)

        fb.addWidget(QLabel("~"))

        # 종료 날짜: 기본값 오늘
        self._dt_to = QDateEdit()
        self._dt_to.setCalendarPopup(True)
        self._dt_to.setDate(QDate.currentDate())
        fb.addWidget(self._dt_to)

        fb.addSpacing(12)
        fb.addWidget(QLabel("학반:"))

        self._cb_class = QComboBox()
        self._cb_class.setMinimumWidth(100)
        fb.addWidget(self._cb_class)

        fb.addSpacing(12)
        fb.addWidget(QLabel("유형:"))

        self._cb_type = QComboBox()
        self._cb_type.addItem("전체",  None)
        self._cb_type.addItem("생성",  "created")
        self._cb_type.addItem("수정",  "modified")
        self._cb_type.addItem("삭제",  "deleted")
        fb.addWidget(self._cb_type)

        fb.addStretch()
        btn = QPushButton("조회")
        btn.setStyleSheet(
            "background:#1B4F8A; color:white; border-radius:4px; "
            "padding:6px 18px; font-weight:bold;"
        )
        btn.clicked.connect(self.refresh)
        fb.addWidget(btn)

        layout.addWidget(filter_bar)

        # ── 이력 테이블 ───────────────────────────────────────────────
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "일시", "학반", "변경 유형", "요일/교시", "상세 내용"
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
        # 행 선택 시 하단 상세 영역에 내용을 표시합니다.
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # ── 상세 내용 표시 영역 ────────────────────────────────────────
        detail_label = QLabel("상세 내용:")
        detail_label.setFont(QFont("", 10, QFont.Weight.Bold))
        layout.addWidget(detail_label)

        self._txt_detail = QTextEdit()
        self._txt_detail.setReadOnly(True)
        self._txt_detail.setMaximumHeight(120)
        self._txt_detail.setStyleSheet("background:#F8F9FA; border:1px solid #CCC;")
        layout.addWidget(self._txt_detail)

        self._populate_class_combo()

    def _populate_class_combo(self):
        """학반 콤보박스를 DB 에서 읽어 채웁니다."""
        session = get_session()
        try:
            self._cb_class.clear()
            self._cb_class.addItem("전체", None)
            classes = (
                session.query(SchoolClass)
                .join(Grade)
                .order_by(Grade.grade_number, SchoolClass.class_number)
                .all()
            )
            for c in classes:
                self._cb_class.addItem(c.display_name, c.id)
        finally:
            session.close()

    def refresh(self):
        """필터 조건에 맞는 이력 레코드를 DB 에서 읽어 테이블을 갱신합니다."""
        session = get_session()
        try:
            # QDate → Python date 변환
            q_from = self._dt_from.date()
            q_to   = self._dt_to.date()
            dt_from = date(q_from.year(), q_from.month(), q_from.day())
            # 종료일의 다음날 자정까지 포함하기 위해 +1일합니다 (반열린 구간).
            dt_to   = date(q_to.year(), q_to.month(), q_to.day()) + timedelta(days=1)

            query = session.query(TimetableChangeLog).filter(
                TimetableChangeLog.changed_at >= dt_from,
                TimetableChangeLog.changed_at < dt_to,
            )

            # 학반 필터 적용
            class_id = self._cb_class.currentData()
            if class_id:
                query = query.filter_by(school_class_id=class_id)

            # 변경 유형 필터 적용
            change_type = self._cb_type.currentData()
            if change_type:
                query = query.filter_by(change_type=change_type)

            # 최신순 정렬, 최대 200건만 조회합니다.
            logs = query.order_by(TimetableChangeLog.changed_at.desc()).limit(200).all()

            self.table.setRowCount(len(logs))
            for row, log in enumerate(logs):
                self.table.setItem(row, 0, self._item(
                    log.changed_at.strftime("%Y-%m-%d %H:%M") if log.changed_at else ""
                ))

                # SQLAlchemy 2.0 방식: session.get(Model, pk)
                school_class = session.get(SchoolClass, log.school_class_id)
                self.table.setItem(row, 1, self._item(
                    school_class.display_name if school_class else ""
                ))

                # 변경 유형 셀: 색상으로 구분합니다.
                type_text = CHANGE_TYPES.get(log.change_type, log.change_type)
                type_item = self._item(type_text)
                if log.change_type == "created":
                    type_item.setBackground(QBrush(QColor("#27AE60")))    # 초록
                    type_item.setForeground(QBrush(QColor("white")))
                elif log.change_type == "modified":
                    type_item.setBackground(QBrush(QColor("#F39C12")))    # 주황
                    type_item.setForeground(QBrush(QColor("white")))
                elif log.change_type == "deleted":
                    type_item.setBackground(QBrush(QColor("#E74C3C")))    # 빨강
                    type_item.setForeground(QBrush(QColor("white")))
                self.table.setItem(row, 2, type_item)

                # 요일/교시 셀: details JSON 에서 day·period 를 추출합니다.
                slot_info = ""
                try:
                    d = json.loads(log.details) if log.details else {}
                    # 변경 유형에 따라 JSON 내 키가 다릅니다.
                    if log.change_type == "deleted":
                        info = d.get("deleted", {})
                    else:
                        info = d.get("after", {})

                    if info:
                        day    = info.get("day", "")
                        period = info.get("period", "")
                        if day and period:
                            slot_info = f"{DAYS_KR[day - 1]} {period}교시"
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
                self.table.setItem(row, 3, self._item(slot_info))

                # 상세 내용 셀: 사람이 읽기 쉬운 형태로 변환합니다.
                self.table.setItem(row, 4, self._item(
                    self._format_details(log.details, log.change_type)
                ))
        finally:
            session.close()

    def _item(self, text: str) -> QTableWidgetItem:
        """가운데 정렬된 QTableWidgetItem 을 생성하는 헬퍼입니다."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _format_details(self, details_str: str, change_type: str) -> str:
        """
        details JSON 을 사람이 읽기 쉬운 텍스트로 변환합니다.
        JSON 파싱 실패 시 원본 문자열 앞 80자를 반환합니다.
        """
        try:
            d = json.loads(details_str) if details_str else {}
        except json.JSONDecodeError:
            return details_str[:80]

        if change_type == "created":
            after = d.get("after", {})
            return f"신규 생성 (과목ID:{after.get('subject_id')}, 교사ID:{after.get('teacher_id')})"

        elif change_type == "modified":
            before = d.get("before", {})
            after  = d.get("after", {})
            parts  = []
            if before.get("subject_id") != after.get("subject_id"):
                parts.append(f"과목:{before.get('subject_id')}→{after.get('subject_id')}")
            if before.get("teacher_id") != after.get("teacher_id"):
                parts.append(f"교사:{before.get('teacher_id')}→{after.get('teacher_id')}")
            if before.get("room_id") != after.get("room_id"):
                parts.append(f"교실:{before.get('room_id')}→{after.get('room_id')}")
            return ", ".join(parts) if parts else "변경 없음"

        elif change_type == "deleted":
            deleted = d.get("deleted", {})
            return f"삭제됨 (과목ID:{deleted.get('subject_id')}, 교사ID:{deleted.get('teacher_id')})"

        return ""

    def _on_selection_changed(self):
        """행 선택 변경 시 하단 상세 영역에 선택된 행의 내용을 표시합니다."""
        row = self.table.currentRow()
        if row < 0:
            self._txt_detail.clear()
            return
        details = self.table.item(row, 4).text()
        self._txt_detail.setPlainText(details)
