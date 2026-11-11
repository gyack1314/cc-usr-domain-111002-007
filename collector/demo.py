"""端到端演示：多空间计划入口、双上下文存储隔离、异常场景的证据隔离。

phase 的切换属于本地来源调度（见 README 与 source-contract.json），由本演示
脚本通过 /__control 完成；采集组件本身只使用门户公开页面，不接触运维入口。
运行：python -m collector.demo
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from pathlib import Path

from portal.__main__ import running

from .diagnostics import verify_context_storage_isolation
from .plan import load_plan
from .runner import run_plan
from .safelog import install_secret_redaction

PLAN = Path(__file__).resolve().parents[1] / "config" / "plan.json"


def set_phase(base, phase):
    request = urllib.request.Request(base + "/__control",
                                     data=json.dumps({"phase": phase}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def show(title, results):
    print(f"\n== {title} ==")
    for space in sorted(results):
        result = results[space]
        line = {"space": space, "status": result.status,
                "records": [r["business_key"] for r in result.records]}
        if result.anomaly:
            line["anomaly"] = result.anomaly.get("kind")
            line["observed"] = result.anomaly.get("observed")
        if result.error:
            line["error"] = result.error[:120]
        print(json.dumps(line, ensure_ascii=False))


def check_clean_results(output_dir, plan):
    """正常结果里不允许出现跨空间内容。"""
    problems = []
    for spec in plan.workspaces:
        final = Path(output_dir) / spec.id / "records.jsonl"
        if not final.is_file():
            problems.append(f"{spec.id}: 缺少结果文件")
            continue
        for line in final.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["space"] != spec.id or not record["business_key"].startswith(spec.id + "/"):
                problems.append(f"{spec.id}: 结果混入其他空间 {record}")
            if f"公司{spec.id}" not in record["detail"]:
                problems.append(f"{spec.id}: 详情内容不属于本空间 {record['business_key']}")
    return problems


async def amain():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    install_secret_redaction()
    output_dir = Path("outputs/demo")
    state_dir = Path("state/demo")
    with running() as (base, _state):
        plan = load_plan(PLAN, base_url=base,
                         output_dir=str(output_dir), state_dir=str(state_dir))

        print("== 1. 真实启动两个 BrowserContext，验证浏览器存储彼此独立 ==")
        isolation = await verify_context_storage_isolation(base)
        print(json.dumps(isolation, ensure_ascii=False))
        assert isolation["ok"], "两个上下文的浏览器存储不独立"

        set_phase(base, "base")
        base_results = await run_plan(plan)
        show("2. 正常阶段：逐空间结果", base_results)
        assert all(r.status == "ok" for r in base_results.values()), "正常阶段应全部成功"

        set_phase(base, "wrong-detail")
        wrong_results = await run_plan(plan)
        show("3. 错误详情阶段：异常资料必须被隔离", wrong_results)
        assert all(r.status == "quarantined" and r.anomaly["kind"] == "wrong-detail"
                   for r in wrong_results.values()), "错误详情应被全部隔离"

        set_phase(base, "stale-list")
        stale_results = await run_plan(plan)
        show("4. 旧列表恢复阶段：异常资料必须被隔离", stale_results)
        assert all(r.status == "quarantined" and r.anomaly["kind"] == "stale-list"
                   for r in stale_results.values()), "旧列表应被全部隔离"

        print("\n== 5. 校验异常资料没有混入正常结果 ==")
        problems = check_clean_results(output_dir, plan)
        for problem in problems:
            print("问题:", problem)
        assert not problems, "异常资料混入了正常结果"
        evidence = sorted(
            str(p) for spec in plan.workspaces
            for p in (output_dir / spec.id / "quarantine").glob("*.evidence.json"))
        print(f"隔离证据 {len(evidence)} 份：")
        for path in evidence:
            print(" 证据:", path)
        print("\n演示完成：异常资料均未混入正常结果。")


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
