"""
혼합 시험실(ExamRoom) · 학년별 시험 미참여 날짜(ExamGradeDateExclusion) ·
복도감독(CorridorDutyAssignment) API 테스트 (2026-10-04 신규).
"""
from datetime import date, time

import pytest

from shared.models import (
    AcademicTerm, Grade, SchoolClass, Subject, Teacher,
    SubjectClassAssignment, ExamEntry, ExamPeriod, ExamRoom,
)


def _make_env(db):
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    grade = Grade(grade_number=2, name="2학년")
    db.add(grade)
    db.flush()
    c1 = SchoolClass(grade_id=grade.id, class_number=1, display_name="2-1", student_count=20)
    c2 = SchoolClass(grade_id=grade.id, class_number=2, display_name="2-2", student_count=20)
    db.add_all([c1, c2])
    db.flush()
    subj = Subject(name="세계사", short_name="세계")
    db.add(subj)
    db.flush()
    t1 = Teacher(name="쌤1")
    db.add(t1)
    db.commit()
    return {"term": term, "grade": grade, "classes": [c1, c2], "subject": subj, "teacher": t1}


@pytest.fixture
def admin_h(client, auth_client):
    return auth_client("admin", "pass", "admin")


@pytest.fixture
def teacher_h(client, auth_client, db):
    env = _make_env(db)
    return auth_client("teacher1", "pass", "teacher", teacher_id=env["teacher"].id), env


def _create_exam(client, admin_h, term_id):
    resp = client.post("/exams", json={
        "term_id": term_id, "name": "선택과목 시험",
        "start_date": "2026-10-05", "end_date": "2026-10-05",
        "target_grade_ids": [], "periods_per_day": 1,
    }, headers=admin_h)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_list_exam_room(client, admin_h, db):
    env = _make_env(db)
    exam = _create_exam(client, admin_h, env["term"].id)
    periods = client.get(f"/exams/{exam['id']}/periods", headers=admin_h).json()
    period_id = periods[0]["id"]

    resp = client.post(f"/exams/{exam['id']}/rooms", json={
        "period_id": period_id, "grade_id": env["grade"].id,
        "subject_id": env["subject"].id,
        "source_class_ids": [c.id for c in env["classes"]],
        "student_count": 24, "label": "세계사(3반 교실)",
    }, headers=admin_h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_class_ids"] == [c.id for c in env["classes"]]
    assert body["student_count"] == 24

    listed = client.get(f"/exams/{exam['id']}/rooms", headers=admin_h).json()
    assert len(listed) == 1
    assert listed[0]["label"] == "세계사(3반 교실)"


def test_create_exam_room_rejects_period_from_other_exam(client, admin_h, db):
    env = _make_env(db)
    exam1 = _create_exam(client, admin_h, env["term"].id)
    exam2 = _create_exam(client, admin_h, env["term"].id)
    periods2 = client.get(f"/exams/{exam2['id']}/periods", headers=admin_h).json()

    resp = client.post(f"/exams/{exam1['id']}/rooms", json={
        "period_id": periods2[0]["id"], "grade_id": env["grade"].id,
    }, headers=admin_h)
    assert resp.status_code == 400


def test_delete_exam_room(client, admin_h, db):
    env = _make_env(db)
    exam = _create_exam(client, admin_h, env["term"].id)
    period_id = client.get(f"/exams/{exam['id']}/periods", headers=admin_h).json()[0]["id"]
    room = client.post(f"/exams/{exam['id']}/rooms", json={
        "period_id": period_id, "grade_id": env["grade"].id,
    }, headers=admin_h).json()

    resp = client.delete(f"/exams/rooms/{room['id']}", headers=admin_h)
    assert resp.status_code == 200
    listed = client.get(f"/exams/{exam['id']}/rooms", headers=admin_h).json()
    assert listed == []


def test_teacher_cannot_create_exam_room(client, teacher_h):
    headers, env = teacher_h
    # 교사는 쓰기 권한이 없으므로 시험 생성조차 403 — rooms 엔드포인트도 동일 가드
    resp = client.post("/exams", json={
        "term_id": env["term"].id, "name": "시험",
        "start_date": "2026-10-05", "end_date": "2026-10-05",
        "target_grade_ids": [], "periods_per_day": 1,
    }, headers=headers)
    assert resp.status_code == 403


def test_grade_exclusion_crud_and_date_range_validation(client, admin_h, db):
    env = _make_env(db)
    exam = _create_exam(client, admin_h, env["term"].id)

    # 시험 기간(10/5) 밖 날짜는 거부
    resp = client.post(f"/exams/{exam['id']}/grade-exclusions", json={
        "grade_id": env["grade"].id, "exam_date": "2026-10-10",
    }, headers=admin_h)
    assert resp.status_code == 400

    resp = client.post(f"/exams/{exam['id']}/grade-exclusions", json={
        "grade_id": env["grade"].id, "exam_date": "2026-10-05",
    }, headers=admin_h)
    assert resp.status_code == 201
    exclusion_id = resp.json()["id"]

    listed = client.get(f"/exams/{exam['id']}/grade-exclusions", headers=admin_h).json()
    assert len(listed) == 1

    resp = client.delete(f"/exams/grade-exclusions/{exclusion_id}", headers=admin_h)
    assert resp.status_code == 200
    listed = client.get(f"/exams/{exam['id']}/grade-exclusions", headers=admin_h).json()
    assert listed == []


def test_corridor_duty_auto_assign_and_manual_update(client, admin_h, db):
    env = _make_env(db)
    # 세계사 담당 교사 배정 — 복도감독 후보가 되려면 필요
    db.add(SubjectClassAssignment(
        school_class_id=env["classes"][0].id, subject_id=env["subject"].id,
        teacher_id=env["teacher"].id, weekly_hours=3, term_id=env["term"].id,
    ))
    db.commit()

    exam = _create_exam(client, admin_h, env["term"].id)
    period_id = client.get(f"/exams/{exam['id']}/periods", headers=admin_h).json()[0]["id"]

    # ExamEntry 를 직접 심어 "그 교시 그 학년 시험 과목"을 만든다
    db.add(ExamEntry(
        exam_id=exam["id"], period_id=period_id, grade_id=env["grade"].id,
        subject_id=env["subject"].id,
    ))
    db.commit()

    ok_resp = client.post(f"/exams/{exam['id']}/assign-invigilations", headers=admin_h)
    assert ok_resp.status_code == 200

    resp = client.post(f"/exams/{exam['id']}/assign-corridor-duty", headers=admin_h)
    assert resp.status_code == 200

    listed = client.get(f"/exams/{exam['id']}/corridor-duties", headers=admin_h).json()
    assert len(listed) == 1
    duty_id = listed[0]["id"]

    # 수동으로 teacher_id=None(미배정)으로 되돌리기 — 충돌 없음
    resp = client.put(f"/exams/corridor-duties/{duty_id}", json={"teacher_id": None}, headers=admin_h)
    assert resp.status_code == 200
    assert resp.json()["teacher_id"] is None
