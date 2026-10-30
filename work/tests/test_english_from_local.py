# -*- coding: utf-8 -*-
"""来源名不能变成 imdbid / tmdbid 之类的编号标记。

用户截图：目录名「将夜 (2018)[imdbid-tt9193596]」，IMDb 条目只有
编号没有标题，结果文件名变成 将夜.imdbid.S01E01…。
根因：_english_from_local 从目录名里抽英文段时，
把 [imdbid-tt…] 里的 imdbid 当成了片名。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


class MR:
    def __init__(self, name):
        self.item = P115Item(fid="root", parent_id="0", name=name,
                             is_dir=True)


def local_en(folder, fn):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="将夜",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="将夜", title="将夜", season=1),
                    match=MatchResult(title_zh="将夜", year=2018,
                                      confidence=1.0),
                    title="将夜", year=2018, category="cn_anime")
    v = P115Item(fid="v1", parent_id="root", name=fn, is_dir=False, size=10)
    plan.context = {"mr": MR(folder), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=fn, title="将夜", season=1, episode=1),
        "folder_season": None, "container": None})()]}
    return Planner(m, NamingOptions())._english_from_local(plan)


def test_no_id_markers():
    """目录里的 [imdbid-tt…] / [tmdbid-…] 不能当英文名。"""
    for folder in ("将夜 (2018)[imdbid-tt9193596]",
                   "将夜 [tmdbid-83612]",
                   "将夜 (2018)[tmdbid-83612]"):
        got = local_en(folder, "将夜.S01E01.mkv")
        assert got == "", f"{folder} → {got!r}"
        assert "imdbid" not in got.lower(), got
        assert "tmdbid" not in got.lower(), got


def test_release_group_not_title():
    """[Group] 这类字幕组标签不能当英文名。"""
    got = local_en("将夜", "[Group] 将夜 - 01 [1080p].mkv")
    assert got == "", got


def test_real_english_extracted():
    """文件名里的 Ever Night 仍要能取出来。"""
    got = local_en(
        "将夜",
        "将夜II.Ever.Night.S02E01.2160p.WEB-DL.H264.AAC-FLTTH.mkv")
    assert got == "Ever Night", got


def test_folder_english_works():
    """目录本身就是英文名时可用。"""
    got = local_en("Ever Night", "将夜.S01E01.mkv")
    assert got == "Ever Night", got


def test_specs_not_picked():
    """规格词不能当英文名。"""
    got = local_en("将夜", "将夜.S01E01.2160p.WEB-DL.H264.AAC.mkv")
    assert got == "", got


def main():
    test_no_id_markers()
    test_release_group_not_title()
    test_real_english_extracted()
    test_folder_english_works()
    test_specs_not_picked()
    print("ENGLISH FROM LOCAL OK")


if __name__ == "__main__":
    main()
