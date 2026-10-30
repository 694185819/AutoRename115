# -*- coding: utf-8 -*-
"""命名规则两个下拉必须真的生效：来源名、副标题各管一段。

用户反馈：把「副标题」选成任意值都没反应；用来源命名时
中文主名称会被换成纯英文。根因有两处：
  1. naming_ref 只读 plan.name_source（从未赋值），下拉被忽略；
  2. _apply_naming_source 把 plan.title 换成了来源标题，
     覆盖了中文主名称。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner

NAMES = {
    "tmdb": ("Ever Night", "长夜", "83612"),
    "douban": ("Ever Night", "将夜·永夜", "27002048"),
    "bangumi": ("将夜", "将夜 第二季", "254656"),
    "imdb": ("Ever Night", "", "tt9193596"),
}
EPS = {
    "tmdb": {2: "TMDB二集"},
    "douban": {2: "豆瓣二集"},
    "bangumi": {2: "BGM二集"},
    "imdb": {2: "IMDB Two"},
}


class MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="将夜",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


class FakeMeta(MetadataClient):
    def __init__(self):
        super().__init__("", use_bangumi=False)
        self.delays = {k: 0.0 for k in self.delays}

    def season_episode_titles(self, tmdb_id, season):
        return dict(EPS["tmdb"])

    def source_episode_titles(self, source, sid, season):
        return dict(EPS.get(source, {}))


def build(sub, seg):
    m = FakeMeta()
    opts = NamingOptions(subtitle_source=sub, name_segment_source=seg)
    match = MatchResult(title_zh="将夜", series_title="将夜", year=2018,
                        country="cn", confidence=1.0)
    for src, (title, orig, sid) in NAMES.items():
        c = Candidate(source=src, title=title, original_title=orig,
                      year=2018, sid=sid, kind="tv")
        c.extra = {}
        c.score = 1.0
        setattr(match, src, c)
    match.source_refs = {k: {"id": v[2], "title": v[0], "year": 2018}
                         for k, v in NAMES.items()}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="将夜",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="将夜", title="将夜", season=2),
                    match=match, title="将夜", year=2018, category="cn_anime")
    v = P115Item(fid="v2", parent_id="root",
                 name="将夜II.Ever.Night.S02E02.2160p.mkv",
                 is_dir=False, size=10)
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="将夜", season=2, episode=2),
        "folder_season": None, "container": None})()]}
    Planner(m, opts).rebuild(plan)
    eps = [o.new_name for o in plan.ops if o.role == "episode"]
    return eps[0] if eps else "", plan


def test_main_title_fixed():
    """无论选哪个来源，中文主名称都必须是「将夜」。"""
    for seg in ("none", "tmdb", "douban", "bangumi", "imdb"):
        name, _plan = build("auto", seg)
        assert name.startswith("将夜"), f"{seg}: {name}"


def test_name_segment_follows_source():
    """来源名那一段跟着下拉走。"""
    name_none, _ = build("auto", "none")
    assert "Ever" not in name_none and "将夜.S02E02" in name_none, name_none

    name_tmdb, _ = build("auto", "tmdb")
    assert "Ever.Night" in name_tmdb, name_tmdb


def test_subtitle_source_effective():
    """副标题来源切换必须改变文件名。"""
    a, _ = build("douban", "tmdb")
    b, _ = build("bangumi", "tmdb")
    c, _ = build("imdb", "tmdb")
    print("douban:", a)
    print("bangumi:", b)
    print("imdb:", c)
    assert "豆瓣二集" in a, a
    assert "BGM二集" in b, b
    assert "IMDB" in c, c
    assert len({a, b, c}) == 3, "三个副标题来源应产生三种结果"


def test_keyword_means_local_only():
    """选「只取原文件名里的标题」时不联网补副标题。"""
    name, _ = build("keyword", "tmdb")
    assert "二集" not in name, name


def main():
    test_main_title_fixed()
    test_name_segment_follows_source()
    test_subtitle_source_effective()
    test_keyword_means_local_only()
    print("NAMING SOURCE EFFECT OK")


if __name__ == "__main__":
    main()
