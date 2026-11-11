"""诊断：真实启动两个 BrowserContext，验证浏览器存储彼此独立。"""
from __future__ import annotations

from playwright.async_api import async_playwright

from .collector import READY

WAIT_MS = 15000


async def verify_context_storage_isolation(base_url, headless=True):
    """在第一个上下文里通过界面切到空间 B，第二个上下文必须保持默认空间 A。

    只读取 localStorage 做核对，不写入；切换只通过门户公开的选择界面完成。
    """
    async with async_playwright() as driver:
        browser = await driver.chromium.launch(headless=headless, args=["--no-sandbox"])
        try:
            context1 = await browser.new_context()
            context2 = await browser.new_context()
            try:
                page1 = await context1.new_page()
                page2 = await context2.new_page()
                await page1.goto(base_url)
                await page2.goto(base_url)
                await page1.wait_for_function(READY, timeout=WAIT_MS)
                await page2.wait_for_function(READY, timeout=WAIT_MS)
                await page1.select_option("#space", "B")
                await page1.wait_for_function(
                    "id => document.querySelector('#navigation').dataset.space === id",
                    arg="B", timeout=WAIT_MS)
                observed = {
                    "context1_storage": await page1.evaluate("() => localStorage.getItem('workspace')"),
                    "context2_storage": await page2.evaluate("() => localStorage.getItem('workspace')"),
                    "context2_select": await page2.locator("#space").input_value(),
                    "context2_navigation": await page2.locator("#navigation").get_attribute("data-space"),
                }
            finally:
                await context1.close()
                await context2.close()
        finally:
            await browser.close()
    ok = (
        observed["context1_storage"] == "B"
        and observed["context2_storage"] == "A"
        and observed["context2_select"] == "A"
        and observed["context2_navigation"] == "A"
    )
    return {"ok": ok, "observed": observed}
