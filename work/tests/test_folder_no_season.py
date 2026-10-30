# -*- coding: utf-8 -*-
"""文件夹名不再包含 Sxx。

用户要求：文件夹统一为「剧名 (年份) [ID]」，
即使原目录名写着 S01（如「大理寺少卿游 White Cat Legend S01」），
也要去掉，保证整部剧命名规范一致。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class _MR:
    def __init__(self, name, is_season_root=False):
        self.item = P115Item(fid="root", parent_id="0", name=name,
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = is_season_root
        self.root_season = None


def build(folder, season=1, is_season_root=False, seasons=None):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(name_segment_source="none"))
    match = MatchResult(title_zh="大奉打更人", series_title="大奉打更人",
                        year=2025, confidence=1.0, tmdb_id="233912")
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name=folder,
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="大奉打更人", title="大奉打更人",
                                      season=season),
                    match=match, title="大奉打更人", year=2025,
                    category="cn_anime", seasons=seasons or [season])
    v = P115Item(fid="v1", parent_id="root",
                 name=f"大奉打更人.S{season:02d}E01.mkv", is_dir=False,
                 size=10)
    plan.context = {"mr": _MR(folder, is_season_root),
                    "entries": [type("E", (), {
                        "item": v, "is_video": True,
                        "parsed": ParsedName(raw=v.name,
                                             title="大奉打更人",
                                             season=season, episode=1),
                        "folder_season": None, "container": None})()]}
    o.rebuild(plan)
    out = [x.new_name for x in plan.ops if x.role == "show"]
    return out[0] if out else ""


def main() -> None:
    cases = [
        "大奉打更人",
        "大奉打更人 S01",
        "大奉打更人 第1季",
        "大奉打更人 S02",
        "大奉打更人 Season 2",
        "大理寺少卿游 White Cat Legend S01",
        "少年歌行 The Blood of Youth S01",
        "师兄太稳健 Pull Strings S01 (2026)",
    ]
    bad = []
    for folder in cases:
        got = build(folder)
        print(f"{folder[:34]:36s} → {got}")
        # 文件夹里不能出现独立的 S01 / S02 标记
        import re
        if re.search(r"(?:^|[\s._])S\d{1,2}(?=$|[\s._(])", got):
            bad.append((folder, got))
        assert "大奉" in got or "大理寺" in got or "少年歌行" in got \
            or "师兄" in got, got
    assert not bad, bad
    print("\nFOLDER WITHOUT SEASON MARKER OK")


if __name__ == "__main__":
    main()
