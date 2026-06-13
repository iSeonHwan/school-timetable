"""
알림 API

GET    /notifications             — 현재 로그인한 사용자의 알림 목록
PATCH  /notifications/{id}/read — 알림 읽음 처리
DELETE /notifications/{id}      — 알림 삭제

이 모듈은 교사 간 수업 교체 동의 요청, 동의 결과, 변경 신청 최종 승인/거절 등의
이벤트를 사용자에게 전달하는 REST 엔드포인트를 제공합니다.

실시간 알림은 server/api/chat.py 의 ConnectionManager.send_to_user() 를 통해
WebSocket 으로 전송되며, 이 파일은 주로 이력 조회와 읽음 처리를 담당합니다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.models import Notification, User
from shared.schemas import NotificationOut, NotificationReadRequest
from server.deps import get_db, get_current_user

router = APIRouter(prefix="/notifications", tags=["알림"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    현재 로그인한 사용자의 알림 목록을 최신순으로 반환합니다.

    Args:
        limit: 최대 반환 개수 (기본 100)

    Returns:
        NotificationOut 리스트
    """
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return rows


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """현재 사용자의 읽지 않은 알림 개수를 반환합니다."""
    count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .count()
    )
    return {"unread_count": count}


@router.patch("/{notification_id}", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    body: NotificationReadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    지정한 알림을 읽음/안읽음으로 표시합니다.

    보안:
      - 본인의 알림만 수정할 수 있습니다.
    """
    notif = db.get(Notification, notification_id)
    if notif is None:
        raise HTTPException(404, "알림을 찾을 수 없습니다.")
    if notif.user_id != current_user.id:
        raise HTTPException(403, "본인의 알림만 수정할 수 있습니다.")
    notif.is_read = body.is_read
    db.commit()
    db.refresh(notif)
    return notif


@router.delete("/{notification_id}", status_code=200)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """본인의 알림을 삭제합니다."""
    notif = db.get(Notification, notification_id)
    if notif is None:
        raise HTTPException(404, "알림을 찾을 수 없습니다.")
    if notif.user_id != current_user.id:
        raise HTTPException(403, "본인의 알림만 삭제할 수 있습니다.")
    db.delete(notif)
    db.commit()
    return {"ok": True}
