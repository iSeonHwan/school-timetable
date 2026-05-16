"""
FastAPI 공통 의존성 모듈

DB 세션 주입, JWT 토큰 검증, 권한 확인 함수를 정의합니다.
각 API 라우터에서 Depends() 로 주입해 사용합니다.
"""
from __future__ import annotations
from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database.connection import get_session
from shared.models import User
from server.auth_utils import decode_token

_bearer = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    """요청마다 새 DB 세션을 생성하고, 응답 후 반드시 닫습니다."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def _get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    Authorization: Bearer <token> 헤더를 검증하고 User 객체를 반환합니다.
    토큰이 없거나 만료됐으면 401 을 반환합니다.
    """
    payload = decode_token(creds.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다.")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="계정을 찾을 수 없거나 비활성화 상태입니다.")
    return user


def get_current_user(user: User = Depends(_get_current_user)) -> User:
    """인증된 사용자를 반환합니다 (role 무관)."""
    return user


def require_admin(user: User = Depends(_get_current_user)) -> User:
    """admin role 이 아니면 403 을 반환합니다."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다.")
    return user
