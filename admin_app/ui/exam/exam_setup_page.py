"""
시험 관리 화면 (2026-09-19 신규, 2026-10-04 혼합 시험실·미참여 날짜 추가)

다섯 개의 섹션으로 구성됩니다:
  1. 시험 생성 폼 — 시험 기본 정보(이름·기간·교시 운영 규칙·감독 금지 규칙) 입력.
     저장 시 기간×교시 수만큼 ExamPeriod 가 자동 생성됩니다.
  2. 시험 목록 — 생성된 시험 조회·게시·삭제. 목록에서 선택한 시험이
     아래 3·4번 섹션의 대상이 됩니다.
     게시(publish)하면 교사 앱에서 시험표·감독표가 조회 가능해집니다.
  3. 학년별 시험 미참여 날짜 — 특정 학년이 시험 기간 중 일부 날짜에
     정상수업을 하는 경우(예: 3학년이 첫날만 정상수업) 등록합니다.
     등록된 날짜는 그 학년의 시험 시간표·감독 슬롯 생성에서 제외됩니다.
  4. 혼합 시험실(선택과목 등) — 여러 반 학생이 섞이는 시험실(2학년
     선택과목, 3학년 공통 고사/미선택실 등)을 등록합니다. 등록 후
     감독 자동 배정을 실행하면 이 시험실도 함께 배정됩니다.
  5. 감독 불가 신청 승인 — 교사가 제출한 감독 불가 신청(pending)을
     승인/거절합니다. 승인된 신청은 다음 감독 자동 배정부터 하드 제약으로
     반영됩니다 (미승인 상태로 감독이 빠지는 사고 방지).

데이터 접근 방식:
  기존 관리자 앱 설정 페이지(ui/setup/*)와 동일하게 SQLAlchemy 로 DB 에
  직접 접근합니다. 게시 알림만 예외적으로 ApiClient 를 사용해 서버의
  POST /exams/{id}/publish 를 호출합니다 — 알림 발송 로직이 서버에만
  있기 때문입니다. 서버에 접속할 수 없으면 DB 상태만 변경합니다
  (알림은 채팅 공지로 보완).

교시 시각 계산 규칙(요구사항 4)은 core.exam_scheduler.rebuild_exam_periods
의 단일 구현을 재사용합니다 — 화면마다 계산식을 따로 두면 서버 API 와
시각이 어긋날 위험이 있기 때문입니다.
"""
import json
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem, QFrame, QMessageBox, QHeaderView,
    QComboBox, QDateEdit, QTimeEdit, QCheckBox, QListWidget,
    QListWidgetItem, QAbstractItemView,
)
from PyQt6.QtCore import QDate, QTime, Qt
from PyQt6.QtGui import QFont, QColor

from database.connection import get_session
from database.models import (
    AcademicTerm, Exam, ExamPeriod, InvigilationConstraint, Teacher,
    Grade, SchoolClass, Subject, ExamRoom, ExamGradeDateExclusion,
)
from core.exam_scheduler import rebuild_exam_periods

# 공통 스타일 — 기존 설정 페이지(class_setup.py)와 동일한 톤을 유지합니다.
HEADER_STYLE = "background:#1B4F8A; color:white; font-weight:bold; padding:6px;"
BTN_PRIMARY  = "background:#1B4F8A; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_SUCCESS  = "background:#27AE60; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;"
BTN_DANGER   = "background:#C0392B; color:white; border-radius:4px; padding:6px 14px;"
BTN_WARN     = "background:#E67E22; color:white; border-radius:4px; padding:6px 14px;"

# 상태 표시 색 — 게시된 시험은 강조, 초안은 회색 표기
STATUS_COLORS = {"draft": QColor("#7F8C8D"), "published": QColor("#27AE60")}


