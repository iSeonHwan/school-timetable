"""
시험 관리 UI 테스트 (관리자 앱, pytest-qt offscreen).

검증 대상 (5단계 산출물):
  - ExamSetupWidget: 시험 목록 로딩·생성 폼 동작
  - ExamGridWidget: 시험표 렌더링·자동 배치 버튼 동작
  - InvigilationGridWidget: 감독표 렌더링·자동 배정·횟수 요약·읽기 전용 모드
  - AdminMainWindow: 시험 3페이지 스택 등록·교감 읽기 전용 페이지

화면 레이아웃·다이얼로그 상호작용의 전수 검증은 아니며, 데이터 흐름
(위젯 → DB → 위젯)이 offscreen 환경에서 올바르게 동작하는지를 검증합니다.
"""
from datetime import date, time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QComboBox

from database.models import (
    AcademicTerm, Grade, SchoolClass, Subject, Teacher,
    SubjectClassAssignment, Exam, ExamPeriod, ExamEntry,
    InvigilationAssignment,
)
from admin_app.ui.exam.exam_setup_page import ExamSetupWidget
from admin_app.ui.exam.exam_grid_page import ExamGridWidget
from admin_app.ui.exam.invigilation_grid_page import InvigilationGridWidget


@pytest.fixture
def qapp():
    """pytest-qt 가 QApplication 을 띄우지 않는 환경을 위한 안전장치."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def exam_env(db):
    """UI 테스트용 데이터셋: 1학년 1반(25명)·과목 2개·교사 2명·초안 시험."""
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
    t1 = Teacher(name="김교사")
    t2 = Teacher(name="박교사")
    db.add_all([t1, t2])
    db.flush()
    for s in (s1, s2):
        db.add(SubjectClassAssignment(
            school_class_id=cls.id, subject_id=s.id,
            teacher_id=t1.id, weekly_hours=2, term_id=term.id))
    db.commit()

    exam = Exam(
        term_id=term.id, name="중간고사", exam_type="midterm",
        school_level="high", target_grade_ids="[]",
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
        first_period_start=time(8, 30), periods_per_day=2,
        break_minutes=10, prep_minutes=5, exam_minutes=50,
        max_subjects_per_day=3, status="draft",
    )
    db.add(exam)
    db.flush()
    periods = []
    for p in (1, 2):
        ep = ExamPeriod(exam_id=exam.id, exam_date=date(2026, 10, 5), period=p,
                        start_time=time(8, 30) if p == 1 else time(9, 30),
                        end_time=time(9, 20) if p == 1 else time(10, 20))
        db.add(ep)
        periods.append(ep)
    db.commit()
    return {"term": term, "grade": grade, "cls": cls,
            "subjects": [s1, s2], "teachers": [t1, t2],
            "exam": exam, "periods": periods}


# ── 시험 관리 페이지 ──────────────────────────────────────────────────────────

def test_exam_setup_lists_and_creates(qtbot, exam_env, db):
    """기존 시험 로딩 + 생성 폼으로 새 시험 추가."""
    widget = ExamSetupWidget(api_client=None)
    qtbot.addWidget(widget)

    # 기존 시험이 목록에 보이는지
    assert widget.tbl_exams.rowCount() == 1
    assert widget.tbl_exams.item(0, 1).text() == "중간고사"

    # 생성 폼 채우기 → 추가
    widget.edit_name.setText("기말고사")
    # 버그 수정(테스트): 시작일이 위젯 기본값(오늘 날짜)에 그대로 의존하면,
    # core.exam_scheduler.rebuild_exam_periods() 가 주말에는 교시를 생성하지
    # 않도록 수정된 이후로 테스트 실행일이 토·일요일이면 이 테스트가 깨집니다
    # (실행 환경의 "오늘"과 무관하게 항상 같은 결과가 나와야 하는 테스트이므로,
    # 확실한 평일 날짜를 명시적으로 지정합니다 — exam_env 픽스처와 동일한
    # 2026-10-05(월요일) 사용).
    from PyQt6.QtCore import QDate
    widget.date_start.setDate(QDate(2026, 10, 5))
    # 폼 기본 종료일은 시작일+1일(2일×3교시=6교시)이므로
    # "1일 × 3교시" 검증을 위해 종료일을 시작일과 같은 날로 맞춥니다.
    widget.date_end.setDate(widget.date_start.date())
    # _add_exam 은 완료 안내 QMessageBox 를 띄우므로 자동 닫기 처리
    monkeypatch_msgbox(qtbot)
    widget._add_exam()

    session_rows = db.query(Exam).filter_by(name="기말고사").all()
    assert len(session_rows) == 1
    # 1일 × 기본 3교시 = 3개 교시 자동 생성 확인
    assert db.query(ExamPeriod).filter_by(exam_id=session_rows[0].id).count() == 3
    # 목록 갱신 확인
    assert widget.tbl_exams.rowCount() == 2


def test_exam_setup_publish_via_db_fallback(qtbot, exam_env, db):
    """ApiClient 없이 게시하면 DB 상태가 published 로 변경됩니다."""
    widget = ExamSetupWidget(api_client=None)
    qtbot.addWidget(widget)

    # 게시 확인 다이얼로그를 자동 승인 처리
    widget.tbl_exams.selectRow(0)
    monkeypatch_msgbox(qtbot)
    widget._publish_exam()

    db.refresh(exam_env["exam"])
    assert exam_env["exam"].status == "published"


def monkeypatch_msgbox(qtbot):
    """QMessageBox.question/information/warning 을 자동 Yes/닫기로 대체."""
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)


# ── 시험 시간표 페이지 ────────────────────────────────────────────────────────

def test_exam_grid_auto_generate(qtbot, exam_env, db):
    """시험 선택 → 자동 배치 실행 → 그리드에 과목이 표시됩니다."""
    widget = ExamGridWidget()
    qtbot.addWidget(widget)

    assert widget.cmb_exam.count() == 1
    assert widget.tbl.columnCount() == 2   # 교시 열 + 1학년 열

    monkeypatch_msgbox(qtbot)
    widget._auto_generate()

    entries = db.query(ExamEntry).filter_by(exam_id=exam_env["exam"].id).all()
    assert len(entries) == 2   # 국어·수학 2칸

    # 그리드 셀에 과목명이 렌더링되었는지
    texts = [widget.tbl.item(r, c).text()
             for r in range(widget.tbl.rowCount())
             for c in range(1, widget.tbl.columnCount())
             if widget.tbl.item(r, c) is not None]
    assert "국어" in texts and "수학" in texts


def test_exam_grid_read_only(qtbot, exam_env, db):
    """읽기 전용 모드에서는 자동 배치 버튼이 비활성화됩니다."""
    widget = ExamGridWidget(read_only=True)
    qtbot.addWidget(widget)
    assert not widget.btn_auto.isEnabled()


# ── 감독 시간표 페이지 ────────────────────────────────────────────────────────

def test_invigilation_grid_assign_and_summary(qtbot, exam_env, db):
    """자동 배정 실행 → 테이블 렌더링 + 교사별 횟수 요약 표시."""
    widget = InvigilationGridWidget()
    qtbot.addWidget(widget)

    monkeypatch_msgbox(qtbot)
    widget._auto_assign()

    # 25명 반 → 2인 1조 × 2교시 = 4슬롯
    slots = db.query(InvigilationAssignment).filter_by(
        exam_id=exam_env["exam"].id).all()
    assert len(slots) == 4

    # 그리드: 2교시 × 1반 = 2행, 6열
    assert widget.tbl.rowCount() == 2
    assert widget.tbl.columnCount() == 6

    # 요약 라벨에 교사별 횟수가 표기되는지
    summary = widget.lbl_summary.text()
    assert "김교사" in summary and "박교사" in summary


def test_invigilation_grid_read_only(qtbot, exam_env, db):
    """읽기 전용 모드에서는 배정·내보내기 버튼이 모두 비활성화됩니다."""
    widget = InvigilationGridWidget(read_only=True)
    qtbot.addWidget(widget)
    assert not widget.btn_assign.isEnabled()
    assert not widget.btn_pdf.isEnabled()
    assert not widget.btn_csv.isEnabled()


# ── 메인 윈도우 스택 구성 ─────────────────────────────────────────────────────

def test_admin_main_window_pages(qtbot, db):
    """시험 3페이지가 스택 인덱스 9·10·11 에 등록되어 있습니다."""
    from admin_app.ui.admin_main_window import AdminMainWindow
    from shared.api_client import ApiClient

    client = ApiClient("http://localhost:1")   # 실제 접속 없는 더미 URL
    # role 은 읽기 전용 @property 이므로 내부 속성을 직접 설정합니다.
    client._role = "admin"
    win = AdminMainWindow(client)
    qtbot.addWidget(win)
    try:
        assert win.stack.count() == 12
        assert win.stack.indexOf(win.page_exam_setup) == 9
        assert win.stack.indexOf(win.page_exam_grid) == 10
        assert win.stack.indexOf(win.page_invigilation) == 11
    finally:
        # ChatPanel 이 생성 즉시 WebSocket 재접속 스레드를 띄우므로
        # 테스트 종료 전 반드시 정리합니다 (안 하면 프로세스가 종료되지 않음).
        win._chat.disconnect_ws()


def test_admin_main_window_vp_read_only(qtbot, db):
    """교감으로 로그인하면 감독 시간표 페이지가 읽기 전용으로 생성됩니다."""
    from admin_app.ui.admin_main_window import AdminMainWindow
    from shared.api_client import ApiClient

    client = ApiClient("http://localhost:1")
    client._role = "vice_principal"
    win = AdminMainWindow(client)
    qtbot.addWidget(win)
    try:
        assert not win.page_invigilation.btn_assign.isEnabled()
        # 교감 사이드바에는 감독 시간표(열람) 항목이 존재
        labels = [b.text() for b in win._nav_buttons]
        assert "감독 시간표(열람)" in labels
    finally:
        win._chat.disconnect_ws()


# ── 교사 앱 "내 감독" 페이지 ────────────────────────────────────────────────

def _fake_exam_api(exams, my_inv, all_inv, constraints, posts):
    """
    교사 앱 테스트용 ApiClient 대역.

    서버 없이 위젯의 데이터 흐름을 검증하기 위해 get/post 를 즉시
    반환하는 함수로 교체합니다. 실제 QThread 워커는 그대로 동작하므로
    시그널 연결까지 원본 경로로 검증됩니다.
    """
    from shared.api_client import ApiClient

    client = ApiClient("http://localhost:1")
    client._role = "teacher"
    client._teacher_id = 1

    def fake_get(path, **params):
        if path == "/exams":
            return exams if not params.get("include_draft") else exams + _fake_exam_api.drafts
        if path == "/exams/my/invigilations":
            return my_inv
        if path.startswith("/exams/") and path.endswith("/invigilations"):
            return all_inv
        if path.startswith("/exams/") and path.endswith("/constraints"):
            return constraints
        if path == "/notifications/unread-count":
            return {"unread_count": 0}
        if path == "/notifications":
            return []
        return []

    def fake_post(path, body):
        posts.append((path, body))
        return {"id": 1}

    client.get = fake_get
    client.post = fake_post
    return client


_fake_exam_api.drafts = []


def test_teacher_invigilation_page(qtbot, db):
    """내 감독 조회 렌더링 + 스왑/불가 신청 제출 본문 검증."""
    import teacher_app.ui.my_invigilation_page as mip
    from shared.api_client import ApiClient

    exams = [{"id": 1, "name": "중간고사", "status": "published",
              "periods_per_day": 2}]
    draft = [{"id": 2, "name": "기말고사", "status": "draft",
              "periods_per_day": 2}]
    _fake_exam_api.drafts = draft
    my_inv = [{
        "id": 11, "exam_id": 1, "period_id": 1, "school_class_id": 1,
        "teacher_id": 1, "pair_index": 1,
        "exam_date": "2026-10-05", "period_number": 1,
        "start_time": "08:30:00", "end_time": "09:20:00",
        "class_name": "1-1", "teacher_name": "김교사", "subject_name": "국어",
    }]
    all_inv = my_inv + [{
        "id": 12, "exam_id": 1, "period_id": 2, "school_class_id": 1,
        "teacher_id": 2, "pair_index": 1,
        "exam_date": "2026-10-05", "period_number": 2,
        "start_time": "09:30:00", "end_time": "10:20:00",
        "class_name": "1-1", "teacher_name": "박교사", "subject_name": "수학",
    }]
    constraints = [{"id": 5, "exam_id": 1, "teacher_id": 1,
                    "exam_date": "2026-10-05", "period": None,
                    "reason": "출장", "status": "approved"}]
    posts: list = []

    client = _fake_exam_api(exams, my_inv, all_inv, constraints, posts)
    widget = mip.MyInvigilationWidget(client)
    qtbot.addWidget(widget)
    monkeypatch_msgbox(qtbot)
    widget.refresh()

    # 워커 스레드 완료 대기 — 콤보박스가 채워지면 populate 완료
    qtbot.waitUntil(lambda: widget.cmb_exam.count() == 1, timeout=3000)
    qtbot.waitUntil(lambda: widget.tbl_my.rowCount() == 1, timeout=3000)

    # 스왑 콤보: 내 슬롯 1개, 상대 후보에서 내 슬롯은 제외 → 1개
    assert widget.cmb_swap_mine.count() == 1
    assert widget.cmb_swap_partner.count() == 1
    # 감독 불가 목록: 초안(draft) 시험도 포함되어야 함 (게시 전 신청 워크플로)
    qtbot.waitUntil(
        lambda: widget.cmb_constraint_exam.count() == 2, timeout=3000)
    assert "기말고사" in widget.cmb_constraint_exam.itemText(1)
    # 내 불가 신청 내역 렌더링 — period=None → "전 교시"
    qtbot.waitUntil(lambda: widget.tbl_constraints.rowCount() == 1,
                    timeout=3000)
    assert widget.tbl_constraints.item(0, 1).text() == "전 교시"

    # ── 스왑 신청 제출 ──
    widget.edit_swap_reason.setText("개인 일정")
    widget._submit_swap()
    qtbot.waitUntil(lambda: len(posts) == 1, timeout=3000)
    path, body = posts[0]
    assert path == "/timetable/requests"
    assert body["request_type"] == "invigilation"
    assert body["invigilation_assignment_id"] == 11
    assert body["swap_partner_invigilation_id"] == 12
    assert body["reason"] == "개인 일정"

    # ── 불가 신청 제출 (초안 시험 선택) ──
    from PyQt6.QtCore import QDate
    widget.cmb_constraint_exam.setCurrentIndex(1)   # 기말고사(draft)
    widget.date_constraint.setDate(QDate(2026, 10, 5))
    widget.chk_all_periods.setChecked(False)
    widget.spin_c_period.setValue(2)
    widget.edit_c_reason.setText("연수")
    widget._submit_constraint()
    qtbot.waitUntil(lambda: len(posts) == 2, timeout=3000)
    path, body = posts[1]
    assert path == "/exams/2/constraints"
    assert body["exam_date"] == "2026-10-05"
    assert body["period"] == 2
    assert body["reason"] == "연수"


def test_teacher_main_window_invigilation_page(qtbot, db):
    """교사 메인 창에 '내 감독' 페이지(인덱스 3)가 등록되어 있습니다."""
    from teacher_app.ui.teacher_main_window import TeacherMainWindow

    posts: list = []
    client = _fake_exam_api([], [], [], [], posts)
    win = TeacherMainWindow(client)
    qtbot.addWidget(win)
    try:
        assert win.stack.count() == 4
        assert win.stack.indexOf(win.page_invigilation) == 3
        labels = [b.text() for b in win._nav_buttons]
        assert "내 감독" in labels
    finally:
        win._chat.disconnect_ws()


# ── 알림 패널: 시험 감독 알림 유형 ─────────────────────────────────────────

def test_notification_panel_exam_types(qtbot, db):
    """새 알림 유형 라벨/색상 + 감독 스왑 요청에 동의 버튼이 표시됩니다."""
    import teacher_app.ui.notification_panel as np
    from shared.api_client import ApiClient

    # 라벨 매핑 — 새 유형이 원문이 아닌 한글로 표기되는지
    assert np.NotificationPanel._type_label(
        "invigilation_swap_request") == "감독 교체 동의 요청"
    assert np.NotificationPanel._type_label("exam_published") == "시험 게시"
    assert np.NotificationPanel._type_label(
        "invigilation_assigned") == "감독 배정"

    client = ApiClient("http://localhost:1")
    client._role = "teacher"
    client._teacher_id = 1
    client.get = lambda path, **params: []
    panel = np.NotificationPanel(client)
    qtbot.addWidget(panel)

    notif = {
        "id": 77, "type": "invigilation_swap_request",
        "message": "10/05 1교시 1-1(1조) ↔ 10/05 2교시 1-1(1조)",
        "is_read": False, "created_at": "2026-10-01T09:00:00",
        "change_request_id": 9,
    }
    row_widget = panel._build_item_widget(notif)
    # 동의/거절 버튼이 행에 포함되는지 (consent_request 와 동일한 처리)
    assert 77 in panel._consent_buttons
    approve, reject = panel._consent_buttons[77]
    assert approve.text() == "동의" and reject.text() == "거절"
    del row_widget


# ── 관리자 앱 신청 목록: 감독 스왑 표시·적용 ────────────────────────────────

def test_admin_request_list_invigilation(qtbot, exam_env, db):
    """감독 스왑 신청이 '감독 교체'로 표시되고 최종 승인 시 교사가 맞바뀝니다."""
    import json
    from database.models import TimetableChangeRequest
    from database.connection import get_session
    from ui.timetable.request_list import ChangeRequestWidget

    t1, t2 = exam_env["teachers"]
    cls = exam_env["cls"]
    p1, p2 = exam_env["periods"]
    # 스왑 신청은 게시된 시험에서만 가능하므로 상태를 게시로 변경
    exam_env["exam"].status = "published"
    db.commit()

    a1 = InvigilationAssignment(exam_id=exam_env["exam"].id, period_id=p1.id,
                                school_class_id=cls.id, teacher_id=t1.id,
                                pair_index=1)
    a2 = InvigilationAssignment(exam_id=exam_env["exam"].id, period_id=p2.id,
                                school_class_id=cls.id, teacher_id=t2.id,
                                pair_index=1)
    db.add_all([a1, a2])
    db.commit()

    # 감독 스왑 신청 — 상대 동의 완료 상태(관리자 최종 승인 대기)로 생성
    snap = json.dumps({
        "my_assignment": {"teacher_id": t1.id, "period_id": p1.id,
                         "school_class_id": cls.id},
        "partner_assignment": {"teacher_id": t2.id, "period_id": p2.id,
                               "school_class_id": cls.id},
    })
    req = TimetableChangeRequest(
        request_type="invigilation", timetable_entry_id=None,
        invigilation_assignment_id=a1.id,
        swap_partner_invigilation_id=a2.id,
        reason="개인 일정", requested_by="t1", status="pending",
        current_step=2, affected_teacher_id=t2.id,
        consent_status="approved", change_snapshot=snap,
    )
    db.add(req)
    db.commit()

    widget = ChangeRequestWidget(role="admin")
    qtbot.addWidget(widget)
    monkeypatch_msgbox(qtbot)
    widget.refresh()

    # 신청 목록에 '감독 교체' 유형으로 표시되는지
    assert widget.table.rowCount() == 1
    assert widget.table.item(0, 1).text() == "감독 교체"
    # 변경 내용 칸에 상대 감독 라벨이 표시되는지
    assert "박교사" in widget.table.item(0, 6).text()

    # 최종 승인 적용 — 두 배정의 교사가 상호 교환됨
    s2 = get_session()
    try:
        req_db = s2.get(TimetableChangeRequest, req.id)
        msg = widget._apply_invigilation_swap(s2, req_db)
        s2.commit()
        assert "감독 교체가 확정" in msg
        db.refresh(a1); db.refresh(a2)
        assert a1.teacher_id == t2.id
        assert a2.teacher_id == t1.id
    finally:
        s2.close()

    # 스냅샷 충돌 — 결재 중 배정이 변경되면 적용이 거부되어야 함
    a1.teacher_id = t1.id   # 신청 시점과 불일치 유도
    db.commit()
    s3 = get_session()
    try:
        req3 = s3.get(TimetableChangeRequest, req.id)
        try:
            widget._apply_invigilation_swap(s3, req3)
            raised = False
        except ValueError:
            raised = True
        assert raised, "스냅샷 불일치 시 ValueError 가 발생해야 합니다"
    finally:
        s3.close()