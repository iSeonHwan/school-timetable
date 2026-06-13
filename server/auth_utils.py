"""
JWT 생성·검증 및 비밀번호 해싱 유틸리티

사용 라이브러리:
  - python-jose  : JWT 생성/검증 (HS256 대칭키 서명)
  - bcrypt (passlib[bcrypt]) : 비밀번호 해싱 (단방향, 솔트 자동 포함)

보안 설계:
  1. JWT_SECRET_KEY — 환경 변수로 주입. 미설정 시 uuid4()로 임시 생성하지만,
     이 경우 서버 재시작 시 모든 기존 토큰이 무효화됩니다.
     운영 환경에서는 반드시 고정된 강력한 키(64자 이상 랜덤 문자열)를 설정하세요.
  2. JWT payload 에는 sub(사용자 ID), role(역할), iat(발급 시각), jti(토큰 고유 ID),
     exp(만료 시각)를 포함합니다. jti 는 향후 토큰 폐기(revocation) 구현을 위한
     기반입니다.
  3. 비밀번호는 bcrypt 로 해싱되며, 평문은 어떤 경로로도 저장·로그 출력되지 않습니다.
  4. JWT_EXPIRE_HOURS (기본 24시간) — 장시간 유효 토큰은 탈취 시 위험하므로
     운영 환경에 맞게 조정하세요.

환경 변수:
  JWT_SECRET_KEY : 서명 키 (운영 환경에서 반드시 고정값 설정)
  JWT_EXPIRE_HOURS: 토큰 유효 시간 (기본 24시간)
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt

import uuid

_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not _SECRET_KEY:
    # ── JWT_SECRET_KEY 미설정 처리 ──────────────────────────────────────────
    # APP_ENV 환경 변수로 실행 환경을 구분합니다.
    #   - APP_ENV=production  → 보안 오류로 서버 시작 거부
    #   - APP_ENV=development (또는 미설정) → 임시 키 생성 후 경고 출력
    #
    # 임시 키(uuid4)의 문제점:
    #   서버 프로세스가 재시작될 때마다 새로운 키가 생성됩니다.
    #   그 결과 이전에 발급된 모든 JWT 토큰이 즉시 무효화되고,
    #   로그인한 모든 사용자가 강제 로그아웃됩니다.
    #
    # 올바른 운영 환경 설정:
    #   export JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    #   export APP_ENV=production
    _app_env = os.getenv("APP_ENV", "development").strip().lower()
    if _app_env == "production":
        # 운영 환경에서 키 미설정은 심각한 보안 위험 — 서버 시작 자체를 거부합니다.
        # RuntimeError 는 uvicorn 기동 단계에서 발생하여 서버가 시작되지 않습니다.
        raise RuntimeError(
            "\n"
            "=" * 60 + "\n"
            "[보안 오류] JWT_SECRET_KEY 환경 변수가 설정되지 않았습니다.\n"
            "운영 환경(APP_ENV=production)에서는 반드시 고정된 강력한 키를\n"
            "환경 변수로 설정해야 합니다.\n\n"
            "설정 방법:\n"
            "  export JWT_SECRET_KEY=$(python3 -c \"import secrets; print(secrets.token_hex(32))\")\n"
            "  export APP_ENV=production\n"
            "=" * 60
        )

    # 개발 환경: 임시 키 허용, 단 경고를 명확히 출력
    _SECRET_KEY = uuid.uuid4().hex
    print(
        "\n" + "!" * 60 + "\n"
        "[보안 경고] JWT_SECRET_KEY 환경 변수가 설정되지 않았습니다.\n"
        "  → 임시 키를 생성했습니다. 서버 재시작 시 모든 로그인 토큰이 무효화됩니다.\n"
        "  → 이 동작은 개발 환경(APP_ENV=development)에서만 허용됩니다.\n"
        "  → 운영 배포 전 반드시 JWT_SECRET_KEY 와 APP_ENV=production 을 설정하세요.\n"
        "!" * 60 + "\n"
    )

_ALGORITHM = "HS256"
_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# ── 비밀번호 ───────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """평문 비밀번호를 bcrypt 해시로 변환합니다."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """평문과 해시를 비교합니다."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT ────────────────────────────────────────────────────────────────────

def create_token(user_id: int, role: str, teacher_id: Optional[int]) -> str:
    """
    JWT 액세스 토큰을 생성합니다.

    payload 에 포함되는 클레임:
      sub       : user.id (str) — 토큰 주체 식별
      role      : "admin" | "vice_principal" | "teacher" — 권한 검사에 사용
      teacher_id: Teacher.id (없으면 None) — 교사 앱에서 본인 시간표 조회용
      iat       : 발급 시각 (issued-at) — 토큰 나이 계산에 사용
      jti       : JWT ID (uuid4) — 향후 토큰 폐기(revocation) 구현을 위한 고유 식별자
      exp       : 만료 시각 — _EXPIRE_HOURS 후 자동 만료
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "teacher_id": teacher_id,
        "iat": now,                # 토큰 발급 시점 (issued-at)
        "jti": str(uuid.uuid4()),  # 토큰 고유 ID (JWT ID — revocation 대비)
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
