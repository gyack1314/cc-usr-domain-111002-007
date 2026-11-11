"""采集计划：用户配置、允许的空间编号与资料类别。

计划是多空间采集的唯一入口配置，明确给出：
- user：运行配置提供的登录材料（用户标识），只来自配置，不在空间间复制会话；
- allowed_spaces：允许接收资料的空间编号集合；
- workspaces：逐空间的编号与资料类别，每个空间的结果独立存放；
- max_contexts：上下文并发上限。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import PlanError

SPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class WorkspaceSpec:
    id: str
    categories: tuple
    state_file: str | None = None


@dataclass(frozen=True)
class Plan:
    user: str
    base_url: str
    allowed_spaces: tuple
    workspaces: tuple
    max_contexts: int
    headless: bool
    output_dir: Path
    state_dir: Path
    resume: bool


def load_plan(source, *, base_url=None, output_dir=None, state_dir=None,
              resume=None, max_contexts=None, headless=None):
    """从 JSON 文件加载计划，命令行覆盖项优先。"""
    path = Path(source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError(f"无法读取计划文件 {path}：{exc}") from exc
    except ValueError as exc:
        raise PlanError(f"计划文件 {path} 不是合法 JSON：{exc}") from exc
    overrides = {"base_url": base_url, "output_dir": output_dir, "state_dir": state_dir,
                 "resume": resume, "max_contexts": max_contexts, "headless": headless}
    for key, value in overrides.items():
        if value is not None:
            raw[key] = value
    return validate(raw)


def validate(raw):
    if not isinstance(raw, dict):
        raise PlanError("计划必须是 JSON 对象")
    user = raw.get("user")
    if not isinstance(user, str) or not user.strip():
        raise PlanError("计划必须给出非空用户 user")
    base_url = raw.get("base_url")
    if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
        raise PlanError("base_url 必须是 http(s) 地址")
    allowed = raw.get("allowed_spaces")
    if not isinstance(allowed, list) or not allowed:
        raise PlanError("allowed_spaces 必须是非空列表")
    for sid in allowed:
        if not isinstance(sid, str) or not SPACE_ID.match(sid):
            raise PlanError(f"允许集合中的空间编号不合法：{sid!r}")
    if len(set(allowed)) != len(allowed):
        raise PlanError("allowed_spaces 存在重复")
    workspaces = raw.get("workspaces")
    if not isinstance(workspaces, list) or not workspaces:
        raise PlanError("workspaces 必须是非空列表")
    seen = set()
    specs = []
    for item in workspaces:
        if not isinstance(item, dict):
            raise PlanError("workspaces 元素必须是对象")
        wid = item.get("id")
        if not isinstance(wid, str) or not SPACE_ID.match(wid):
            raise PlanError(f"空间编号不合法：{wid!r}")
        if wid not in allowed:
            raise PlanError(f"空间 {wid} 不在计划允许集合内")
        if wid in seen:
            raise PlanError(f"空间 {wid} 在计划中重复")
        seen.add(wid)
        cats = item.get("categories")
        if not isinstance(cats, list) or not cats or not all(isinstance(c, str) and c.strip() for c in cats):
            raise PlanError(f"空间 {wid} 的资料类别 categories 必须是非空字符串列表")
        state_file = item.get("state_file")
        if state_file is not None and not isinstance(state_file, str):
            raise PlanError(f"空间 {wid} 的 state_file 必须是字符串")
        specs.append(WorkspaceSpec(id=wid, categories=tuple(cats), state_file=state_file))
    max_contexts = raw.get("max_contexts", 2)
    if not isinstance(max_contexts, int) or isinstance(max_contexts, bool) or not 1 <= max_contexts <= 8:
        raise PlanError("max_contexts 必须是 1..8 的整数")
    for key in ("output_dir", "state_dir"):
        value = raw.get(key)
        if value is not None and not isinstance(value, (str, os.PathLike)):
            raise PlanError(f"{key} 必须是路径字符串")
    return Plan(
        user=user.strip(),
        base_url=base_url.rstrip("/"),
        allowed_spaces=tuple(allowed),
        workspaces=tuple(specs),
        max_contexts=max_contexts,
        headless=bool(raw.get("headless", True)),
        output_dir=Path(raw.get("output_dir", "outputs")),
        state_dir=Path(raw.get("state_dir", "state")),
        resume=bool(raw.get("resume", False)),
    )
