"""
메인 윈도우 — 사이드바 네비게이션 + 콘텐츠 영역(QStackedWidget)

레이아웃 구조:
  QMainWindow
  └── QWidget (central)
      └── QHBoxLayout
          ├── QFrame (sidebar, 고정 너비 200px)
          │   └── QVBoxLayout
          │       ├── 앱 타이틀 QLabel
          │       ├── 섹션 QLabel × N
          │       └── QPushButton (네비게이션/액션) × N
          └── QStackedWidget (pages)
              ├── [0] ClassSetupWidget     — 편제 설정
              ├── [1] TeacherSetupWidget   — 교사 관리
              ├── [2] SubjectSetupWidget   — 교과목/시수
              ├── [3] RoomSetupWidget      — 교실 관리
              ├── [4] ClassTimetableView   — 반별 시간표
              ├── [5] TeacherTimetableView — 교사별 시간표
              ├── [6] ChangeRequestWidget  — 변경 신청/결재
              ├── [7] CalendarWidget       — 학사일정
              └── [8] HistoryWidget        — 변경 이력

데이터 연결성 (Data Connectivity):
  모든 페이지 전환 시 refresh() 를 호출하여 DB 의 최신 데이터를 다시 읽습니다.
  이를 통해 선행 작업(예: 학반 등록)의 결과가 후속 페이지(예: 교사 관리의
  담임 학반 콤보박스)에 자동으로 연동됩니다.

  데이터 흐름 예시:
    편제 설정(0): 학년·반 등록
        ↓ (페이지 전환 시 refresh)
    교사 관리(1): 담임 학반 콤보박스에 등록된 반 목록 표시
    교과목/시수(2): 학반·교과·교사 콤보박스에 등록된 목록 표시
        ↓ (시수 배정 완료 후)
    자동 생성 → 반별 시간표(4)·교사별 시간표(5) 조회

자동 생성은 GenerateWorker(QThread)에서 실행되어 UI 가 멈추지 않습니다.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame,
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QDialogButtonBox, QMessageBox, QProgressDialog,
    QDateEdit, QCheckBox, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QFont, QIcon

from database.connection import get_session
from database.models import AcademicTerm
from core.generator import generate_timetable
from ui.setup.class_setup import ClassSetupWidget
from ui.setup.teacher_setup import TeacherSetupWidget
from ui.setup.subject_setup import SubjectSetupWidget
from ui.setup.room_setup import RoomSetupWidget
from ui.timetable.class_view import ClassTimetableView
from ui.timetable.teacher_view import TeacherTimetableView
from ui.timetable.request_list import ChangeRequestWidget
from ui.calendar.calendar_widget import CalendarWidget
from ui.history.history_view import HistoryWidget
from ui.export.pdf_export import PDFExportDialog
from ui.export.neis_export import NEISExportDialog
from ui.feedback import FeedbackDialog

# 사이드바 고정 너비 (픽셀)
SIDEBAR_W = 200

# 사이드바 네비게이션 버튼 공통 스타일시트
NAV_BTN_STYLE = """
QPushButton {
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 0;
    background: transparent;
    color: #D0E4F7;
    font-size: 13px;
}
QPushButton:hover {
    background: #163d6a;
    color: white;
}
QPushButton:checked {
    background: #0d2d52;
    color: white;
    font-weight: bold;
    border-left: 4px solid #5dade2;  /* 선택된 항목 좌측 강조 바 */
}
"""

# 사이드바 섹션 제목 레이블 스타일시트
SECTION_LABEL_STYLE = """
    color: #7fb3d3;
    font-size: 11px;
    font-weight: bold;
    padding: 14px 16px 4px 16px;
    letter-spacing: 1px;
