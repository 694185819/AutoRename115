# -*- coding: utf-8 -*-
"""IMDb 只给拼音时，来源名要用文件名里的真英文名。

用户截图：目录「万春逗笑社 4K Web」，IMDb 条目 tt33318704 的标题是
拼音 Wan Chun Dou Xiao She，而视频文件名里写着
Amusing.Club.of.Wanchun —— 文件夹名却用了拼音。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner, _is_pinyin_of

FN = ("[万春逗笑社]Amusing.Club.of.Wanchun.2024.S01E01.2160p."
      "WEB-DL.HEVC.DDP.2Audios-QHstudI.mp4")


class MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="万春逗笑社 4K Web",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def build(imdb_title, seg="imdb"):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(name_segment_source=seg))
    match = MatchResult(title_zh="万春逗笑社", series_title="万春逗笑社",
                        year=2024, confidence=1.0)
    im = Candidate(source="imdb", title=imdb_title, original_title="",
                   year=2024, sid="tt33318704", kind="tv")
    im.extra = {}
    match.imdb = im
    match.source_refs = {"imdb": {"id": "tt33318704", "title": imdb_title,
                                  "year": 2024}}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0",
                                  name="万春逗笑社 4K Web", is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="万春逗笑社", title="万春逗笑社",
                                      season=1),
                    match=match, title="万春逗笑社", year=2024,
                    category="cn_anime")
    v = P115Item(fid="v1", parent_id="root", name=FN, is_dir=False, size=10)
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="万春逗笑社", season=1,
                             episode=1),
        "folder_season": None, "container": None})()]}
    o.rebuild(plan)
    folder = [x.new_name for x in plan.ops if x.role == "show"]
    eps = [x.new_name for x in plan.ops if x.role == "episode"]
    return (folder[0] if folder else ""), (eps[0] if eps else "")


def test_pinyin_detection():
    """拼音能被识别，真英文名不会误判。"""
    cases = [
        ("Ever Night", "将夜", False),
        ("Ling Cage", "灵笼", False),
        ("Frieren", "葬送的芙莉莲", False),
        ("Joy of Life", "庆余年", False),
        ("Amusing Club of Wanchun", "万春逗笑社", False),
        ("Wan Chun Dou Xiao She", "万春逗笑社", True),
        ("Jiang Ye", "将夜", True),
        ("Qing Yu Nian", "庆余年", True),
    ]
    bad = []
    for en, cn, want in cases:
        got = _is_pinyin_of(en, cn)
        if got != want:
            bad.append(f"{en!r} vs {cn!r} → {got}，期望 {want}")
    assert not bad, "\n".join(bad)


def test_folder_prefers_real_english():
    """IMDb 是拼音时，文件夹名用文件名里的真英文名。"""
    folder, _ep = build("Wan Chun Dou Xiao She")
    print("文件夹:", folder)
    assert "Amusing Club of Wanchun" in folder, folder
    assert "Wan Chun" not in folder, folder


def test_folder_keeps_real_english():
    """IMDb 本身就是真英文名时照用。"""
    folder, _ep = build("Amusing Club of Wanchun")
    print("文件夹:", folder)
    assert "Amusing Club of Wanchun" in folder, folder


def test_episode_also_real_english():
    """剧集名的来源段同样不能是拼音。"""
    _folder, ep = build("Wan Chun Dou Xiao She")
    print("剧集:", ep)
    assert "Amusing.Club.of.Wanchun" in ep, ep
    assert "Wan.Chun" not in ep, ep


def main():
    test_pinyin_detection()
    test_folder_prefers_real_english()
    test_folder_keeps_real_english()
    test_episode_also_real_english()
    print("PINYIN FALLBACK OK")


if __name__ == "__main__":
    main()
