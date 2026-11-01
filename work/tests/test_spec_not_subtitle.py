# -*- coding: utf-8 -*-
"""规格/语言标记不能被当成副标题；目录里的 DIY中字 不能重复进名字。

用户场景：
  Kengan Ashura S01E01-[1080p][BDRemux][cht+chs+jpn][788-Remux].mkv
  目录 [BD-REMUX]拳愿阿修罗「ケンガンアシュラ」DIY中字 [JP][7^ACG@OurBits]

以前：
  视频 → ケンガンアシュラ S01E01.1080p[BDRemux][cht+chs+jpn][788-Remux].mkv
  目录 → [BD-REMUX]拳愿阿修罗 ケンガンアシュラ 拳愿阿修罗「ケンガンアシュラ」
          DIY中字 (2019)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import P115Item
from app.parser import parse_name
from app.planner import FileEntry, NamingOptions, Planner


def _planner():
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    return Planner(m, NamingOptions(jp_folder_style="bdremux"))


def test_spec_not_subtitle():
    """方括号里的规格/语言标记不能变成副标题。"""
    o = _planner()
    cases = [
        "Kengan Ashura S01E01-[1080p][BDRemux][cht+chs+jpn]"
        "[788-Remux].mkv",
        "Show S01E01.1080p.WEB-DL.mkv",
        "Show S01E01.2160p.WEB-DL.H265.mkv",
        "Show S01E01-[chs].mkv",
    ]
    for n in cases:
        it = P115Item(fid="v", parent_id="r", name=n, is_dir=False)
        e = FileEntry(item=it, parsed=parse_name(n))
        got = o._episode_subtitle(e)
        print(f"{n[:50]:52s} → {got!r}")
        assert got == "", (n, got)


def test_real_subtitle_kept():
    """真正的副标题必须保留。"""
    o = _planner()
    cases = [
        ("Show S01E01.第一集.mkv", "第一集"),
        ("Show S01E01.沙漠意大利面大作戰.mkv", "沙漠意大利面大作戰"),
    ]
    for n, want in cases:
        it = P115Item(fid="v", parent_id="r", name=n, is_dir=False)
        e = FileEntry(item=it, parsed=parse_name(n))
        got = o._episode_subtitle(e)
        print(f"{n[:44]:46s} → {got!r}")
        assert got == want, (n, got, want)


def test_folder_no_duplicate_title():
    """目录里的「中文名「日文名」DIY中字」不能重复成两段中文名。"""
    from app.models import ParsedName, PlanItem

    o = _planner()
    plan = PlanItem(item=P115Item(fid="r", parent_id="0", name="x",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="x", title="拳愿阿修罗 ケンガンアシュラ",
                                      season=1),
                    title="拳愿阿修罗 ケンガンアシュラ", year=2019,
                    category="jp_anime")
    local = {"jp": "拳愿阿修罗「ケンガンアシュラ」DIY中字"}
    got = o._local_second_title(plan, local)
    print("第二语言名:", repr(got))
    assert "拳愿阿修罗" not in got, got
    assert "DIY" not in got, got


def main():
    test_spec_not_subtitle()
    test_real_subtitle_kept()
    test_folder_no_duplicate_title()
    print("\nSPEC NOT SUBTITLE OK")


if __name__ == "__main__":
    main()
