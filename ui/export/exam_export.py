"""
시험표·감독표 내보내기 (2026-09-19 신규)

  export_invigilation_pdf(session, exam, filepath)
      — 감독 시간표를 A4 가로 PDF 로 출력합니다.
  export_invigilation_csv(session, exam, filepath)
      — 감독 배정을 CSV 로 출력합니다 (Excel 에서 바로 열림).

기존 수업 시간표 PDF 출력(ui/export/pdf_export.py)의 구성 요소를
재사용합니다:
  - _find_korean_font() — OS 별 한국어 폰트 탐색
  - SimpleDocTemplate/landscape(A4) 문서 구성과 테이블 스타일 톤

감독표는 요일 반복 구조(수업)가 아니라 날짜 기반 1회성 이벤트이므로
별도 함수로 분리했습니다.
"""
import csv
from datetime import date

from database.connection import get_session
from database.models import (
    Exam, ExamPeriod, InvigilationAssignment, SchoolClass, Teacher, User,
)

# pdf_export 의 폰트 탐색 함수를 재사용 — 중복 구현 금지 (규칙 일관성).
from ui.export.pdf_export import _find_korean_font

# 헤더 남색 — 기존 pdf_export 의 테이블 헤더색과 동일한 톤을 유지합니다.
_HEADER_HEX = "#1B4F8A"


def export_invigilation_pdf(session, exam: Exam, filepath: str) -> None:
    """
    감독 시간표를 PDF 로 출력합니다.

    페이지 구성:
      타이틀(시험명·기간) → 총평(교사별 감독 횟수) → 감독표 테이블
      테이블 열: 날짜 / 교시(시간) / 반 / 1조 / 2조 / 시험 과목

    Args:
        session: 열린 SQLAlchemy 세션
        exam: 출력할 시험
        filepath: 저장할 .pdf 경로
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # ── 데이터 수집 ───────────────────────────────────────────────────────
    periods = (
        session.query(ExamPeriod).filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )
    classes = {c.id: c for c in session.query(SchoolClass)}
    teachers = {t.id: t for t in session.query(Teacher)}
    assignments = (
        session.query(InvigilationAssignment)
        .filter_by(exam_id=exam.id)
        .order_by(InvigilationAssignment.period_id,
                  InvigilationAssignment.school_class_id,
                  InvigilationAssignment.pair_index)
        .all()
    )
    # 시험 과목 표기용: (period_id, grade_id) → 과목명 대신 subject_id 맵
    from database.models import ExamEntry, Subject
    entries = session.query(ExamEntry).filter_by(exam_id=exam.id).all()
    subjects = {s.id: s for s in session.query(Subject)}
    entry_map = {(e.period_id, e.grade_id): subjects.get(e.subject_id) for e in entries}

    # ── 감독 교사 이름 매핑: (period_id, class_id) → {pair_index: 교사명} ──
    # 2인 1조(학생 20명 이상) 반은 pair 1·2 두 칸에 교사 이름이 들어갑니다.
    slot_map: dict = {}
    duty_count: dict = {}   # 교사별 감독 횟수 (총평 표기용)
    for a in assignments:
        key = (a.period_id, a.school_class_id)
        slot_map.setdefault(key, {})
        name = teachers[a.teacher_id].name if a.teacher_id in teachers else "(미배정)"
        slot_map[key][a.pair_index] = name
        if a.teacher_id is not None:
            duty_count[a.teacher_id] = duty_count.get(a.teacher_id, 0) + 1

    # ── 문서 구성 ────────────────────────────────────────────────────────
    font_path = _find_korean_font()
    korean_font = "Helvetica"
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", font_path))
            korean_font = "KoreanFont"
        except Exception:
            pass

    doc = SimpleDocTemplate(
        filepath, pagesize=landscape(A4),
        topMargin=30, bottomMargin=30, leftMargin=30, rightMargin=30,
    )
    elements = []
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = korean_font

    elements.append(Spacer(1, 12))
    elements.append(Paragraph(
        f"{exam.name} 감독 시간표 "
        f"({exam.start_date:%Y-%m-%d}~{exam.end_date:%Y-%m-%d})",
        title_style))
    elements.append(Spacer(1, 6))

    # 교사별 감독 횟수 총평 — 형평성(요구사항 3)을 출력물에서 바로 확인 가능
    if duty_count:
        names_sorted = sorted(
            (teachers[tid].name, cnt) for tid, cnt in duty_count.items())
        summary = ", ".join(f"{n} {c}회" for n, c in names_sorted)
        body_style = styles["BodyText"]
        body_style.fontName = korean_font
        elements.append(Paragraph(f"교사별 감독 횟수 — {summary}", body_style))
    elements.append(Spacer(1, 8))

    # ── 감독표 테이블 ────────────────────────────────────────────────────
    header = ["날짜", "교시(시간)", "반", "시험 과목", "1조", "2조"]
    table_data = [header]
    for p in periods:
        # 이 교시에 감독이 필요한 반들 (slot_map 에 등록된 반 순회)
        cls_ids = sorted({cid for (pid, cid) in slot_map if pid == p.id})
        for cid in cls_ids:
            cls = classes.get(cid)
            if cls is None:
                continue
            subj = entry_map.get((p.id, cls.grade_id))
            slots = slot_map[(p.id, cid)]
            table_data.append([
                f"{p.exam_date:%m/%d}",
                f"{p.period}교시 ({p.start_time:%H:%M}~{p.end_time:%H:%M})",
                cls.display_name,
                subj.name if subj else "-",
                slots.get(1, "-"),
                slots.get(2, "-"),
            ])

    t = Table(table_data, colWidths=[60, 130, 110, 110, 150, 150], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, -1), korean_font),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor(_HEADER_HEX)),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F8F9FA"), colors.white]),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)
    doc.build(elements)


def export_invigilation_csv(session, exam: Exam, filepath: str) -> None:
    """
    감독 배정을 CSV 로 출력합니다 (Excel 호환, UTF-8 BOM).

    PDF 와 같은 열 구성이므로 인쇄용은 PDF, 편집·통계용은 CSV 로
    용도를 나눠 사용합니다.
    """
    periods = (
        session.query(ExamPeriod).filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )
    classes = {c.id: c for c in session.query(SchoolClass)}
    teachers = {t.id: t for t in session.query(Teacher)}

    slot_map: dict = {}
    for a in session.query(InvigilationAssignment).filter_by(exam_id=exam.id):
        slot_map.setdefault((a.period_id, a.school_class_id), {})[a.pair_index] = (
            teachers[a.teacher_id].name if a.teacher_id in teachers else "미배정")

    # encoding="utf-8-sig" — Excel 이 BOM 없으면 한글을 깨져 읽는 문제 방지
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["날짜", "교시", "시작", "종료", "반", "1조", "2조"])
        for p in periods:
            cls_ids = sorted({cid for (pid, cid) in slot_map if pid == p.id})
            for cid in cls_ids:
                cls = classes.get(cid)
                slots = slot_map[(p.id, cid)]
                w.writerow([
                    f"{p.exam_date:%Y-%m-%d}", p.period,
                    f"{p.start_time:%H:%M}", f"{p.end_time:%H:%M}",
                    cls.display_name if cls else cid,
                    slots.get(1, "-"), slots.get(2, "-"),
                ])