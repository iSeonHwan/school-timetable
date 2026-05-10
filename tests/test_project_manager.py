"""
project_manager 모듈 테스트

import/export 기능을 검증합니다. 모든 테스트는 인메모리 SQLite DB를 사용하며
파일 입출력은 tempfile을 통해 임시 디렉토리에서 수행합니다.
"""
import json
import os
import tempfile
from datetime import date as date_type

import pytest

from database.connection import init_db, get_session
from database.models import (
    AcademicTerm, Grade, Room, Subject, SchoolClass, Teacher,
    SubjectClassAssignment, TeacherConstraint, TimetableEntry,
    SchoolEvent,
)
from core.project_manager import (
    export_project, import_project, validate_project_file,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_db():
    """각 테스트 전 인메모리 SQLite DB를 초기화하고 테스트 후 정리합니다."""
    init_db("sqlite:///:memory:")
    yield
    # 세션 팩토리 초기화 (다음 테스트를 위해)
    init_db("sqlite:///:memory:")


@pytest.fixture
def session():
    """매 테스트마다 새 세션을 제공합니다."""
    s = get_session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def tmpfile():
    """임시 파일 경로를 제공합니다. 테스트 종료 후 자동 삭제됩니다."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ── Helper ──────────────────────────────────────────────────────────────────


def _populate_minimal(session):
    """
    최소한의 현실적인 데이터셋을 DB에 삽입합니다.
    1학기, 1학년(2개 반), 1개 교실, 2개 교과목, 2명 교사,
    시수 배정, 시간표, 불가시간, 학사일정 포함.
    """
    # Tier 0: 독립 테이블
    term = AcademicTerm(year=2025, semester=1, is_current=True)
    session.add(term)

    grade1 = Grade(grade_number=1, name="1학년")
    session.add(grade1)

    room1 = Room(name="1-1 교실", room_type="일반", capacity=30, floor=1)
    session.add(room1)

    subj_math = Subject(name="수학", short_name="수", color_hex="#E3F2FD")
    subj_kor = Subject(name="국어", short_name="국", color_hex="#FFE0B2")
    session.add_all([subj_math, subj_kor])
    session.flush()

    # Tier 1: SchoolClass
    class1_1 = SchoolClass(grade_id=grade1.id, class_number=1, display_name="1-1",
                           homeroom_room_id=room1.id)
    class1_2 = SchoolClass(grade_id=grade1.id, class_number=2, display_name="1-2")
    session.add_all([class1_1, class1_2])
    session.flush()

    # Tier 2: Teacher
    t_kim = Teacher(name="김철수", employee_number="T001", is_homeroom=True,
                    homeroom_class_id=class1_1.id, max_daily_classes=5)
    t_park = Teacher(name="박영희", employee_number="T002", is_homeroom=False,
                     max_daily_classes=6)
    session.add_all([t_kim, t_park])
    session.flush()

    # Tier 3: Assignments, Constraints, Entries, Events
    assign1 = SubjectClassAssignment(
        school_class_id=class1_1.id, subject_id=subj_math.id,
        teacher_id=t_kim.id, weekly_hours=4,
    )
    assign2 = SubjectClassAssignment(
        school_class_id=class1_1.id, subject_id=subj_kor.id,
        teacher_id=t_park.id, weekly_hours=3, preferred_room_id=room1.id,
    )
    session.add_all([assign1, assign2])

    constraint1 = TeacherConstraint(
        teacher_id=t_kim.id, day_of_week=3, period=5, constraint_type="unavailable"
    )
    session.add(constraint1)

    entry1 = TimetableEntry(
        term_id=term.id, school_class_id=class1_1.id,
        subject_id=subj_math.id, teacher_id=t_kim.id,
        room_id=room1.id, day_of_week=1, period=1,
    )
    entry2 = TimetableEntry(
        term_id=term.id, school_class_id=class1_1.id,
        subject_id=subj_kor.id, teacher_id=t_park.id,
        room_id=None, day_of_week=1, period=2,
    )
    session.add_all([entry1, entry2])

    event1 = SchoolEvent(
        term_id=term.id, title="개교기념일", event_type="개교기념일",
        start_date=date_type(2025, 5, 15), end_date=date_type(2025, 5, 15),
    )
    session.add(event1)

    session.commit()
    return {
        "term": term, "grade1": grade1, "room1": room1,
        "subj_math": subj_math, "subj_kor": subj_kor,
        "class1_1": class1_1, "class1_2": class1_2,
        "t_kim": t_kim, "t_park": t_park,
        "assign1": assign1, "assign2": assign2,
        "constraint1": constraint1,
        "entry1": entry1, "entry2": entry2,
        "event1": event1,
    }


# ── Tests: Export ────────────────────────────────────────────────────────────


def test_export_empty_db_creates_valid_file(session, tmpfile):
    """빈 DB를 export 하면 유효한 JSON 파일이 생성되어야 합니다."""
    total = export_project(session, tmpfile)

    assert total == 0
    assert os.path.exists(tmpfile)

    with open(tmpfile, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "metadata" in data
    assert data["metadata"]["app_name"] == "학교 시간표 관리 시스템"
    assert "data" in data
    # 모든 테이블이 빈 배열로 존재해야 함
    assert data["data"]["academic_terms"] == []
    assert data["data"]["grades"] == []
    assert data["data"]["timetable_entries"] == []


def test_export_with_data(session, tmpfile):
    """데이터가 있는 DB를 export 하면 모든 행이 저장되어야 합니다."""
    _populate_minimal(session)
    total = export_project(session, tmpfile)

    assert total > 0

    with open(tmpfile, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["data"]["academic_terms"]) == 1
    assert len(data["data"]["grades"]) == 1
    assert len(data["data"]["rooms"]) == 1
    assert len(data["data"]["subjects"]) == 2
    assert len(data["data"]["school_classes"]) == 2
    assert len(data["data"]["teachers"]) == 2
    assert len(data["data"]["subject_class_assignments"]) == 2
    assert len(data["data"]["teacher_constraints"]) == 1
    assert len(data["data"]["timetable_entries"]) == 2
    assert len(data["data"]["school_events"]) == 1


def test_export_preserves_dates_and_nulls(session, tmpfile):
    """날짜 컬럼은 ISO 문자열로, None 은 null 로 직렬화되어야 합니다."""
    term = AcademicTerm(year=2025, semester=1, start_date=date_type(2025, 3, 2),
                        end_date=None, is_current=True)
    session.add(term)
    session.commit()

    total = export_project(session, tmpfile)
    assert total == 1

    with open(tmpfile, "r", encoding="utf-8") as f:
        data = json.load(f)

    t = data["data"]["academic_terms"][0]
    assert t["start_date"] == "2025-03-02"
    assert t["end_date"] is None
    assert t["is_current"] is True


# ── Tests: Roundtrip ────────────────────────────────────────────────────────


def test_roundtrip_preserves_all_data(session, tmpfile):
    """Export → Import 왕복 후 모든 데이터가 복원되어야 합니다."""
    ref = _populate_minimal(session)

    # 1차 export → import
    export_project(session, tmpfile)
    summary = import_project(session, tmpfile)

    assert summary["academic_terms"] == 1
    assert summary["grades"] == 1
    assert summary["subjects"] == 2
    assert summary["school_classes"] == 2
    assert summary["teachers"] == 2
    assert summary["subject_class_assignments"] == 2
    assert summary["teacher_constraints"] == 1
    assert summary["timetable_entries"] == 2
    assert summary["school_events"] == 1

    # 개별 데이터 검증
    terms = session.query(AcademicTerm).all()
    assert len(terms) == 1
    assert terms[0].year == 2025
    assert terms[0].semester == 1

    grades = session.query(Grade).all()
    assert len(grades) == 1
    assert grades[0].grade_number == 1

    subjects = session.query(Subject).order_by(Subject.name).all()
    assert len(subjects) == 2
    assert subjects[0].name == "국어"
    assert subjects[1].name == "수학"

    teachers = session.query(Teacher).order_by(Teacher.name).all()
    assert len(teachers) == 2
    assert teachers[0].name == "김철수"
    assert teachers[1].name == "박영희"


def test_roundtrip_preserves_relationships(session, tmpfile):
    """왕복 후 FK 관계가 올바르게 유지되어야 합니다."""
    _populate_minimal(session)
    export_project(session, tmpfile)
    import_project(session, tmpfile)

    # 교사의 담임 학반 확인
    t_kim = session.query(Teacher).filter_by(name="김철수").first()
    assert t_kim is not None
    assert t_kim.homeroom_class is not None
    assert t_kim.homeroom_class.display_name == "1-1"

    # 시간표 항목의 관계 확인
    entries = session.query(TimetableEntry).order_by(TimetableEntry.period).all()
    assert len(entries) == 2
    assert entries[0].subject.name == "수학"
    assert entries[0].teacher.name == "김철수"
    assert entries[0].school_class.display_name == "1-1"
    assert entries[0].room.name == "1-1 교실"

    # room_id=None 인 항목도 정상 복원
    assert entries[1].room is None
    assert entries[1].subject.name == "국어"

    # 교사 제약 확인
    constraints = session.query(TeacherConstraint).all()
    assert len(constraints) == 1
    assert constraints[0].teacher.name == "김철수"
    assert constraints[0].day_of_week == 3
    assert constraints[0].period == 5


def test_roundtrip_twice_is_idempotent(session, tmpfile):
    """두 번 왕복해도 데이터가 손상되지 않아야 합니다 (idempotency)."""
    _populate_minimal(session)

    export_project(session, tmpfile)
    import_project(session, tmpfile)   # 1차
    export_project(session, tmpfile)
    import_project(session, tmpfile)   # 2차

    assert session.query(Teacher).count() == 2
    assert session.query(TimetableEntry).count() == 2
    assert session.query(SubjectClassAssignment).count() == 2


# ── Tests: Import ID Remapping ───────────────────────────────────────────────


def test_import_with_non_contiguous_ids(session, tmpfile):
    """
    원본 데이터의 ID 가 비연속적이어도 import 후 FK 관계가 올바르게
    재매핑되어야 합니다. DB에서는 항상 1부터 새로운 autoincrement ID가 할당됩니다.
    """
    # 비연속 ID 를 가진 데이터 생성 (강제로 큰 ID 할당)
    term = AcademicTerm(id=100, year=2025, semester=1, is_current=True)
    session.add(term)
    grade1 = Grade(id=200, grade_number=1, name="1학년")
    session.add(grade1)
    session.flush()

    class1 = SchoolClass(id=300, grade_id=200, class_number=1, display_name="1-1")
    session.add(class1)
    session.flush()

    teacher1 = Teacher(id=400, name="홍길동", homeroom_class_id=300, max_daily_classes=5)
    session.add(teacher1)
    session.commit()

    export_project(session, tmpfile)
    import_project(session, tmpfile)

    # import 후 새 ID는 1부터 시작되어야 함
    imported_teacher = session.query(Teacher).first()
    assert imported_teacher is not None
    # 새 ID가 원본(400)과 달라야 함 (ID 재매핑 확인)
    assert imported_teacher.id != 400
    # 하지만 FK 관계는 올바르게 유지되어야 함
    assert imported_teacher.homeroom_class is not None
    assert imported_teacher.homeroom_class.display_name == "1-1"


# ── Tests: Import Overwrite ──────────────────────────────────────────────────


def test_import_replaces_all_existing_data(session, tmpfile):
    """Import 하면 기존 데이터가 모두 파일 내용으로 대체되어야 합니다."""
    # 먼저 데이터셋 A 삽입 후 export
    _populate_minimal(session)
    export_project(session, tmpfile)

    # 데이터셋 B 삽입 (데이터셋 A + 추가 데이터)
    term2 = AcademicTerm(year=2026, semester=1, is_current=True)
    session.add(term2)
    grade3 = Grade(grade_number=3, name="3학년")
    session.add(grade3)
    session.commit()

    # import 하면 데이터셋 A 상태로 되돌아가야 함
    import_project(session, tmpfile)

    # 데이터셋 B의 데이터는 사라져야 함
    assert session.query(AcademicTerm).count() == 1
    assert session.query(AcademicTerm).first().year == 2025
    assert session.query(Grade).count() == 1
    assert session.query(Grade).first().grade_number == 1


# ── Tests: Import Error Handling ─────────────────────────────────────────────


def test_import_rollback_preserves_original_data(session, tmpfile):
    """Import 실패 시 기존 데이터가 그대로 보존되어야 합니다."""
    _populate_minimal(session)
    orig_count = session.query(Teacher).count()

    # 손상된 JSON 파일 생성 (존재하지 않는 teacher_id 참조)
    bad_data = {
        "metadata": {"app_name": "test", "file_version": "1.0", "exported_at": ""},
        "data": {
            "academic_terms": [{"id": 1, "year": 2025, "semester": 1,
                                "start_date": None, "end_date": None, "is_current": True}],
            "grades": [],
            "rooms": [],
            "subjects": [],
            "school_classes": [{"id": 1, "grade_id": 999, "class_number": 1,
                                "display_name": "X", "homeroom_room_id": None}],
            "teachers": [],
            "subject_class_assignments": [],
            "teacher_constraints": [],
            "timetable_entries": [],
            "school_events": [],
            "timetable_change_logs": [],
            "timetable_change_requests": [],
        },
    }
    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump(bad_data, f)

    with pytest.raises(ValueError, match="grade_id"):
        import_project(session, tmpfile)

    # 기존 데이터가 보존되었는지 확인
    assert session.query(Teacher).count() == orig_count


def test_import_corrupted_json_raises(session, tmpfile):
    """깨진 JSON 파일은 ValueError 를 발생시켜야 합니다."""
    with open(tmpfile, "w", encoding="utf-8") as f:
        f.write("이것은 JSON이 아닙니다 {{{")

    with pytest.raises(ValueError, match="JSON"):
        import_project(session, tmpfile)


# ── Tests: Validation ────────────────────────────────────────────────────────


def test_validate_rejects_missing_metadata(tmpfile):
    """metadata 키가 없으면 검증에 실패해야 합니다."""
    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump({"data": {}}, f)

    valid, msg = validate_project_file(tmpfile)
    assert not valid
    assert "metadata" in msg


def test_validate_rejects_missing_data(tmpfile):
    """data 키가 없으면 검증에 실패해야 합니다."""
    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"file_version": "1.0"}}, f)

    valid, msg = validate_project_file(tmpfile)
    assert not valid
    assert "data" in msg


def test_validate_rejects_wrong_version(tmpfile):
    """file_version 이 다르면 검증에 실패해야 합니다."""
    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"file_version": "0.5"}, "data": {}}, f)

    valid, msg = validate_project_file(tmpfile)
    assert not valid
    assert "버전" in msg


def test_validate_accepts_valid_file(session, tmpfile):
    """유효한 파일은 검증을 통과해야 합니다."""
    _populate_minimal(session)
    export_project(session, tmpfile)

    valid, msg = validate_project_file(tmpfile)
    assert valid
    assert msg == ""


def test_validate_rejects_nonexistent_file():
    """존재하지 않는 파일은 검증에 실패해야 합니다."""
    valid, msg = validate_project_file("/nonexistent/path/file.json")
    assert not valid
    assert "찾을 수 없" in msg


# ── Tests: Special Characters ────────────────────────────────────────────────


def test_export_preserves_unicode_text(session, tmpfile):
    """한글, 특수문자 등 Unicode 텍스트가 정상적으로 보존되어야 합니다."""
    term = AcademicTerm(year=2025, semester=1, is_current=True)
    session.add(term)
    grade = Grade(grade_number=1, name="1학년")
    session.add(grade)
    session.flush()

    room = Room(name="과학🔬실험실", room_type="과학실", notes="특별실 — 환기 필수")
    session.add(room)
    session.flush()

    subj = Subject(name="사회·문화", short_name="사문", color_hex="#F3E5F5")
    session.add(subj)
    session.flush()

    cls = SchoolClass(grade_id=grade.id, class_number=1, display_name="1-1",
                      homeroom_room_id=room.id)
    session.add(cls)
    session.flush()

    teacher = Teacher(name="이영민", employee_number="한-T2025-03", is_homeroom=True,
                      homeroom_class_id=cls.id)
    session.add(teacher)
    session.commit()

    export_project(session, tmpfile)
    import_project(session, tmpfile)

    # 검증
    imported_room = session.query(Room).first()
    assert imported_room.name == "과학🔬실험실"
    assert imported_room.notes == "특별실 — 환기 필수"

    imported_subj = session.query(Subject).filter_by(short_name="사문").first()
    assert imported_subj is not None
    assert imported_subj.name == "사회·문화"

    imported_teacher = session.query(Teacher).first()
    assert imported_teacher.name == "이영민"
    assert imported_teacher.employee_number == "한-T2025-03"
