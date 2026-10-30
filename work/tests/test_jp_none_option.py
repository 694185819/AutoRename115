# -*- coding: utf-8 -*-
"""日番文件夹格式：新增「不使用」时，日番按普通剧集规则命名。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.naming_panel import JP_FOLDER_OPTIONS
from app.planner import NamingOptions, Planner


class MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0",
                             name="[Group] 葬送的芙莉莲", is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def build(style):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    opts = NamingOptions(jp_folder_style=style)
    match = MatchResult(title_zh="葬送的芙莉莲", series_title="葬送的芙莉莲",
                        year=2023, country="jp", animation=True,
                        confidence=1.0, title_original="葬送のフリーレン")
    for src, title, orig, sid in (
            ("tmdb", "Frieren: Beyond Journey's End", "葬送のフリーレン",
             "209867"),
            ("imdb", "Frieren: Beyond Journey's End", "", "tt22248376")):
        c = Candidate(source=src, title=title, original_title=orig,
                      year=2023, sid=sid, kind="tv")
        c.extra = {}
        c.score = 1.0
        setattr(match, src, c)
    match.source_refs = {
        "tmdb": {"id": "209867", "title": "Frieren", "year": 2023},
        "bangumi": {"id": "400602", "title": "葬送的芙莉莲", "year": 2023},
    }
    plan = PlanItem(item=P115Item(fid="root", parent_id="0",
                                  name="葬送的芙莉莲", is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="葬送的芙莉莲", title="葬送的芙莉莲",
                                      season=1),
                    match=match, title="葬送的芙莉莲", year=2023,
                    category="jp_anime")
    videos = [P115Item(fid=f"v{i}", parent_id="root",
                       name=f"葬送的芙莉莲 - 0{i}.mkv", is_dir=False, size=10)
              for i in (1, 2)]
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="葬送的芙莉莲", season=1,
                             episode=i),
        "folder_season": None, "container": None})()
        for i, v in enumerate(videos, 1)]}
    Planner(m, opts).rebuild(plan)
    folder = [o.new_name for o in plan.ops if o.role == "show"]
    eps = [o.new_name for o in plan.ops if o.role == "episode"]
    return (folder[0] if folder else ""), eps


def test_option_exists():
    """下拉里必须有「不使用」这一项。"""
    assert "none" in JP_FOLDER_OPTIONS, JP_FOLDER_OPTIONS
    assert "不使用" in JP_FOLDER_OPTIONS["none"]


def test_none_uses_normal_rule():
    """选「不使用」时：文件夹带英文名、不加 [BD-REMUX]、剧集用中文名。"""
    folder, eps = build("none")
    print("不使用 →", folder, eps)
    assert "[BD-REMUX]" not in folder, folder
    assert "Frieren" in folder, f"应保留英文名（普通规则）：{folder}"
    assert eps and eps[0].startswith("葬送的芙莉莲"), eps


def test_bdremux_still_works():
    """其他选项行为不变：BD-REMUX 加前缀、剧集用日文名。"""
    folder, eps = build("bdremux")
    print("BD-REMUX →", folder, eps)
    assert folder.startswith("[BD-REMUX]"), folder
    assert eps and eps[0].startswith("葬送のフリーレン"), eps


def main():
    test_option_exists()
    test_none_uses_normal_rule()
    test_bdremux_still_works()
    print("JP NONE OPTION OK")


if __name__ == "__main__":
    main()
