"""
시간표 변경 신청 + 피교사 동의 + 교환/제안 API 테스트

server/api/timetable.py 의 다음 흐름을 검증합니다:
  - 교실 변경은 동의(consent)가 필요 없습니다.
  - 교사 변경은 피교사 동의가 필요하며, 동의 전에는 관리자 승인이 불가능합니다.
  - 교사 변경 동의 → 관리자 승인 → 최종 승인까지 정상 진행됩니다.
  - 피교사가 동의 거절하면 최종 거절 상태가 됩니다.
  - 시간표 교환(swap) 제안 및 신청이 정상 동작합니다.
"""
from datetime import date

import pytest

from database.models import (
    AcademicTerm, Grade, Room, Subject, SchoolClass, Teacher,
    TimetableEntry,
)


@pytest.fixture
def dataset(db):
    """변경 신청 테스트에 필요한 최소 데이터셋을 생성합니다."""
    term = AcademicTerm(year=2025, semester=1, is_current=True,
                        start_date=date(2025, 3, 2), end_date=date(2025, 8, 31))
    db.add(term)

    grade = Grade(grade_number=1, name="1학년")
    db.add(grade)

    room1 = Room(name="1-1 교실", room_type="일반", capacity=30, floor=1)
    room2 = Room(name="1-2 교실", room_type="일반", capacity=30, floor=1)
    db.add_all([room1, room2])

    subject = Subject(name="수학", short_name="수", color_hex="#E3F2FD")
    db.add(subject)
    db.flush()

    school_class = SchoolClass(grade_id=grade.id, class_number=1, display_name="1-1")
    db.add(school_class)
    db.flush()

    t1 = Teacher(name="김교사", employee_number="T001", max_daily_classes=5)
    t2 = Teacher(name="박교사", employee_number="T002", max_daily_classes=5)
    db.add_all([t1, t2])
    db.flush()

    entry1 = TimetableEntry(
        term_id=term.id, school_class_id=school_class.id,
        subject_id=subject.id, teacher_id=t1.id, room_id=room1.id,
        day_of_week=1, period=1,
    )
    entry2 = TimetableEntry(
        term_id=term.id, school_class_id=school_class.id,
        subject_id=subject.id, teacher_id=t2.id, room_id=room2.id,
        day_of_week=2, period=1,
    )
    db.add_all([entry1, entry2])
    db.commit()

    return {
        "term": term, "grade": grade,
        "room1": room1, "room2": room2,
        "subject": subject, "school_class": school_class,
        "teacher1": t1, "teacher2": t2,
        "entry1": entry1, "entry2": entry2,
    }


@pytest.fixture
def admin_headers(auth_client):
    return auth_client("admin", "adminpass", "admin")


@pytest.fixture
def vice_principal_headers(auth_client):
    return auth_client("vp", "vppass", "vice_principal")


@pytest.fixture
def teacher1_headers(auth_client, dataset):
    return auth_client("kim", "pass", "teacher", dataset["teacher1"].id)


@pytest.fixture
def teacher2_headers(auth_client, dataset):
    return auth_client("park", "pass", "teacher", dataset["teacher2"].id)