class ExamSetupWidget(QWidget):
    """
    시험 관리 화면 위젯.

    Args:
        api_client: 로그인된 ApiClient (게시 알림용). None 이면 게시 시
                    DB 상태만 변경합니다 — 서버 없이 구동하는 테스트·
                    오프라인 환경에서 동작하기 위한 폴백 경로입니다.
    """

    def __init__(self, api_client=None, parent=None):
        super().__init__(parent)
        self._client = api_client
        self._init_ui()
        self._load_data()

    # ── UI 구성 ─────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        title = QLabel("시험 관리")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #1B4F8A;")
        layout.addWidget(title)

        layout.addWidget(self._build_exam_form())
        layout.addWidget(self._build_exam_list(), stretch=1)
        layout.addWidget(self._build_grade_exclusion_panel(), stretch=1)
        layout.addWidget(self._build_room_panel(), stretch=1)
        layout.addWidget(self._build_constraint_panel(), stretch=1)

    def _build_exam_form(self) -> QFrame:
        """섹션 1: 시험 생성 폼."""
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("시험 추가")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        # ── 1행: 이름·유형·학급급·대상 학년 ────────────────────────────
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("시험명:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("예: 1학기 중간고사")
        self.edit_name.setFixedWidth(160)
        row1.addWidget(self.edit_name)

        row1.addSpacing(8)
        row1.addWidget(QLabel("유형:"))
        self.cmb_type = QComboBox()
        self.cmb_type.addItem("중간고사", "midterm")
        self.cmb_type.addItem("기말고사", "final")
        self.cmb_type.addItem("모의고사", "mock")
        row1.addWidget(self.cmb_type)

        row1.addSpacing(8)
        row1.addWidget(QLabel("학급:"))
        self.cmb_level = QComboBox()
        # 요구사항 1: 고등학교 기본, 설정으로 중학교 전환 (기능 차이 없음 — 표기용)
        self.cmb_level.addItem("고등학교", "high")
        self.cmb_level.addItem("중학교", "middle")
        row1.addWidget(self.cmb_level)

        row1.addSpacing(8)
        row1.addWidget(QLabel("대상 학년:"))
        self.edit_grades = QLineEdit()
        self.edit_grades.setPlaceholderText("예: 1,2 (비우면 전체)")
        self.edit_grades.setFixedWidth(130)
        self.edit_grades.setToolTip(
            "쉼표로 구분된 학년 번호. 시험을 치르는 학년만 감독 대상이 되고,\n"
            "시험 치르지 않는 학년의 수업 교사는 감독 후보에서 제외됩니다."
        )
        row1.addWidget(self.edit_grades)

        row1.addStretch()
        f.addLayout(row1)

        # ── 2행: 기간·교시 운영 규칙 (요구사항 4) ───────────────────────
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("시작일:"))
        self.date_start = QDateEdit(QDate.currentDate())
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        row2.addWidget(self.date_start)

        row2.addSpacing(8)
        row2.addWidget(QLabel("종료일:"))
        self.date_end = QDateEdit(QDate.currentDate().addDays(1))
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        row2.addWidget(self.date_end)

        row2.addSpacing(8)
        row2.addWidget(QLabel("1교시 시작:"))
        self.time_first = QTimeEdit(QTime(8, 30))   # 요구사항 기본값 08:30
        self.time_first.setDisplayFormat("HH:mm")
        row2.addWidget(self.time_first)

        row2.addSpacing(8)
        row2.addWidget(QLabel("하루 교시:"))
        self.spin_periods = QSpinBox(); self.spin_periods.setRange(1, 10); self.spin_periods.setValue(3)
        row2.addWidget(self.spin_periods)

        row2.addSpacing(8)
        row2.addWidget(QLabel("시험시간(분):"))
        self.spin_exam_min = QSpinBox(); self.spin_exam_min.setRange(10, 240); self.spin_exam_min.setValue(50)
        row2.addWidget(self.spin_exam_min)

        row2.addSpacing(8)
        row2.addWidget(QLabel("쉬는시간(분):"))
        self.spin_break = QSpinBox(); self.spin_break.setRange(0, 60); self.spin_break.setValue(10)
        row2.addWidget(self.spin_break)

        row2.addSpacing(8)
        row2.addWidget(QLabel("준비(분):"))
        self.spin_prep = QSpinBox(); self.spin_prep.setRange(0, 30); self.spin_prep.setValue(5)
        self.spin_prep.setToolTip("준비령 = 각 교시 종료 N 분 전. 파생값이라 저장하지 않고 표시에만 사용합니다.")
        row2.addWidget(self.spin_prep)
        row2.addStretch()
        f.addLayout(row2)

        # ── 3행: 하루 과목 상한 + 감독 금지 규칙 (요구사항 2·7) ──────────
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("하루 과목 수 상한:"))
        self.spin_max_subjects = QSpinBox(); self.spin_max_subjects.setRange(1, 10); self.spin_max_subjects.setValue(3)
        row3.addWidget(self.spin_max_subjects)

        row3.addSpacing(16)
        # 요구사항 2: 감독 금지 규칙 기본 ON, 필요 시 해제 가능
        self.chk_ban_homeroom = QCheckBox("담임 반 감독 금지")
        self.chk_ban_homeroom.setChecked(True)
        row3.addWidget(self.chk_ban_homeroom)
        self.chk_ban_own = QCheckBox("담당 과목 시험 감독 금지")
        self.chk_ban_own.setChecked(True)
        row3.addWidget(self.chk_ban_own)

        row3.addSpacing(16)
        row3.addWidget(QLabel("부감독 기준(명 이상):"))
        self.spin_pair_threshold = QSpinBox()
        self.spin_pair_threshold.setRange(1, 100)
        self.spin_pair_threshold.setValue(20)
        self.spin_pair_threshold.setToolTip(
            "한 시험실의 학생 수가 이 값 이상이면 감독교사를 2인 1조로 배정합니다.\n"
            "학교별 실제 운영 기준이 다를 수 있습니다(예: 1학기 실 사례 기준 24명)."
        )
        row3.addWidget(self.spin_pair_threshold)

        btn_add = QPushButton("시험 추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_exam)
        row3.addStretch()
        row3.addWidget(btn_add)
        f.addLayout(row3)

        return frame

    def _build_exam_list(self) -> QFrame:
        """섹션 2: 시험 목록 + 게시/삭제 버튼."""
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("시험 목록")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        self.tbl_exams = QTableWidget(0, 7)
        self.tbl_exams.setHorizontalHeaderLabels(
            ["ID", "시험명", "기간", "교시 운영", "대상 학년", "상태", "규칙"])
        self.tbl_exams.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_exams.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_exams.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_exams.setStyleSheet("border:none;")
        # 선택 시험이 바뀌면 아래 "학년별 미참여 날짜"·"혼합 시험실" 패널의
        # 대상도 함께 갱신 — 두 패널 모두 "지금 선택된 시험"을 기준으로 동작.
        self.tbl_exams.itemSelectionChanged.connect(self._on_exam_selection_changed)
        f.addWidget(self.tbl_exams)

        btn_row = QHBoxLayout()
        btn_publish = QPushButton("선택 시험 게시")
        btn_publish.setStyleSheet(BTN_SUCCESS)
        btn_publish.clicked.connect(self._publish_exam)
        btn_row.addWidget(btn_publish)

        btn_del = QPushButton("선택 시험 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._delete_exam)
        btn_row.addWidget(btn_del)

        btn_row.addWidget(QLabel(
            "게시하면 교사 앱에서 시험표·감독표가 보입니다. 게시 후에는 수정할 수 없습니다."))
        btn_row.addStretch()
        f.addLayout(btn_row)
        return frame

    def _build_grade_exclusion_panel(self) -> QFrame:
        """
        섹션 3: 학년별 시험 미참여 날짜 (2026-10-04 추가).

        실제 사례: 시험 기간 첫날은 특정 학년만 정상수업이고 둘째 날부터
        그 학년도 시험(자습·고사)에 들어가는 경우. 여기 등록한 (학년,날짜)
        조합은 core.exam_scheduler 가 그 학년의 시험 시간표 배치·감독
        슬롯 생성에서 제외합니다.
        """
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("학년별 시험 미참여 날짜 (정상수업 등) — 위 목록에서 선택한 시험 대상")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        row = QHBoxLayout()
        row.addWidget(QLabel("학년:"))
        self.cmb_exclusion_grade = QComboBox()
        row.addWidget(self.cmb_exclusion_grade)
        row.addSpacing(8)
        row.addWidget(QLabel("미참여 날짜:"))
        self.date_exclusion = QDateEdit(QDate.currentDate())
        self.date_exclusion.setCalendarPopup(True)
        self.date_exclusion.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(self.date_exclusion)
        btn_add = QPushButton("추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_grade_exclusion)
        row.addWidget(btn_add)
        row.addStretch()
        f.addLayout(row)

        self.tbl_exclusions = QTableWidget(0, 3)
        self.tbl_exclusions.setHorizontalHeaderLabels(["ID", "학년", "미참여 날짜"])
        self.tbl_exclusions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_exclusions.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_exclusions.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_exclusions.setStyleSheet("border:none;")
        self.tbl_exclusions.setMaximumHeight(120)
        f.addWidget(self.tbl_exclusions)

        btn_del = QPushButton("선택 항목 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._delete_grade_exclusion)
        f.addWidget(btn_del)
        return frame

    def _build_room_panel(self) -> QFrame:
        """
        섹션 4: 혼합 시험실(선택과목 등) — 2026-10-04 추가.

        실제 사례: 2학년 선택과목(세계사 등)처럼 여러 반 학생이 섞여
        한 시험실에서 시험을 보거나, 3학년 공통 고사/미선택실처럼 반
        경계를 넘는 시험실을 등록합니다. 담임·담당과목 감독 금지는
        "포함 반" 목록을 기준으로 판정됩니다.
        """
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("혼합 시험실 (선택과목·공통 고사 등 — 여러 반이 섞이는 시험실) — "
                     "위 목록에서 선택한 시험 대상")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("교시:"))
        self.cmb_room_period = QComboBox()
        self.cmb_room_period.setMinimumWidth(160)
        row1.addWidget(self.cmb_room_period)
        row1.addSpacing(8)
        row1.addWidget(QLabel("학년:"))
        self.cmb_room_grade = QComboBox()
        self.cmb_room_grade.currentIndexChanged.connect(self._refresh_room_class_list)
        row1.addWidget(self.cmb_room_grade)
        row1.addSpacing(8)
        row1.addWidget(QLabel("과목(선택, 비우면 자습):"))
        self.cmb_room_subject = QComboBox()
        self.cmb_room_subject.addItem("(자습/미선택)", None)
        row1.addWidget(self.cmb_room_subject)
        row1.addSpacing(8)
        row1.addWidget(QLabel("인원:"))
        self.spin_room_count = QSpinBox()
        self.spin_room_count.setRange(1, 100)
        self.spin_room_count.setValue(24)
        row1.addWidget(self.spin_room_count)
        row1.addStretch()
        f.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("포함 반(복수 선택):"))
        self.list_room_classes = QListWidget()
        self.list_room_classes.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.list_room_classes.setMaximumHeight(70)
        row2.addWidget(self.list_room_classes, stretch=1)
        f.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("설명:"))
        self.edit_room_label = QLineEdit()
        self.edit_room_label.setPlaceholderText("예: 세계사(3반 교실)")
        row3.addWidget(self.edit_room_label, stretch=1)
        btn_add = QPushButton("시험실 추가")
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_exam_room)
        row3.addWidget(btn_add)
        f.addLayout(row3)

        self.tbl_rooms = QTableWidget(0, 5)
        self.tbl_rooms.setHorizontalHeaderLabels(["ID", "교시", "학년", "설명", "인원"])
        self.tbl_rooms.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_rooms.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_rooms.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_rooms.setStyleSheet("border:none;")
        self.tbl_rooms.setMaximumHeight(120)
        f.addWidget(self.tbl_rooms)

        btn_del = QPushButton("선택 시험실 삭제")
        btn_del.setStyleSheet(BTN_DANGER)
        btn_del.clicked.connect(self._delete_exam_room)
        f.addWidget(btn_del)
        return frame

    def _build_constraint_panel(self) -> QFrame:
        """섹션 3: 감독 불가 신청 승인."""
        frame = QFrame()
        frame.setStyleSheet("border:1px solid #CCCCCC; border-radius:6px; background:white;")
        f = QVBoxLayout(frame)
        f.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel("감독 불가 신청 (승인하면 다음 자동 배정부터 반영)")
        lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#1B4F8A; border:none;")
        f.addWidget(lbl)

        self.tbl_constraints = QTableWidget(0, 6)
        self.tbl_constraints.setHorizontalHeaderLabels(
            ["ID", "시험", "교사", "날짜", "교시", "사유 / 상태"])
        self.tbl_constraints.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_constraints.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_constraints.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_constraints.setStyleSheet("border:none;")
        f.addWidget(self.tbl_constraints)

        btn_row = QHBoxLayout()
        btn_approve = QPushButton("승인")
        btn_approve.setStyleSheet(BTN_SUCCESS)
        btn_approve.clicked.connect(self._approve_constraint)
        btn_row.addWidget(btn_approve)

        btn_reject = QPushButton("거절")
        btn_reject.setStyleSheet(BTN_WARN)
        btn_reject.clicked.connect(self._reject_constraint)
        btn_row.addWidget(btn_reject)
        btn_row.addStretch()
        f.addLayout(btn_row)
        return frame

    # ── 데이터 로딩 ─────────────────────────────────────────────────────

    def _load_data(self):
        """시험 목록·학년/과목 조회 목록·감독 불가 신청 목록을 갱신합니다."""
        self._load_grade_and_subject_lookups()
        self._load_exams()
        self._load_constraints()
        self._on_exam_selection_changed()   # 선택 시험 기준 패널(미참여 날짜·혼합 시험실) 갱신

    def _load_grade_and_subject_lookups(self):
        """
        학년·과목 조회 콤보박스를 DB 기준으로 채웁니다(혼합 시험실·미참여
        날짜 폼용). _load_data() 가 화면 전환·새로고침마다 호출하므로,
        학년/과목이 설정 화면에서 추가·삭제된 뒤에도 이 폼이 항상 최신
        목록을 보여줍니다.

        clear() 후 다시 addItem() 하는 매 호출마다 두 가지를 조심합니다:
          1. blockSignals(True/False) — clear()/addItem() 자체도
             currentIndexChanged 시그널을 발생시킵니다. cmb_room_grade 는
             그 시그널에 _refresh_room_class_list() 가 연결돼 있어, 신호를
             막지 않으면 콤보가 다시 채워지는 중간 과정(항목이 0개인
             순간 등)마다 반 목록이 불필요하게 깜빡이며 다시 그려집니다.
          2. currentData() 로 갱신 전 선택값을 저장했다가 findData() 로
             같은 항목을 다시 찾아 복원 — 그냥 clear() 만 하면 사용자가
             골라둔 학년이 매번 "첫 항목"으로 리셋되어, 예를 들어 혼합
             시험실 폼을 작성하다가 다른 화면에 갔다 오면 선택이
             날아가는 불편이 생깁니다.
        """
        session = get_session()
        try:
            grades = session.query(Grade).order_by(Grade.grade_number).all()
            for cmb in (self.cmb_exclusion_grade, self.cmb_room_grade):
                current = cmb.currentData()
                cmb.blockSignals(True)
                cmb.clear()
                for g in grades:
                    cmb.addItem(g.name, g.id)
                idx = cmb.findData(current)
                if idx >= 0:
                    cmb.setCurrentIndex(idx)
                cmb.blockSignals(False)

            subjects = session.query(Subject).order_by(Subject.name).all()
            current_subj = self.cmb_room_subject.currentData()
            self.cmb_room_subject.blockSignals(True)
            self.cmb_room_subject.clear()
            self.cmb_room_subject.addItem("(자습/미선택)", None)
            for s in subjects:
                self.cmb_room_subject.addItem(s.name, s.id)
            idx = self.cmb_room_subject.findData(current_subj)
            if idx >= 0:
                self.cmb_room_subject.setCurrentIndex(idx)
            self.cmb_room_subject.blockSignals(False)
        finally:
            session.close()
        self._refresh_room_class_list()

    def refresh(self):
        """페이지 전환 시 main_window 에서 호출되는 갱신 진입점."""
        self._load_data()

    def _load_exams(self):
        session = get_session()
        try:
            exams = session.query(Exam).order_by(Exam.start_date.desc()).all()
            self.tbl_exams.setRowCount(len(exams))
            for row, ex in enumerate(exams):
                self.tbl_exams.setItem(row, 0, QTableWidgetItem(str(ex.id)))
                self.tbl_exams.setItem(row, 1, QTableWidgetItem(ex.name))
                self.tbl_exams.setItem(row, 2, QTableWidgetItem(
                    f"{ex.start_date:%m/%d}~{ex.end_date:%m/%d}"))
                self.tbl_exams.setItem(row, 3, QTableWidgetItem(
                    f"{ex.first_period_start:%H:%M} 시작 / 하루 {ex.periods_per_day}교시 / {ex.exam_minutes}분"))

                # 대상 학년 표기 — 저장값은 JSON 배열 문자열이므로 파싱해 표시
                try:
                    grade_ids = json.loads(ex.target_grade_ids or "[]")
                except (json.JSONDecodeError, TypeError):
                    grade_ids = []
                grade_text = ", ".join(str(g) for g in grade_ids) if grade_ids else "전체"
                self.tbl_exams.setItem(row, 4, QTableWidgetItem(grade_text))

                # 상태 — 색으로 구분 (초안 회색 / 게시 녹색)
                status_item = QTableWidgetItem(
                    "게시됨" if ex.status == "published" else "초안")
                status_item.setForeground(STATUS_COLORS.get(ex.status, QColor("black")))
                self.tbl_exams.setItem(row, 5, status_item)

                rules = []
                if ex.ban_homeroom_invigilation:
                    rules.append("담임금지")
                if ex.ban_own_subject:
                    rules.append("담당과목금지")
                rules.append(f"부감독{ex.pair_threshold}명↑")
                self.tbl_exams.setItem(row, 6, QTableWidgetItem(
                    " / ".join(rules) if rules else "없음"))
        finally:
            session.close()

    def _load_constraints(self):
        session = get_session()
        try:
            rows = (
                session.query(InvigilationConstraint)
                .order_by(InvigilationConstraint.requested_at.desc())
                .all()
            )
            self.tbl_constraints.setRowCount(len(rows))
            for row, c in enumerate(rows):
                exam = session.get(Exam, c.exam_id)
                teacher = session.get(Teacher, c.teacher_id)
                self.tbl_constraints.setItem(row, 0, QTableWidgetItem(str(c.id)))
                self.tbl_constraints.setItem(row, 1, QTableWidgetItem(
                    exam.name if exam else f"#{c.exam_id}"))
                self.tbl_constraints.setItem(row, 2, QTableWidgetItem(
                    teacher.name if teacher else f"#{c.teacher_id}"))
                self.tbl_constraints.setItem(row, 3, QTableWidgetItem(
                    f"{c.exam_date:%m/%d}"))
                self.tbl_constraints.setItem(row, 4, QTableWidgetItem(
                    "전 교시" if c.period is None else f"{c.period}교시"))
                state_text = c.status
                if c.status == "approved" and c.reviewed_by:
                    state_text = f"승인({c.reviewed_by})"
                elif c.status == "rejected" and c.reviewed_by:
                    state_text = f"거절({c.reviewed_by})"
                item = QTableWidgetItem(f"{c.reason or '(사유 없음)'} — {state_text}")
                # pending 은 주황색으로 눈에 띄게 — 처리 대기 신청을 놓치지 않도록
                if c.status == "pending":
                    item.setForeground(QColor("#E67E22"))
                self.tbl_constraints.setItem(row, 5, item)
        finally:
            session.close()

    # ── 시험 생성·게시·삭제 ─────────────────────────────────────────────

    def _add_exam(self):
        """폼 입력값으로 시험을 생성하고 교시를 자동 생성합니다."""
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "시험명을 입력해 주세요.")
            return
        start = self.date_start.date().toPyDate()
        end = self.date_end.date().toPyDate()
        if end < start:
            QMessageBox.warning(self, "입력 오류", "종료일이 시작일보다 빠릅니다.")
            return

        # 대상 학년 파싱 — "1,2" → [1, 2]. 비어 있으면 전체 학년([]).
        grade_numbers = []
        for part in self.edit_grades.text().replace(" ", "").split(","):
            if part.isdigit():
                grade_numbers.append(int(part))

        session = get_session()
        try:
            term = (
                session.query(AcademicTerm)
                .filter_by(is_current=True)
                .order_by(AcademicTerm.id.desc())
                .first()
            )
            if term is None:
                QMessageBox.warning(
                    self, "학기 없음", "현재 학기가 없습니다. 먼저 학기를 등록해 주세요.")
                return

            # 학년 번호 → Grade id 매핑 (시험은 학년 id 를 JSON 으로 저장)
            if grade_numbers:
                from database.models import Grade
                grade_ids = [
                    g.id for g in session.query(Grade)
                    .filter(Grade.grade_number.in_(grade_numbers)).all()
                ]
                grade_ids_json = json.dumps(grade_ids)
            else:
                grade_ids_json = "[]"

            exam = Exam(
                term_id=term.id,
                name=name,
                exam_type=self.cmb_type.currentData(),
                school_level=self.cmb_level.currentData(),
                target_grade_ids=grade_ids_json,
                start_date=start,
                end_date=end,
                first_period_start=self.time_first.time().toPyTime(),
                periods_per_day=self.spin_periods.value(),
                break_minutes=self.spin_break.value(),
                prep_minutes=self.spin_prep.value(),
                exam_minutes=self.spin_exam_min.value(),
                max_subjects_per_day=self.spin_max_subjects.value(),
                ban_homeroom_invigilation=self.chk_ban_homeroom.isChecked(),
                ban_own_subject=self.chk_ban_own.isChecked(),
                pair_threshold=self.spin_pair_threshold.value(),
                status="draft",
            )
            session.add(exam)
            session.flush()
            # 기간·교시 규칙에 맞춰 ExamPeriod 자동 생성 (core 공통 구현 재사용)
            rebuild_exam_periods(session, exam)
            session.commit()
            self._load_data()
            QMessageBox.information(
                self, "완료", f"'{name}' 시험이 등록되었습니다.\n"
                "시험 시간표 / 감독 시간표 페이지에서 배치·배정을 진행하세요.")
        finally:
            session.close()

    def _selected_exam_id(self, show_warning: bool = True) -> int | None:
        """
        시험 목록에서 선택된 행의 시험 ID 반환.

        show_warning=False (조용히 조회만 하는 자동 갱신 경로 — 예:
        _on_exam_selection_changed, _load_rooms) 에서는 "시험을 선택해
        주세요" 안내창을 띄우지 않습니다. 사용자가 아무 시험도 선택하지
        않은 "정상 상태"일 뿐이라, 매 데이터 갱신마다 경고창이 뜨면
        방해가 됩니다.
        """
        row = self.tbl_exams.currentRow()
        if row < 0:
            if show_warning:
                QMessageBox.information(self, "안내", "시험을 선택해 주세요.")
            return None
        return int(self.tbl_exams.item(row, 0).text())

    def _publish_exam(self):
        """
        선택 시험을 게시합니다.

        ApiClient 가 있으면 서버의 POST /exams/{id}/publish 를 호출해
        전 교사 알림(exam_published + 감독 배정 안내)까지 함께 발송합니다.
        서버에 접속할 수 없는 환경이면 DB 상태만 published 로 변경합니다.
        """
        exam_id = self._selected_exam_id()
        if exam_id is None:
            return

        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            if exam is None:
                return
            if exam.status == "published":
                QMessageBox.information(self, "안내", "이미 게시된 시험입니다.")
                return
            reply = QMessageBox.question(
                self, "게시 확인",
                f"'{exam.name}' 을(를) 게시할까요?\n"
                "게시 후에는 시험표·기간 수정이 불가하며, 전 교사에게 알림이 갑니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            name = exam.name

            # 경로 1 — 서버 API 경유(알림 발송 포함)
            if self._client is not None and self._client.is_logged_in:
                try:
                    self._client.post(f"/exams/{exam_id}/publish", {})
                    self._load_data()
                    QMessageBox.information(self, "게시 완료", f"'{name}' 이(가) 게시되었습니다.")
                    return
                except Exception:
                    # 서버 통신 실패 → DB 직접 경로로 폴백 (아래에서 처리)
                    pass

            # 경로 2 — DB 직접 변경 (서버 부재 시). 알림은 채팅 공지로 보완.
            exam.status = "published"
            session.commit()
            self._load_data()
            QMessageBox.information(
                self, "게시 완료",
                f"'{name}' 이(가) 게시되었습니다.\n"
                "(서버에 접속할 수 없어 알림은 발송되지 않았습니다 — 채팅 공지를 권장합니다.)")
        finally:
            session.close()

    def _delete_exam(self):
        """선택 시험을 삭제합니다. cascade 로 교시·시험표·감독 배정·불가 신청이 함께 삭제됩니다."""
        exam_id = self._selected_exam_id()
        if exam_id is None:
            return
        reply = QMessageBox.question(
            self, "삭제 확인",
            "시험과 딸린 교시·시험표·감독 배정·감독 불가 신청이 모두 삭제됩니다. 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            session.query(Exam).filter_by(id=exam_id).delete()
            session.commit()
            self._load_data()
        finally:
            session.close()

    # ── 감독 불가 신청 승인/거절 ────────────────────────────────────────

    def _approve_constraint(self):
        """선택한 감독 불가 신청을 승인합니다. 승인 즉시 하드 제약으로 반영됩니다."""
        self._review_constraint("approved")

    def _reject_constraint(self):
        """선택한 감독 불가 신청을 거절합니다. 감독 배정에 반영되지 않습니다."""
        self._review_constraint("rejected")

    def _review_constraint(self, new_status: str):
        row = self.tbl_constraints.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "처리할 신청을 선택해 주세요.")
            return
        cid = int(self.tbl_constraints.item(row, 0).text())

        session = get_session()
        try:
            c = session.get(InvigilationConstraint, cid)
            if c is None:
                return
            if c.status != "pending":
                QMessageBox.information(self, "안내", "이미 처리된 신청입니다.")
                return
            c.status = new_status
            # 승인/거절자·시각 기록 — 누가 처리했는지 감사 추적용
            c.reviewed_by = "관리자앱"
            c.reviewed_at = datetime.now()
            session.commit()
            self._load_constraints()
        finally:
            session.close()

    # ── 학년별 시험 미참여 날짜 ───────────────────────────────────────────

    def _on_exam_selection_changed(self):
        """
        시험 목록 선택이 바뀔 때마다 "학년별 미참여 날짜"·"혼합 시험실"
        패널을 그 시험 기준으로 다시 그립니다. 교시 콤보(cmb_room_period)도
        선택된 시험의 ExamPeriod 로 다시 채웁니다.
        """
        exam_id = self._selected_exam_id(show_warning=False)

        self.cmb_room_period.blockSignals(True)
        self.cmb_room_period.clear()
        if exam_id is not None:
            session = get_session()
            try:
                periods = (
                    session.query(ExamPeriod).filter_by(exam_id=exam_id)
                    .order_by(ExamPeriod.exam_date, ExamPeriod.period).all()
                )
                for p in periods:
                    self.cmb_room_period.addItem(
                        f"{p.exam_date:%m/%d} {p.period}교시", p.id)
            finally:
                session.close()
        self.cmb_room_period.blockSignals(False)

        self._load_grade_exclusions()
        self._load_rooms()

    def _add_grade_exclusion(self):
        """
        선택된 시험·학년·날짜로 "시험 미참여 날짜"(ExamGradeDateExclusion)를
        등록합니다.

        날짜 유효성 검사(시험 기간 안인지)를 여기서도 수행하는 이유: 서버
        API(POST /exams/{id}/grade-exclusions)는 같은 검증을 하지만, 관리자
        앱은 DB 에 직접 접근하는 구조라 API 를 거치지 않습니다. 검증을
        생략하면 시험 기간 밖의 날짜가 등록돼도 아무 효과가 없는데(해당
        날짜엔 애초에 ExamPeriod 자체가 없어 조회되지 않음) 사용자가
        "등록했는데 왜 반영이 안 되냐"고 혼란스러워할 수 있어, 입력 시점에
        바로 알려줍니다.

        중복 등록 방지: (exam_id, grade_id, exam_date) 가 이미 있으면 다시
        추가하지 않습니다 — DB 의 UniqueConstraint(uq_grade_date_exclusion)
        가 있긴 하지만, 그 위반으로 예외가 터지는 대신 조용히 무시해 같은
        학년·날짜를 두 번 눌러도 사용자에게 에러창이 뜨지 않게 합니다.
        """
        exam_id = self._selected_exam_id()
        if exam_id is None:
            return
        grade_id = self.cmb_exclusion_grade.currentData()
        if grade_id is None:
            QMessageBox.information(self, "안내", "학년 정보가 없습니다. 학년을 먼저 등록하세요.")
            return
        exam_date = self.date_exclusion.date().toPyDate()

        session = get_session()
        try:
            exam = session.get(Exam, exam_id)
            if exam is None:
                return
            if not (exam.start_date <= exam_date <= exam.end_date):
                QMessageBox.warning(self, "입력 오류", "시험 기간 밖의 날짜입니다.")
                return
            existing = session.query(ExamGradeDateExclusion).filter_by(
                exam_id=exam_id, grade_id=grade_id, exam_date=exam_date,
            ).first()
            if existing is None:
                session.add(ExamGradeDateExclusion(
                    exam_id=exam_id, grade_id=grade_id, exam_date=exam_date,
                ))
                session.commit()
            self._load_grade_exclusions()
        finally:
            session.close()

    def _load_grade_exclusions(self):
        """
        선택된 시험의 "시험 미참여 날짜" 목록을 테이블에 다시 그립니다.

        exam_id=None(아무 시험도 선택 안 됨)인 상태는 정상적인 초기 화면
        상태이므로 _selected_exam_id(show_warning=False) 로 호출해 경고창을
        띄우지 않습니다 — _on_exam_selection_changed() 가 시험 목록이
        로드될 때마다(처음 화면이 뜰 때 포함) 이 함수를 호출하기 때문에,
        경고를 띄우면 화면을 열 때마다 불필요한 알림이 뜹니다.
        """
        exam_id = self._selected_exam_id(show_warning=False)
        session = get_session()
        try:
            rows = []
            if exam_id is not None:
                rows = (
                    session.query(ExamGradeDateExclusion).filter_by(exam_id=exam_id)
                    .order_by(ExamGradeDateExclusion.exam_date).all()
                )
            self.tbl_exclusions.setRowCount(len(rows))
            for row, ex in enumerate(rows):
                grade = session.get(Grade, ex.grade_id)
                self.tbl_exclusions.setItem(row, 0, QTableWidgetItem(str(ex.id)))
                self.tbl_exclusions.setItem(row, 1, QTableWidgetItem(
                    grade.name if grade else f"#{ex.grade_id}"))
                self.tbl_exclusions.setItem(row, 2, QTableWidgetItem(f"{ex.exam_date:%Y-%m-%d}"))
        finally:
            session.close()

    def _delete_grade_exclusion(self):
        """
        선택한 "시험 미참여 날짜" 행을 삭제합니다.

        삭제의 효과: 그 학년은 다음 자동 배치/배정부터 그 날짜에도 다시
        시험 대상이 됩니다(원래의 target_grade_ids 기준으로 복귀) — 별도
        되돌림 로직이 필요 없는 이유는 ExamGradeDateExclusion 이 "예외
        블랙리스트"라 행을 지우면 곧바로 예외가 사라지기 때문입니다.
        """
        row = self.tbl_exclusions.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 항목을 선택해 주세요.")
            return
        exclusion_id = int(self.tbl_exclusions.item(row, 0).text())
        session = get_session()
        try:
            session.query(ExamGradeDateExclusion).filter_by(id=exclusion_id).delete()
            session.commit()
            self._load_grade_exclusions()
        finally:
            session.close()

    # ── 혼합 시험실(선택과목 등) ──────────────────────────────────────────

    def _refresh_room_class_list(self):
        """
        선택된 학년의 반 목록으로 "포함 반" 다중 선택 목록을 다시 그립니다.

        학년 콤보(cmb_room_grade) 변경 시그널에 연결돼 있습니다 — 학년을
        바꾸면 반 목록도 당연히 바뀌어야 하는데, 이전 학년의 반이 그대로
        남아 있으면 관리자가 잘못된 반을 혼합 시험실에 포함시키는 실수를
        할 수 있습니다(예: 2학년 선택과목인데 목록에 1학년 반이 남아 있어
        실수로 체크). 그래서 선택이 바뀔 때마다 완전히 새로 그립니다.

        QListWidgetItem.setData(UserRole, sc.id) 로 각 항목에 반 id 를
        숨겨 담아둡니다 — 표시 텍스트(반 이름)는 바뀔 수 있어도 id 는
        안정적이므로, _add_exam_room() 이 선택된 항목에서 id 를 그대로
        꺼내 쓸 수 있게 합니다.
        """
        self.list_room_classes.clear()
        grade_id = self.cmb_room_grade.currentData()
        if grade_id is None:
            return
        session = get_session()
        try:
            classes = (
                session.query(SchoolClass).filter_by(grade_id=grade_id)
                .order_by(SchoolClass.class_number).all()
            )
            for sc in classes:
                item = QListWidgetItem(sc.display_name)
                item.setData(Qt.ItemDataRole.UserRole, sc.id)
                self.list_room_classes.addItem(item)
        finally:
            session.close()

    def _add_exam_room(self):
        """
        입력된 정보로 혼합 시험실(ExamRoom)을 생성합니다.

        포함 반을 1개 이상 선택해야 하는 이유: source_class_ids 가 비어
        있으면 core.exam_scheduler._collect_hard_constraints() 가 담임·
        담당과목 금지 교사 집합을 계산할 근거(어느 반 학생이 섞였는지)가
        없어, 사실상 아무도 감독 금지되지 않는 "구멍"이 생깁니다. 그런
        상태로 저장되는 것을 막기 위해 생성 시점에 검증합니다.

        설명(label)을 필수로 받는 이유: 관리자 화면·감독표 그리드·PDF/CSV
        출력 어디서나 이 시험실은 "반 이름" 대신 label 로만 표시됩니다
        (단일 반이 아니므로 표시할 반 이름 자체가 없음) — 비워두면 모든
        화면에 빈 칸이 뜨게 됩니다.
        """
        exam_id = self._selected_exam_id()
        if exam_id is None:
            return
        period_id = self.cmb_room_period.currentData()
        if period_id is None:
            QMessageBox.information(self, "안내", "교시를 선택해 주세요(교시가 없으면 먼저 시험 기간을 등록하세요).")
            return
        grade_id = self.cmb_room_grade.currentData()
        if grade_id is None:
            QMessageBox.information(self, "안내", "학년 정보가 없습니다.")
            return
        source_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.list_room_classes.selectedItems()
        ]
        if not source_ids:
            QMessageBox.warning(self, "입력 오류", "포함 반을 1개 이상 선택해 주세요.")
            return
        label = self.edit_room_label.text().strip()
        if not label:
            QMessageBox.warning(self, "입력 오류", "설명을 입력해 주세요.")
            return

        session = get_session()
        try:
            room = ExamRoom(
                exam_id=exam_id, period_id=period_id, grade_id=grade_id,
                subject_id=self.cmb_room_subject.currentData(),
                source_class_ids=json.dumps(source_ids),
                student_count=self.spin_room_count.value(),
                label=label,
            )
            session.add(room)
            session.commit()
            self.edit_room_label.clear()
            self._load_rooms()
        finally:
            session.close()

    def _load_rooms(self):
        """
        선택된 시험의 혼합 시험실 목록을 테이블에 다시 그립니다.

        _load_grade_exclusions() 와 같은 이유로 show_warning=False —
        "아직 아무 시험도 선택 안 함"은 정상 상태입니다.
        """
        exam_id = self._selected_exam_id(show_warning=False)
        session = get_session()
        try:
            rows = []
            if exam_id is not None:
                rows = session.query(ExamRoom).filter_by(exam_id=exam_id).all()
            self.tbl_rooms.setRowCount(len(rows))
            for row, r in enumerate(rows):
                period = session.get(ExamPeriod, r.period_id)
                grade = session.get(Grade, r.grade_id)
                self.tbl_rooms.setItem(row, 0, QTableWidgetItem(str(r.id)))
                self.tbl_rooms.setItem(row, 1, QTableWidgetItem(
                    f"{period.exam_date:%m/%d} {period.period}교시" if period else "-"))
                self.tbl_rooms.setItem(row, 2, QTableWidgetItem(
                    grade.name if grade else f"#{r.grade_id}"))
                self.tbl_rooms.setItem(row, 3, QTableWidgetItem(r.label))
                self.tbl_rooms.setItem(row, 4, QTableWidgetItem(
                    str(r.student_count) if r.student_count is not None else "-"))
        finally:
            session.close()

    def _delete_exam_room(self):
        """
        선택한 혼합 시험실을 삭제합니다.

        딸린 InvigilationAssignment(그 시험실의 감독 배정)을 먼저 지우는
        이유: exam_room_id 가 ExamRoom.id 를 참조하는 FK 인데, ExamRoom
        모델에 cascade 관계가 선언돼 있지 않아(ExamRoom 쪽은 "독립적으로
        관리되는 보조 테이블"이라 Exam 의 cascade 체계에만 걸려 있음—
        shared/models.py 의 Exam.rooms 참조) SQLAlchemy 가 자동으로
        함께 지워주지 않습니다. 먼저 지우지 않으면 FK 제약 위반으로
        ExamRoom 삭제 자체가 실패하거나(DB 엔진에 따라), 참조가 끊긴
        "갈 곳 없는" 배정 행이 남을 수 있습니다. 서버 API 의
        delete_exam_room() 과 동일한 순서를 따릅니다.
        """
        row = self.tbl_rooms.currentRow()
        if row < 0:
            QMessageBox.information(self, "안내", "삭제할 시험실을 선택해 주세요.")
            return
        room_id = int(self.tbl_rooms.item(row, 0).text())
        session = get_session()
        try:
            from database.models import InvigilationAssignment
            session.query(InvigilationAssignment).filter_by(exam_room_id=room_id).delete()
            session.query(ExamRoom).filter_by(id=room_id).delete()
            session.commit()
            self._load_rooms()
        finally:
            session.close()