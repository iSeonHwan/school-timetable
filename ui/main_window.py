"""메인 윈도우 — 사이드바 네비게이션 + 콘텐츠 영역"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame,
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QDialogButtonBox, QMessageBox, QProgressDialog,
    QDateEdit, QCheckBox
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

SIDEBAR_W = 200
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
    border-left: 4px solid #5dade2;
}
"""
SECTION_LABEL_STYLE = """
    color: #7fb3d3;
    font-size: 11px;
    font-weight: bold;
    padding: 14px 16px 4px 16px;
    letter-spacing: 1px;
"""


class GenerateWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, term_id: int, max_periods: int):
        super().__init__()
        self.term_id = term_id
        self.max_periods = max_periods

    def run(self):
        session = get_session()
        try:
            ok, msg = generate_timetable(session, self.term_id, self.max_periods)
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            session.close()


class GenerateDialog(QDialog):
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

        self.cb_term = QComboBox()
        self.cb_term.setMinimumWidth(200)
        session = get_session()
        try:
            terms = session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self.cb_term.addItem(str(t), t.id)
            if not terms:
                self.cb_term.addItem("(학기 없음)", None)
        finally:
            session.close()
        form.addRow("학기:", self.cb_term)

        self.spin_periods = QSpinBox()
        self.spin_periods.setRange(4, 9)
        self.spin_periods.setValue(7)
        form.addRow("일 최대 교시:", self.spin_periods)

        layout.addLayout(form)

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
        return self.cb_term.currentData()

    @property
    def max_periods(self):
        return self.spin_periods.value()


