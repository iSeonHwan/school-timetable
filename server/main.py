"""
FastAPI 서버 진입점

실행 방법:
  uvicorn server.main:app --host 0.0.0.0 --port 8000

환경 변수:
  DB_URL             : SQLAlchemy DB URL (미설정 시 config.py 의 get_db_url() 사용)
  JWT_SECRET_KEY     : JWT 서명 키 (운영 환경에서 반드시 설정)
  JWT_EXPIRE_HOURS   : 토큰 유효 시간 (기본 24)
  ADMIN_USERNAME     : 최초 일과계 아이디 (기본 "admin")
  ADMIN_PASSWORD     : 최초 일과계 비밀번호 (기본 "admin1234")
  VP_USERNAME        : 최초 교감 아이디 (기본 "vice_principal")
  VP_PASSWORD        : 최초 교감 비밀번호 (기본 "vp1234")
  CHAT_RETENTION_DAYS: 채팅 메시지 보관 기간(일) (기본 60, 0=무기한)
"""
import os
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    서버 시작 시 DB 초기화, 최초 관리자 계정 생성, 채팅 정리 태스크 시작.
    서버 종료 시 채팅 정리 태스크를 안전하게 종료합니다.
    """
    db_url = os.getenv("DB_URL")
    init_db(db_url)
    _ensure_admin()

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

    두 종류의 관리자 계정을 생성합니다:
      - 일과계 선생님 (admin): 전체 관리 권한
        환경 변수 ADMIN_USERNAME / ADMIN_PASSWORD 로 설정 (기본값 admin / admin1234)
      - 교감 선생님 (vice_principal): 변경 신청 최종 승인만 가능
        환경 변수 VP_USERNAME / VP_PASSWORD 로 설정 (기본값 vice_principal / vp1234)
    """
    db = get_session()
    try:
        # ── 일과계 선생님 계정 (admin) ──────────────────────────────────────
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin1234")
        if not db.query(User).filter_by(role="admin").first():
            admin = User(
                username=admin_username,
                password_hash=hash_password(admin_password),
                role="admin",
            )
            db.add(admin)
            db.commit()
            print(f"[서버] 최초 일과계 선생님 계정 생성: {admin_username} (비밀번호를 즉시 변경하세요!)")

        # ── 교감 선생님 계정 (vice_principal) ───────────────────────────────
        vp_username = os.getenv("VP_USERNAME", "vice_principal")
        vp_password = os.getenv("VP_PASSWORD", "vp1234")
        if not db.query(User).filter_by(role="vice_principal").first():
            vp = User(
                username=vp_username,
                password_hash=hash_password(vp_password),
                role="vice_principal",
            )
            db.add(vp)
            db.commit()
            print(f"[서버] 최초 교감 선생님 계정 생성: {vp_username} (비밀번호를 즉시 변경하세요!)")
    finally:
        db.close()


app = FastAPI(
    title="학교 시간표 관리 서버",
    version="2.0.0",
    description="시간표·편제·교사 정보 관리 및 채팅 기능을 제공하는 API 서버",
    lifespan=lifespan,
)

# 개발 중 CORS 허용 — 운영 환경에서는 allow_origins 를 서버 IP 로 제한하세요.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(timetable_router)
app.include_router(chat_router)


@app.get("/", tags=["상태"])
def health_check():
    """서버 상태 확인 엔드포인트."""
    return {"status": "ok", "service": "학교 시간표 관리 서버 v2"}
