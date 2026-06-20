"""
FastAPI 서버 진입점

실행 방법:
  uvicorn server.main:app --host 0.0.0.0 --port 8000

환경 변수:
  DB_URL             : SQLAlchemy DB URL (미설정 시 config.py 의 get_db_url() 사용)
  JWT_SECRET_KEY     : JWT 서명 키 (운영 환경에서 반드시 설정, 미설정 시 임시 키 생성)
  JWT_EXPIRE_HOURS   : 토큰 유효 시간 (기본 24)
  ADMIN_USERNAME     : 최초 일과계 아이디 (기본 "admin")
  ADMIN_PASSWORD     : 최초 일과계 비밀번호 (미설정 시 랜덤 생성, 콘솔에 출력)
  VP_USERNAME        : 최초 교감 아이디 (기본 "vice_principal")
  VP_PASSWORD        : 최초 교감 비밀번호 (미설정 시 랜덤 생성, 콘솔에 출력)
  CHAT_RETENTION_DAYS: 채팅 메시지 보관 기간(일) (기본 60, 0=무기한)
"""
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.connection import init_db, get_session
from shared.models import User
from server.auth_utils import hash_password
from server.api.auth import router as auth_router
from server.api.setup import router as setup_router
from server.api.timetable import router as timetable_router
from server.api.chat import router as chat_router, start_cleanup_task
from server.api.workflow import router as workflow_router
from server.api.notifications import router as notifications_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    서버 시작 시 DB 초기화, 최초 관리자 계정 생성, 채팅 정리 태스크 시작.
    서버 종료 시 채팅 정리 태스크를 안전하게 종료합니다.
    """
    db_url = os.getenv("DB_URL")
    init_db(db_url)
    _migrate_columns()               # 기존 DB에 누락된 컬럼 일괄 추가 (가장 먼저 실행)
    _ensure_alembic_state()          # Alembic 버전 테이블 동기화 (stamp 또는 upgrade)
    _ensure_admin()
    _ensure_assignment_terms()       # 기존 시수 배정 term_id 백필
    _ensure_default_workflow()

    # 채팅 메시지 자동 정리 백그라운드 태스크 시작
    _cleanup_task = start_cleanup_task()

    yield

    # 종료 시 정리: 백그라운드 태스크 취소
    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except Exception:
        pass  # CancelledError 는 무시


def _ensure_admin():
    """
    최초 실행 시 관리자 계정이 없으면 자동으로 생성합니다.

    세 종류의 관리자 계정을 생성합니다 (각 role 별 1개씩, 기존 계정이 없을 때만):
      - 일과계 선생님 (admin): 전체 관리 권한 — 편제·계정·시간표 생성·결재 라인 설정
        환경 변수 ADMIN_USERNAME / ADMIN_PASSWORD 로 제어.
      - 교감 선생님 (vice_principal): 시간표 열람 + 변경 신청 승인
        환경 변수 VP_USERNAME / VP_PASSWORD 로 제어.
      - 교무부장 (department_head): 시간표 열람 + 변경 신청 승인 (중간 결재자)
        환경 변수 DH_USERNAME / DH_PASSWORD 로 제어.

    비밀번호 미설정 시 secrets.token_urlsafe(12)로 랜덤 생성 후
    콘솔에 1회 출력합니다. 생성된 비밀번호는 서버 로그에만 남으므로
    반드시 기록해 두세요.

    이미 해당 role 의 계정이 존재하면 아무 작업도 하지 않습니다 (멱등성 보장).
    """
    db = get_session()
    try:
        # ── 일과계 선생님 계정 (admin) ──────────────────────────────────────
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        if not db.query(User).filter_by(role="admin").first():
            admin = User(
                username=admin_username,
                password_hash=hash_password(admin_password),
                role="admin",
            )
            db.add(admin)
            db.commit()
            if not os.getenv("ADMIN_PASSWORD"):
                # 랜덤 생성된 초기 비밀번호를 출력합니다.
                # ★ 보안 주의: 이 비밀번호는 서버 로그에 남습니다.
                # CI/CD 파이프라인이나 로그 집계 시스템을 사용한다면
                # 로그가 외부에 노출되지 않도록 주의하세요.
                # 운영 환경에서는 ADMIN_PASSWORD 환경 변수로 직접 지정하는 것을 권장합니다.
                print("\n" + "=" * 60)
                print(f"[서버] 최초 일과계 선생님 계정이 생성되었습니다.")
                print(f"  아이디   : {admin_username}")
                print(f"  초기비밀번호: {admin_password}")
                print(f"  ★ 이 비밀번호는 이번 한 번만 표시됩니다!")
                print(f"  ★ 지금 바로 안전한 곳에 기록하고, 로그인 후 즉시 변경하세요.")
                print("=" * 60 + "\n")
            else:
                print(f"[서버] 최초 일과계 선생님 계정 생성: {admin_username} (로그인 후 비밀번호를 변경하세요!)")

        # ── 교감 선생님 계정 (vice_principal) ───────────────────────────────
        vp_username = os.getenv("VP_USERNAME", "vice_principal")
        vp_password = os.getenv("VP_PASSWORD") or secrets.token_urlsafe(12)
        if not db.query(User).filter_by(role="vice_principal").first():
            vp = User(
                username=vp_username,
                password_hash=hash_password(vp_password),
                role="vice_principal",
            )
            db.add(vp)
            db.commit()
            if not os.getenv("VP_PASSWORD"):
                print("\n" + "=" * 60)
                print(f"[서버] 최초 교감 선생님 계정이 생성되었습니다.")
                print(f"  아이디   : {vp_username}")
                print(f"  초기비밀번호: {vp_password}")
                print(f"  ★ 이 비밀번호는 이번 한 번만 표시됩니다!")
                print(f"  ★ 지금 바로 안전한 곳에 기록하고, 로그인 후 즉시 변경하세요.")
                print("=" * 60 + "\n")
            else:
                print(f"[서버] 최초 교감 선생님 계정 생성: {vp_username} (로그인 후 비밀번호를 변경하세요!)")

        # ── 교무부장 계정 (department_head) ──────────────────────────────
        dh_username = os.getenv("DH_USERNAME", "department_head")
        dh_password = os.getenv("DH_PASSWORD") or secrets.token_urlsafe(12)
        if not db.query(User).filter_by(role="department_head").first():
            dh = User(
                username=dh_username,
                password_hash=hash_password(dh_password),
                role="department_head",
            )
            db.add(dh)
            db.commit()
            if not os.getenv("DH_PASSWORD"):
                print("\n" + "=" * 60)
                print(f"[서버] 최초 교무부장 계정이 생성되었습니다.")
                print(f"  아이디   : {dh_username}")
                print(f"  초기비밀번호: {dh_password}")
                print(f"  ★ 이 비밀번호는 이번 한 번만 표시됩니다!")
                print(f"  ★ 지금 바로 안전한 곳에 기록하고, 로그인 후 즉시 변경하세요.")
                print("=" * 60 + "\n")
            else:
                print(f"[서버] 최초 교무부장 계정 생성: {dh_username} (로그인 후 비밀번호를 변경하세요!)")
    finally:
        db.close()


def _ensure_assignment_terms():
    """
    기존 subject_class_assignments 데이터에 term_id 를 백필합니다.

    2026-06-13 변경:
      - SubjectClassAssignment 에 term_id 컬럼이 추가되면서, 기존 데이터의
        term_id 가 비어 있을 경우 자동으로 현재 학기로 채웁니다.
      - 현재 학기가 없으면 DB 의 첫 번째 학기를 사용합니다.
      - 이미 term_id 가 설정된 행은 건드리지 않으므로 멱등성이 보장됩니다.
    """
    from sqlalchemy import text
    from shared.models import AcademicTerm, SubjectClassAssignment

    db = get_session()
    try:
        # term_id 가 비어있는 행이 있는지 먼저 확인
        empty_count = db.query(SubjectClassAssignment).filter(
            (SubjectClassAssignment.term_id.is_(None)) | (SubjectClassAssignment.term_id == 0)
        ).count()
        if empty_count == 0:
            return

        # 백필용 학기 결정: 현재 학기 → 첫 번째 학기
        target_term = db.query(AcademicTerm).filter_by(is_current=True).first()
        if target_term is None:
            target_term = db.query(AcademicTerm).order_by(AcademicTerm.year, AcademicTerm.semester).first()
        if target_term is None:
            print("[마이그레이션] 학기가 하나도 없어 subject_class_assignments.term_id 를 백필할 수 없습니다.")
            return

        db.execute(text(
            "UPDATE subject_class_assignments SET term_id=:term_id "
            "WHERE term_id IS NULL OR term_id=0"
        ), {"term_id": target_term.id})
        db.commit()
        print(f"[마이그레이션] {empty_count}개의 시수 배정에 term_id={target_term.id}({target_term})를 백필했습니다.")
    finally:
        db.close()


def _migrate_columns():
    """
    서버 업데이트 시 기존 DB 에 누락된 컬럼을 일괄 추가합니다.

    SQLAlchemy 의 create_all() 은 새 테이블은 생성하지만, 기존 테이블에
    새로 추가된 컬럼은 자동으로 반영하지 않습니다. 이 함수가 그 역할을 합니다.

    멱등성 보장:
      각 ALTER TABLE 은 개별 try/except 로 감싸져 있습니다.
      컬럼이 이미 존재하면 DB 가 오류를 반환하고 무시합니다.
      반복 실행해도 안전합니다.

    실행 순서:
      init_db() 직후, 다른 ensure/migrate 함수보다 반드시 먼저 실행해야 합니다.
      (다른 함수들이 이 컬럼들을 읽거나 쓰기 때문)

    SQLite 와 PostgreSQL 모두 동작합니다.
    """
    from sqlalchemy import text

    # 추가할 컬럼 목록: (SQL 문, 설명)
    # 새로운 컬럼이 추가될 때마다 이 목록에 append 하세요.
    migrations = [
        # ── subject_class_assignments ─────────────────────────────────────────
        # 2026-06-13: 학기별 시수 배정 분리를 위해 term_id 추가
        (
            "ALTER TABLE subject_class_assignments ADD COLUMN term_id INTEGER REFERENCES academic_terms(id)",
            "subject_class_assignments.term_id",
        ),
        # ── timetable_change_requests — 동적 결재 워크플로우 필드 ──────────────
        # 하드코딩된 2단계 결재에서 동적 워크플로우로 전환할 때 추가된 컬럼들
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN current_step INTEGER NOT NULL DEFAULT 0",
            "timetable_change_requests.current_step",
        ),
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN approval_history TEXT DEFAULT '[]'",
            "timetable_change_requests.approval_history",
        ),
        # ── timetable_change_requests — 피교사 동의(consent) 필드 ─────────────
        # 2026-06-13: 교사 간 수업 교체 시 피교사 사전 동의 기능 추가
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN affected_teacher_id INTEGER REFERENCES teachers(id)",
            "timetable_change_requests.affected_teacher_id",
        ),
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN consent_status VARCHAR(20) NOT NULL DEFAULT 'not_required'",
            "timetable_change_requests.consent_status",
        ),
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN consent_by_user_id INTEGER REFERENCES users(id)",
            "timetable_change_requests.consent_by_user_id",
        ),
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN consent_at DATETIME",
            "timetable_change_requests.consent_at",
        ),
        # ── timetable_change_requests — 교환(swap) 필드 ───────────────────────
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN swap_partner_entry_id INTEGER REFERENCES timetable_entries(id)",
            "timetable_change_requests.swap_partner_entry_id",
        ),
        # ── timetable_change_requests — 스냅샷(race condition 감지) ───────────
        # 2026-06-13: swap 신청 시점 슬롯 상태 저장 → 최종 승인 시 충돌 감지
        (
            "ALTER TABLE timetable_change_requests ADD COLUMN change_snapshot TEXT",
            "timetable_change_requests.change_snapshot",
        ),
        # ── timetable_entries — 낙관적 잠금 version 컬럼 ─────────────────────
        # 2026-06-20: 동시 편집 충돌 방지용 version 컬럼 추가.
        # 기존 행은 자동으로 default=1 로 채워집니다.
        (
            "ALTER TABLE timetable_entries ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            "timetable_entries.version",
        ),
    ]

    db = get_session()
    added = []
    try:
        for sql, label in migrations:
            try:
                db.execute(text(sql))
                db.commit()
                added.append(label)
            except Exception:
                # 컬럼이 이미 존재하거나 다른 오류 — 무시하고 계속 진행
                db.rollback()
    finally:
        db.close()

    if added:
        print(f"[마이그레이션] {len(added)}개 컬럼 추가: {', '.join(added)}")


def _ensure_alembic_state():
    """
    Alembic 마이그레이션 상태를 DB 에 동기화합니다 (2026-06-20 신규).

    동작:
      1. alembic_version 테이블이 없으면 — 아직 Alembic 관리를 시작하지 않은 DB.
         create_all() + _migrate_columns() 가 이미 스키마를 최신 상태로 맞췄으므로
         `alembic stamp head` 로 현재를 baseline 으로 마킹합니다.
         (마이그레이션 파일을 재실행하지 않음 — 안전)
      2. alembic_version 테이블이 있으면 — 이미 Alembic 관리 중인 DB.
         `alembic upgrade head` 로 미적용 revision 이 있으면 적용.

    이중 보호 설계:
      - _migrate_columns() 는 레거시 DB 의 누락 컬럼을 보충 (하위 호환).
      - Alembic 은 그 이후의 스키마 변경을 버전 관리.
      - 신규 DB: create_all() 이 테이블 생성 → stamp head 로 초기화.
      - 레거시 DB: _migrate_columns() 가 컬럼 보충 → stamp head 로 전환.
      - 이미 Alembic 관리 중인 DB: upgrade head 로 최신 revision 적용.

    실패 시 영향 최소화:
      - Alembic 설정/마이그레이션 오류가 서버 부팅을 막지 않도록 예외를 잡아
        경고 로그만 남기고 계속 진행합니다.
        (운영 DB 는 여전히 create_all + _migrate_columns 로 정상 동작)
    """
    from sqlalchemy import inspect, text
    from alembic.config import Config
    from alembic import command

    try:
        # alembic_version 테이블 존재 여부로 상태 판단
        engine = _get_engine()
        insp = inspect(engine)
        alembic_initialized = "alembic_version" in insp.get_table_names()

        # alembic Config 구성 — alembic.ini 경로는 프로젝트 루트 기준
        project_root = os.path.dirname(os.path.dirname(__file__))
        alembic_cfg_path = os.path.join(project_root, "alembic.ini")
        if not os.path.exists(alembic_cfg_path):
            # alembic.ini 가 없는 환경 (예: 일부 테스트) — 조용히 스킵
            return

        cfg = Config(alembic_cfg_path)
        # DB URL 을 env.py 가 환경 변수에서 읽도록 그대로 둠

        if not alembic_initialized:
            # 신규/레거시 DB — 현재를 baseline 으로 마킹
            command.stamp(cfg, "head")
            print("[마이그레이션] Alembic baseline 으로 마킹했습니다 (stamp head).")
        else:
            # 이미 Alembic 관리 중 — 미적용 revision 이 있으면 적용
            command.upgrade(cfg, "head")
    except Exception as exc:
        # Alembic 실패가 서버 부팅을 막지 않도록 경고만 남기고 진행.
        # 운영 DB 는 create_all + _migrate_columns 로 정상 동작하므로 안전.
        print(f"[마이그레이션] Alembic 상태 동기화 중 오류 (계속 진행): {exc}")


def _get_engine():
    """database.connection 모듈의 싱글턴 엔진을 반환 (init_db 이후 유효)."""
    from database.connection import _engine
    if _engine is None:
        raise RuntimeError("DB 엔진이 초기화되지 않았습니다. init_db() 먼저 호출.")
    return _engine


def _ensure_default_workflow():
    """
    최초 실행 시 기본 2단계 결재 워크플로우를 생성하고 기존 데이터를 마이그레이션합니다.

    이 함수는 서버 시작 시마다 호출되지만, 이미 워크플로우가 존재하면
    아무 작업도 수행하지 않습니다 (멱등성 보장).

    1. 기본 워크플로우 생성 (approval_workflows 테이블이 비어있을 때만):
       - "기본 2단계 결재": 일과계 1차 승인 → 교감 최종 승인
       - is_active=True 로 생성되어 즉시 사용 가능

    2. 기존 timetable_change_requests 데이터 백필 (마이그레이션):
       기존의 하드코딩된 2단계 결재(status 기반)에서
       동적 워크플로우(current_step 기반)로 전환 시 기존 데이터를 보정합니다.

       이전 상태              → 새 필드 값
       ──────────────────────────────────────────────
       pending                 → current_step=1, approval_history=[]
       scheduler_approved      → current_step=2 (1단계 승인 완료, 2단계 대기)
       approved                → current_step=3 (모든 단계 완료, total_steps+1)
       rejected                → 변경 없음 (current_step 은 유지)

       IDEMPOTENT: (current_step IS NULL OR current_step=0) 조건으로
       이미 마이그레이션된 행을 건너뛰므로 반복 실행해도 안전합니다.
    """
    from shared.models import ApprovalWorkflow, ApprovalStep
    from sqlalchemy import text

    db = get_session()
    try:
        # 1. 기본 워크플로우 생성
        if db.query(ApprovalWorkflow).count() == 0:
            wf = ApprovalWorkflow(
                name="기본 2단계 결재",
                description="일과계 1차 승인 → 교감 최종 승인",
                is_active=True,
            )
            db.add(wf)
            db.flush()
            db.add(ApprovalStep(
                workflow_id=wf.id, step_order=1,
                role_required="admin", step_name="1차 승인 (일과계)",
            ))
            db.add(ApprovalStep(
                workflow_id=wf.id, step_order=2,
                role_required="vice_principal", step_name="최종 승인 (교감)",
            ))
            db.commit()
            print("[서버] 기본 2단계 결재 워크플로우가 생성되었습니다.")

        # 2. 기존 change request 데이터 마이그레이션
        # pending → current_step=1, approval_history=[]
        db.execute(text(
            "UPDATE timetable_change_requests SET current_step=1, approval_history='[]' "
            "WHERE status='pending' AND (current_step IS NULL OR current_step=0)"
        ))
        # scheduler_approved → current_step=2 (1단계 통과, 2단계 대기)
        db.execute(text(
            "UPDATE timetable_change_requests SET current_step=2 "
            "WHERE status='scheduler_approved' AND (current_step IS NULL OR current_step=0)"
        ))
        # approved → current_step=3 (모든 단계 완료)
        db.execute(text(
            "UPDATE timetable_change_requests SET current_step=3 "
            "WHERE status='approved' AND (current_step IS NULL OR current_step=0)"
        ))
        db.commit()
    finally:
        db.close()


app = FastAPI(
    title="학교 시간표 관리 서버",
    version="2.0.0",
    description="시간표·편제·교사 정보 관리 및 채팅 기능을 제공하는 API 서버",
    lifespan=lifespan,
)

# TLS 경고: 운영 환경에서는 HTTPS/WSS 사용을 권장합니다.
_http_port = int(os.getenv("PORT", "8000"))
if not os.getenv("SSL_CERT_FILE"):
    print("[보안] TLS(HTTPS/WSS)가 설정되지 않았습니다. "
          "운영 환경에서는 nginx 리버스 프록시 또는 uvicorn --ssl 옵션으로 TLS를 활성화하세요. "
          "평문 HTTP 통신 시 JWT 토큰과 모든 데이터가 네트워크에 노출됩니다.")

# CORS 설정 — 환경 변수 CORS_ORIGINS 로 제어 (기본값: localhost 만 허용)
# 운영 환경에서는 서버의 실제 IP/도메인으로 설정하세요. 쉼표로 구분하여 여러 개 지정 가능.
# allow_credentials=True 이므로 allow_origins=["*"] 와일드카드는 사용할 수 없습니다
# (CORS 스펙 위반 + 보안 취약점). 반드시 명시적 origin 목록을 지정하세요.
_allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(timetable_router)
app.include_router(chat_router)
app.include_router(workflow_router)
app.include_router(notifications_router)


@app.get("/", tags=["상태"])
def health_check():
    """서버 상태 확인 엔드포인트."""
    return {"status": "ok", "service": "학교 시간표 관리 서버 v2"}
