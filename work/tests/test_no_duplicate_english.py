# -*- coding: utf-8 -*-
"""中文完整名称自带英文时，不得再拼一遍来源名。

用户说明：「中文完整名称就是带英文，国外原名也一致，不是错误名称」。
所以「Thunderbolt Fantasy 東离剑游记」本身是正确的主标题，
来源名段（Thunderbolt Fantasy 東離劍遊紀）与它只是繁简差异，
不能重复追加，否则会出现
  Thunderbolt.Fantasy.東离剑游记.Thunderbolt.Fantasy.東離劍遊紀.S01E01
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class _MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0",
                             name="東离剑游记", is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = True
        self.root_season = None


def build(title, seg="tmdb"):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(name_segment_source=seg))
    match = MatchResult(title_zh=title, series_title=title, year=2016,
                        confidence=0.93, tmdb_id="67345")
    tm = Candidate(source="tmdb",
                   title="Thunderbolt Fantasy 東离剑游记",
                   original_title="Thunderbolt Fantasy 東離劍遊紀",
                   year=2016, sid="67345", kind="tv")
    tm.extra = {}
    match.tmdb = tm
    match.source_refs = {"tmdb": {"id": "67345",
                                  "title": "Thunderbolt Fantasy 東离剑游记",
                                  "year": 2016}}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name=title,
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw=title, title=title, season=1),
                    match=match, title=title, year=2016, category="tv")
    v = P115Item(fid="v1", parent_id="root",
                 name="東离剑游记1 Thunderbolt Fantasy S1E01.m2ts",
                 is_dir=False, size=10)
    plan.context = {"mr": _MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="東离剑游记", season=1,
                             episode=1),
        "folder_season": 1, "container": None})()]}
    o.rebuild(plan)
    ep = [x.new_name for x in plan.ops if x.role == "episode"]
    folder = [x.new_name for x in plan.ops if x.role == "show"]
    return (ep[0] if ep else ""), (folder[0] if folder else "")


def test_no_duplicate_when_title_has_english():
    ep, folder = build("Thunderbolt Fantasy 東离剑游记")
    print("剧集:", ep)
    print("文件夹:", folder)
    assert ep.count("Thunderbolt") == 1, ep
    assert folder.count("Thunderbolt") == 1, folder


def test_source_added_when_title_pure_cjk():
    ep, folder = build("東离剑游记")
    print("剧集:", ep)
    print("文件夹:", folder)
    # 纯中文标题时，来源名正常追加一次
    assert ep.count("Thunderbolt") == 1, ep
    assert folder.count("Thunderbolt") == 1, folder


def test_none_means_no_english():
    ep, folder = build("東离剑游记", seg="none")
    print("剧集:", ep)
    print("文件夹:", folder)
    assert "Thunderbolt" not in ep, ep
    assert "Thunderbolt" not in folder, folder


def main():
    test_no_duplicate_when_title_has_english()
    test_source_added_when_title_pure_cjk()
    test_none_means_no_english()
    print("\nNO DUPLICATE ENGLISH OK")


if __name__ == "__main__":
    main()
