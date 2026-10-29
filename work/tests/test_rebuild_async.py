# -*- coding: utf-8 -*-
"""按来源命名必须在后台重建：主线程不得联网，点击后界面立即可用。"""
import sys
import threading
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem


class SlowMeta:
    """模拟“联网很慢”的来源：rebuild 时会请求单集标题。"""

    def __init__(self, delay=1.2):
        self.delay = delay
        self.threads = []
        self.calls = 0

    def source_episode_titles(self, source, sid, season):
        import time as _t
        self.calls += 1
        self.threads.append(threading.current_thread().name)
        _t.sleep(self.delay)
        return {1: "灯塔和光影会"} if int(season) == 1 else {}

    def season_episode_titles(self, tmdb_id, season):
        return {}

    def save_cache(self):
        pass


def make_plan():
    item = P115Item(fid="root", parent_id="0", name="灵笼", is_dir=True)
    m = MatchResult(title_zh="灵笼", series_title="灵笼", year=2019,
                    tmdb_id="91097", country="cn", animation=True,
                    confidence=1.0)
    m.source_refs = {"douban": {"id": "27121260", "title": "灵笼 第一季",
                                "year": 2019},
                     "tmdb": {"id": "91097", "title": "灵笼", "year": 2019}}
    plan = PlanItem(item=item, media_type="series",
                    parsed=ParsedName(raw="灵笼", title="灵笼", season=1),
                    match=m, title="灵笼", year=2019, category="cn_anime")
    return plan


def main():
    app = App(tempfile.mkdtemp(prefix="arn115_rebuild_"))
    app.withdraw()
    app._init_meta = lambda: None
    app.meta = SlowMeta()
    from app.planner import NamingOptions, Planner
    app.planner = Planner(app.meta, NamingOptions())
    app.client = None

    video = P115Item(fid="v1", parent_id="root", name="灵笼 S01E01.mp4",
                     is_dir=False, size=10)

    class MR:
        item = P115Item(fid="mr", parent_id="0", name="灵笼", is_dir=True)
        sidecars = []
        season_dirs = []

    plan = make_plan()
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": video, "is_video": True, "parsed": ParsedName(
            raw=video.name, title="灵笼", season=1, episode=1),
        "folder_season": None, "container": None})()]}
    app.plans = [plan]
    app._render_plans()
    app.detail_plan = plan

    main_thread = threading.current_thread().name
    t0 = time.time()
    app._set_naming_source(plan, "douban")
    elapsed = time.time() - t0
    print("点击到返回耗时: %.3fs" % elapsed)
    # 主线程必须立即返回（远小于 1.2s 的网络延迟）
    assert elapsed < 0.8, elapsed
    assert plan.name_source == "douban"

    # 等后台重建完成
    deadline = time.time() + 10
    while time.time() < deadline and not app.meta.calls:
        app.update()
        time.sleep(0.02)
    while time.time() < deadline and app.busy:
        app.update()
        time.sleep(0.02)
    print("后台调用次数:", app.meta.calls, "| 线程:", set(app.meta.threads))
    assert app.meta.calls >= 1
    assert main_thread not in app.meta.threads, "联网必须在后台线程"
    assert not app.busy, "后台重建结束后应解除忙碌状态"

    app.destroy()
    print("REBUILD IN BACKGROUND OK")


if __name__ == "__main__":
    main()
