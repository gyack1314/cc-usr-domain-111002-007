"""单空间结果目录：partial 暂存、final 提交、quarantine 隔离。

每个空间的结果独立存放在 outputs/<空间>/ 下：
- 采集过程中先写入 partial/，整条链核对通过后才原子替换为 records.jsonl；
- 发现空间不一致或失败时，未完成输出与证据一起移入 quarantine/，
  已有的正式结果保持原样，异常资料不会混入。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


class SpaceStore:
    def __init__(self, root, space):
        self.dir = Path(root) / space
        self.partial_dir = self.dir / "partial"
        self.quarantine_dir = self.dir / "quarantine"
        self.final_file = self.dir / "records.jsonl"
        self.accepted = []
        self.evidence_files = []
        self._fp = None

    def begin(self):
        self.partial_dir.mkdir(parents=True, exist_ok=True)
        self._fp = (self.partial_dir / "records.jsonl").open("w", encoding="utf-8")

    def add(self, record):
        self.accepted.append(record)
        if self._fp is not None:
            self._fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fp.flush()

    def _close(self):
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def commit(self):
        """采集链全部通过：暂存结果原子替换为正式结果。"""
        self._close()
        self.dir.mkdir(parents=True, exist_ok=True)
        partial = self.partial_dir / "records.jsonl"
        if partial.exists():
            os.replace(partial, self.final_file)
        else:
            self.final_file.touch()
        shutil.rmtree(self.partial_dir, ignore_errors=True)

    def abort(self, evidence, screenshot=None):
        """失败或不一致：证据与未完成输出一起隔离，正式结果保持原样。"""
        self._close()
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        kind = str(evidence.get("kind", "unknown"))
        base = f"{stamp}-{kind}"
        evidence_path = self.quarantine_dir / f"{base}.evidence.json"
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        self.evidence_files.append(str(evidence_path))
        if screenshot:
            shot_path = self.quarantine_dir / f"{base}.png"
            shot_path.write_bytes(screenshot)
            self.evidence_files.append(str(shot_path))
        partial = self.partial_dir / "records.jsonl"
        if partial.exists() and partial.stat().st_size > 0:
            target = self.quarantine_dir / f"{base}.partial.jsonl"
            os.replace(partial, target)
            self.evidence_files.append(str(target))
        shutil.rmtree(self.partial_dir, ignore_errors=True)
