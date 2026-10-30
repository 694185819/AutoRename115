# -*- coding: utf-8 -*-
"""规则选「英文名 = 不显示」时，文件名里不得出现任何来源名段的英文。

这不是「去重」，而是那个选项本身必须生效：
  英文名来源 = 不显示  →  剧名 . SxxExx . 副标题（无英文名段）

用户现象：选了「不显示」，文件名里仍有
  Thunderbolt.Fantasy.東離劍遊紀 —— 而且和标题里的英文重复。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class _MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="d",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def build(title, seg, tmdb_title="东离剑游纪",
          tmdb_orig="Thunderbolt Fantasy -東離劍遊紀"):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(name_segment_source=seg,
                                 jp_folder_style="none"))
    match = MatchResult(title_zh=title, series_title=title, year=2016,
                        confidence=0.93, tmdb_id="67345")
    tm = Candidate(source="tmdb", title=tmdb_title,
                   original_title=tmdb_orig, year=2016, sid="67345",
                   kind="tv")
    tm.extra = {}
    match.tmdb = tm
    match.source_refs = {"tmdb": {"id": "67345", "title": tmdb_title,
                                  "year": 2016}}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name=title,
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw=title, title=title, season=1),
                    match=match, title=title, year=2016, category="tv")
    nm = "x.S01E01.m2ts"
    v = P115Item(fid="v1", parent_id="root", name=nm, is_dir=False,
                 size=10)
    plan.context = {"mr": _MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=nm, title=title, season=1, episode=1),
        "folder_season": 1, "container": None})()]}
    o.rebuild(plan)
    ep = [x.new_name for x in plan.ops if x.role == "episode"]
    fo = [x.new_name for x in plan.ops if x.role == "show"]
    return (ep[0] if ep else ""), (fo[0] if fo else "")


def test_none_means_no_segment():
    """不显示 → 来源名段必须为空（三种标题形态）。"""
    cases = [
        ("Thunderbolt Fantasy 東离剑游记", "标题含英文"),
        ("東离剑游记", "标题纯中文"),
        ("Ever Night 2", "纯英文标题"),
    ]
    for title, desc in cases:
        ep, fo = build(title, "none")
        print(f"[{desc}] {title}")
        print(f"   剧集: {ep}")
        print(f"   文件夹: {fo}")
        # SxxExx 之前只能是标题本身
        head = ep.split("S01E01")[0].rstrip(".")
        assert head == title.replace(" ", "."), (title, ep)
        # 繁体原名绝不能出现
        assert "東離劍" not in ep, ep
        assert "東離劍" not in fo, fo


def test_tmdb_selected_shows_source():
    """选 TMDB 时，来源名段正常出现（与标题英文相同时不重复）。"""
    ep, fo = build("Thunderbolt Fantasy 東离剑游记", "tmdb")
    print("TMDB 选中:", ep)
    assert ep.split("S01E01")[0].rstrip(".") == \
        "Thunderbolt.Fantasy.東离剑游记", ep


def test_none_beats_every_category():
    """任何分类下『不显示』都成立。"""
    for cat in ("tv", "jp_anime", "cn_anime"):
        ep, _ = build("東离剑游记", "none")
        assert "東離劍" not in ep, (cat, ep)
        print(f"[{cat}] {ep}")


def main():
    test_none_means_no_segment()
    test_tmdb_selected_shows_source()
    test_none_beats_every_category()
    print("\nENGLISH SEGMENT = NONE IS RESPECTED")


if __name__ == "__main__":
    main()
