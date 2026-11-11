"""运行状态文件：按空间隔离保存与恢复，路径与空间不符即拒绝。

每个空间的会话状态只保存在 state/<空间>/ 下，并附带所属空间元数据。
恢复时只加载明确属于本空间的文件：路径必须位于本空间目录内，且元数据中的
空间编号与目标空间一致，否则抛出 StateFileRejected。状态文件含有会话材料，
只写文件，绝不写入日志。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import StateFileRejected

STATE_NAME = "storage-state.json"
META_NAME = "storage-state.meta.json"


def space_state_dir(state_dir, space):
    return Path(state_dir) / space


def state_path_for(state_dir, space):
    return space_state_dir(state_dir, space) / STATE_NAME


def _check_meta(state_path, space):
    meta = state_path.with_name(META_NAME)
    if not meta.is_file():
        raise StateFileRejected(f"{state_path} 缺少空间元数据，无法证明属于空间 {space}，拒绝加载")
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StateFileRejected(f"状态元数据不可读：{exc}") from exc
    owner = data.get("workspace")
    if owner != space:
        raise StateFileRejected(f"状态文件属于空间 {owner!r}，与目标空间 {space!r} 不符，拒绝加载")


def resume_state_path(state_dir, space, override=None):
    """返回通过校验的本空间状态文件路径；不属于本空间则抛 StateFileRejected。"""
    if override:
        candidate = Path(override).resolve()
        own_dir = space_state_dir(state_dir, space).resolve()
        if not candidate.is_relative_to(own_dir):
            raise StateFileRejected(f"状态文件路径 {candidate} 不在空间 {space} 的目录 {own_dir} 内，拒绝加载")
        if not candidate.is_file():
            raise StateFileRejected(f"状态文件不存在：{candidate}")
        _check_meta(candidate, space)
        return candidate
    default = state_path_for(state_dir, space)
    if default.is_file():
        _check_meta(default, space)
        return default.resolve()
    return None


async def save_state(context, state_dir, space, user):
    """保存本空间会话状态及所属元数据；内容含会话材料，不写入日志。"""
    target_dir = space_state_dir(state_dir, space)
    target_dir.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(target_dir / STATE_NAME))
    meta = {"workspace": space, "user": user,
            "saved_at": datetime.now(timezone.utc).isoformat()}
    (target_dir / META_NAME).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
