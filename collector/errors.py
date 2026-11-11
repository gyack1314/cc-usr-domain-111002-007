"""采集组件的异常类型。"""


class PlanError(ValueError):
    """计划配置不合法。"""


class StateFileRejected(Exception):
    """状态文件与空间不符，拒绝加载。"""


class WorkspaceAnomaly(Exception):
    """页面出现跨空间不一致；evidence 为可保存的证据（不含会话秘密）。"""

    def __init__(self, kind, evidence=None):
        self.kind = kind
        self.evidence = {"kind": kind, **(evidence or {})}
        super().__init__(kind)
