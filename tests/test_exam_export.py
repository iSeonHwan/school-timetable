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
