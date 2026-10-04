"""
시험 감독표 내보내기(PDF/CSV) 테스트 — 혼합 시험실(ExamRoom) 지원 검증
(2026-10-04 신규).

배경: InvigilationAssignment.school_class_id 가 nullable 이 되면서
(혼합 시험실 슬롯은 school_class_id=None, exam_room_id=<id>), 내보내기가
예전처럼 (period_id, school_class_id) 만으로 행을 구분하면 같은 교시의
여러 혼합 시험실이 전부 None 키로 겹쳐 사라지거나 뒤섞일 수 있었다.
이 테스트는 PDF(크래시 없이 생성)·CSV(행 내용까지 검증)로 그 회귀를 잡는다.
"""
import csv
from datetime import date, time

from shared.models import (
    AcademicTerm, Grade, SchoolClass, Subject, Teacher,
    Exam, ExamPeriod, ExamRoom, InvigilationAssignment,
)
from ui.export.exam_export import export_invigilation_pdf, export_invigilation_csv


def _make_env(db):
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    grade = Grade(grade_number=2, name="2학년")
    db.add(grade)
    db.flush()
    c1 = SchoolClass(grade_id=grade.id, class_number=1, display_name="2-1", student_count=20)
    db.add(c1)
    db.flush()
    t1 = Teacher(name="쌤1")
    t2 = Teacher(name="쌤2")
    db.add_all([t1, t2])
    db.flush()
    subj = Subject(name="세계사", short_name="세계")
    db.add(subj)
    db.flush()

    exam = Exam(
        term_id=term.id, name="내보내기 테스트",
        target_grade_ids=f"[{grade.id}]",
        start_date=date(2026, 10, 2), end_date=date(2026, 10, 2),
        first_period_start=time(9, 0), periods_per_day=1,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        status="draft",
    )
    db.add(exam)
    db.flush()
    p1 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 2), period=1,
                    start_time=time(9, 0), end_time=time(9, 50))
    db.add(p1)
    db.flush()

    # 같은 교시에 혼합 시험실 2개 — 둘 다 school_class_id=None, exam_room_id 로만 구분
    room_a = ExamRoom(exam_id=exam.id, period_id=p1.id, grade_id=grade.id,
                      subject_id=subj.id, source_class_ids=f"[{c1.id}]",
                      student_count=10, label="시험실A")
    room_b = ExamRoom(exam_id=exam.id, period_id=p1.id, grade_id=grade.id,
                      subject_id=subj.id, source_class_ids=f"[{c1.id}]",
                      student_count=10, label="시험실B")
    db.add_all([room_a, room_b])
    db.flush()

    db.add(InvigilationAssignment(
        exam_id=exam.id, period_id=p1.id, exam_room_id=room_a.id,
        teacher_id=t1.id, pair_index=1,
    ))
    db.add(InvigilationAssignment(
        exam_id=exam.id, period_id=p1.id, exam_room_id=room_b.id,
        teacher_id=t2.id, pair_index=1,
    ))
    # 일반 반 슬롯도 하나 섞어서 함께 나오는지 확인
    db.add(InvigilationAssignment(
        exam_id=exam.id, period_id=p1.id, school_class_id=c1.id,
        teacher_id=t1.id, pair_index=1,
    ))
    db.commit()
    return {"exam": exam, "rooms": [room_a, room_b], "class": c1,
            "teachers": [t1, t2]}


