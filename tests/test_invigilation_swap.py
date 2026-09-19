"""
감독 스왑 승인 라인 E2E 테스트 (요구사항 8).

감독 교체 신청은 수업 변경 신청과 동일한 결재 파이프라인을 재사용합니다:
  교사 A 스왑 신청 → 상대 교사 B 동의 → 일과계 1차 승인 → 교감 최종 승인
  → 두 감독 배정의 teacher_id 상호 교환.

검증 대상:
  - 전체 승인 라인 통과 시 감독 실제 교환
  - 본인 감독 배정이 아닌 슬롯으로 신청 → 403 (타인 감독 임의 교체 차단)
  - 미배정 상대 슬롯 → 400, 게시 전 시험 → 400
  - 상대 교사 동의 거절 → 신청 최종 거절 + 감독 불변
  - 결재 기간 중 배정 변경(스냅샷 충돌) → 409 + 롤백
"""
from datetime import date, time

import pytest

from database.models import (
    AcademicTerm, Grade, SchoolClass, Teacher,
    Exam, ExamPeriod, InvigilationAssignment,
)


# ── 공통 데이터셋 ─────────────────────────────────────────────────────────────

@pytest.fixture
def dataset(db):
    """
    감독 스왑 테스트용 표준 시나리오.

    시험(게시됨) 1일 2교시, 1학년 1반(25명 → 2인 1조):
      - 1교시 pair1 = 김교사(T1), pair2 = 박교사(T2)
      - 2교시 pair1 = 김교사(T1), pair2 = 박교사(T2)
    → 두 교사가 서로 다른 교시 조를 맞바꾸는 시나리오가 자연스럽게 성립.
    """
    term = AcademicTerm(year=2026, semester=2, is_current=True)
    db.add(term)
    db.flush()
    grade = Grade(grade_number=1, name="1학년")
    db.add(grade)
    db.flush()
    cls = SchoolClass(grade_id=grade.id, class_number=1,
                      display_name="1-1", student_count=25)
    db.add(cls)
    db.flush()
    t1 = Teacher(name="김교사")
    t2 = Teacher(name="박교사")
    t3 = Teacher(name="이교사")   # 스냅샷 충돌 테스트의 대체자
    db.add_all([t1, t2, t3])
    db.commit()

    exam = Exam(
        term_id=term.id, name="중간고사", exam_type="midterm",
        school_level="high", target_grade_ids="[]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
        first_period_start=time(8, 30), periods_per_day=2,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=3,
        status="published",   # 감독 스왑은 게시된 시험만 가능
    )
    db.add(exam)
    db.flush()
    p1 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=1,
                    start_time=time(8, 30), end_time=time(9, 20))
    p2 = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=2,
                    start_time=time(9, 30), end_time=time(10, 20))
    db.add_all([p1, p2])
    db.flush()
    # 1교시: T1(조1) + T2(조2) / 2교시: T1(조1) + T2(조2)
    a_p1_t1 = InvigilationAssignment(exam_id=exam.id, period_id=p1.id,
                                     school_class_id=cls.id, teacher_id=t1.id, pair_index=1)
    a_p1_t2 = InvigilationAssignment(exam_id=exam.id, period_id=p1.id,
                                     school_class_id=cls.id, teacher_id=t2.id, pair_index=2)
    a_p2_t1 = InvigilationAssignment(exam_id=exam.id, period_id=p2.id,
                                     school_class_id=cls.id, teacher_id=t1.id, pair_index=1)
    a_p2_t2 = InvigilationAssignment(exam_id=exam.id, period_id=p2.id,
                                     school_class_id=cls.id, teacher_id=t2.id, pair_index=2)
    db.add_all([a_p1_t1, a_p1_t2, a_p2_t1, a_p2_t2])
    db.commit()

    return {
        "term": term, "grade": grade, "cls": cls,
        "teacher1": t1, "teacher2": t2, "teacher3": t3,
        "exam": exam, "p1": p1, "p2": p2,
        # 스왑 시나리오: T1 의 2교시 조 ↔ T2 의 1교시 조
        "mine": a_p2_t1, "partner": a_p1_t2,
    }


@pytest.fixture
def admin_h(auth_client):
    return auth_client("admin", "adminpass", "admin")


@pytest.fixture
def vp_h(auth_client):
    return auth_client("vp", "vppass", "vice_principal")


@pytest.fixture
def t1_h(auth_client, dataset):
    return auth_client("kim", "pass", "teacher", dataset["teacher1"].id)


@pytest.fixture
def t2_h(auth_client, dataset):
    return auth_client("park", "pass", "teacher", dataset["teacher2"].id)


def _submit_swap(client, t1_h, dataset, **overrides):
    """표준 스왑 신청 제출 헬퍼 — overrides 로 일부 필드 교체."""
    payload = {
        "request_type": "invigilation",
        "invigilation_assignment_id": dataset["mine"].id,
        "swap_partner_invigilation_id": dataset["partner"].id,
        "reason": "개인 사정",
    }
    payload.update(overrides)
    return client.post("/timetable/requests", headers=t1_h, json=payload)


# ── E2E: 제출 → 동의 → 1차 → 최종 ────────────────────────────────────────────