def test_room_change_does_not_require_consent(client, dataset, teacher1_headers):
    """교실만 변경하면 동의가 필요 없고 바로 결재 단계로 넘어갑니다."""
    entry_id = dataset["entry1"].id
    room2_id = dataset["room2"].id

    resp = client.post("/timetable/requests", headers=teacher1_headers, json={
        "timetable_entry_id": entry_id,
        "new_room_id": room2_id,
        "reason": "교실 이동",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["consent_status"] == "not_required"
    assert data["current_step"] == 1
    assert data["affected_teacher_id"] is None


def test_teacher_change_requires_consent(client, dataset, teacher1_headers):
    """담당 교사를 바꾸면 피교사 동의가 필요하며 관리자는 아직 승인할 수 없습니다."""
    entry_id = dataset["entry1"].id
    teacher2_id = dataset["teacher2"].id

    resp = client.post("/timetable/requests", headers=teacher1_headers, json={
        "timetable_entry_id": entry_id,
        "new_teacher_id": teacher2_id,
        "reason": "업무 조정으로 인한 교체",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["consent_status"] == "pending"
    assert data["current_step"] == 0
    assert data["affected_teacher_id"] == teacher2_id

    # 동의 전 관리자 승인은 불가능
    req_id = data["id"]
    admin_h = auth_client_for_test(client, "admin2", "admin")
    resp2 = client.patch(f"/timetable/requests/{req_id}", headers=admin_h, json={
        "action": "approve",
    })
    assert resp2.status_code == 400


def test_consent_approve_then_admin_approve(client, dataset, teacher1_headers, teacher2_headers):
    """피교사 동의 → 일과계 승인 → 교감 최종 승인 순서로 변경이 반영됩니다."""
    entry_id = dataset["entry1"].id
    teacher2_id = dataset["teacher2"].id

    resp = client.post("/timetable/requests", headers=teacher1_headers, json={
        "timetable_entry_id": entry_id,
        "new_teacher_id": teacher2_id,
        "reason": "업무 조정",
    })
    assert resp.status_code == 201
    req = resp.json()
    assert req["consent_status"] == "pending"

    # 피교사(박교사) 동의 승인
    req_id = req["id"]
    resp = client.patch(f"/timetable/requests/{req_id}/consent", headers=teacher2_headers, json={
        "action": "approve",
    })
    assert resp.status_code == 200
    assert resp.json()["consent_status"] == "approved"
    assert resp.json()["current_step"] == 1

    # 일과계 1차 승인
    admin_h = auth_client_for_test(client, "admin3", "admin")
    resp = client.patch(f"/timetable/requests/{req_id}", headers=admin_h, json={
        "action": "approve",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["current_step"] == 2

    # 교감 최종 승인
    vp_h = auth_client_for_test(client, "vp3", "vice_principal")
    resp = client.patch(f"/timetable/requests/{req_id}", headers=vp_h, json={
        "action": "approve",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["consent_status"] == "approved"


def test_consent_reject_finalizes_rejected(client, dataset, teacher1_headers, teacher2_headers):
    """피교사가 동의를 거절하면 신청은 최종 거절 상태가 됩니다."""
    entry_id = dataset["entry1"].id
    teacher2_id = dataset["teacher2"].id

    resp = client.post("/timetable/requests", headers=teacher1_headers, json={
        "timetable_entry_id": entry_id,
        "new_teacher_id": teacher2_id,
        "reason": "업무 조정",
    })
    req_id = resp.json()["id"]

    resp = client.patch(f"/timetable/requests/{req_id}/consent", headers=teacher2_headers, json={
        "action": "reject",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["consent_status"] == "rejected"
    assert data["status"] == "rejected"

    # 거절된 신청은 관리자도 승인 불가
    admin_h = auth_client_for_test(client, "admin4", "admin")
    resp2 = client.patch(f"/timetable/requests/{req_id}", headers=admin_h, json={
        "action": "approve",
    })
    assert resp2.status_code == 400


def test_swap_suggestion(client, dataset, teacher1_headers):
    """GET /timetable/suggestions 는 교환 가능한 상대 슬롯을 제안해야 합니다."""
    entry1_id = dataset["entry1"].id
    entry2_id = dataset["entry2"].id

    resp = client.get("/timetable/suggestions", headers=teacher1_headers, params={
        "entry_id": entry1_id,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"]["entry_id"] == entry1_id
    swap_ids = {opt["swap_partner_entry_id"] for opt in data["swaps"]}
    assert entry2_id in swap_ids


def test_swap_request_requires_consent(client, dataset, teacher1_headers):
    """교환(swap) 신청은 상대 교사의 동의가 필요합니다."""
    entry1_id = dataset["entry1"].id
    entry2_id = dataset["entry2"].id
    teacher2_id = dataset["teacher2"].id

    resp = client.post("/timetable/requests", headers=teacher1_headers, json={
        "timetable_entry_id": entry1_id,
        "swap_partner_entry_id": entry2_id,
        "reason": "서로 수업 교환",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["consent_status"] == "pending"
    assert data["affected_teacher_id"] == teacher2_id
    assert data["swap_partner_entry_id"] == entry2_id


# ── 내부 헬퍼 ───────────────────────────────────────────────────────────────

def auth_client_for_test(client, username: str, role: str, password: str = "pass"):
    """
    테스트 파일 내부에서 간단히 인증 헤더를 만드는 헬퍼.

    이미 존재하는 사용자면 생성을 건너뛰고 바로 로그인합니다.
    """
    from database.connection import get_session
    from server.auth_utils import hash_password
    from shared.models import User

    s = get_session()
    try:
        user = s.query(User).filter_by(username=username).first()
        if user is None:
            user = User(username=username, password_hash=hash_password(password),
                        role=role, is_active=True)
            s.add(user)
            s.commit()
    finally:
        s.close()

    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
