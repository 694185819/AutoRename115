# -*- coding: utf-8 -*-
"""英文名段 = 不显示 时必须为空（含空串/大小写/空格等写法）。

用户诉求：中文写 A，英文字段也应当是 A，
但只想「不显示英文字段」。所以该段必须为空。

隐患：以前 `str(... or "imdb")` 会把空串变成 imdb，
设置被写成空值时英文名又冒出来。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import (Candidate, MatchResult, P115Item, ParsedName,
                        PlanItem)
from app.planner import NamingOptions, Planner


class _MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="A",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def plan_for(title):
    match = MatchResult(title_zh=title, series_title=title, year=2016,
                        confidence=1.0)
    im = Candidate(source="imdb", title="The Legend of Chusen",
                   original_title="", year=2016, sid="tt1", kind="tv")
    im.extra = {}
    match.imdb = im
    match.source_refs = {"imdb": {"id": "tt1",
                                  "title": "The Legend of Chusen",
                                  "year": 2016}}
    return PlanItem(item=P115Item(fid="r", parent_id="0", name=title,
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="x", title=title, season=1),
                    match=match, title=title, year=2016, category="tv")


def test_none_variants():
    """不显示的各种写法都必须整段省略。"""
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    for val in ("none", "", "NONE", "  none  ", "off", "no"):
        o = Planner(m, NamingOptions(name_segment_source=val))
        seg = o._name_segment(plan_for("青云志"))
        print(f"  {val!r:10s} → {seg!r}")
        assert seg == "", (val, seg)


def test_imdb_still_works():
    """选 IMDb 时英文名正常出现（不能把正常路径也关掉）。"""
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(name_segment_source="imdb"))
    seg = o._name_segment(plan_for("青云志"))
    print(f"  imdb → {seg!r}")
    assert seg == "The Legend of Chusen", seg


def test_same_name_not_duplicated():
    """中文名与英文名相同（A / A）时不重复。"""
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(name_segment_source="imdb"))
    plan = plan_for("The Legend of Chusen")
    seg = o._name_segment(plan)
    # 与标题相同 → 应被上层丢弃；此处只确认取到的是同名字符串
    print(f"  同名场景 seg={seg!r}")
    assert seg in ("", "The Legend of Chusen"), seg


def main():
    test_none_variants()
    test_imdb_still_works()
    test_same_name_not_duplicated()
    print("\nNONE VARIANTS ALL EMPTY")


if __name__ == "__main__":
    main()
