"""PDF 출력 기능"""
import os
import platform
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog, QMessageBox,
    QDialogButtonBox, QCheckBox,
)
from database.connection import get_session
from database.models import (
    TimetableEntry, SchoolClass, Grade, Teacher, AcademicTerm,
)


DAYS_KR = ["월", "화", "수", "목", "금"]
PERIOD_LABELS = [f"{i}교시" for i in range(1, 8)]


def _find_korean_font():
    system = platform.system()
    candidates = []
    if system == "Darwin":
        candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/Library/Fonts/NanumGothic.ttf",
        ]
    elif system == "Windows":
        candidates = [
            "C:\\Windows\\Fonts\\malgun.ttf",
            "C:\\Windows\\Fonts\\gulim.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


class PDFExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 출력")
        self.setMinimumWidth(400)
        self._init_ui()

    def _init_ui(self):
        layout = QFormLayout(self)

        session = get_session()
        try:
            self._cmb_term = QComboBox()
            terms = session.query(AcademicTerm).order_by(
                AcademicTerm.year.desc(), AcademicTerm.semester.desc()
            ).all()
            for t in terms:
                self._cmb_term.addItem(str(t), t.id)
            if not terms:
                self._cmb_term.addItem("(학기 없음)", None)
            layout.addRow("학기:", self._cmb_term)

            self._cmb_scope = QComboBox()
            self._cmb_scope.addItem("전체 학반", "all_classes")
            self._cmb_scope.addItem("전체 교사", "all_teachers")
            self._cmb_scope.addItem("학반 + 교사 모두", "both")
            layout.addRow("출력 범위:", self._cmb_scope)
        finally:
            session.close()

        # 저장 경로
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
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF 저장 경로", "timetable.pdf",
            "PDF Files (*.pdf)"
        )
        if path:
            self._lbl_path.setText(path)

    def _export(self):
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


def export_to_pdf(session, term_id, scope, filepath):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = _find_korean_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", font_path))
            korean_font = "KoreanFont"
        except Exception:
            korean_font = "Helvetica"
    else:
        korean_font = "Helvetica"

    page_w, page_h = landscape(A4)
    doc = SimpleDocTemplate(
        filepath, pagesize=landscape(A4),
        topMargin=30, bottomMargin=30, leftMargin=30, rightMargin=30,
    )
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = korean_font

    def build_grid(title_text, entries):

        elements.append(Spacer(1, 12))
        elements.append(Paragraph(title_text, title_style))
        elements.append(Spacer(1, 8))

        # Build day x period grid
        grid = {}
        for e in entries:
            key = (e.day_of_week, e.period)
            grid[key] = e

        max_periods = max((e.period for e in entries), default=7)

        header = [""] + DAYS_KR
        table_data = [header]
        for period in range(1, max_periods + 1):
            row = [PERIOD_LABELS[period - 1]]
            for day in range(1, 6):
                key = (day, period)
                if key in grid:
                    e = grid[key]
                    subj_name = e.subject.short_name if e.subject else ""
                    tchr_name = e.teacher.name if e.teacher else ""
                    cell_text = f"{subj_name}\n{tchr_name}"
                else:
                    cell_text = ""
                row.append(cell_text)
            table_data.append(row)

        col_widths = [60] + [100] * 5
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), korean_font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4F8A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#E8ECF0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (1, 1), (-1, -1), [colors.HexColor("#F8F9FA"), colors.white]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(PageBreak())

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

    if scope in ("all_teachers", "both"):
        teachers = session.query(Teacher).order_by(Teacher.name).all()
        for teacher in teachers:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, teacher_id=teacher.id)
                .all()
            )
            if entries:
                data = []
                for e in entries:
                    data.append({
                        "day": e.day_of_week,
                        "period": e.period,
                        "subject_name": e.subject.short_name if e.subject else "",
                        "teacher_name": e.school_class.display_name if e.school_class else "",
                        "color_hex": e.subject.color_hex if e.subject else "#FFFFFF",
                    })
                # Use a slightly different title for teacher view
                build_grid(f"{teacher.name} 선생님 시간표", entries)

    doc.build(elements)
    QMessageBox.information(None, "PDF 출력 완료", f"PDF가 저장되었습니다:\n{filepath}")
