"""교실 및 특별실 관리 화면"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
    QFrame, QMessageBox, QHeaderView, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from database.connection import get_session
from database.models import Room

BTN_PRIMARY = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"

ROOM_TYPES = ["일반", "과학실", "음악실", "미술실", "체육관", "컴퓨터실", "어학실", "도서관", "기타"]


class RoomSetupWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("교실 / 특별실 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f_layout = QVBoxLayout(frame)
        f_layout.setContentsMargins(12, 10, 12, 10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("교실명:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("예: 1-1교실, 과학1실")
        self.edit_name.setFixedWidth(140)
        row1.addWidget(self.edit_name)

        row1.addSpacing(8)
        row1.addWidget(QLabel("유형:"))
        self.cb_type = QComboBox()
        for t in ROOM_TYPES:
            self.cb_type.addItem(t)
        self.cb_type.setFixedWidth(100)
        row1.addWidget(self.cb_type)

        row1.addSpacing(8)
        row1.addWidget(QLabel("수용인원:"))
        self.spin_cap = QSpinBox()
        self.spin_cap.setRange(1, 200)
        self.spin_cap.setValue(30)
        self.spin_cap.setFixedWidth(70)
        row1.addWidget(self.spin_cap)

        row1.addSpacing(8)
        row1.addWidget(QLabel("층:"))
        self.spin_floor = QSpinBox()
        self.spin_floor.setRange(1, 10)
        self.spin_floor.setValue(1)
        self.spin_floor.setFixedWidth(60)
        row1.addWidget(self.spin_floor)

        row1.addSpacing(8)
        row1.addWidget(QLabel("비고:"))
        self.edit_notes = QLineEdit()
        self.edit_notes.setFixedWidth(140)
        row1.addWidget(self.edit_notes)

        btn_add = QPushButton("교실 추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_room)
        row1.addWidget(btn_add)
        row1.addStretch()
        f_layout.addLayout(row1)

        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["ID", "교실명", "유형", "수용", "층", "비고"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setStyleSheet("border:none;")
        f_layout.addWidget(self.tbl)

        btn_del = QPushButton("선택 교실 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._del_room)
        f_layout.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(frame)
        layout.addStretch()

    def _load_data(self):
        session = get_session()
        try:
            rooms = session.query(Room).order_by(Room.room_type, Room.name).all()
            self.tbl.setRowCount(len(rooms))
            for row, r in enumerate(rooms):
                self.tbl.setItem(row, 0, QTableWidgetItem(str(r.id)))
                self.tbl.setItem(row, 1, QTableWidgetItem(r.name))
                self.tbl.setItem(row, 2, QTableWidgetItem(r.room_type))
                self.tbl.setItem(row, 3, QTableWidgetItem(str(r.capacity)))
                self.tbl.setItem(row, 4, QTableWidgetItem(str(r.floor)))
                self.tbl.setItem(row, 5, QTableWidgetItem(r.notes or ""))
        finally:
            session.close()

    def refresh(self):
        self._load_data()

    def _add_room(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "교실명을 입력해 주세요.")
            return
        session = get_session()
        try:
            r = Room(
                name=name,
                room_type=self.cb_type.currentText(),
                capacity=self.spin_cap.value(),
                floor=self.spin_floor.value(),
                notes=self.edit_notes.text().strip(),
            )
            session.add(r)
            session.commit()
            self.edit_name.clear()
            self.edit_notes.clear()
            self._load_data()
        finally:
            session.close()

    def _del_room(self):
        row = self.tbl.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 교실을 선택해 주세요.")
            return
        rid = int(self.tbl.item(row, 0).text())
        session = get_session()
        try:
            session.query(Room).filter_by(id=rid).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()
