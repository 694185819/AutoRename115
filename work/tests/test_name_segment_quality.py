# -*- coding: utf-8 -*-
"""来源名与中文主名称的两个缺陷：

1. 选「豆瓣」时出现两段中文「将夜.将夜.第二季」
   （豆瓣条目名带季号后缀，没剥离就整段塞进来源名）
2. 没有 IMDb/TMDB 数据时，来源名整段消失
   （文件名里明明有 Ever Night，却不去取）
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class MR:
    def __init__(self, name="将夜"):
        self.item = P115Item(fid="root", parent_id="0", name=name,
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def build(seg, with_imdb=True,
          fn="将夜II.Ever.Night.S02E01.2160p.WEB-DL.H264.AAC-FLTTH.mkv"):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    opts = NamingOptions(name_segment_source=seg)
    match = MatchResult(title_zh="将夜", series_title="将夜", year=2018,
                        country="cn", confidence=0.9)
    db = Candidate(source="douban", title="将夜 第二季",
                   original_title="将夜 第二季", year=2028,
                   sid="28683560", kind="tv")
    db.extra = {}
    match.douban = db
    if with_imdb:
        im = Candidate(source="imdb", title="Ever Night", original_title="",
                       year=2018, sid="tt9193596", kind="tv")
        im.extra = {"aliases": ["Ever Night"]}
        match.imdb = im
    match.source_refs = {"douban": {"id": "28683560",
                                    "title": "将夜 第二季", "year": 2028}}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="将夜",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="将夜", title="将夜", season=2),
                    match=match, title="将夜", year=2018, category="cn_anime")
    v = P115Item(fid="v1", parent_id="root", name=fn, is_dir=False, size=10)
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="将夜", season=2, episode=1),
        "folder_season": None, "container": None})()]}
    Planner(m, opts).rebuild(plan)
    eps = [o.new_name for o in plan.ops if o.role == "episode"]
    return eps[0] if eps else ""


def test_no_double_chinese():
    """选豆瓣时不能出现「将夜.将夜.第二季」这种重复中文。"""
    for seg in ("none", "local", "imdb", "tmdb", "douban", "bangumi"):
        name = build(seg)
        assert "将夜.将夜" not in name, f"{seg}: {name}"
        assert "第二季" not in name, f"{seg}: {name}"


def test_chinese_title_always_first():
    """中文主名称永远在最前面。"""
    for seg in ("local", "imdb", "douban"):
        name = build(seg)
        assert name.startswith("将夜"), f"{seg}: {name}"


def test_english_segment_present():
    """有 IMDb 时来源名必须是 Ever Night，不能消失。"""
    for seg in ("local", "imdb", "douban"):
        name = build(seg)
        assert "Ever.Night" in name, f"{seg}: {name}"


def test_fallback_from_filename():
    """没有 IMDb 时，从文件名里取 Ever Night 当来源名。"""
    name = build("local", with_imdb=False)
    print("无 IMDb + local →", name)
    assert "Ever.Night" in name, name


def test_none_has_no_segment():
    """选「不显示」时不应出现英文段。"""
    name = build("none")
    assert "Ever" not in name, name


def main():
    test_no_double_chinese()
    test_chinese_title_always_first()
    test_english_segment_present()
    test_fallback_from_filename()
    test_none_has_no_segment()
    print("NAME SEGMENT QUALITY OK")


if __name__ == "__main__":
    main()
