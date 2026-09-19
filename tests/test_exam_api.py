"""
시험 관리 API (/exams) 테스트.

검증 대상:
  - 시험 생성 시 교시(ExamPeriod) 자동 생성 + 시각 계산 (요구사항 4)
  - 권한 규칙: 쓰기=일과계, 교사는 게시된 시험만 조회
  - PATCH 시 교시 재생성 / 게시된 시험 수정 거부
  - 시험 시간표 자동 배치 엔드포인트
  - 감독 자동 배정 + 수동 변경(동시간 중복 409)
  - 감독 불가 신청: 교사 제출 → 관리자 승인 라인
  - 게시(publish) → 교사 조회 가능 + 내 감독 조회
"""
from datetime import date, time

import pytest

from shared.models import (
    AcademicTerm, Grade, SchoolClass, Subject, Teacher,
    SubjectClassAssignment, ExamEntry, ExamPeriod, InvigilationAssignment,
)


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _make_env(db):
    """
    API 테스트용 최소 데이터셋: 학기 1개, 1학년 1반(25명), 과목 2개,
    자유 교사 2명. 대부분의 테스트가 이 구성을 변형해 사용합니다.
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
    s1 = Subject(name="국어", short_name="국")
    s2 = Subject(name="수학", short_name="수")
    db.add_all([s1, s2])
    db.flush()
    t1 = Teacher(name="쌤1")
    t2 = Teacher(name="쌤2")
    # 쌤3: 감독 자동 배정 결과와 무관한 여유 교사.
    # 자동 배정은 랜덤 재시작을 쓰므로, 배정에 관여하지 않는 교사를 통한
    # 수동 변경 테스트를 해야 결과가 결정적입니다.
    t3 = Teacher(name="쌤3")
    db.add_all([t1, t2, t3])
    db.commit()
    return {"term": term, "grade": grade, "cls": cls,
            "subjects": [s1, s2], "teachers": [t1, t2, t3]}


def _assign_subjects(db, env):
    """1반에 국어·수학 과목 배정 — 자동 배치의 대상 과목 생성용."""
    for s in env["subjects"]:
        db.add(SubjectClassAssignment(
            school_class_id=env["cls"].id, subject_id=s.id,
            teacher_id=env["teachers"][0].id, weekly_hours=2,
            term_id=env["term"].id))
    db.commit()


def _exam_payload(term, **overrides):
    """POST /exams 기본 페이로드 — overrides 로 필드 일부 교체."""
    payload = {
        "term_id": term.id,
        "name": "중간고사",
        "start_date": "2026-10-05",
        "end_date": "2026-10-06",
        "target_grade_ids": [],
        "periods_per_day": 2,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def admin_h(client, auth_client):
    """일과계(admin) 로그인 헤더."""
    return auth_client("admin", "pass", "admin")


@pytest.fixture
def vp_h(client, auth_client):
    """교감(vice_principal) 로그인 헤더."""
    return auth_client("vp", "pass", "vice_principal")


@pytest.fixture
def teacher_h(client, auth_client, db):
    """교사(role="teacher") 로그인 헤더 — teacher_id 연결 필수."""
    t = Teacher(name="교사쌤")
    db.add(t)
    db.commit()
    return auth_client("teacher1", "pass", "teacher", teacher_id=t.id)


# ── 시험 CRUD ────────────────────────────────────────────────────────────────

def test_create_exam_generates_periods(client, admin_h, db):
    """생성 시 기간×교시 수만큼 ExamPeriod 자동 생성 + 시각 계산 검증."""
    env = _make_env(db)
    resp = client.post("/exams", headers=admin_h,
                       json=_exam_payload(env["term"]))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"

    # 2일 × 2교시 = 4개 교시
    resp = client.get(f"/exams/{body['id']}/periods", headers=admin_h)
    periods = resp.json()
    assert len(periods) == 4
    # 기본값: 08:30 시작, 시험 50분, 쉬는시간 10분
    assert periods[0]["start_time"].startswith("08:30")
    assert periods[0]["end_time"].startswith("09:20")
    assert periods[1]["start_time"].startswith("09:30")


def test_create_exam_rejects_bad_range(client, admin_h, db):
    """end < start 인 생성 요청은 400."""
    env = _make_env(db)
    resp = client.post("/exams", headers=admin_h, json=_exam_payload(
        env["term"], start_date="2026-10-06", end_date="2026-10-05"))
    assert resp.status_code == 400


def test_create_exam_permission(client, db, teacher_h, vp_h):
    """시험 생성은 일과계만 가능 — 교사·교감은 403."""
    env = _make_env(db)
    payload = _exam_payload(env["term"])
    assert client.post("/exams", headers=teacher_h, json=payload).status_code == 403
    assert client.post("/exams", headers=vp_h, json=payload).status_code == 403


def test_teacher_sees_published_only(client, admin_h, db, teacher_h):
    """교사는 draft 시험 목록에서 제외되고, 게시 후에만 보입니다."""
    env = _make_env(db)
    resp = client.post("/exams", headers=admin_h,
                       json=_exam_payload(env["term"]))
    exam_id = resp.json()["id"]

    # draft — 관리자는 보이고, 교사는 안 보임
    assert len(client.get("/exams", headers=admin_h).json()) == 1
    assert len(client.get("/exams", headers=teacher_h).json()) == 0
    # 단건 조회도 교사는 403
    assert client.get(f"/exams/{exam_id}", headers=teacher_h).status_code == 403

    client.post(f"/exams/{exam_id}/publish", headers=admin_h)
    assert len(client.get("/exams", headers=teacher_h).json()) == 1
    assert client.get(f"/exams/{exam_id}", headers=teacher_h).status_code == 200


def test_patch_rebuilds_periods_and_blocks_published(client, admin_h, db):
    """PATCH 로 교시 수 변경 시 periods 재생성, 게시된 시험은 수정 거부."""
    env = _make_env(db)
    exam_id = client.post("/exams", headers=admin_h,
                          json=_exam_payload(env["term"])).json()["id"]

    resp = client.patch(f"/exams/{exam_id}", headers=admin_h,
                        json={"periods_per_day": 3})
    assert resp.status_code == 200
    periods = client.get(f"/exams/{exam_id}/periods", headers=admin_h).json()
    assert len(periods) == 6   # 2일 × 3교시

    client.post(f"/exams/{exam_id}/publish", headers=admin_h)
    resp = client.patch(f"/exams/{exam_id}", headers=admin_h,
                        json={"name": "바뀐이름"})
    assert resp.status_code == 400


def test_delete_exam(client, admin_h, db):
    """삭제 시 딸린 교시까지 cascade 삭제."""
    env = _make_env(db)
    exam_id = client.post("/exams", headers=admin_h,
                         json=_exam_payload(env["term"])).json()["id"]
    assert client.delete(f"/exams/{exam_id}", headers=admin_h).status_code == 200
    assert db.query(ExamPeriod).count() == 0
    assert client.get(f"/exams/{exam_id}", headers=admin_h).status_code == 404


# ── 시험 시간표 (과목 배치) ────────────────────────────────────────────────────

def test_generate_entries_endpoint(client, admin_h, db):
    """자동 배치 엔드포인트 → entries 조회에 과목명 주입 확인."""
    env = _make_env(db)
    # 1반에 국어·수학 배정 → 자동 배치 대상 과목 2개
    _assign_subjects(db, env)

    exam_id = client.post("/exams", headers=admin_h,
                         json=_exam_payload(env["term"])).json()["id"]
    resp = client.post(f"/exams/{exam_id}/generate-entries", headers=admin_h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    entries = client.get(f"/exams/{exam_id}/entries", headers=admin_h).json()
    assert len(entries) == 2   # 과목 2개 → 칸 2개
    names = {e["subject_name"] for e in entries}
    assert names == {"국어", "수학"}


def test_manual_entry_edit_blocked_after_publish(client, admin_h, db):
    """시험표 수동 편집은 게시 전까지만 가능."""
    env = _make_env(db)
    _assign_subjects(db, env)
    exam_id = client.post("/exams", headers=admin_h,
                          json=_exam_payload(env["term"])).json()["id"]
    client.post(f"/exams/{exam_id}/generate-entries", headers=admin_h)
    entries = client.get(f"/exams/{exam_id}/entries", headers=admin_h).json()
    entry_id = entries[0]["id"]

    other_subject = env["subjects"][1].id
    resp = client.put(f"/exams/entries/{entry_id}", headers=admin_h,
                      json={"subject_id": other_subject})
    assert resp.status_code == 200
    assert resp.json()["is_manual"] is True

    client.post(f"/exams/{exam_id}/publish", headers=admin_h)
    resp = client.put(f"/exams/entries/{entry_id}", headers=admin_h,
                      json={"subject_id": other_subject})
    assert resp.status_code == 400


# ── 감독 시간표 ───────────────────────────────────────────────────────────────

def test_assign_and_manual_update_invigilation(client, admin_h, db):
    """
    자동 배정 → 수동 변경 → 동시간 중복 409 흐름 검증.

    감독 자동 배정의 알고리즘 상세는 test_exam_scheduler.py 에서
    이미 검증했으므로, 여기서는 API 계약(응답 형태·409 충돌)만 확인.
    """
    env = _make_env(db)
    exam_id = client.post("/exams", headers=admin_h,
                          json=_exam_payload(env["term"])).json()["id"]

    resp = client.post(f"/exams/{exam_id}/assign-invigilations", headers=admin_h)
    assert resp.status_code == 200
    body = resp.json()
    # 25명 반 1개 → 2인 1조 × 2일 × 2교시 = 8슬롯
    assert body["ok"] is True

    rows = client.get(f"/exams/{exam_id}/invigilations", headers=admin_h).json()
    assert len(rows) == 8
    assert all(r["class_name"] == "1-1" for r in rows)
    assert rows[0]["period_number"] == 1

    # 수동 변경: 자동 배정은 랜덤 재시작을 쓰므로 배정 결과가 매번 다릅니다.
    # 결정적 테스트를 위해 "대상 교시에 배정되지 않은 교사"를 동적으로 선택.
    # (교사 3명 > 교시당 슬롯 2개 이므로 항상 존재)
    target = rows[0]
    busy = {r["teacher_id"] for r in rows
             if r["exam_date"] == target["exam_date"]
             and r["period_number"] == target["period_number"]}
    free_teacher = next(t.id for t in env["teachers"] if t.id not in busy)
    resp = client.put(f"/exams/invigilations/{target['id']}", headers=admin_h,
                      json={"teacher_id": free_teacher})
    assert resp.status_code == 200

    # 같은 교시의 다른 슬롯에 동일 교사 지정 → 409
    other = [r for r in rows
             if r["exam_date"] == target["exam_date"]
             and r["period_number"] == target["period_number"]
             and r["id"] != target["id"]][0]
    resp = client.put(f"/exams/invigilations/{other['id']}", headers=admin_h,
                      json={"teacher_id": free_teacher})
    assert resp.status_code == 409


def test_my_invigilations_requires_published(client, admin_h, db, teacher_h):
    """"내 감독" 조회는 게시된 시험만 반환 — route 순서("my" 파싱) 검증 포함."""
    env = _make_env(db)
    exam_id = client.post("/exams", headers=admin_h,
                          json=_exam_payload(env["term"])).json()["id"]
    # teacher 계정에 연결된 교사에게 감독 슬롯 직접 생성
    period = db.query(ExamPeriod).filter_by(exam_id=exam_id).order_by(
        ExamPeriod.period).first()
    from shared.models import User
    tu = db.query(User).filter_by(username="teacher1").first()
    db.add(InvigilationAssignment(
        exam_id=exam_id, period_id=period.id, school_class_id=env["cls"].id,
        teacher_id=tu.teacher_id, pair_index=1))
    db.commit()

    # 게시 전에는 "내 감독"이 비어 있어야 함
    resp = client.get("/exams/my/invigilations", headers=teacher_h)
    assert resp.status_code == 200
    assert resp.json() == []

    client.post(f"/exams/{exam_id}/publish", headers=admin_h)
    resp = client.get("/exams/my/invigilations", headers=teacher_h)
    assert resp.status_code == 200
    mine = resp.json()
    assert len(mine) == 1
    assert mine[0]["class_name"] == "1-1"
    assert mine[0]["period_number"] == 1


# ── 감독 불가 신청 ───────────────────────────────────────────────────────────

def test_constraint_submit_and_review_flow(client, admin_h, db, teacher_h, vp_h):
    """교사 신청 → 중복 409 → 교감 승인 → 재처리 400 흐름."""
    env = _make_env(db)
    exam_id = client.post("/exams", headers=admin_h,
                          json=_exam_payload(env["term"])).json()["id"]

    # 시험 기간 밖 날짜 → 400
    resp = client.post(f"/exams/{exam_id}/constraints", headers=teacher_h,
                       json={"exam_date": "2026-11-01", "reason": "공결"})
    assert resp.status_code == 400

    # 정상 신청
    resp = client.post(f"/exams/{exam_id}/constraints", headers=teacher_h,
                       json={"exam_date": "2026-10-05", "reason": "공결"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"

    # 같은 날짜·교시 중복 → 409
    resp = client.post(f"/exams/{exam_id}/constraints", headers=teacher_h,
                       json={"exam_date": "2026-10-05", "reason": "중복"})
    assert resp.status_code == 409

    # 교사는 본인 신청만 조회 (전체 1개 = 본인 것)
    mine = client.get(f"/exams/{exam_id}/constraints", headers=teacher_h).json()
    assert len(mine) == 1

    # 교사는 승인 권한 없음 → 403
    cid = mine[0]["id"]
    resp = client.patch(f"/exams/constraints/{cid}", headers=teacher_h,
                        json={"action": "approve"})
    assert resp.status_code == 403

    # 교감 승인
    resp = client.patch(f"/exams/constraints/{cid}", headers=vp_h,
                        json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["reviewed_by"] == "vp"

    # 이미 처리된 신청 재처리 → 400
    resp = client.patch(f"/exams/constraints/{cid}", headers=vp_h,
                        json={"action": "approve"})
    assert resp.status_code == 400


def test_admin_account_cannot_submit_constraint(client, admin_h, db):
    """teacher_id 미연결 계정(일과계)은 감독 불가 신청 자체가 403."""
    env = _make_env(db)
    exam_id = client.post("/exams", headers=admin_h,
                          json=_exam_payload(env["term"])).json()["id"]
    resp = client.post(f"/exams/{exam_id}/constraints", headers=admin_h,
                       json={"exam_date": "2026-10-05", "reason": "테스트"})
    assert resp.status_code == 403