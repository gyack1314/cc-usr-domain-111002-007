"""多空间计划入口：python -m collector --plan config/plan.json"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .errors import PlanError
from .plan import load_plan
from .runner import run_plan
from .safelog import install_secret_redaction


def main(argv=None):
    parser = argparse.ArgumentParser(prog="collector", description="多工作空间隔离采集")
    parser.add_argument("--plan", required=True, help="计划文件（用户配置、允许的空间编号与资料类别）")
    parser.add_argument("--base-url", help="覆盖计划中的门户地址")
    parser.add_argument("--output-dir", help="覆盖计划中的结果目录")
    parser.add_argument("--state-dir", help="覆盖计划中的状态目录")
    parser.add_argument("--resume", action="store_true", help="恢复本空间自己的状态文件")
    parser.add_argument("--max-contexts", type=int, help="上下文并发上限")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    install_secret_redaction()

    overrides = {"base_url": args.base_url, "output_dir": args.output_dir,
                 "state_dir": args.state_dir, "max_contexts": args.max_contexts,
                 "resume": True if args.resume else None}
    try:
        plan = load_plan(args.plan, **{k: v for k, v in overrides.items() if v is not None})
    except PlanError as exc:
        print(f"计划不合法：{exc}", file=sys.stderr)
        return 2

    results = asyncio.run(run_plan(plan))
    for space in sorted(results):
        result = results[space]
        line = {"space": space, "status": result.status,
                "records": [r["business_key"] for r in result.records],
                "output": result.output_dir}
        if result.anomaly:
            line["anomaly"] = result.anomaly.get("kind")
        if result.error:
            line["error"] = result.error[:120]
        print(json.dumps(line, ensure_ascii=False))
    return 0 if all(r.status == "ok" for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