class TermDialog(QDialog):
    """학기 추가 다이얼로그"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("학기 추가")
        self.setMinimumWidth(300)
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.spin_year = QSpinBox()
        self.spin_year.setRange(2020, 2040)
        self.spin_year.setValue(QDate.currentDate().year())
        layout.addRow("연도:", self.spin_year)

        self.cb_semester = QComboBox()
        self.cb_semester.addItems(["1학기", "2학기"])
        layout.addRow("학기:", self.cb_semester)

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
        return self.cb_semester.currentIndex() + 1

    @property
    def is_current(self):
        return self.chk_current.isChecked()


class DBConfigDialog(QDialog):
    """데이터베이스 연결 설정 다이얼로그"""
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("데이터베이스 연결 설정")
        self.setMinimumWidth(420)
        self._cfg = cfg
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("DB 연결 설정")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        form = QFormLayout()

        self.cb_type = QComboBox()
        self.cb_type.addItems(["SQLite (로컬)", "PostgreSQL (네트워크)"])
        if self._cfg.get("db_type") == "postgresql":
            self.cb_type.setCurrentIndex(1)
        self.cb_type.currentIndexChanged.connect(self._toggle_pg)
        form.addRow("DB 종류:", self.cb_type)

        # SQLite
        self.sqlite_frame = QWidget()
        sf = QFormLayout(self.sqlite_frame)
        sf.setContentsMargins(0, 0, 0, 0)
        self.edit_sqlite_path = QLineEdit(self._cfg.get("sqlite_path", "timetable.db"))
        sf.addRow("파일 경로:", self.edit_sqlite_path)
        form.addRow(self.sqlite_frame)

        # PostgreSQL
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
        self.edit_pg_pw.setEchoMode(QLineEdit.EchoMode.Password)
        pf.addRow("비밀번호:", self.edit_pg_pw)
        form.addRow(self.pg_frame)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._toggle_pg(self.cb_type.currentIndex())

    def _toggle_pg(self, idx: int):
        self.sqlite_frame.setVisible(idx == 0)
        self.pg_frame.setVisible(idx == 1)

    def get_config(self) -> dict:
        cfg = dict(self._cfg)
        if self.cb_type.currentIndex() == 0:
            cfg["db_type"] = "sqlite"
            cfg["sqlite_path"] = self.edit_sqlite_path.text().strip()
        else:
            cfg["db_type"] = "postgresql"
            cfg["pg_host"] = self.edit_pg_host.text().strip()
            cfg["pg_port"] = self.spin_pg_port.value()
            cfg["pg_dbname"] = self.edit_pg_dbname.text().strip()
            cfg["pg_user"] = self.edit_pg_user.text().strip()
            cfg["pg_password"] = self.edit_pg_pw.text()
        return cfg


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("학교 시간표 관리 시스템")
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 사이드바 ───────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(SIDEBAR_W)
        sidebar.setStyleSheet("background:#1B4F8A;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # 앱 타이틀
        app_title = QLabel("📅 시간표 관리")
        app_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_title.setFont(QFont("", 13, QFont.Weight.Bold))
        app_title.setStyleSheet(
            "color: white; background:#153d6a; padding:18px 8px;"
        )
        sb_layout.addWidget(app_title)

        self._nav_buttons: list[QPushButton] = []

        def add_section(label: str):
            lbl = QLabel(label)
            lbl.setStyleSheet(SECTION_LABEL_STYLE)
            sb_layout.addWidget(lbl)

        def add_nav(text: str, idx: int) -> QPushButton:
            btn = QPushButton(f"  {text}")
            btn.setCheckable(True)
            btn.setStyleSheet(NAV_BTN_STYLE)
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sb_layout.addWidget(btn)
            self._nav_buttons.append(btn)
            return btn

        # 기초 데이터
        add_section("기초 데이터 입력")
        add_nav("편제 설정 (학년/반)", 0)
        add_nav("교사 관리", 1)
        add_nav("교과목 / 시수", 2)
        add_nav("교실 관리", 3)

        # 시간표 생성
        add_section("시간표 생성")
        btn_gen = QPushButton("  ▶ 자동 생성")
        btn_gen.setStyleSheet(NAV_BTN_STYLE)
        btn_gen.clicked.connect(self._run_generate)
        sb_layout.addWidget(btn_gen)

        btn_term = QPushButton("  + 학기 추가")
        btn_term.setStyleSheet(NAV_BTN_STYLE)
        btn_term.clicked.connect(self._add_term)
        sb_layout.addWidget(btn_term)

        # 시간표 조회
        add_section("시간표 조회")
        add_nav("반별 시간표", 4)
        add_nav("교사별 시간표", 5)

        # 변경 관리
        add_section("변경 관리")
        add_nav("변경 신청/결재", 6)

        # 기타 관리
        add_section("기타 관리")
        add_nav("학사일정", 7)
        add_nav("변경 이력", 8)

        # 내보내기
        add_section("내보내기")
        btn_pdf = QPushButton("  📄 PDF 출력")
        btn_pdf.setStyleSheet(NAV_BTN_STYLE)
        btn_pdf.clicked.connect(self._export_pdf)
        sb_layout.addWidget(btn_pdf)

        btn_neis = QPushButton("  📊 NEIS 내보내기")
        btn_neis.setStyleSheet(NAV_BTN_STYLE)
        btn_neis.clicked.connect(self._export_neis)
        sb_layout.addWidget(btn_neis)

        sb_layout.addStretch()

        # 피드백
        btn_feedback = QPushButton("  💬 피드백 보내기")
        btn_feedback.setStyleSheet(NAV_BTN_STYLE)
        btn_feedback.clicked.connect(self._open_feedback)
        sb_layout.addWidget(btn_feedback)

        # DB 설정
        btn_db = QPushButton("  ⚙ DB 연결 설정")
        btn_db.setStyleSheet(NAV_BTN_STYLE)
        btn_db.clicked.connect(self._open_db_config)
        sb_layout.addWidget(btn_db)

        root.addWidget(sidebar)

        # ── 콘텐츠 영역 ───────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:#F4F7FB;")

        self.page_class = ClassSetupWidget()
        self.page_teacher = TeacherSetupWidget()
        self.page_subject = SubjectSetupWidget()
        self.page_room = RoomSetupWidget()
        self.page_class_view = ClassTimetableView()
        self.page_teacher_view = TeacherTimetableView()
        self.page_request_list = ChangeRequestWidget()
        self.page_calendar = CalendarWidget()
        self.page_history = HistoryWidget()

        for page in [
            self.page_class, self.page_teacher, self.page_subject, self.page_room,
            self.page_class_view, self.page_teacher_view,
            self.page_request_list, self.page_calendar, self.page_history,
        ]:
            self.stack.addWidget(page)

        root.addWidget(self.stack)

        self._switch_page(0)

    def _switch_page(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)

        # 페이지 진입 시 데이터 갱신
        if idx == 4:
            self.page_class_view.refresh()
        elif idx == 5:
            self.page_teacher_view.refresh()
        elif idx == 6:
            self.page_request_list.refresh()
        elif idx == 7:
            self.page_calendar.refresh()
        elif idx == 8:
            self.page_history.refresh()

    def _run_generate(self):
        dlg = GenerateDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        term_id = dlg.term_id
        if not term_id:
            QMessageBox.warning(self, "오류", "학기를 먼저 추가해 주세요.")
            return

        progress = QProgressDialog("시간표를 생성하고 있습니다...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        self._worker = GenerateWorker(term_id, dlg.max_periods)
        self._worker.finished.connect(lambda ok, msg: self._on_generate_done(ok, msg, progress))
        self._worker.start()

    def _on_generate_done(self, ok: bool, msg: str, progress: QProgressDialog):
        progress.close()
        if ok:
            QMessageBox.information(self, "생성 완료", msg)
            self.page_class_view.refresh()
            self.page_teacher_view.refresh()
        else:
            QMessageBox.critical(self, "생성 실패", msg)

    def _add_term(self):
        dlg = TermDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        session = get_session()
        try:
            if dlg.is_current:
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
        PDFExportDialog(self).exec()

    def _export_neis(self):
        NEISExportDialog(self).exec()

    def _open_feedback(self):
        FeedbackDialog(self).exec()

    def _open_db_config(self):
        from config import load_config, save_config, get_db_url
        from database.connection import init_db
        cfg = load_config()
        dlg = DBConfigDialog(cfg, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_cfg = dlg.get_config()
        save_config(new_cfg)
        try:
            init_db(get_db_url(new_cfg))
            QMessageBox.information(self, "연결 성공", "데이터베이스 연결 설정이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "연결 실패", f"DB 연결 오류:\n{e}")
