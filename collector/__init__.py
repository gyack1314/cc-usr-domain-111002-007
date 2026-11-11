"""多工作空间门户的浏览器上下文隔离采集组件。"""
from .collector import SpaceResult
from .diagnostics import verify_context_storage_isolation
from .errors import PlanError, StateFileRejected, WorkspaceAnomaly
from .plan import Plan, WorkspaceSpec, load_plan
from .runner import run_plan

__all__ = [
    "Plan",
    "PlanError",
    "SpaceResult",
    "StateFileRejected",
    "WorkspaceAnomaly",
    "WorkspaceSpec",
    "load_plan",
    "run_plan",
    "verify_context_storage_isolation",
]
