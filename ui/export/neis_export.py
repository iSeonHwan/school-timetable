"""NEIS 내보내기 (Excel)"""
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog, QMessageBox,
    QDialogButtonBox,
)
from database.connection import get_session
from database.models import (
    TimetableEntry, SchoolClass, Grade, Teacher, AcademicTerm,
)


DAYS_KR = ["월", "화", "수", "목", "금"]


class NEISExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NEIS 내보내기")
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
            self._cmb_scope.addItem("반별 시간표", "classes")
            self._cmb_scope.addItem("교사별 시간표", "teachers")
            self._cmb_scope.addItem("모두", "both")
            layout.addRow("내보내기 범위:", self._cmb_scope)
        finally:
            session.close()

        path_layout = QHBoxLayout()
        self._lbl_path = QLabel("(선택 안 됨)")
        self._lbl_path.setStyleSheet("color:#888;")
        path_layout.addWidget(self._lbl_path)
        btn_browse = QPushButton("찾아보기...")
        btn_browse.clicked.connect(self._browse)
        path_layout.addWidget(btn_browse)
        layout.addRow("저장 경로:", path_layout)

        note = QLabel(
            "NEIS에 직접 업로드 가능한 형식이 아닌, "
            "NEIS 템플릿에 복사하여 사용할 수 있는 정리된 Excel 파일을 생성합니다."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:10pt; padding:8px 0;")
        layout.addRow(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._export)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "NEIS Excel 저장 경로", "timetable_neis.xlsx",
            "Excel Files (*.xlsx)"
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
            export_neis(session, term_id, scope, filepath)
        finally:
            session.close()

        self.accept()


def export_neis(session, term_id, scope, filepath):
    from openpyxl import Workbook
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side,
    )
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    header_fill = PatternFill(start_color="1B4F8A", end_color="1B4F8A", fill_type="solid")
    header_font = Font(name="맑은 고딕", bold=True, color="FFFFFF", size=10)
    cell_font = Font(name="맑은 고딕", size=9)
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    def build_class_sheet(ws, title, entries):
        max_periods = max((e.period for e in entries), default=7)

        # Title row
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
        title_cell = ws.cell(row=1, column=1, value=title)
        title_cell.font = Font(name="맑은 고딕", bold=True, size=14, color="1B4F8A")
        title_cell.alignment = Alignment(horizontal="center")

        # Header row
        headers = [""] + DAYS_KR
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center_align
            cell.border = thin_border

        for period in range(1, max_periods + 1):
            row = period + 3
            # Period label
            cell = ws.cell(row=row, column=1, value=f"{period}교시")
            cell.font = Font(name="맑은 고딕", bold=True, size=9)
            cell.alignment = center_align
            cell.fill = PatternFill(start_color="E8ECF0", end_color="E8ECF0", fill_type="solid")
            cell.border = thin_border

            for day in range(1, 6):
                col = day + 1
                entry = None
                for e in entries:
                    if e.day_of_week == day and e.period == period:
                        entry = e
                        break

                if entry:
                    subj_name = entry.subject.short_name if entry.subject else ""
                    tchr_name = entry.teacher.name if entry.teacher else ""
                    cell = ws.cell(row=row, column=col, value=f"{subj_name}\n{tchr_name}")
                else:
                    cell = ws.cell(row=row, column=col, value="")
                cell.font = cell_font
                cell.alignment = center_align
                cell.border = thin_border

        # Adjust column widths
        ws.column_dimensions["A"].width = 10
        for day in range(5):
            ws.column_dimensions[get_column_letter(day + 2)].width = 18

    if scope in ("classes", "both"):
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
                ws = wb.create_sheet(title=cls.display_name) if wb.sheetnames else None
                if ws is None:
                    ws = wb.active
                    ws.title = cls.display_name
                build_class_sheet(ws, f"{cls.display_name} 시간표", entries)

    if scope in ("teachers", "both"):
        teachers = session.query(Teacher).order_by(Teacher.name).all()
        for teacher in teachers:
            entries = (
                session.query(TimetableEntry)
                .filter_by(term_id=term_id, teacher_id=teacher.id)
                .all()
            )
            if entries:
                safe_name = teacher.name[:20]
                if wb.sheetnames and wb.sheetnames[0] == "Sheet":
                    ws = wb.active
                    ws.title = safe_name
                else:
                    ws = wb.create_sheet(title=safe_name)
                build_class_sheet(ws, f"{teacher.name} 선생님 시간표", entries)

    # Remove default sheet if unused and there are other sheets
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        del wb["Sheet"]

    wb.save(filepath)
    QMessageBox.information(None, "NEIS 내보내기 완료",
                            f"Excel 파일이 저장되었습니다:\n{filepath}\n\n"
                            "이 파일을 NEIS 템플릿에 복사하여 사용하세요.")