def test_swap_full_approval_line(client, dataset, t1_h, t2_h, admin_h, vp_h):
    """전체 승인 라인 통과 시 두 감독 배정의 교사가 실제로 맞바뀝니다."""
    # 1단계 — T1 스왑 신청
    resp = _submit_swap(client, t1_h, dataset)
    assert resp.status_code == 201, resp.text
    req = resp.json()
    assert req["request_type"] == "invigilation"
    assert req["consent_status"] == "pending"
    assert req["current_step"] == 0
    assert req["affected_teacher_id"] == dataset["teacher2"].id
    req_id = req["id"]

    # 2단계 — 상대 교사 T2 동의 → 결재 라인 진입
    resp = client.patch(f"/timetable/requests/{req_id}/consent",
                        headers=t2_h, json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["consent_status"] == "approved"
    assert resp.json()["current_step"] == 1

    # 3단계 — 일과계 1차 승인
    resp = client.patch(f"/timetable/requests/{req_id}",
                        headers=admin_h, json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["current_step"] == 2   # 교감 최종 단계로

    # 4단계 — 교감 최종 승인 → 감독 실제 교환
    resp = client.patch(f"/timetable/requests/{req_id}",
                        headers=vp_h, json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    from database.connection import get_session
    s = get_session()
    try:
        mine = s.get(InvigilationAssignment, dataset["mine"].id)
        partner = s.get(InvigilationAssignment, dataset["partner"].id)
        # 교환 검증: 내 슬롯에 T2, 상대 슬롯에 T1
        assert mine.teacher_id == dataset["teacher2"].id
        assert partner.teacher_id == dataset["teacher1"].id
    finally:
        s.close()


# ── 검증 규칙 ────────────────────────────────────────────────────────────────

def test_cannot_swap_others_assignment(client, dataset, t2_h):
    """본인 감독 배정이 아닌 슬롯을 '내 슬롯'으로 신청 → 403."""
    # T2 가 T1 의 슬롯(mine) 을 본인 것처럼 신청하는 경우
    resp = client.post("/timetable/requests", headers=t2_h, json={
        "request_type": "invigilation",
        "invigilation_assignment_id": dataset["mine"].id,   # T1 의 슬롯
        "swap_partner_invigilation_id": dataset["partner"].id,
        "reason": "타인 슬롯 신청",
    })
    assert resp.status_code == 403


def test_unassigned_partner_rejected(client, dataset, db, t1_h):
    """상대 슬롯에 배정된 교사가 없으면 스왑 신청 자체가 400."""
    a_none = InvigilationAssignment(
        exam_id=dataset["exam"].id, period_id=dataset["p1"].id,
        school_class_id=dataset["cls"].id, teacher_id=None, pair_index=3)
    db.add(a_none)
    db.commit()
    resp = _submit_swap(client, t1_h, dataset,
                        swap_partner_invigilation_id=a_none.id)
    assert resp.status_code == 400


def test_draft_exam_swap_rejected(client, dataset, db, t1_h):
    """게시 전(draft) 시험의 감독은 결재 라인 없이 관리자 수동 배정 영역 → 400."""
    dataset["exam"].status = "draft"
    db.commit()
    resp = _submit_swap(client, t1_h, dataset)
    assert resp.status_code == 400


def test_same_teacher_slots_rejected(client, dataset, db, t1_h):
    """교사가 자기 감독 두 조를 맞바꾸는 무의미한 신청 → 400."""
    a_own = InvigilationAssignment(
        exam_id=dataset["exam"].id, period_id=dataset["p2"].id,
        school_class_id=dataset["cls"].id,
        teacher_id=dataset["teacher1"].id, pair_index=3)
    db.add(a_own)
    db.commit()
    resp = _submit_swap(client, t1_h, dataset,
                        swap_partner_invigilation_id=a_own.id)
    assert resp.status_code == 400


def test_consent_reject_blocks_swap(client, dataset, t1_h, t2_h, admin_h):
    """상대 교사 동의 거절 → 신청 최종 거절, 감독 배정은 불변."""
    req_id = _submit_swap(client, t1_h, dataset).json()["id"]

    resp = client.patch(f"/timetable/requests/{req_id}/consent",
                        headers=t2_h, json={"action": "reject"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    # 동의 거절로 종료된 신청을 관리자가 승인 시도 → 400
    resp = client.patch(f"/timetable/requests/{req_id}",
                        headers=admin_h, json={"action": "approve"})
    assert resp.status_code == 400

    from database.connection import get_session
    s = get_session()
    try:
        mine = s.get(InvigilationAssignment, dataset["mine"].id)
        partner = s.get(InvigilationAssignment, dataset["partner"].id)
        assert mine.teacher_id == dataset["teacher1"].id
        assert partner.teacher_id == dataset["teacher2"].id
    finally:
        s.close()


def test_snapshot_conflict_returns_409(client, dataset, t1_h, t2_h, admin_h, vp_h):
    """
    결재 기간 중 감독 배정이 바뀌면 최종 승인 적용 시 409 Conflict.

    시나리오: 신청 → 동의 → 일과계 승인까지 마친 뒤, 관리자가 수동 배정
    변경으로 상대 슬롯의 교사를 바꿈 → 교감 최종 승인 시 스냅샷 불일치로
    409 발생, 트랜잭션 롤백으로 감독은 교환되지 않음.
    """
    req_id = _submit_swap(client, t1_h, dataset).json()["id"]
    client.patch(f"/timetable/requests/{req_id}/consent",
                 headers=t2_h, json={"action": "approve"})
    client.patch(f"/timetable/requests/{req_id}",
                 headers=admin_h, json={"action": "approve"})

    # 결재 기간 중 관리자의 수동 배정 변경 (예: 질병으로 대체자 투입).
    # 대체자는 이교사(T3) — T1 은 이미 같은 교시(p1)에 감독 중이라 409 에 걸림.
    resp = client.put(f"/exams/invigilations/{dataset['partner'].id}",
                      headers=admin_h, json={"teacher_id": dataset["teacher3"].id})
    assert resp.status_code == 200

    # 교감 최종 승인 → 스냅샷 불일치 409
    resp = client.patch(f"/timetable/requests/{req_id}",
                        headers=vp_h, json={"action": "approve"})
    assert resp.status_code == 409