def test_csv_export_keeps_both_mixed_rooms_separate(db, tmp_path):
    """같은 교시의 혼합 시험실 2개가 CSV 에서 서로 다른 행으로 유지됨(과거엔 겹쳐 사라짐)."""
    env = _make_env(db)
    out = tmp_path / "invigilation.csv"
    export_invigilation_csv(db, env["exam"], str(out))

    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    body = rows[1:]   # 헤더 제외
    assert len(body) == 3, f"혼합 시험실 2개 + 일반 반 1개 = 3행이어야 함: {body}"

    labels = [r[4] for r in body]
    assert "[혼합] 시험실A" in labels
    assert "[혼합] 시험실B" in labels
    assert env["class"].display_name in labels

    # 각 혼합 시험실 행에 각자 다른 교사가 기록돼야 함(겹쳐서 하나로 뭉개지지 않음)
    room_a_row = next(r for r in body if r[4] == "[혼합] 시험실A")
    room_b_row = next(r for r in body if r[4] == "[혼합] 시험실B")
    assert room_a_row[5] == "쌤1"
    assert room_b_row[5] == "쌤2"


def test_pdf_export_does_not_crash_with_mixed_rooms(db, tmp_path):
    """혼합 시험실이 있어도 PDF 생성이 예외 없이 끝나는지 확인 (렌더링 내용은 CSV로 검증)."""
    env = _make_env(db)
    out = tmp_path / "invigilation.pdf"
    export_invigilation_pdf(db, env["exam"], str(out))
    assert out.exists() and out.stat().st_size > 0


# ── 학생 배치 안내문 (export_room_assignment_notice_*, 2026-10-04 추가) ────

def _add_student_roster(db, room, entries):
    """ExamRoomStudent 여러 줄을 한 번에 추가하는 테스트 헬퍼."""
    from shared.models import ExamRoomStudent
    for number, name, cls in entries:
        db.add(ExamRoomStudent(
            exam_room_id=room.id, student_number=number, student_name=name,
            source_class_id=cls.id if cls else None,
        ))
    db.commit()


def test_room_notice_csv_lists_students_per_room(db, tmp_path):
    """명단이 있는 시험실은 학번·이름·소속반이 CSV 행으로 나옴."""
    from ui.export.exam_export import export_room_assignment_notice_csv

    env = _make_env(db)
    _add_student_roster(db, env["rooms"][0], [
        ("10101", "김철수", env["class"]),
        ("10102", "이영희", None),
    ])

    out = tmp_path / "notice.csv"
    export_room_assignment_notice_csv(db, env["exam"], str(out))
    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    # 이 문서는 전부 혼합 시험실 섹션이므로("[혼합]" 접두어는 일반 반과
    # 섞여 나오는 export_invigilation_csv 에서만 필요) 순수 label 로 매칭.
    body = [r for r in rows[1:] if r[2] == "시험실A"]
    assert len(body) == 2
    numbers = {r[4] for r in body}
    assert numbers == {"10101", "10102"}
    kim_row = next(r for r in body if r[4] == "10101")
    assert kim_row[6] == env["class"].display_name   # 소속 반 표기


def test_room_notice_csv_flags_missing_roster(db, tmp_path):
    """명단을 등록하지 않은 시험실은 '(명단 미등록)'으로 표시되어 빠짐이 눈에 보임."""
    from ui.export.exam_export import export_room_assignment_notice_csv

    env = _make_env(db)   # room B 는 명단을 등록하지 않음
    out = tmp_path / "notice.csv"
    export_room_assignment_notice_csv(db, env["exam"], str(out))
    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    body = [r for r in rows[1:] if r[2] == "시험실B"]
    assert len(body) == 1
    assert body[0][5] == "(명단 미등록)"


def test_room_notice_pdf_does_not_crash(db, tmp_path):
    """명단이 섞여 있어도(일부만 등록) PDF 생성이 예외 없이 끝나는지 확인."""
    from ui.export.exam_export import export_room_assignment_notice_pdf

    env = _make_env(db)
    _add_student_roster(db, env["rooms"][0], [("10101", "김철수", env["class"])])
    out = tmp_path / "notice.pdf"
    export_room_assignment_notice_pdf(db, env["exam"], str(out))
    assert out.exists() and out.stat().st_size > 0


