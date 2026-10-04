"""
시험표·감독표 내보내기 (2026-09-19 신규, 2026-10-04 학생 배치 안내문·
Markdown 안내문/공지문 추가)

  export_invigilation_pdf(session, exam, filepath)
      — 감독 시간표를 A4 가로 PDF 로 출력합니다.
  export_invigilation_csv(session, exam, filepath)
      — 감독 배정을 CSV 로 출력합니다 (Excel 에서 바로 열림).
  export_room_assignment_notice_pdf(session, exam, filepath)
      — 혼합 시험실(선택과목 등) 학생 배치 안내문을 PDF 로 출력합니다.
        "이 학생이 이 과목 시험을 어디서 보는지" 안내하는 용도.
  export_room_assignment_notice_csv(session, exam, filepath)
      — 위와 같은 내용을 CSV 로 출력합니다.
  export_student_exam_guide_markdown(session, exam, filepath)
      — 학생용 시험 안내문(.md): 시험 기간·교시 시간(준비령/본령/종료령)·
        날짜별 시험 시간표·선택과목 응시 장소. 감독교사 정보는 절대
        포함하지 않습니다(학생에게 공개돼서는 안 되는 정보).
  export_teacher_invigilation_notice_markdown(session, exam, filepath)
      — 교사 공지용 감독표(.md): 교실감독·복도감독 배정 + 감독 횟수 총평.
        교사에게만 공지하는 문서이며 학생에게 배포해서는 안 됩니다.

기존 수업 시간표 PDF 출력(ui/export/pdf_export.py)의 구성 요소를
재사용합니다:
  - _find_korean_font() — OS 별 한국어 폰트 탐색
  - SimpleDocTemplate/landscape(A4) 문서 구성과 테이블 스타일 톤

감독표는 요일 반복 구조(수업)가 아니라 날짜 기반 1회성 이벤트이므로
별도 함수로 분리했습니다.
"""
import csv
import json
from datetime import date, datetime, timedelta

from database.connection import get_session
from database.models import (
    Exam, ExamPeriod, InvigilationAssignment, SchoolClass, Teacher, User,
    ExamRoom, ExamRoomStudent,
)

