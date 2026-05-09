"""
시간표 셀 수정 다이얼로그 — 직접 수정 또는 변경 신청
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLabel, QComboBox, QTextEdit, QDialogButtonBox,
    QPushButton, QGroupBox,
)
from PyQt6.QtCore import Qt
from database.connection import get_session
from database.models import (
    TimetableEntry, Subject, Teacher, Room, SchoolClass,
    SubjectClassAssignment,
)


DAYS_KR = ["월", "화", "수", "목", "금"]


class EditDialog(QDialog):
    def __init__(self, entry: TimetableEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.direct_edit = False
        self._session = get_session()
        self._init_ui()
        self._populate()

    def _init_ui(self):
        self.setWindowTitle("시간표 수정")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        # 현재 정보
        info_group = QGroupBox("현재 시간표")
        info_layout = QFormLayout(info_group)
        school_class = self._session.query(SchoolClass).get(self.entry.school_class_id)
        self._lbl_class = QLabel(school_class.display_name if school_class else "")
        info_layout.addRow("학반:", self._lbl_class)
        self._lbl_slot = QLabel(f"{DAYS_KR[self.entry.day_of_week - 1]}요일 {self.entry.period}교시")
        info_layout.addRow("시간:", self._lbl_slot)
        current_subject = self._session.query(Subject).get(self.entry.subject_id)
        self._lbl_subject = QLabel(current_subject.name if current_subject else "")
        info_layout.addRow("현재 과목:", self._lbl_subject)
        current_teacher = self._session.query(Teacher).get(self.entry.teacher_id)
        self._lbl_teacher = QLabel(current_teacher.name if current_teacher else "")
        info_layout.addRow("현재 교사:", self._lbl_teacher)
        layout.addWidget(info_group)

        # 변경 폼
        change_group = QGroupBox("변경 내용")
        change_layout = QFormLayout(change_group)

        self._cmb_subject = QComboBox()
        self._cmb_subject.addItem("(변경 없음)", None)
        assignments = self._session.query(SubjectClassAssignment).filter_by(
            school_class_id=self.entry.school_class_id
        ).all()
        seen_subject_ids = set()
        for a in assignments:
            subj = self._session.query(Subject).get(a.subject_id)
            if subj and subj.id not in seen_subject_ids:
                seen_subject_ids.add(subj.id)
                self._cmb_subject.addItem(subj.name, subj.id)
        change_layout.addRow("새 과목:", self._cmb_subject)

        self._cmb_teacher = QComboBox()
        self._cmb_teacher.addItem("(변경 없음)", None)
        all_teachers = self._session.query(Teacher).order_by(Teacher.name).all()
        for t in all_teachers:
            self._cmb_teacher.addItem(t.name, t.id)
        change_layout.addRow("새 교사:", self._cmb_teacher)

        self._cmb_room = QComboBox()
        self._cmb_room.addItem("(변경 없음)", None)
        all_rooms = self._session.query(Room).order_by(Room.name).all()
        for r in all_rooms:
            self._cmb_room.addItem(r.name, r.id)
        change_layout.addRow("새 교실:", self._cmb_room)

        layout.addWidget(change_group)

        # 사유
        reason_group = QGroupBox("변경 사유")
        reason_layout = QVBoxLayout(reason_group)
        self._txt_reason = QTextEdit()
        self._txt_reason.setMaximumHeight(80)
        self._txt_reason.setPlaceholderText("변경 사유를 입력하세요...")
        reason_layout.addWidget(self._txt_reason)
        layout.addWidget(reason_group)

        # 버튼
        btn_layout = QHBoxLayout()
        self._btn_direct = QPushButton("직접 수정")
        self._btn_direct.setStyleSheet(
            "QPushButton { background-color: #1B4F8A; color: white; font-weight: bold; "
            "border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #163d6a; }"
        )
        self._btn_direct.clicked.connect(self._on_direct_edit)
        btn_layout.addWidget(self._btn_direct)

        self._btn_request = QPushButton("변경 신청")
        self._btn_request.setStyleSheet(
            "QPushButton { background-color: #E67E22; color: white; font-weight: bold; "
            "border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #D35400; }"
        )
        self._btn_request.clicked.connect(self._on_request)
        btn_layout.addWidget(self._btn_request)

        btn_cancel = QPushButton("취소")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def _populate(self):
        pass

    def _on_direct_edit(self):
        self.direct_edit = True
        self.accept()

    def _on_request(self):
        self.direct_edit = False
        self.accept()

    def get_changes(self) -> dict:
        return {
            "new_subject_id": self._cmb_subject.currentData(),
            "new_teacher_id": self._cmb_teacher.currentData(),
            "new_room_id": self._cmb_room.currentData(),
            "reason": self._txt_reason.toPlainText().strip(),
        }

    def closeEvent(self, event):
        self._session.close()
        super().closeEvent(event)
