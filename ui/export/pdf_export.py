"""
PDF 출력 기능

ReportLab 을 사용해 시간표를 A4 가로 방향 PDF 로 출력합니다.
한국어 폰트를 OS 별로 자동 탐색하며, 찾지 못하면 Helvetica 로 대체합니다.
(한글 폰트가 없으면 출력물에 한글이 깨져 보일 수 있습니다.)

데이터 의존성:
  - 학기: AcademicTerm (TermDialog 로 등록)
  - 반별 출력: SchoolClass + TimetableEntry (GenerateWorker 로 생성)
  - 교사별 출력: Teacher + TimetableEntry
  - 다이얼로그를 열 때마다 DB 에서 최신 데이터를 조회하므로
    페이지 refresh 와 무관하게 항상 최신 상태로 출력됩니다.

출력 범위:
  - 전체 학반: 반마다 1페이지 (해당 반의 TimetableEntry 가 있을 때만)
  - 전체 교사: 교사마다 1페이지 (해당 교사의 TimetableEntry 가 있을 때만)
  - 학반 + 교사 모두: 위 두 가지 합산 (많은 페이지가 생성될 수 있음)

각 페이지 구조:
  Spacer → 타이틀(Paragraph) → Spacer → Table(교시 행 × 요일 열) → PageBreak
  Table 은 repeatRows=1 로 설정되어 페이지가 넘어가도 헤더가 반복됩니다.

폰트 탐색 우선순위:
  macOS: Apple SD Gothic Neo > Apple Gothic > Nanum Gothic
  Windows: 맑은 고딕 > 굴림
  Linux: Nanum Gothic > Noto Sans CJK
"""
import os
import platform
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog, QMessageBox,
    QDialogButtonBox,
)
from database.connection import get_session
from database.models import (
    TimetableEntry, SchoolClass, Grade, Teacher, AcademicTerm,
)

DAYS_KR       = ["월", "화", "수", "목", "금"]
PERIOD_LABELS = [f"{i}교시" for i in range(1, 8)]


def _find_korean_font() -> str | None:
    """
    OS 별로 한국어 TrueType 폰트 경로를 탐색합니다.
    찾으면 경로를 반환하고, 찾지 못하면 None 을 반환합니다.
    """
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/Library/Fonts/NanumGothic.ttf",
        ]
    elif system == "Windows":
        candidates = [
            "C:\\Windows\\Fonts\\malgun.ttf",    # 맑은 고딕
            "C:\\Windows\\Fonts\\gulim.ttc",      # 굴림
        ]
    else:  # Linux
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


