"""采集组件的隔离、异常检测与状态文件校验。"""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from collector.diagnostics import verify_context_storage_isolation
from collector.plan import PlanError, load_plan
from collector.runner import run_plan
from portal.__main__ import running

ROOT = Path(__file__).resolve().parents[1]


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = running()
        self.base, _ = self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.output = Path(self.tmp.name) / "outputs"
        self.state = Path(self.tmp.name) / "state"

    def set_phase(self, phase):
        request = Request(self.base + "/__control",
                          data=json.dumps({"phase": phase}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def make_plan(self, workspaces=None, **extra):
        raw = {
            "user": "demo-user",
            "base_url": self.base,
            "allowed_spaces": ["A", "B"],
            "workspaces": workspaces or [
                {"id": "A", "categories": ["资料"]},
                {"id": "B", "categories": ["资料"]},
            ],
            "max_contexts": 2,
            "output_dir": str(self.output),
            "state_dir": str(self.state),
        }
        raw.update(extra)
        path = Path(self.tmp.name) / "plan.json"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return load_plan(path)

    def records(self, space):
        final = self.output / space / "records.jsonl"
        if not final.is_file():
            return None
        return [json.loads(line) for line in
                final.read_text(encoding="utf-8").splitlines() if line.strip()]

    def evidence(self, space):
        directory = self.output / space / "quarantine"
        if not directory.is_dir():
            return []
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(directory.glob("*.evidence.json"))]

    async def test_plan_entry_and_per_space_results(self):
        results = await run_plan(self.make_plan())
        self.assertEqual({"A", "B"}, set(results))
        for space in ("A", "B"):
            self.assertEqual("ok", results[space].status)
            records = self.records(space)
            self.assertEqual(1, len(records))
            record = records[0]
            # 业务主键带空间；同一 record-id 在两个空间各自成立
            self.assertEqual(f"{space}/R-17", record["business_key"])
            self.assertEqual(space, record["space"])
            self.assertIn(f"公司{space}", record["title"])
            self.assertIn(f"公司{space}", record["detail"])
            self.assertTrue(record["new_tab_verified"])
            self.assertEqual({"navigation": space, "list": space,
                              "detail": space, "new_tab": space}, record["identity"])
            last_run = json.loads(
                (self.output / space / "last-run.json").read_text(encoding="utf-8"))
            self.assertEqual("ok", last_run["status"])
            self.assertEqual([f"{space}/R-17"], last_run["records"])

    async def test_two_contexts_storage_independent(self):
        outcome = await verify_context_storage_isolation(self.base)
        self.assertTrue(outcome["ok"], outcome)

    async def test_wrong_detail_quarantined_not_mixed(self):
        plan = self.make_plan()
        await run_plan(plan)  # base：先留下干净结果
        clean = {s: (self.output / s / "records.jsonl").read_bytes() for s in ("A", "B")}
        self.set_phase("wrong-detail")
        results = await run_plan(plan)
        for space, other in (("A", "B"), ("B", "A")):
            self.assertEqual("quarantined", results[space].status)
            self.assertEqual("wrong-detail", results[space].anomaly["kind"])
            self.assertTrue(any(
                e["kind"] == "wrong-detail"
                and e["observed"]["navigation"] == space
                and e["observed"]["list"] == space
                and e["observed"]["detail"] == other
                for e in self.evidence(space)))
            # 正式结果未被异常运行改动，异常资料没有混入
            self.assertEqual(clean[space],
                             (self.output / space / "records.jsonl").read_bytes())
            for record in self.records(space):
                self.assertEqual(space, record["space"])
                self.assertIn(f"公司{space}", record["detail"])

    async def test_stale_list_quarantined(self):
        self.set_phase("stale-list")
        plan = self.make_plan()
        results = await run_plan(plan)
        for space, other in (("A", "B"), ("B", "A")):
            self.assertEqual("quarantined", results[space].status)
            self.assertEqual("stale-list", results[space].anomaly["kind"])
            self.assertTrue(any(
                e["kind"] == "stale-list"
                and e["observed"]["navigation"] == space
                and e["observed"]["list"] == other
                for e in self.evidence(space)))
            self.assertIsNone(self.records(space))  # 异常资料没有进入结果
        self.set_phase("base")
        results = await run_plan(plan)
        self.assertTrue(all(r.status == "ok" for r in results.values()))

    async def test_state_file_foreign_workspace_rejected(self):
        # B 空间的状态文件真实存在，再让 A 指向它：路径与空间不符必须拒绝
        b_dir = self.state / "B"
        b_dir.mkdir(parents=True)
        (b_dir / "storage-state.json").write_text("{}", encoding="utf-8")
        (b_dir / "storage-state.meta.json").write_text(
            json.dumps({"workspace": "B", "user": "demo-user"}), encoding="utf-8")
        plan = self.make_plan(workspaces=[
            {"id": "A", "categories": ["资料"],
             "state_file": str(b_dir / "storage-state.json")},
            {"id": "B", "categories": ["资料"]},
        ])
        results = await run_plan(plan)
        self.assertEqual("failed", results["A"].status)
        self.assertIn("state-rejected", results["A"].error)
        self.assertIsNone(self.records("A"))
        self.assertEqual("ok", results["B"].status)  # 一个空间失败，其他空间继续
        self.assertEqual(1, len(self.records("B")))

    async def test_resume_only_loads_own_state(self):
        plan = self.make_plan(resume=True)
        results = await run_plan(plan)
        self.assertTrue(all(r.status == "ok" for r in results.values()))
        meta = json.loads(
            (self.state / "A" / "storage-state.meta.json").read_text(encoding="utf-8"))
        self.assertEqual("A", meta["workspace"])
        # 篡改所属元数据后必须拒绝加载
        (self.state / "A" / "storage-state.meta.json").write_text(
            json.dumps({"workspace": "B"}), encoding="utf-8")
        results = await run_plan(plan)
        self.assertEqual("failed", results["A"].status)
        self.assertIn("state-rejected", results["A"].error)
        self.assertEqual("ok", results["B"].status)

    async def test_plan_rejects_workspace_outside_allowed(self):
        with self.assertRaises(PlanError):
            self.make_plan(workspaces=[{"id": "C", "categories": ["资料"]}])

    def test_collector_never_uses_ops_or_storage_forgery(self):
        # 采集路径不得借用运维入口，也不得写 localStorage 冒充切换
        forbidden = ("/__control", "/__state", "setItem")
        for module in (ROOT / "collector").glob("*.py"):
            if module.name == "demo.py":
                continue  # demo 负责来源调度（设置 phase），不属于采集路径
            text = module.read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, text, f"{module.name} 不应出现 {needle}")


if __name__ == "__main__":
    unittest.main()
