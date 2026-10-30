# -*- coding: utf-8 -*-
"""方案 1：搜索阶段预取，每个接口拿到自己的词句。

用户要求：每个接口都获取到自己对应的词句。
  - 来源名 = IMDb → 用 IMDb 的英文名
  - 副标题 = TMDB → 用 TMDB 的分集名
互不混用。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class _MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="青云志",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def make_plan():
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="青云志",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="青云志", title="青云志", season=2),
                    match=MatchResult(title_zh="青云志",
                                      series_title="青云志", year=2016,
                                      confidence=0.9),
                    title="青云志", year=2016, category="cn_anime")
    v = P115Item(fid="v1", parent_id="root",
                 name="青云志.S02E01.2160p.mkv", is_dir=False, size=10)
    plan.context = {"mr": _MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="青云志", season=2,
                             episode=1),
        "folder_season": None, "container": None})()]}
    return plan


def build(m, plan, seg, sub):
    o = Planner(m, NamingOptions(name_segment_source=seg,
                                 subtitle_source=sub))
    o.rebuild(plan)
    ep = [x.new_name for x in plan.ops if x.role == "episode"]
    folder = [x.new_name for x in plan.ops if x.role == "show"]
    return (ep[0] if ep else ""), (folder[0] if folder else "")


def main() -> None:
    app = App(r"I:\实验\AutoRename115")
    app.withdraw()
    m = app.meta
    m.delays = {k: 0.0 for k in m.delays}
    m._cache = {}
    app.is_demo = True
    app.busy = False
    app._init_meta()
    m = app.meta
    m.delays = {k: 0.0 for k in m.delays}
    m._cache = {}

    plan = make_plan()
    app.plans = [plan]
    app._render_plans()
    app.update()

    imdb = Candidate(source="imdb", title="Noble Aspirations",
                     original_title="", year=2016, sid="tt6284026",
                     kind="tv")
    imdb.extra = {}
    ids = m.resolve_ids(imdb, "series")
    app._apply_manual_candidate(plan, imdb, ids)

    print("=== IMDb 英文名 + TMDB 分集名 ===")
    ep, folder = build(m, plan, "imdb", "tmdb")
    print("  剧集:", ep)
    print("  文件夹:", folder)
    assert "Noble.Aspirations" in ep, ep
    assert "救碧瑶" in ep or len(ep.split("S02E01")[-1].strip(" .mkv")) > 2, ep
    assert "Noble Aspirations" in folder, folder

    print("\n=== 关闭副标题：只剩 IMDb 英文名 ===")
    ep2, _ = build(m, plan, "imdb", "keyword")
    print("  剧集:", ep2)
    assert "Noble.Aspirations" in ep2, ep2
    tail = ep2.split("S02E01")[-1].strip(" .")
    assert tail in ("", "mkv"), ep2

    print("\n=== 不显示来源名：只剩 TMDB 分集名 ===")
    ep3, f3 = build(m, plan, "none", "tmdb")
    print("  剧集:", ep3)
    print("  文件夹:", f3)
    assert "Noble" not in ep3, ep3
    assert "Noble" not in f3, f3

    app.destroy()
    print("\nPREFETCH PER SOURCE OK")


if __name__ == "__main__":
    main()
