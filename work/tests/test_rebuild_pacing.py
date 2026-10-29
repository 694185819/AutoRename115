# -*- coding: utf-8 -*-
"""节奏相关：后台任务进行中再触发重建时，不得弹窗阻塞（只记日志/状态）。"""
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile
import threading

from app.gui import App
from app.models import MatchResult, P115Item, ParsedName, PlanItem


class SlowMeta:
    def __init__(self, delay=1.0):
        self.delay = delay
        self.calls = 0

    def source_episode_titles(self, source, sid, season):
        self.calls += 1
        time.sleep(self.delay)
        return {1: "第一集"} if int(season) == 1 else {}

    def season_episode_titles(self, tmdb_id, season):
        return {}

    def save_cache(self):
        pass


def build_plan():
    item = P115Item(fid="root", parent_id="0", name="灵笼", is_dir=True)
    m = MatchResult(title_zh="灵笼", series_title="灵笼", year=2019,
                    tmdb_id="91097", country="cn", animation=True,
                    confidence=1.0)
    m.source_refs = {"douban": {"id": "27121260", "title": "灵笼 第一季",
                                "year": 2019}}
    plan = PlanItem(item=item, media_type="series",
                    parsed=ParsedName(raw="灵笼", title="灵笼", season=1),
                    match=m, title="灵笼", year=2019, category="cn_anime")

    video = P115Item(fid="v1", parent_id="root", name="灵笼 S01E01.mp4",
                     is_dir=False, size=10)

    class MR:
        def __init__(self, root):
            self.item = root
            self.sidecars = []
            self.season_dirs = []

    mr = MR(item)

    entry = type("E", (), {
        "item": video, "is_video": True,
        "parsed": ParsedName(raw=video.name, title="灵笼", season=1,
                             episode=1),
        "folder_season": None, "container": None})()
    plan.context = {"mr": mr, "entries": [entry]}
    return plan


def main():
    # 监控 messagebox：出现弹窗即失败
    from app import gui as gui_mod
    popups = []
    real = gui_mod.messagebox.showinfo

    def spy(*a, **k):
        popups.append(a[:2])
        return None
    gui_mod.messagebox.showinfo = spy

    try:
        app = gui_mod.App(tempfile.mkdtemp(prefix="arn115_pace_"))
        app.withdraw()
        app._init_meta = lambda: None
        app.meta = SlowMeta()
        from app.planner import NamingOptions, Planner
        app.planner = Planner(app.meta, NamingOptions())
        app.client = None

        plan = build_plan()
        app.plans = [plan]
        app._render_plans()
        app.detail_plan = plan

        # 第一次：启动后台重建
        app._set_naming_source(plan, "douban")
        assert app.busy, "第一次重建应进入忙碌"
        # 忙碌期间连续再点两次：应被跳过，且不弹窗
        app._set_naming_source(plan, "tmdb")
        app._set_naming_source(plan, "douban")
        app.rebuild_detail()
        app.update()
        assert not popups, f"忙碌期间不应弹窗：{popups}"
        assert "跳过" in app.status_var.get() or "跳过" in "".join(
            app.log_text.get("1.0", "end")), app.status_var.get()

        # 等第一次结束
        assert app.wait_for_rebuild(15), "后台重建应在超时内结束"
        assert not app.busy, "结束后必须解除忙碌"

        # 结束后应能正常再发起
        app._set_naming_source(plan, "douban")
        assert app.busy
        app.wait_for_rebuild(15)
        assert not app.busy
        assert not popups, f"全程不应弹窗：{popups}"

        app.destroy()
    finally:
        gui_mod.messagebox.showinfo = real
    print("REBUILD PACING OK")


if __name__ == "__main__":
    main()
