"""
JWT 생성·검증 및 비밀번호 해싱 유틸리티

사용 라이브러리:
  - python-jose  : JWT 생성/검증
  - bcrypt (passlib[bcrypt]) : 비밀번호 해싱

환경 변수:
  JWT_SECRET_KEY : 서명 키 (미설정 시 기본값 사용 — 운영 환경에서는 반드시 변경)
  JWT_EXPIRE_HOURS: 토큰 유효 시간 (기본 24시간)
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

# 운영 환경에서는 환경 변수로 반드시 교체하세요.
_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE_THIS_SECRET_IN_PRODUCTION_ENV")
_ALGORITHM = "HS256"
_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── 비밀번호 ───────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """평문 비밀번호를 bcrypt 해시로 변환합니다."""
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """평문과 해시를 비교합니다."""
    return _pwd_ctx.verify(plain, hashed)


# ── JWT ────────────────────────────────────────────────────────────────────

def create_token(user_id: int, role: str, teacher_id: Optional[int]) -> str:
    """
    JWT 액세스 토큰을 생성합니다.

    payload:
      sub       : user.id (str 로 저장)
      role      : "admin" | "teacher"
      teacher_id: Teacher.id (없으면 None)
      exp       : 만료 시각
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "teacher_id": teacher_id,
        "exp": expire,
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    JWT 를 검증하고 payload 딕셔너리를 반환합니다.
    만료되거나 서명이 잘못된 경우 None 을 반환합니다.
    sub 필드는 int 로 변환해서 반환합니다.
    """
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        payload["sub"] = int(payload["sub"])
        return payload
    except (JWTError, ValueError):
        return None
