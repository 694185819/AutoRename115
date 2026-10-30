# -*- coding: utf-8 -*-
"""命名规则定好什么，文件夹和文件名都要跟着变。

用户诉求：IMDb / TMDB 哪个英文名更准就选哪个，但选了不生效；
分集副标题选 TMDB 也「不生效」（其实生效了，只是文件夹没变）。

修的问题：
  1. 日番分类下（即使选了「不使用」）文件名不走 _name_segment，
     来源名下拉对它无效
  2. 文件夹名的英文段固定用 _english_title，不跟「主名称」下拉
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="青云志",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def build(seg, category="cn_anime", jp="none"):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    opts = NamingOptions(name_segment_source=seg, jp_folder_style=jp)
    match = MatchResult(title_zh="青云志", series_title="青云志",
                        year=2016, confidence=1.0, tmdb_id="67814",
                        series_imdb_id="tt6378944")
    im = Candidate(source="imdb", title="The Legend of Chusen",
                   original_title="", year=2016, sid="tt6378944",
                   kind="tv")
    im.extra = {}
    match.imdb = im
    match.source_refs = {"imdb": {"id": "tt6378944",
                                  "title": "The Legend of Chusen",
                                  "year": 2016}}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="青云志",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="青云志", title="青云志", season=2),
                    match=match, title="青云志", year=2016,
                    category=category, series_imdb_id="tt6378944")
    v = P115Item(fid="v1", parent_id="root",
                 name="青云志.The.Legend.of.Chusen.S02E01.2160p.mkv",
                 is_dir=False, size=10)
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="青云志", season=2,
                             episode=1),
        "folder_season": None, "container": None})()],
        "imdb_id": "tt6378944"}
    Planner(m, opts).rebuild(plan)
    eps = [x.new_name for x in plan.ops if x.role == "episode"]
    folder = [x.new_name for x in plan.ops if x.role == "show"]
    return (eps[0] if eps else ""), (folder[0] if folder else "")


def test_folder_follows_dropdown():
    """文件夹里的英文段跟随「主名称」下拉。"""
    ep_none, folder_none = build("none")
    ep_imdb, folder_imdb = build("imdb")
    print("none →", folder_none)
    print("imdb →", folder_imdb)
    assert "The Legend" not in folder_none, folder_none
    assert "The Legend" in folder_imdb, folder_imdb


def test_episode_follows_dropdown():
    """剧集文件名的来源段同样跟随。"""
    ep_none, _ = build("none")
    ep_imdb, _ = build("imdb")
    assert ep_none == "青云志.S02E01.mkv", ep_none
    assert "The.Legend.of.Chusen" in ep_imdb, ep_imdb


def test_jp_none_uses_normal_rule():
    """日番选「不使用」时，剧集名走普通规则（含来源段）。"""
    for cat in ("cn_anime", "jp_anime", "tv"):
        ep_none, f_none = build("none", category=cat)
        ep_imdb, f_imdb = build("imdb", category=cat)
        assert ep_none == "青云志.S02E01.mkv", (cat, ep_none)
        assert "The.Legend" in ep_imdb, (cat, ep_imdb)
        assert "The Legend" not in f_none, (cat, f_none)
        assert "The Legend" in f_imdb, (cat, f_imdb)


def main():
    test_folder_follows_dropdown()
    test_episode_follows_dropdown()
    test_jp_none_uses_normal_rule()
    print("NAMING RULE DRIVES EVERYTHING OK")


if __name__ == "__main__":
    main()
