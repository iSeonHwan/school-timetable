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
from shared.models import User
from shared.schemas import (
    LoginRequest, TokenResponse, UserOut, UserCreate, UserUpdate,
)
from server.auth_utils import verify_password, hash_password, create_token
from server.deps import get_db, get_current_user, require_scheduler

router = APIRouter(prefix="/auth", tags=["인증"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """아이디·비밀번호로 로그인하고 JWT 토큰을 발급합니다."""
    user = db.query(User).filter_by(username=body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
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
    """새 사용자 계정을 생성합니다. 관리자 전용."""
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
    """사용자 정보를 수정합니다. 관리자 전용."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.role is not None:
        user.role = body.role
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
    current_user: User = Depends(require_admin),
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
