"""多空间计划入口：并发受限地逐空间采集，结果互不影响。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from .collector import SpaceResult, collect_workspace
from .store import SpaceStore


async def run_plan(plan, logger=None):
    """按计划逐空间采集；每个空间独立 BrowserContext，失败互不影响。

    max_contexts 限制并发上下文数；信号量在整个空间任务（含上下文关闭）
    完成后才释放，释放浏览器资源时不会把在途新标签归到下一个空间。
    """
    logger = logger or logging.getLogger("collector")
    semaphore = asyncio.Semaphore(plan.max_contexts)
    results = {}
    async with async_playwright() as driver:
        browser = await driver.chromium.launch(headless=plan.headless, args=["--no-sandbox"])
        try:
            async def run_one(spec):
                async with semaphore:
                    store = SpaceStore(plan.output_dir, spec.id)
                    try:
                        result = await collect_workspace(
                            browser=browser, plan=plan, spec=spec, store=store, logger=logger)
                    except Exception as exc:  # 兜底隔离：未预期错误也不影响其他空间
                        logger.getChild(spec.id).error("未预期错误：%s", exc)
                        store.abort({"kind": "error", "space": spec.id, "error": str(exc)[:500],
                                     "at": datetime.now(timezone.utc).isoformat()})
                        result = SpaceResult(space=spec.id, status="failed",
                                             error=str(exc)[:500], output_dir=str(store.dir))
                    result.evidence = list(store.evidence_files)
                    _write_last_run(store.dir, result)
                    results[spec.id] = result

            await asyncio.gather(*(run_one(spec) for spec in plan.workspaces))
        finally:
            await browser.close()
    return results


def _write_last_run(directory, result):
    """逐空间结果摘要；不含会话秘密。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "space": result.space,
        "status": result.status,
        "record_count": len(result.records),
        "records": [r.get("business_key") for r in result.records],
        "anomaly": result.anomaly,
        "error": result.error,
        "evidence": result.evidence,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (directory / "last-run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
