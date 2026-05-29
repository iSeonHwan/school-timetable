"""
결재 워크플로우 관리 API (관리자 전용)

ApprovalWorkflow + ApprovalStep 테이블의 CRUD 를 제공합니다.
일과계 선생님이 결재 단계 수와 각 단계의 승인자를 자유롭게 구성할 수 있습니다.

엔드포인트:
  GET    /workflows            — 모든 워크플로우 목록 (일과계·교감·교무부장 읽기 가능)
  GET    /workflows/active     — 현재 활성 워크플로우 반환 (교사 포함 모든 역할 접근 가능)
  POST   /workflows            — 새 워크플로우 생성 (일과계 전용, steps 포함)
  DELETE /workflows/{id}       — 워크플로우 삭제 (일과계 전용, 활성 워크플로우는 삭제 불가)
  POST   /workflows/{id}/activate — 워크플로우 활성화 (일과계 전용)

활성화 로직:
  - 한 번에 하나의 워크플로우만 is_active=True 일 수 있습니다.
  - 새 워크플로우를 is_active=True 로 생성하거나 activate 엔드포인트 호출 시,
    기존 활성 워크플로우를 자동으로 is_active=False 로 변경합니다.
  - 활성화된 워크플로우는 삭제할 수 없습니다 (실수로 결재 라인 제거 방지).

보안:
  - 생성·삭제·활성화는 require_scheduler 가드로 일과계(admin)만 접근 가능
  - 조회(GET)는 require_admin_or_vice_principal 가드로 일과계·교감·교무부장 접근 가능
  - /workflows/active 는 교사도 접근 가능 (변경 신청 상태 표시에 필요)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from shared.models import ApprovalWorkflow, ApprovalStep, User
from shared.schemas import (
    ApprovalWorkflowOut, ApprovalWorkflowCreate,
)
from server.deps import get_db, get_current_user, require_scheduler, require_admin_or_vice_principal

router = APIRouter(prefix="/workflows", tags=["결재 워크플로우"])


@router.get("", response_model=list[ApprovalWorkflowOut])
def list_workflows(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_or_vice_principal),
):
    """모든 워크플로우 목록을 반환합니다. (일과계·교감·교무부장 읽기 가능)"""
    return db.query(ApprovalWorkflow).order_by(ApprovalWorkflow.created_at.desc()).all()


@router.get("/active", response_model=ApprovalWorkflowOut)
def get_active_workflow(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    현재 활성화된 워크플로우를 반환합니다.

    모든 역할(교사 포함)이 접근 가능합니다.
    교사 앱에서 변경 신청 상태 표시에 사용됩니다.
    """
    wf = db.query(ApprovalWorkflow).filter_by(is_active=True).first()
    if wf is None:
        raise HTTPException(404, "활성화된 워크플로우가 없습니다. 관리자에게 문의하세요.")
    return wf


@router.post("", response_model=ApprovalWorkflowOut, status_code=201)
def create_workflow(
    body: ApprovalWorkflowCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    새 결재 워크플로우를 생성합니다. (일과계 전용)

    is_active=True 로 생성 시 기존 활성 워크플로우는 자동 비활성화됩니다.
    steps 는 step_order 순서대로 저장되며, 1부터 연속되어야 합니다.
    """
    if body.is_active:
        db.query(ApprovalWorkflow).filter_by(is_active=True).update(
            {"is_active": False}, synchronize_session="evaluate"
        )
    wf = ApprovalWorkflow(name=body.name, description=body.description, is_active=body.is_active)
    db.add(wf)
    db.flush()  # wf.id 확보
    for step in body.steps:
        s = ApprovalStep(
            workflow_id=wf.id,
            step_order=step.step_order,
            role_required=step.role_required,
            step_name=step.step_name,
        )
        db.add(s)
    db.commit()
    db.refresh(wf)
    return wf


@router.delete("/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    워크플로우를 삭제합니다. (일과계 전용)

    활성화된 워크플로우는 삭제할 수 없습니다.
    먼저 다른 워크플로우를 활성화한 후 삭제하세요.
    """
    wf = db.get(ApprovalWorkflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "워크플로우를 찾을 수 없습니다.")
    if wf.is_active:
        raise HTTPException(400, "활성화된 워크플로우는 삭제할 수 없습니다. 먼저 다른 워크플로우를 활성화하세요.")
    db.delete(wf)  # cascade 로 steps 도 자동 삭제
    db.commit()
    return {"ok": True}


@router.post("/{workflow_id}/activate", response_model=ApprovalWorkflowOut)
def activate_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """
    지정한 워크플로우를 활성화합니다. (일과계 전용)

    기존에 활성화된 워크플로우는 자동으로 비활성화됩니다.
    활성화된 워크플로우가 변경 신청 승인/거절 시 사용됩니다.
    """
    wf = db.get(ApprovalWorkflow, workflow_id)
    if wf is None:
        raise HTTPException(404, "워크플로우를 찾을 수 없습니다.")
    # 기존 활성 워크플로우 모두 비활성화 후 대상만 활성화
    db.query(ApprovalWorkflow).filter_by(is_active=True).update(
        {"is_active": False}, synchronize_session="evaluate"
    )
    wf.is_active = True
    db.commit()
    db.refresh(wf)
    return wf
