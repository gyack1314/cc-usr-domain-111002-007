"""单空间采集：独立 BrowserContext、界面切换、三处身份核对。

身份规则：
- 空间标识必须同时出现在导航、列表、详情三处且一致，并属于计划允许集合，
  才接收资料（计划校验已保证目标空间在允许集合内，三处一致即满足）；
- 业务主键 = 空间 + record-id，同一 record-id 可在不同空间复用；
- 文件跳转打开的新标签子页同样核对身份与空间；地址栏 ?detail= 参数不作为
  身份依据，也绝不把地址里的空间编号写回资料；
- 切换空间只使用门户公开的选择界面（select），不修改 localStorage 冒充切换；
- 导航正确不能替代列表核对：列表可能从合法缓存恢复旧空间内容；
- 发现任何不一致即保留证据并停止本空间链，异常资料不进入正式结果。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .errors import StateFileRejected, WorkspaceAnomaly
from .session import resume_state_path, save_state
from .store import SpaceStore

READY = "() => { const el = document.querySelector('#status'); return !!el && el.textContent !== '页面加载中'; }"
NAV_IS = "id => { const el = document.querySelector('#navigation'); return !!el && el.dataset.space === id; }"
DETAIL_RECORD = ("rid => { const el = document.querySelector('#detail [data-record-id]');"
                 " return !!el && el.getAttribute('data-record-id') === rid; }")
WAIT_MS = 15000


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def classify(title):
    """按标题归纳资料类别；门户合成记录形如“公司X资料”。"""
    return "资料" if title.endswith("资料") else "其他"


@dataclass
class SpaceResult:
    space: str
    status: str  # ok | quarantined | failed
    records: list = field(default_factory=list)
    anomaly: dict | None = None
    error: str | None = None
    output_dir: str = ""
    evidence: list = field(default_factory=list)


async def _nav(page):
    loc = page.locator("#navigation")
    return (await loc.get_attribute("data-space")) or "", ((await loc.text_content()) or "").strip()


async def _try_screenshot(page):
    if page is None:
        return None
    try:
        if page.is_closed():
            return None
        return await page.screenshot(full_page=True)
    except Exception:
        return None


async def collect_workspace(*, browser, plan, spec, store, logger):
    """采集单个空间；任何异常都被隔离在本空间内，不影响其他空间。"""
    log = logger.getChild(spec.id)
    result = SpaceResult(space=spec.id, status="failed", output_dir=str(store.dir))

    try:
        state_path = None
        if plan.resume or spec.state_file:
            state_path = resume_state_path(plan.state_dir, spec.id, spec.state_file)
    except StateFileRejected as exc:
        log.error("拒绝加载状态文件：%s", exc)
        store.abort({"kind": "state-rejected", "space": spec.id, "error": str(exc), "at": _utcnow()})
        result.error = f"state-rejected: {exc}"
        return result

    store.begin()
    # 每个空间独立 BrowserContext：登录材料只来自运行配置或本空间状态文件，
    # 不向别的空间复制 cookie 或存储状态。
    context = await browser.new_context(**({"storage_state": str(state_path)} if state_path else {}))
    shot_page = None
    try:
        page = await context.new_page()
        shot_page = page
        await page.goto(plan.base_url)
        await page.wait_for_function(READY, timeout=WAIT_MS)

        # 会话身份：运行配置提供的用户必须与页面显示一致，否则视为访问被撤销
        nav_space, nav_text = await _nav(page)
        if not nav_text.startswith(plan.user + " | "):
            raise WorkspaceAnomaly("session-identity", {
                "space": spec.id, "observed": {"navigation_text": nav_text}, "at": _utcnow()})

        # 通过门户公开的选择界面切换空间；不读取/修改 localStorage 来冒充切换
        await page.select_option("#space", spec.id)
        try:
            await page.wait_for_function(NAV_IS, arg=spec.id, timeout=WAIT_MS)
        except PlaywrightTimeout:
            nav_space, _ = await _nav(page)
            raise WorkspaceAnomaly("switch-failed", {
                "space": spec.id, "observed": {"navigation": nav_space}, "at": _utcnow()})
        select_value = await page.locator("#space").input_value()
        nav_space, _ = await _nav(page)
        if select_value != spec.id or nav_space != spec.id:
            raise WorkspaceAnomaly("navigation-mismatch", {
                "space": spec.id, "observed": {"navigation": nav_space, "select": select_value},
                "at": _utcnow()})

        await page.click("#load")
        await page.wait_for_selector("#list article", timeout=WAIT_MS)
        list_space = (await page.locator("#list").get_attribute("data-space")) or ""
        if list_space != spec.id:
            # 导航正确不能替代列表核对：可能从合法缓存恢复了旧空间列表
            raise WorkspaceAnomaly("stale-list", {
                "space": spec.id, "observed": {"navigation": nav_space, "list": list_space},
                "at": _utcnow()})

        articles = page.locator("#list article")
        for index in range(await articles.count()):
            art = articles.nth(index)
            rid = (await art.get_attribute("data-record-id")) or ""
            rspace = (await art.get_attribute("data-space")) or ""
            title = ((await art.evaluate(
                "el => el.childNodes[0] ? el.childNodes[0].textContent : ''")) or "").strip()
            if rspace != spec.id:
                raise WorkspaceAnomaly("record-space-mismatch", {
                    "space": spec.id, "record_id": rid,
                    "observed": {"navigation": nav_space, "list": list_space, "record": rspace},
                    "at": _utcnow()})
            category = classify(title)
            if category not in spec.categories:
                log.info("记录 %s 类别 %s 不在计划内，跳过", rid, category)
                continue

            await art.locator("#open-detail").click()
            await page.wait_for_function(DETAIL_RECORD, arg=rid, timeout=WAIT_MS)
            detail_space = (await page.locator("#detail").get_attribute("data-space")) or ""
            drec = page.locator("#detail [data-record-id]")
            dspace = (await drec.get_attribute("data-space")) or ""
            drid = (await drec.get_attribute("data-record-id")) or ""
            dtext = ((await drec.text_content()) or "").strip()
            if detail_space != spec.id or dspace != spec.id:
                raise WorkspaceAnomaly("wrong-detail", {
                    "space": spec.id, "record_id": rid,
                    "observed": {"navigation": nav_space, "list": list_space,
                                 "detail": detail_space, "detail_record": dspace},
                    "at": _utcnow()})
            if drid != rid:
                raise WorkspaceAnomaly("record-id-mismatch", {
                    "space": spec.id, "record_id": rid,
                    "observed": {"detail_record_id": drid}, "at": _utcnow()})

            # 新标签子页：同样核对身份与空间；地址栏 ?detail= 参数不作为身份依据
            async with context.expect_page() as popup_info:
                await art.locator("#new-tab").click()
            popup = await popup_info.value
            shot_page = popup
            if popup.context is not context:
                raise WorkspaceAnomaly("foreign-popup", {
                    "space": spec.id, "record_id": rid, "at": _utcnow()})
            await popup.wait_for_function(READY, timeout=WAIT_MS)
            await popup.wait_for_selector("#detail [data-record-id]", timeout=WAIT_MS)
            pnav = (await popup.locator("#navigation").get_attribute("data-space")) or ""
            pdetail = (await popup.locator("#detail").get_attribute("data-space")) or ""
            pdrec = popup.locator("#detail [data-record-id]")
            pspace = (await pdrec.get_attribute("data-space")) or ""
            prid = (await pdrec.get_attribute("data-record-id")) or ""
            ptext = ((await pdrec.text_content()) or "").strip()
            if pnav != spec.id or pdetail != spec.id or pspace != spec.id:
                raise WorkspaceAnomaly("new-tab-space-mismatch", {
                    "space": spec.id, "record_id": rid,
                    "observed": {"popup_navigation": pnav, "popup_detail": pdetail,
                                 "popup_record": pspace},
                    "at": _utcnow()})
            if prid != rid or ptext != dtext:
                raise WorkspaceAnomaly("new-tab-content-mismatch", {
                    "space": spec.id, "record_id": rid,
                    "observed": {"popup_record_id": prid, "popup_detail": ptext},
                    "at": _utcnow()})
            await popup.close()
            shot_page = page

            store.add({
                "business_key": f"{spec.id}/{rid}",
                "space": spec.id,
                "record_id": rid,
                "category": category,
                "title": title,
                "detail": dtext,
                "new_tab_verified": True,
                "identity": {"navigation": nav_space, "list": list_space,
                             "detail": detail_space, "new_tab": pnav},
                "collected_at": _utcnow(),
            })
            log.info("空间 %s 接收资料 %s（类别 %s）", spec.id, rid, category)

        store.commit()
        try:
            await save_state(context, plan.state_dir, spec.id, plan.user)
        except Exception as exc:  # 状态保存失败不影响已验证结果
            log.warning("空间 %s 状态保存失败：%s", spec.id, exc)
        result.status = "ok"
        result.records = list(store.accepted)
    except WorkspaceAnomaly as exc:
        log.warning("空间 %s 发现不一致（%s），保留证据并停止本空间链", spec.id, exc.kind)
        store.abort(exc.evidence, screenshot=await _try_screenshot(shot_page))
        result.status = "quarantined"
        result.anomaly = exc.evidence
    except Exception as exc:
        log.error("空间 %s 采集失败：%s", spec.id, exc)
        store.abort({"kind": "error", "space": spec.id, "error": str(exc)[:500], "at": _utcnow()},
                    screenshot=await _try_screenshot(shot_page))
        result.error = str(exc)[:500]
    finally:
        # 先关闭本空间全部页面（含仍在途的新标签），再释放上下文。
        # 上下文只属于本空间且不被复用，在途标签不会归到下一个空间。
        for open_page in list(context.pages):
            try:
                await open_page.close()
            except Exception:
                pass
        try:
            await context.close()
        except Exception:
            pass
    return result