# ── 학생 안내문 / 교사 공지문 (Markdown, 2026-10-04 추가) ──────────────────
#
# 핵심 요구사항: 학생 안내문에는 감독교사 이름이 절대 나오면 안 되고,
# 교사 공지문에는 감독 배정이 그대로 나와야 한다. 두 요구사항을 한 번에
# 검증할 수 있도록, 같은 시나리오(교사 이름이 뚜렷이 구분되는 이름)를
# 두 문서 모두에 돌려보고 교차 검증한다.

def _make_full_scenario(db):
    """
    일반 과목(ExamEntry) + 선택과목(ExamRoom) + 학년별 미참여 날짜
    (ExamGradeDateExclusion) + 교실감독·복도감독 배정을 모두 갖춘 시나리오.
    """
    from shared.models import (
        ExamEntry, ExamGradeDateExclusion, CorridorDutyAssignment,
    )

    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    g1 = Grade(grade_number=1, name="1학년")
    g2 = Grade(grade_number=2, name="2학년")
    db.add_all([g1, g2])
    db.flush()
    c1 = SchoolClass(grade_id=g1.id, class_number=1, display_name="1-1", student_count=20)
    c2 = SchoolClass(grade_id=g2.id, class_number=1, display_name="2-1", student_count=18)
    db.add_all([c1, c2])
    db.flush()
    kor = Subject(name="국어", short_name="국")
    world = Subject(name="세계사", short_name="세계")
    db.add_all([kor, world])
    db.flush()
    # 교사 이름을 뚜렷이 구분되게 지어 "학생 문서에 이 이름이 있으면 바로 실패"
    # 를 문자열 검색으로 명확히 판정할 수 있게 한다.
    supervisor = Teacher(name="박감독")
    corridor_t = Teacher(name="최복도")
    db.add_all([supervisor, corridor_t])
    db.flush()

    exam = Exam(
        term_id=term.id, name="MD안내문테스트",
        target_grade_ids=f"[{g1.id},{g2.id}]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
        first_period_start=time(9, 0), periods_per_day=1,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        status="draft",
    )
    db.add(exam)
    db.flush()
    p1 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=1,
                    start_time=time(9, 0), end_time=time(9, 50))
    db.add(p1)
    db.flush()

    # 1학년: 국어 공통 시험(본인 교실)
    db.add(ExamEntry(exam_id=exam.id, period_id=p1.id, grade_id=g1.id, subject_id=kor.id))
    db.add(InvigilationAssignment(
        exam_id=exam.id, period_id=p1.id, school_class_id=c1.id,
        teacher_id=supervisor.id, pair_index=1,
    ))

    # 2학년: 선택과목(세계사, 혼합 시험실) + 그날은 2학년 시험 미참여로 등록
    # (서로 다른 셀이므로 한 시나리오에 같이 둬도 충돌 없음 — 미참여 등록은
    # ExamGradeDateExclusion 자체 검증용으로 별도 날짜가 필요하므로 여기서는
    # 사용하지 않고, 아래 room 검증과 섞이지 않도록 별도 그레이드로 구분)
    room = ExamRoom(
        exam_id=exam.id, period_id=p1.id, grade_id=g2.id, subject_id=world.id,
        source_class_ids=f"[{c2.id}]", student_count=18, label="세계사실",
    )
    db.add(room)
    db.flush()
    db.add(InvigilationAssignment(
        exam_id=exam.id, period_id=p1.id, exam_room_id=room.id,
        teacher_id=supervisor.id, pair_index=1,
    ))
    db.add(CorridorDutyAssignment(
        exam_id=exam.id, period_id=p1.id, grade_id=g1.id, teacher_id=corridor_t.id,
    ))
    db.commit()
    return {
        "exam": exam, "grades": {"g1": g1, "g2": g2}, "classes": {"c1": c1, "c2": c2},
        "teachers": {"supervisor": supervisor, "corridor": corridor_t},
        "subjects": {"국어": kor, "세계사": world}, "room": room, "period": p1,
    }