"""


# ── 백그라운드 워커 ─────────────────────────────────────────────────────────

class GenerateWorker(QThread):
    """
    시간표 자동 생성을 별도 스레드에서 실행합니다.
    메인 스레드(UI)가 멈추지 않도록 QThread 를 사용합니다.

    Signals:
        finished(bool, str): 생성 완료 시 (성공여부, 메시지) 를 방출합니다.
    """
    finished = pyqtSignal(bool, str)

    def __init__(self, term_id: int, max_periods: int):
        super().__init__()
        self.term_id = term_id
        self.max_periods = max_periods

    def run(self):
        """QThread.start() 호출 시 자동으로 실행됩니다."""
        session = get_session()
        try:
            ok, msg = generate_timetable(session, self.term_id, self.max_periods)
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            session.close()


# ── 다이얼로그: 자동 생성 설정 ────────────────────────────────────────────

class GenerateDialog(QDialog):
    """
    자동 생성 설정 다이얼로그.
    사용자가 학기와 일 최대 교시를 선택한 뒤 '생성 시작'을 누릅니다.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("시간표 자동 생성")
        self.setMinimumWidth(380)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("시간표 자동 생성 설정")
        title.setFont(QFont("", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#1B4F8A;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        # 학기 콤보박스: DB 에서 학기 목록을 읽어 채웁니다.
        self.cb_term = QComboBox()
        self.cb_term.setMinimumWidth(200)
        session = get_session()
        try:
            terms = session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self.cb_term.addItem(str(t), t.id)   # userData 로 term.id 를 저장
            if not terms:
                self.cb_term.addItem("(학기 없음)", None)
        finally:
            session.close()
        form.addRow("학기:", self.cb_term)

        # 일 최대 교시 수 (4~9교시 중 선택)
        self.spin_periods = QSpinBox()
        self.spin_periods.setRange(4, 9)
        self.spin_periods.setValue(7)
        form.addRow("일 최대 교시:", self.spin_periods)

        layout.addLayout(form)

        # 안내 문구
        notice = QLabel(
            "※ 기존 해당 학기 시간표는 덮어씌워집니다.\n"
            "   교과/시수 배정이 완료된 후 실행하세요."
        )
        notice.setStyleSheet("color:#888; font-size:10pt;")
        layout.addWidget(notice)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("생성 시작")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    @property
    def term_id(self):
        """선택된 학기 ID를 반환합니다."""
        return self.cb_term.currentData()

    @property
    def max_periods(self):
        """선택된 일 최대 교시 수를 반환합니다."""
        return self.spin_periods.value()


# ── 다이얼로그: 학기 추가 ─────────────────────────────────────────────────

class TermDialog(QDialog):
    """학기 추가 다이얼로그. 연도·학기·현재 학기 여부를 입력받습니다."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("학기 추가")
        self.setMinimumWidth(300)
        layout = QFormLayout(self)
        layout.setSpacing(10)

        # 연도 스핀박스: 2020~2040 범위, 기본값은 현재 연도
        self.spin_year = QSpinBox()
        self.spin_year.setRange(2020, 2040)
        self.spin_year.setValue(QDate.currentDate().year())
        layout.addRow("연도:", self.spin_year)

        self.cb_semester = QComboBox()
        self.cb_semester.addItems(["1학기", "2학기"])
        layout.addRow("학기:", self.cb_semester)

        # 체크 시 다른 학기의 is_current 를 False 로 초기화한 뒤 이 학기를 True 로 설정합니다.
        self.chk_current = QCheckBox("현재 학기로 설정")
        self.chk_current.setChecked(True)
        layout.addRow("", self.chk_current)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    @property
    def year(self):
        return self.spin_year.value()

    @property
    def semester(self):
        # 콤보박스 인덱스 0 → 1학기, 1 → 2학기
        return self.cb_semester.currentIndex() + 1

    @property
    def is_current(self):
        return self.chk_current.isChecked()


# ── 다이얼로그: DB 연결 설정 ──────────────────────────────────────────────

class DBConfigDialog(QDialog):
    """
    데이터베이스 연결 설정 다이얼로그.
    SQLite(로컬 파일)와 PostgreSQL(네트워크) 중 선택할 수 있습니다.
    DB 종류 변경 시 해당 입력 폼이 표시/숨김 처리됩니다.
    """
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("데이터베이스 연결 설정")
        self.setMinimumWidth(420)
        self._cfg = cfg  # 현재 설정값을 초기값으로 사용합니다.
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("DB 연결 설정")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        form = QFormLayout()

        # DB 종류 선택 콤보박스
        self.cb_type = QComboBox()
        self.cb_type.addItems(["SQLite (로컬)", "PostgreSQL (네트워크)"])
        if self._cfg.get("db_type") == "postgresql":
            self.cb_type.setCurrentIndex(1)
        self.cb_type.currentIndexChanged.connect(self._toggle_pg)
        form.addRow("DB 종류:", self.cb_type)

        # ── SQLite 설정 프레임 ──────────────────────────────────────────
        self.sqlite_frame = QWidget()
        sf = QFormLayout(self.sqlite_frame)
        sf.setContentsMargins(0, 0, 0, 0)
        self.edit_sqlite_path = QLineEdit(self._cfg.get("sqlite_path", "timetable.db"))
        sf.addRow("파일 경로:", self.edit_sqlite_path)
        form.addRow(self.sqlite_frame)

        # ── PostgreSQL 설정 프레임 ─────────────────────────────────────
        self.pg_frame = QWidget()
        pf = QFormLayout(self.pg_frame)
        pf.setContentsMargins(0, 0, 0, 0)

        self.edit_pg_host = QLineEdit(self._cfg.get("pg_host", "localhost"))
        pf.addRow("호스트:", self.edit_pg_host)

        self.spin_pg_port = QSpinBox()
        self.spin_pg_port.setRange(1, 65535)
        self.spin_pg_port.setValue(self._cfg.get("pg_port", 5432))
        pf.addRow("포트:", self.spin_pg_port)

        self.edit_pg_dbname = QLineEdit(self._cfg.get("pg_dbname", "school_timetable"))
        pf.addRow("DB명:", self.edit_pg_dbname)

        self.edit_pg_user = QLineEdit(self._cfg.get("pg_user", "postgres"))
        pf.addRow("사용자:", self.edit_pg_user)

        self.edit_pg_pw = QLineEdit(self._cfg.get("pg_password", ""))
        self.edit_pg_pw.setEchoMode(QLineEdit.EchoMode.Password)  # 비밀번호 마스킹
        pf.addRow("비밀번호:", self.edit_pg_pw)

        form.addRow(self.pg_frame)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # 초기 상태에 맞게 프레임 표시/숨김
        self._toggle_pg(self.cb_type.currentIndex())

    def _toggle_pg(self, idx: int):
        """DB 종류에 따라 SQLite/PostgreSQL 설정 프레임을 전환합니다."""
        self.sqlite_frame.setVisible(idx == 0)
        self.pg_frame.setVisible(idx == 1)

    def get_config(self) -> dict:
        """현재 입력값을 딕셔너리로 반환합니다."""
        cfg = dict(self._cfg)
        if self.cb_type.currentIndex() == 0:
            cfg["db_type"] = "sqlite"
            cfg["sqlite_path"] = self.edit_sqlite_path.text().strip()
        else:
            cfg["db_type"] = "postgresql"
            cfg["pg_host"]     = self.edit_pg_host.text().strip()
            cfg["pg_port"]     = self.spin_pg_port.value()
            cfg["pg_dbname"]   = self.edit_pg_dbname.text().strip()
            cfg["pg_user"]     = self.edit_pg_user.text().strip()
            cfg["pg_password"] = self.edit_pg_pw.text()
        return cfg


# ── 메인 윈도우 ───────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """
    애플리케이션 최상위 윈도우.
    좌측 사이드바와 우측 페이지 영역(QStackedWidget)으로 구성됩니다.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("학교 시간표 관리 시스템")
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)
        self._worker = None  # GenerateWorker 참조 — 생성 전 접근 방지용
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 사이드바 ────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(SIDEBAR_W)
        sidebar.setStyleSheet("background:#1B4F8A;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # 앱 타이틀 레이블
        app_title = QLabel("📅 시간표 관리")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_title.setFont(QFont("", 13, QFont.Weight.Bold))
        app_title.setStyleSheet("color: white; background:#153d6a; padding:18px 8px;")
        sb_layout.addWidget(app_title)

        # 네비게이션 버튼들은 _nav_buttons 리스트로 관리합니다.
        # 페이지 전환 시 해당 버튼만 checked=True 로 설정합니다.
        self._nav_buttons: list[QPushButton] = []

        def add_section(label: str):
            """사이드바 섹션 제목 레이블을 추가합니다."""
            lbl = QLabel(label)
            lbl.setStyleSheet(SECTION_LABEL_STYLE)
            sb_layout.addWidget(lbl)

        def add_nav(text: str, idx: int) -> QPushButton:
            """페이지 전환 네비게이션 버튼을 추가합니다. idx 는 QStackedWidget 인덱스입니다."""
            btn = QPushButton(f"  {text}")
            btn.setCheckable(True)
            btn.setStyleSheet(NAV_BTN_STYLE)
            # lambda 기본 인자(i=idx)로 루프 변수 캡처 문제를 회피합니다.
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sb_layout.addWidget(btn)
            self._nav_buttons.append(btn)
            return btn

        # 기초 데이터 입력 섹션
        add_section("기초 데이터 입력")
        add_nav("편제 설정 (학년/반)", 0)
        add_nav("교사 관리", 1)
        add_nav("교과목 / 시수", 2)
        add_nav("교실 관리", 3)

        # 시간표 생성 섹션 (페이지 전환 없는 액션 버튼)
        add_section("시간표 생성")
        btn_gen = QPushButton("  ▶ 자동 생성")
        btn_gen.setStyleSheet(NAV_BTN_STYLE)
        btn_gen.clicked.connect(self._run_generate)
        sb_layout.addWidget(btn_gen)

        btn_term = QPushButton("  + 학기 추가")
        btn_term.setStyleSheet(NAV_BTN_STYLE)
        btn_term.clicked.connect(self._add_term)
        sb_layout.addWidget(btn_term)

        # 시간표 조회 섹션
        add_section("시간표 조회")
        add_nav("반별 시간표", 4)
        add_nav("교사별 시간표", 5)

        # 변경 관리 섹션
        add_section("변경 관리")
        add_nav("변경 신청/결재", 6)

        # 기타 관리 섹션
        add_section("기타 관리")
        add_nav("학사일정", 7)
        add_nav("변경 이력", 8)

        # 내보내기 섹션 (액션 버튼)
        add_section("내보내기")
        btn_pdf = QPushButton("  📄 PDF 출력")
        btn_pdf.setStyleSheet(NAV_BTN_STYLE)
        btn_pdf.clicked.connect(self._export_pdf)
        sb_layout.addWidget(btn_pdf)

        btn_neis = QPushButton("  📊 NEIS 내보내기")
        btn_neis.setStyleSheet(NAV_BTN_STYLE)
        btn_neis.clicked.connect(self._export_neis)
        sb_layout.addWidget(btn_neis)

        add_section("프로젝트")
        btn_save = QPushButton("  💾 프로젝트 저장")
        btn_save.setStyleSheet(NAV_BTN_STYLE)
        btn_save.clicked.connect(self._save_project)
        sb_layout.addWidget(btn_save)

        btn_load = QPushButton("  📂 프로젝트 불러오기")
        btn_load.setStyleSheet(NAV_BTN_STYLE)
        btn_load.clicked.connect(self._load_project)
        sb_layout.addWidget(btn_load)

        # 하단: 늘어나는 공간
        sb_layout.addStretch()

        # 피드백 / DB 설정 (하단 고정)
        btn_feedback = QPushButton("  💬 피드백 보내기")
        btn_feedback.setStyleSheet(NAV_BTN_STYLE)
        btn_feedback.clicked.connect(self._open_feedback)
        sb_layout.addWidget(btn_feedback)

        btn_db = QPushButton("  ⚙ DB 연결 설정")
        btn_db.setStyleSheet(NAV_BTN_STYLE)
        btn_db.clicked.connect(self._open_db_config)
        sb_layout.addWidget(btn_db)

        root.addWidget(sidebar)

        # ── 콘텐츠 영역 (QStackedWidget) ────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:#F4F7FB;")

        # 각 페이지 위젯 생성 (순서가 사이드바 인덱스와 일치해야 합니다)
        self.page_class        = ClassSetupWidget()
        self.page_teacher      = TeacherSetupWidget()
        self.page_subject      = SubjectSetupWidget()
        self.page_room         = RoomSetupWidget()
        self.page_class_view   = ClassTimetableView()
        self.page_teacher_view = TeacherTimetableView()
        self.page_request_list = ChangeRequestWidget()
        self.page_calendar     = CalendarWidget()
        self.page_history      = HistoryWidget()

        for page in [
            self.page_class, self.page_teacher, self.page_subject, self.page_room,
            self.page_class_view, self.page_teacher_view,
            self.page_request_list, self.page_calendar, self.page_history,
        ]:
            self.stack.addWidget(page)

        root.addWidget(self.stack)

        # 시작 페이지: 편제 설정(0번)
        self._switch_page(0)

    def _switch_page(self, idx: int):
        """
        QStackedWidget 페이지를 전환하고 사이드바 버튼 상태를 갱신합니다.

        모든 페이지(0~8) 전환 시 refresh()를 호출하여 선행 작업에서 입력된
        최신 데이터가 후속 페이지의 콤보박스·테이블에 반영되도록 합니다.

        예: 편제 설정(0)에서 학반 추가 → 교사 관리(1)로 이동하면
            담임 학반 콤보박스에 방금 추가한 학반이 나타납니다.
        """
        self.stack.setCurrentIndex(idx)

        # 현재 페이지에 해당하는 버튼만 checked 상태로 설정합니다.
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)

        # 모든 페이지 진입 시 refresh()를 호출해 DB의 최신 데이터를 반영합니다.
        # 이렇게 하면 선행 작업(예: 학반 등록)의 결과가 후속 페이지(예: 교사 관리)의
        # 콤보박스에 자동으로 연동됩니다.
        refresh_map = {
            0: self.page_class.refresh,
            1: self.page_teacher.refresh,
            2: self.page_subject.refresh,
            3: self.page_room.refresh,
            4: self.page_class_view.refresh,
            5: self.page_teacher_view.refresh,
            6: self.page_request_list.refresh,
            7: self.page_calendar.refresh,
            8: self.page_history.refresh,
        }
        if idx in refresh_map:
            refresh_map[idx]()

    def _run_generate(self):
        """자동 생성 다이얼로그를 열고 사용자 확인 후 백그라운드 스레드에서 생성합니다."""
        dlg = GenerateDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        term_id = dlg.term_id
        if not term_id:
            QMessageBox.warning(self, "오류", "학기를 먼저 추가해 주세요.")
            return

        # 생성 중 진행 다이얼로그를 표시합니다 (취소 버튼 없음, 모달).
        progress = QProgressDialog("시간표를 생성하고 있습니다...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        # QThread 기반 워커 실행
        self._worker = GenerateWorker(term_id, dlg.max_periods)
        self._worker.finished.connect(
            lambda ok, msg: self._on_generate_done(ok, msg, progress)
        )
        self._worker.start()

    def _on_generate_done(self, ok: bool, msg: str, progress: QProgressDialog):
        """생성 완료 시 진행 다이얼로그를 닫고 결과를 표시합니다."""
        progress.close()
        if ok:
            QMessageBox.information(self, "생성 완료", msg)
            # 시간표 조회 페이지를 최신 데이터로 갱신합니다.
            self.page_class_view.refresh()
            self.page_teacher_view.refresh()
        else:
            QMessageBox.critical(self, "생성 실패", msg)

    def _add_term(self):
        """학기 추가 다이얼로그를 열고 DB 에 저장합니다."""
        dlg = TermDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = get_session()
        try:
            if dlg.is_current:
                # 기존 현재 학기 플래그를 모두 해제합니다.
                session.query(AcademicTerm).update({"is_current": False})
            term = AcademicTerm(
                year=dlg.year,
                semester=dlg.semester,
                is_current=dlg.is_current,
            )
            session.add(term)
            session.commit()
            QMessageBox.information(
                self, "추가 완료",
                f"{dlg.year}년 {dlg.semester}학기가 추가되었습니다."
            )
        finally:
            session.close()

    def _export_pdf(self):
        """PDF 출력 다이얼로그를 엽니다."""
        PDFExportDialog(self).exec()

    def _export_neis(self):
        """NEIS(Excel) 내보내기 다이얼로그를 엽니다."""
        NEISExportDialog(self).exec()

    def _save_project(self):
        """
        프로젝트 전체 데이터를 JSON 파일로 저장합니다.
        QFileDialog 로 저장 경로를 선택한 뒤 core/project_manager 의
        export_project() 를 호출합니다.
        """
        filepath, _ = QFileDialog.getSaveFileName(
            self, "프로젝트 저장", "timetable_project.json",
            "JSON Files (*.json)"
        )
        if not filepath:
            return

        session = get_session()
        try:
            from core.project_manager import export_project
            total = export_project(session, filepath)
            QMessageBox.information(
                self, "저장 완료",
                f"프로젝트가 저장되었습니다.\n"
                f"총 {total}개 항목이 저장되었습니다.\n\n"
                f"파일: {filepath}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "저장 실패",
                f"프로젝트 저장 중 오류가 발생했습니다:\n{e}"
            )
        finally:
            session.close()

    def _load_project(self):
        """
        JSON 프로젝트 파일을 불러와 DB를 대체합니다.

        흐름:
          1. QFileDialog 로 파일 선택
          2. validate_project_file() 로 파일 검증
          3. 경고 다이얼로그로 사용자 확인 (기존 데이터 삭제됨)
          4. import_project() 실행 (실패 시 자동 rollback)
          5. 전체 페이지 refresh() 로 UI 갱신
        """
        filepath, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 불러오기", "",
            "JSON Files (*.json)"
        )
        if not filepath:
            return

        from core.project_manager import validate_project_file, import_project

        valid, error = validate_project_file(filepath)
        if not valid:
            QMessageBox.critical(self, "파일 오류", error)
            return

        reply = QMessageBox.warning(
            self, "프로젝트 불러오기",
            "기존 모든 데이터가 삭제되고\n"
            "파일 내용으로 대체됩니다.\n\n"
            f"파일: {filepath}\n\n"
            "계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            summary = import_project(session, filepath)
            total = sum(summary.values())

            lines = [f" · {t}: {n}개" for t, n in summary.items() if n > 0]
            lines.insert(0, f"프로젝트를 성공적으로 불러왔습니다.\n총 {total}개 항목:\n")
            QMessageBox.information(self, "불러오기 완료", "\n".join(lines))

            # 모든 페이지를 최신 데이터로 갱신
            for page in [
                self.page_class, self.page_teacher, self.page_subject, self.page_room,
                self.page_class_view, self.page_teacher_view,
                self.page_request_list, self.page_calendar, self.page_history,
            ]:
                page.refresh()
        except Exception as e:
            QMessageBox.critical(
                self, "불러오기 실패",
                f"프로젝트 불러오기 중 오류가 발생했습니다.\n"
                f"데이터는 복구되었습니다.\n\n{e}"
            )
        finally:
            session.close()

    def _open_feedback(self):
        """피드백 다이얼로그를 엽니다."""
        FeedbackDialog(self).exec()

    def _open_db_config(self):
        """DB 연결 설정 다이얼로그를 열고 저장 후 즉시 재연결을 시도합니다."""
        from config import load_config, save_config, get_db_url
        from database.connection import init_db

        cfg = load_config()
        dlg = DBConfigDialog(cfg, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_cfg = dlg.get_config()
        save_config(new_cfg)    # db_config.json 에 저장
        try:
            init_db(get_db_url(new_cfg))  # 새 설정으로 즉시 재연결
            QMessageBox.information(self, "연결 성공", "데이터베이스 연결 설정이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "연결 실패", f"DB 연결 오류:\n{e}")
