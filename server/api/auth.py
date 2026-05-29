"""
인증 API 라우터

POST /auth/login     — 로그인, JWT 발급
GET  /auth/me        — 현재 로그인한 사용자 정보
GET  /auth/users     — 사용자 목록 (관리자 전용)
POST /auth/users     — 사용자 생성 (관리자 전용)
PATCH /auth/users/{id} — 사용자 정보 수정 (관리자 전용)
DELETE /auth/users/{id} — 사용자 삭제 (관리자 전용)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import time
from shared.models import User
from shared.schemas import (
    LoginRequest, TokenResponse, UserOut, UserCreate, UserUpdate,
)
from server.auth_utils import verify_password, hash_password, create_token
from server.deps import get_db, get_current_user, require_scheduler

router = APIRouter(prefix="/auth", tags=["인증"])

# ── 로그인 실패 추적 (메모리 기반, 프로세스 재시작 시 초기화) ─────────────
# 무차별 대입 공격(brute-force)을 방지하기 위한 간단한 rate limiter 입니다.
# username 별로 실패 시각을 기록하고, 최근 _LOCK_MINUTES 분 내 _MAX_FAILED 회
# 실패하면 429 Too Many Requests 를 반환합니다.
# 프로덕션 환경에서는 Redis 등 영속적 저장소로 대체하여 여러 서버 인스턴스 간
# 공유할 수 있도록 개선하세요. 현재는 단일 프로세스 메모리 기반입니다.
_failed_attempts: dict[str, list[float]] = {}  # username → [timestamps]
_MAX_FAILED = 5         # 5회 연속 실패 시 잠금
_LOCK_MINUTES = 15      # 잠금 해제까지 대기 시간 (분)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """아이디·비밀번호로 로그인하고 JWT 토큰을 발급합니다."""
    username = body.username

    # ── Rate Limiting: 5회 실패 시 15분간 로그인 차단 ─────────────────────
    now_ts = time.time()
    attempts = _failed_attempts.get(username, [])
    # 최근 _LOCK_MINUTES 분 이내 실패만 필터링
    cutoff = now_ts - (_LOCK_MINUTES * 60)
    recent = [t for t in attempts if t > cutoff]
    _failed_attempts[username] = recent
    if len(recent) >= _MAX_FAILED:
        remaining = int((recent[0] + _LOCK_MINUTES * 60 - now_ts) / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"로그인 시도가 너무 많습니다. {remaining}분 후에 다시 시도하세요.",
        )

    user = db.query(User).filter_by(username=username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        # 실패 기록
        _failed_attempts.setdefault(username, []).append(now_ts)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
    # 로그인 성공 시 실패 기록 초기화
    _failed_attempts.pop(username, None)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다. 관리자에게 문의하세요.",
        )
    token = create_token(user.id, user.role, user.teacher_id)
    return TokenResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        teacher_id=user.teacher_id,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """현재 로그인한 사용자 정보를 반환합니다."""
    return current_user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    """전체 사용자 목록을 반환합니다. 관리자 전용."""
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    """
    새 사용자 계정을 생성합니다. 관리자(일과계) 전용.

    보안:
      - role 값 화이트리스트 검증으로 알 수 없는 role 주입 방지.
        허용된 role: admin(일과계), vice_principal(교감), department_head(교무부장), teacher(교사).
        예를 들어 body.role="superadmin" 같은 임의 값은 400 에러로 차단됩니다.
      - 아이디 중복 검사로 동일 username 생성 방지 (DB unique 제약조건과 이중 방어).
      - 비밀번호는 hash_password() 로 bcrypt 해싱 후 저장 (평문 저장 금지).
        비밀번호는 UserCreate.password 필드로 평문 전송되므로,
        반드시 HTTPS(TLS) 환경에서만 이 엔드포인트를 사용해야 합니다.
    """
    _ALLOWED_ROLES = {"admin", "vice_principal", "department_head", "teacher"}
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 역할입니다: {body.role}")
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        teacher_id=body.teacher_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """사용자 정보를 수정합니다. 관리자 전용.

    수정 가능한 필드: password, teacher_id, is_active.
    role 필드는 UserUpdate 스키마에서 제외되었으므로 이 엔드포인트로
    역할을 변경할 수 없습니다 (권한 상승 방지)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.teacher_id is not None:
        user.teacher_id = body.teacher_id
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scheduler),
):
    """사용자 계정을 삭제합니다. 관리자 전용. 자기 자신은 삭제할 수 없습니다."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="자기 자신의 계정은 삭제할 수 없습니다.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    db.delete(user)
    db.commit()
    return {"ok": True}
