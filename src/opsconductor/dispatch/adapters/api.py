"""Dispatch HTTP API：快照、目标、审批、异常与 Demo 编排端点。

路由统一挂载在 ``/api/v1/dispatch``，错误映射与前端契约保持一致：

- 未知审批 / 异常 → 404；
- 审批重复裁决 → 409；
- 空白目标或非法取值 → 422。

所有写操作返回裁决后的最新快照，前端只需一次 ``applySnapshot`` 即可重绘。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from opsconductor.dispatch.adapters.container import get_service
from opsconductor.dispatch.adapters.serialize import (
    approval_payload,
    exception_payload,
    report_payload,
    snapshot_payload,
)
from opsconductor.dispatch.application.service import DispatchService
from opsconductor.dispatch.domain.errors import (
    ApprovalAlreadyDecided,
    ApprovalNotFound,
    ExceptionNotFound,
    InvalidGoal,
)

router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])

Service = Annotated[DispatchService, Depends(get_service)]


class GoalRequest(BaseModel):
    """创建目标请求；空白指令在领域层判定后返回 422。"""

    instruction: str = Field(min_length=1, max_length=500)


class DecisionRequest(BaseModel):
    """审批裁决请求；``actor`` 缺省为 Demo 操作员。"""

    decision: Literal["approve", "reject"]
    actor: str = Field(default="demo-operator", min_length=1, max_length=80)


def _invalid(exc: Exception) -> HTTPException:
    """把领域/取值错误映射为 422 响应。"""
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/snapshot")
def snapshot(service: Service) -> dict[str, Any]:
    """返回调度台完整快照。"""
    return snapshot_payload(service.snapshot())


@router.post("/goals")
def create_goal(payload: GoalRequest, service: Service) -> dict[str, Any]:
    """用自然语言目标重建计划与种子审批，并返回新快照。"""
    try:
        return snapshot_payload(service.create_goal(payload.instruction))
    except (InvalidGoal, ValueError) as exc:
        raise _invalid(exc) from exc


@router.post("/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    payload: DecisionRequest,
    service: Service,
) -> dict[str, Any]:
    """裁决一件审批案；重复裁决返回 409，未知审批返回 404。"""
    try:
        updated = service.decide_approval(
            approval_id, payload.decision, payload.actor
        )
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalAlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc
    return {
        "approval": approval_payload(updated.approvals[approval_id]),
        "snapshot": snapshot_payload(updated),
    }


@router.post("/approvals/reset")
def reset_approvals(service: Service) -> dict[str, Any]:
    """把所有审批案恢复为待批并返回快照。"""
    return snapshot_payload(service.reset_approvals())


@router.post("/demo/run")
def run_demo(service: Service) -> dict[str, Any]:
    """执行一次 Agent 编排演示，返回报告与当前快照投影。"""
    report = service.run_demo()
    return {
        "report": report_payload(report),
        "snapshot": snapshot_payload(service.snapshot()),
    }


@router.post("/reset")
def reset(service: Service) -> dict[str, Any]:
    """恢复 Demo 种子状态并返回快照。"""
    return snapshot_payload(service.reset())


@router.get("/exceptions/{exception_id}")
def get_exception(exception_id: str, service: Service) -> dict[str, Any]:
    """返回一条异常的完整 playbook；未知 ID 返回 404。"""
    try:
        return exception_payload(service.get_exception(exception_id))
    except ExceptionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["DecisionRequest", "GoalRequest", "router"]