class PDFExportDialog(QDialog):
    """PDF 출력 설정 다이얼로그."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 출력")
        self.setMinimumWidth(400)
        self._init_ui()

    def _init_ui(self):
        layout = QFormLayout(self)

        session = get_session()
        try:
            # 학기 콤보박스
            self._cmb_term = QComboBox()
            terms = session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self._cmb_term.addItem(str(t), t.id)
            if not terms:
                self._cmb_term.addItem("(학기 없음)", None)
            layout.addRow("학기:", self._cmb_term)

            # 출력 범위 콤보박스
            self._cmb_scope = QComboBox()
            self._cmb_scope.addItem("전체 학반",    "all_classes")
            self._cmb_scope.addItem("전체 교사",    "all_teachers")
            self._cmb_scope.addItem("학반 + 교사 모두", "both")
            layout.addRow("출력 범위:", self._cmb_scope)
        finally:
            session.close()

        # 저장 경로 선택
        path_layout = QHBoxLayout()
        self._lbl_path = QLabel("(선택 안 됨)")
        self._lbl_path.setStyleSheet("color:#888;")
        path_layout.addWidget(self._lbl_path)
        btn_browse = QPushButton("찾아보기...")
        btn_browse.clicked.connect(self._browse)
        path_layout.addWidget(btn_browse)
        layout.addRow("저장 경로:", path_layout)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._export)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _browse(self):
        """파일 저장 경로를 선택하는 다이얼로그를 엽니다."""
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF 저장 경로", "timetable.pdf",
            "PDF Files (*.pdf)"
        )
        if path:
            self._lbl_path.setText(path)

    def _export(self):
        """입력 값을 검증하고 export_to_pdf() 를 호출합니다."""
        filepath = self._lbl_path.text()
        if filepath == "(선택 안 됨)":
            QMessageBox.warning(self, "경로 오류", "저장 경로를 선택해 주세요.")
            return

        term_id = self._cmb_term.currentData()
        if not term_id:
            QMessageBox.warning(self, "학기 오류", "학기를 선택해 주세요.")
            return

        scope = self._cmb_scope.currentData()
        session = get_session()
        try:
            export_to_pdf(session, term_id, scope, filepath)
        finally:
            session.close()

        self.accept()


def export_to_pdf(session, term_id: int, scope: str, filepath: str) -> None:
    """
    ReportLab 으로 PDF 파일을 생성합니다.

    Args:
        session  : 열린 SQLAlchemy 세션
        term_id  : 출력할 학기 ID
        scope    : "all_classes" / "all_teachers" / "both"
        filepath : 저장할 .pdf 파일 경로
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # 한국어 폰트 등록 (실패 시 Helvetica 사용)
    font_path = _find_korean_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", font_path))
            korean_font = "KoreanFont"
        except Exception:
            korean_font = "Helvetica"
    else:
        korean_font = "Helvetica"

    # A4 가로 방향으로 문서를 설정합니다.
    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(A4),
        topMargin=30, bottomMargin=30, leftMargin=30, rightMargin=30,
    )
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = korean_font

    def build_grid(title_text: str, entries: list) -> None:
        """
        단일 시간표 페이지를 elements 에 추가합니다.
        entries: TimetableEntry 리스트
        """
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(title_text, title_style))
        elements.append(Spacer(1, 8))

        # (day, period) → TimetableEntry 맵 구성
        grid = {(e.day_of_week, e.period): e for e in entries}
        max_periods = max((e.period for e in entries), default=7)

        # 테이블 데이터 구성: [헤더 행, 교시1행, 교시2행, ...]
        header = [""] + DAYS_KR
        table_data = [header]
        for period in range(1, max_periods + 1):
            row = [PERIOD_LABELS[period - 1]]
            for day in range(1, 6):
                entry = grid.get((day, period))
                if entry:
                    subj_name = entry.subject.short_name if entry.subject else ""
                    tchr_name = entry.teacher.name if entry.teacher else ""
                    cell_text = f"{subj_name}\n{tchr_name}"
                else:
                    cell_text = ""
                row.append(cell_text)
            table_data.append(row)

        # 열 너비: 교시 레이블 60pt + 요일 5개 × 100pt
        col_widths = [60] + [100] * 5
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTNAME",    (0, 0), (-1, -1), korean_font),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#1B4F8A")),  # 헤더 남색
            ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
            ("BACKGROUND",  (0, 1), (0, -1),  colors.HexColor("#E8ECF0")),  # 교시 레이블 회색
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.grey),
            # 홀수/짝수 행 배경을 교대로 적용합니다.
            ("ROWBACKGROUNDS", (1, 1), (-1, -1), [colors.HexColor("#F8F9FA"), colors.white]),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(PageBreak())

    # ── 반별 시간표 출력 ──────────────────────────────────────────────
    if scope in ("all_classes", "both"):
        classes = (
            session.query(SchoolClass)
            .join(Grade)
            .order_by(Grade.grade_number, SchoolClass.class_number)
            .all()
        )
        for cls in classes:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, school_class_id=cls.id)
                .all()
            )
            if entries:
                build_grid(f"{cls.display_name} 시간표", entries)

    # ── 교사별 시간표 출력 ────────────────────────────────────────────
    if scope in ("all_teachers", "both"):
        teachers = session.query(Teacher).order_by(Teacher.name).all()
        for teacher in teachers:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, teacher_id=teacher.id)
                .all()
            )
            if entries:
                build_grid(f"{teacher.name} 선생님 시간표", entries)

    doc.build(elements)
    QMessageBox.information(None, "PDF 출력 완료", f"PDF가 저장되었습니다:\n{filepath}")