def test_student_guide_markdown_never_contains_teacher_names(db, tmp_path):
    """
    핵심 보안 요구사항: 학생 안내문에는 어떤 형태로든 감독교사 이름이
    나오면 안 된다. 일반 과목·선택과목 양쪽 다 감독 배정이 있는 시나리오로
    확인한다.
    """
    from ui.export.exam_export import export_student_exam_guide_markdown

    data = _make_full_scenario(db)
    out = tmp_path / "student_guide.md"
    export_student_exam_guide_markdown(db, data["exam"], str(out))
    text = out.read_text(encoding="utf-8")

    assert "박감독" not in text, "학생 안내문에 교실감독 교사 이름이 노출됨"
    assert "최복도" not in text, "학생 안내문에 복도감독 교사 이름이 노출됨"

    # 내용은 정상적으로 담겨야 함
    assert "준비령" in text and "본령" in text and "종료령" in text
    assert "국어 (본인 교실)" in text
    assert "세계사→세계사실" in text


def test_student_guide_markdown_shows_normal_class_for_excluded_grade(db, tmp_path):
    """ExamGradeDateExclusion 이 등록된 (학년,날짜) 칸은 '정상수업'으로 표기."""
    from shared.models import ExamGradeDateExclusion
    from ui.export.exam_export import export_student_exam_guide_markdown

    data = _make_full_scenario(db)
    db.add(ExamGradeDateExclusion(
        exam_id=data["exam"].id, grade_id=data["grades"]["g1"].id,
        exam_date=data["period"].exam_date,
    ))
    db.commit()

    out = tmp_path / "student_guide.md"
    export_student_exam_guide_markdown(db, data["exam"], str(out))
    text = out.read_text(encoding="utf-8")
    assert "| 1교시 | 정상수업 |" in text
    assert "박감독" not in text and "최복도" not in text


def test_student_guide_markdown_excludes_rooms_for_excluded_grade_date(db, tmp_path):
    """
    날짜별 표에서 '정상수업'으로 표시된 (학년,날짜)는 '선택과목 응시 장소'
    요약표에도 나오면 안 된다 — 같은 문서 안에서 서로 모순되는 내용이
    되기 때문 (한쪽은 "시험 없음", 다른 쪽은 "이 시간에 시험실 있음").
    """
    from shared.models import ExamGradeDateExclusion
    from ui.export.exam_export import export_student_exam_guide_markdown

    data = _make_full_scenario(db)
    # 세계사 시험실은 2학년 소속 — 2학년을 그 날짜 미참여로 등록
    db.add(ExamGradeDateExclusion(
        exam_id=data["exam"].id, grade_id=data["grades"]["g2"].id,
        exam_date=data["period"].exam_date,
    ))
    db.commit()

    out = tmp_path / "student_guide.md"
    export_student_exam_guide_markdown(db, data["exam"], str(out))
    text = out.read_text(encoding="utf-8")
    assert "## 선택과목 응시 장소" not in text, (
        "미참여 학년의 시험실만 있는데도 '선택과목 응시 장소' 섹션이 생성됨"
    )


def test_teacher_notice_markdown_includes_assignments_and_warning(db, tmp_path):
    """교사 공지문에는 교실감독·복도감독 이름이 전부 나오고, 배포 금지 경고문도 포함."""
    from ui.export.exam_export import export_teacher_invigilation_notice_markdown

    data = _make_full_scenario(db)
    out = tmp_path / "teacher_notice.md"
    export_teacher_invigilation_notice_markdown(db, data["exam"], str(out))
    text = out.read_text(encoding="utf-8")

    assert "박감독" in text
    assert "최복도" in text
    assert "학생에게 배포하지 마세요" in text
    assert "[혼합] 세계사실" in text

    # 감독 횟수 총평은 교실감독뿐 아니라 복도감독도 합산해야 함 —
    # 최복도는 복도감독만 했으므로, 그 집계표에서도 빠지면 안 됨.
    summary_section = text.split("## 교사별 감독 횟수")[1]
    assert "박감독 | 2회" in summary_section
    assert "최복도 | 1회" in summary_section