# Markdown 안내문의 날짜 헤더에 쓰는 요일 표기 — datetime.weekday() (월=0) 순서.
_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _slot_key(a: InvigilationAssignment) -> tuple:
    """
    InvigilationAssignment → (period_id, kind, ref_id) 슬롯 식별자.

    2026-10-04 변경: school_class_id 가 nullable 이 되고 exam_room_id 가
    추가되면서(혼합 시험실 지원), 과거처럼 (period_id, school_class_id) 만
    키로 쓰면 같은 교시의 혼합 시험실들이 전부 school_class_id=None 으로
    겹쳐 한 슬롯인 것처럼 섞여버립니다. kind 로 네임스페이스를 분리합니다
    (core.exam_scheduler 의 슬롯 키 규칙과 동일).
    """
    if a.exam_room_id is not None:
        return (a.period_id, "room", a.exam_room_id)
    return (a.period_id, "class", a.school_class_id)

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
    rooms = {r.id: r for r in session.query(ExamRoom).filter_by(exam_id=exam.id)}
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

    # ── 감독 교사 이름 매핑: (period_id, kind, ref_id) → {pair_index: 교사명} ──
    # 2인 1조(학생 수 >= pair_threshold) 반/시험실은 pair 1·2 두 칸에 이름이 들어갑니다.
    slot_map: dict = {}
    duty_count: dict = {}   # 교사별 감독 횟수 (총평 표기용)
    for a in assignments:
        key = _slot_key(a)
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
    header = ["날짜", "교시(시간)", "반/시험실", "시험 과목", "1조", "2조"]
    table_data = [header]
    for p in periods:
        # 이 교시에 감독이 필요한 반/시험실들 (slot_map 에 등록된 키 순회)
        # 일반 반(class) 먼저, 혼합 시험실(room)은 뒤에 — 둘 다 ref_id 순.
        period_keys = sorted(
            (k for k in slot_map if k[0] == p.id),
            key=lambda k: (0 if k[1] == "class" else 1, k[2]),
        )
        for key in period_keys:
            _, kind, ref_id = key
            slots = slot_map[key]
            if kind == "class":
                cls = classes.get(ref_id)
                if cls is None:
                    continue
                label = cls.display_name
                subj = entry_map.get((p.id, cls.grade_id))
                subj_name = subj.name if subj else "-"
            else:
                room = rooms.get(ref_id)
                label = f"[혼합] {room.label}" if room and room.label else f"시험실#{ref_id}"
                subj_name = "-"
                if room is not None and room.subject_id is not None:
                    subj = subjects.get(room.subject_id)
                    subj_name = subj.name if subj else "-"
            table_data.append([
                f"{p.exam_date:%m/%d}",
                f"{p.period}교시 ({p.start_time:%H:%M}~{p.end_time:%H:%M})",
                label,
                subj_name,
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
    rooms = {r.id: r for r in session.query(ExamRoom).filter_by(exam_id=exam.id)}
    teachers = {t.id: t for t in session.query(Teacher)}

    slot_map: dict = {}
    for a in session.query(InvigilationAssignment).filter_by(exam_id=exam.id):
        slot_map.setdefault(_slot_key(a), {})[a.pair_index] = (
            teachers[a.teacher_id].name if a.teacher_id in teachers else "미배정")

    # encoding="utf-8-sig" — Excel 이 BOM 없으면 한글을 깨져 읽는 문제 방지
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["날짜", "교시", "시작", "종료", "반/시험실", "1조", "2조"])
        for p in periods:
            period_keys = sorted(
                (k for k in slot_map if k[0] == p.id),
                key=lambda k: (0 if k[1] == "class" else 1, k[2]),
            )
            for key in period_keys:
                _, kind, ref_id = key
                slots = slot_map[key]
                if kind == "class":
                    cls = classes.get(ref_id)
                    label = cls.display_name if cls else ref_id
                else:
                    room = rooms.get(ref_id)
                    label = f"[혼합] {room.label}" if room and room.label else f"시험실#{ref_id}"
                w.writerow([
                    f"{p.exam_date:%Y-%m-%d}", p.period,
                    f"{p.start_time:%H:%M}", f"{p.end_time:%H:%M}",
                    label,
                    slots.get(1, "-"), slots.get(2, "-"),
                ])


def _room_roster_sections(session, exam: Exam) -> list[dict]:
    """
    혼합 시험실 학생 배치 안내문의 섹션별 데이터를 모읍니다.

    PDF/CSV 두 내보내기 함수가 완전히 같은 데이터·정렬 규칙을 쓰도록
    여기 한 곳에 모아둡니다(한쪽만 고치고 다른 쪽을 잊어버리는 사고
    방지 — export_invigilation_pdf/csv 가 _slot_key() 를 공유하는 것과
    같은 이유).

    ExamRoomStudent 명단이 비어 있는 시험실도 섹션 자체는 만듭니다 —
    "이 시험실은 아직 명단이 없다"는 사실이 눈에 보여야 관리자가
    빠진 입력을 알아챌 수 있기 때문입니다(명단 없이 조용히 생략하면
    안내문에 그 시험실이 통째로 빠진 것처럼 보여 더 혼란스러움).

    반환: [{period, room, students: [ExamRoomStudent, ...]}, ...]
    날짜·교시 순으로 정렬된 리스트. students 는 학번(없으면 이름) 순.
    """
    rooms = (
        session.query(ExamRoom).filter_by(exam_id=exam.id)
        .join(ExamPeriod, ExamPeriod.id == ExamRoom.period_id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period, ExamRoom.id)
        .all()
    )
    sections = []
    for room in rooms:
        period = session.get(ExamPeriod, room.period_id)
        students = (
            session.query(ExamRoomStudent).filter_by(exam_room_id=room.id)
            .order_by(ExamRoomStudent.student_number, ExamRoomStudent.student_name)
            .all()
        )
        sections.append({"period": period, "room": room, "students": students})
    return sections


def export_room_assignment_notice_pdf(session, exam: Exam, filepath: str) -> None:
    """
    혼합 시험실(선택과목 등) 학생 배치 안내문을 PDF 로 출력합니다.

    목적: 선택과목처럼 같은 반 학생이 서로 다른 시험실로 흩어지는
    경우, 시험 기간 중 "이 과목은 어디서 보는지"를 학생에게 안내하기
    위한 문서입니다. 교실 문·게시판에 붙이거나 학급별로 나눠줄 수 있게,
    시험실(ExamRoom) 하나당 한 섹션으로 날짜·교시·과목·설명과 함께
    등록된 학생 명단(학번순)을 나열합니다.

    명단을 전혀 등록하지 않은 경우: ExamRoomStudent 가 전부 선택
    입력이므로, 이 문서는 ExamRoom 자체가 하나도 없으면 생성하지
    않고 안내 문구만 출력합니다(사용법을 모를 수 있으니).
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    sections = _room_roster_sections(session, exam)

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
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = korean_font
    heading_style = styles["Heading3"]
    heading_style.fontName = korean_font
    body_style = styles["BodyText"]
    body_style.fontName = korean_font

    elements = [
        Spacer(1, 12),
        Paragraph(f"{exam.name} 학생 시험실 배치 안내", title_style),
        Spacer(1, 10),
    ]

    if not sections:
        elements.append(Paragraph(
            "등록된 혼합 시험실(선택과목 등)이 없습니다. "
            "관리자 앱의 '혼합 시험실' 패널에서 먼저 시험실을 등록하세요.",
            body_style))
    for sec in sections:
        p, room = sec["period"], sec["room"]
        when = f"{p.exam_date:%m/%d} {p.period}교시" if p else "?"
        elements.append(Paragraph(f"{when} — {room.label or f'시험실#{room.id}'}", heading_style))
        students = sec["students"]
        if not students:
            elements.append(Paragraph(
                f"(명단 미등록 — 인원 {room.student_count if room.student_count is not None else '?'}명)",
                body_style))
        else:
            table_data = [["학번", "이름", "소속 반"]]
            for s in students:
                cls_name = s.source_class.display_name if s.source_class else "-"
                table_data.append([s.student_number or "-", s.student_name or "-", cls_name])
            t = Table(table_data, colWidths=[100, 100, 100])
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
                ("TOPPADDING",  (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(t)
        elements.append(Spacer(1, 10))

    doc.build(elements)


def export_room_assignment_notice_csv(session, exam: Exam, filepath: str) -> None:
    """
    혼합 시험실 학생 배치 안내문을 CSV 로 출력합니다 (Excel 호환, UTF-8 BOM).

    PDF 와 달리 섹션(시험실)별로 나누지 않고 한 줄에 날짜·교시·시험실·
    과목·학번·이름·소속반을 모두 담아 평평한(flat) 표로 만듭니다 —
    Excel 에서 학번 기준으로 정렬·필터링하기에는 이 구조가 더 편합니다
    (PDF 는 "게시물"용, CSV 는 "데이터 가공"용이라는 기존 역할 분담과
    동일 — export_invigilation_pdf/csv 참조).
    """
    from database.models import Subject

    sections = _room_roster_sections(session, exam)
    subjects = {s.id: s for s in session.query(Subject)}

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["날짜", "교시", "시험실", "과목", "학번", "이름", "소속 반"])
        for sec in sections:
            p, room, students = sec["period"], sec["room"], sec["students"]
            when_date = f"{p.exam_date:%Y-%m-%d}" if p else ""
            when_period = p.period if p else ""
            subj = subjects.get(room.subject_id) if room.subject_id else None
            room_label = room.label or f"시험실#{room.id}"
            if not students:
                w.writerow([when_date, when_period, room_label,
                            subj.name if subj else "-", "", "(명단 미등록)", ""])
                continue
            for s in students:
                cls_name = s.source_class.display_name if s.source_class else ""
                w.writerow([
                    when_date, when_period, room_label,
                    subj.name if subj else "-",
                    s.student_number or "", s.student_name or "", cls_name,
                ])


def export_student_exam_guide_markdown(session, exam: Exam, filepath: str) -> None:
    """
    학생용 시험 안내문을 Markdown(.md)으로 출력합니다.

    ⚠ 설계상 반드시 지켜야 하는 제약: 이 함수는 감독 배정(InvigilationAssignment·
    CorridorDutyAssignment)을 절대 조회하지 않습니다. 시험 감독표는 부정행위
    방지를 위해 학생에게 공개돼서는 안 되는 정보이기 때문입니다 — 이 함수
    안에서 그 두 모델을 참조하는 코드가 추가된다면, 그것 자체가 "학생 문서에
    교사 배정 정보가 섞이는" 사고이므로 리뷰에서 반드시 걸러내야 합니다.
    (반대로 교사 공지용은 export_teacher_invigilation_notice_markdown() 를
    따로 둬서, 두 문서가 서로 다른 데이터 소스를 쓰도록 애초에 분리했습니다.)

    담는 내용:
      1. 시험 기간
      2. 교시 운영 시간 — 본령(시작)·준비령(종료 N분 전)·종료령(종료).
         모든 날짜에서 같은 교시는 같은 시각입니다 — core.exam_scheduler.
         rebuild_exam_periods() 가 날짜와 무관하게 "1교시 시작" 기준
         시각만으로 N교시 시각을 계산하기 때문입니다(날짜 성분은 버리고
         시각만 저장). 그래서 "교시 운영 시간" 표는 날짜별로 반복하지
         않고 한 번만 싣습니다.
      3. 날짜·학년별 시험 시간표 — 칸마다:
         - 그 학년이 그 날짜에 시험 미참여(ExamGradeDateExclusion)면 "정상수업"
         - 혼합 시험실(ExamRoom, 선택과목 등)이 있으면 "과목→장소"(교사 미표기)
         - 공통 시험 과목(ExamEntry)이 있으면 "과목 (본인 교실)"
         - 둘 다 없으면 "자습"
      4. 선택과목 응시 장소 요약표 (날짜·교시·학년·과목·장소·인원 — 교사 없음)
    """
    periods = (
        session.query(ExamPeriod).filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )
    if not periods:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {exam.name} 시험 안내\n\n시험 교시가 아직 등록되지 않았습니다.\n")
        return

    from database.models import ExamEntry, ExamGradeDateExclusion, Grade, Subject

    # 대상 학년 — target_grade_ids 가 비어 있으면("[]") 전체 학년이 대상
    try:
        target_ids = json.loads(exam.target_grade_ids or "[]")
    except (ValueError, TypeError):
        target_ids = []
    grades = session.query(Grade).order_by(Grade.grade_number).all()
    if target_ids:
        grades = [g for g in grades if g.id in target_ids]

    entries = session.query(ExamEntry).filter_by(exam_id=exam.id).all()
    entry_map = {(e.period_id, e.grade_id): e for e in entries}
    subjects = {s.id: s for s in session.query(Subject)}

    rooms = session.query(ExamRoom).filter_by(exam_id=exam.id).all()
    rooms_by_slot: dict[tuple, list] = {}
    for r in rooms:
        rooms_by_slot.setdefault((r.period_id, r.grade_id), []).append(r)

    exclusions: dict[int, set] = {}
    for ex in session.query(ExamGradeDateExclusion).filter_by(exam_id=exam.id):
        exclusions.setdefault(ex.grade_id, set()).add(ex.exam_date)

    lines: list[str] = [
        f"# {exam.name} 시험 안내", "",
        f"**시험 기간**: {exam.start_date:%Y-%m-%d} ~ {exam.end_date:%Y-%m-%d}", "",
    ]

    # ── 교시 운영 시간 ────────────────────────────────────────────────────
    period_times: dict[int, tuple] = {}
    for p in periods:
        if p.period not in period_times:
            prep_dt = datetime.combine(date.today(), p.end_time) - timedelta(minutes=exam.prep_minutes)
            period_times[p.period] = (p.start_time, prep_dt.time(), p.end_time)

    lines.append("## 교시 운영 시간")
    lines.append("")
    lines.append(f"| 교시 | 본령(시작) | 준비령(종료 {exam.prep_minutes}분 전) | 종료령(종료) |")
    lines.append("|---|---|---|---|")
    for period_num in sorted(period_times):
        start_t, prep_t, end_t = period_times[period_num]
        lines.append(f"| {period_num}교시 | {start_t:%H:%M} | {prep_t:%H:%M} | {end_t:%H:%M} |")
    lines.append("")

    # ── 날짜·학년별 시험 시간표 ────────────────────────────────────────────
    lines.append("## 날짜별 시험 시간표")
    lines.append("")
    by_date: dict = {}
    for p in periods:
        by_date.setdefault(p.exam_date, []).append(p)

    for d, day_periods in sorted(by_date.items()):
        lines.append(f"### {d:%Y-%m-%d} ({_WEEKDAY_KO[d.weekday()]})")
        lines.append("")
        lines.append("| 교시 | " + " | ".join(g.name for g in grades) + " |")
        lines.append("|---|" + "---|" * len(grades))
        for p in sorted(day_periods, key=lambda x: x.period):
            row = [f"{p.period}교시"]
            for g in grades:
                if d in exclusions.get(g.id, set()):
                    row.append("정상수업")
                    continue
                cell_rooms = rooms_by_slot.get((p.id, g.id), [])
                if cell_rooms:
                    parts = []
                    for r in cell_rooms:
                        subj = subjects.get(r.subject_id) if r.subject_id else None
                        parts.append(f"{subj.name if subj else '자습'}→{r.label or f'시험실#{r.id}'}")
                    row.append("; ".join(parts))
                    continue
                entry = entry_map.get((p.id, g.id))
                if entry is not None:
                    subj = subjects.get(entry.subject_id)
                    row.append(f"{subj.name if subj else '-'} (본인 교실)")
                else:
                    row.append("자습")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # ── 선택과목 응시 장소 요약 ────────────────────────────────────────────
    # 날짜별 표와 똑같이 ExamGradeDateExclusion 을 적용합니다 — 적용하지
    # 않으면, 위 날짜별 표에서는 그 학년·그 날짜가 "정상수업"으로 표시돼
    # 있는데 이 요약표에는 똑같은 (날짜,교시)의 선택과목 시험실이 버젓이
    # 나오는 자기 모순적인 문서가 됩니다(실제로 생성해 눈으로 확인하다가
    # 발견한 불일치 — 날짜별 표 로직과 따로 짜여 있어 놓쳤던 부분).
    period_by_id = {p.id: p for p in periods}
    grade_by_id = {g.id: g for g in grades}
    visible_rooms = [
        r for r in rooms
        if period_by_id[r.period_id].exam_date not in exclusions.get(r.grade_id, set())
    ]
    if visible_rooms:
        lines.append("## 선택과목 응시 장소")
        lines.append("")
        lines.append("| 날짜 | 교시 | 학년 | 과목 | 장소 | 인원 |")
        lines.append("|---|---|---|---|---|---|")
        for r in sorted(visible_rooms, key=lambda r: (
            period_by_id[r.period_id].exam_date, period_by_id[r.period_id].period,
        )):
            p = period_by_id[r.period_id]
            grade = grade_by_id.get(r.grade_id)
            subj = subjects.get(r.subject_id) if r.subject_id else None
            lines.append(
                f"| {p.exam_date:%Y-%m-%d} | {p.period}교시 | {grade.name if grade else '-'} | "
                f"{subj.name if subj else '자습'} | {r.label or f'시험실#{r.id}'} | "
                f"{r.student_count if r.student_count is not None else '-'} |"
            )
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def export_teacher_invigilation_notice_markdown(session, exam: Exam, filepath: str) -> None:
    """
    교사 공지용 감독표를 Markdown(.md)으로 출력합니다.

    ⚠ 이 문서는 교사 전용 공지물입니다 — 학생에게 배포해서는 안 됩니다.
    export_student_exam_guide_markdown() 과 역할이 정확히 반대입니다:
    그쪽은 감독 정보를 절대 포함하지 않고, 이 함수는 감독 배정
    (InvigilationAssignment·CorridorDutyAssignment)을 핵심 데이터로 씁니다.
    두 함수를 하나로 합치지 않고 완전히 분리해 둔 이유도 이 때문입니다 —
    "옵션으로 감독 정보 포함 여부를 끄고 켜는" 하나의 함수로 만들면, 플래그를
    잘못 설정해 학생용 출력에 감독표가 섞이는 사고가 날 수 있습니다.

    담는 내용: 날짜별 교실감독표(반/시험실·과목·1조·2조) + 복도감독표 +
    교사별 감독 횟수 총평(형평성 확인용, export_invigilation_pdf 의 총평과 동일 취지).
    """
    from database.models import ExamEntry, Subject, CorridorDutyAssignment, Grade

    periods = (
        session.query(ExamPeriod).filter_by(exam_id=exam.id)
        .order_by(ExamPeriod.exam_date, ExamPeriod.period)
        .all()
    )
    if not periods:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {exam.name} 감독표 공지\n\n시험 교시가 아직 등록되지 않았습니다.\n")
        return

    classes = {c.id: c for c in session.query(SchoolClass)}
    rooms = {r.id: r for r in session.query(ExamRoom).filter_by(exam_id=exam.id)}
    teachers = {t.id: t for t in session.query(Teacher)}
    entries = session.query(ExamEntry).filter_by(exam_id=exam.id).all()
    subjects = {s.id: s for s in session.query(Subject)}
    entry_map = {(e.period_id, e.grade_id): subjects.get(e.subject_id) for e in entries}

    # (period_id, kind, ref_id) → {pair_index: teacher_id or None}
    slot_map: dict = {}
    duty_count: dict = {}
    for a in session.query(InvigilationAssignment).filter_by(exam_id=exam.id):
        slot_map.setdefault(_slot_key(a), {})[a.pair_index] = a.teacher_id
        if a.teacher_id is not None:
            duty_count[a.teacher_id] = duty_count.get(a.teacher_id, 0) + 1

    def _teacher_name(tid):
        if tid is None:
            return "(미배정)"
        t = teachers.get(tid)
        return t.name if t else f"#{tid}"

    lines: list[str] = [
        f"# {exam.name} 감독표 공지", "",
        f"**시험 기간**: {exam.start_date:%Y-%m-%d} ~ {exam.end_date:%Y-%m-%d}", "",
        "> ⚠ 이 문서는 교사 공지용입니다. 학생에게 배포하지 마세요.", "",
    ]

    by_date: dict = {}
    for p in periods:
        by_date.setdefault(p.exam_date, []).append(p)

    for d, day_periods in sorted(by_date.items()):
        lines.append(f"## {d:%Y-%m-%d} ({_WEEKDAY_KO[d.weekday()]})")
        lines.append("")
        lines.append("| 교시 | 반/시험실 | 과목 | 1조 | 2조 |")
        lines.append("|---|---|---|---|---|")
        for p in sorted(day_periods, key=lambda x: x.period):
            period_keys = sorted(
                (k for k in slot_map if k[0] == p.id),
                key=lambda k: (0 if k[1] == "class" else 1, k[2]),
            )
            for key in period_keys:
                _, kind, ref_id = key
                slots = slot_map[key]
                if kind == "class":
                    cls = classes.get(ref_id)
                    if cls is None:
                        continue
                    label = cls.display_name
                    subj = entry_map.get((p.id, cls.grade_id))
                    subj_name = subj.name if subj else "-"
                else:
                    room = rooms.get(ref_id)
                    label = f"[혼합] {room.label}" if room and room.label else f"시험실#{ref_id}"
                    subj_name = "-"
                    if room is not None and room.subject_id is not None:
                        subj = subjects.get(room.subject_id)
                        subj_name = subj.name if subj else "-"
                pair1 = _teacher_name(slots.get(1))
                pair2 = _teacher_name(slots.get(2)) if 2 in slots else "-"
                lines.append(f"| {p.period}교시 | {label} | {subj_name} | {pair1} | {pair2} |")
        lines.append("")

    corridor = (
        session.query(CorridorDutyAssignment).filter_by(exam_id=exam.id)
        .order_by(CorridorDutyAssignment.period_id).all()
    )
    if corridor:
        lines.append("## 복도감독")
        lines.append("")
        lines.append("| 날짜 | 교시 | 학년 | 담당 교사 |")
        lines.append("|---|---|---|---|")
        period_by_id = {p.id: p for p in periods}
        grades = {g.id: g for g in session.query(Grade)}
        for c in corridor:
            p = period_by_id.get(c.period_id)
            grade = grades.get(c.grade_id)
            if p is None:
                continue
            lines.append(
                f"| {p.exam_date:%Y-%m-%d} | {p.period}교시 | "
                f"{grade.name if grade else '-'} | {_teacher_name(c.teacher_id)} |"
            )
            # 교실감독뿐 아니라 복도감독도 "감독 횟수"에 포함합니다 — 이
            # 문서는 교실감독과 복도감독을 모두 보여주는 유일한 문서라서,
            # 총평에서 복도감독만 쓴 교사(예: 최복도)가 빠지면 "이 교사는
            # 이번 시험 기간에 하나도 안 했다"는 잘못된 인상을 줍니다.
            # (ui/export/exam_export.py 의 다른 PDF/CSV 출력들은 교실감독
            # 전용 문서라 복도감독을 세지 않는 것이 맞으므로 거기는 그대로
            # 둡니다 — 이 함수에만 해당하는 보정입니다.)
            if c.teacher_id is not None:
                duty_count[c.teacher_id] = duty_count.get(c.teacher_id, 0) + 1
        lines.append("")

    if duty_count:
        lines.append("## 교사별 감독 횟수 (교실+복도 합산)")
        lines.append("")
        lines.append("| 교사 | 횟수 |")
        lines.append("|---|---|")
        for tid, cnt in sorted(duty_count.items(), key=lambda kv: _teacher_name(kv[0])):
            lines.append(f"| {_teacher_name(tid)} | {cnt}회 |")
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")