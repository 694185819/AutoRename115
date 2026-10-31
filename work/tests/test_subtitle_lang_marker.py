# -*- coding: utf-8 -*-
"""简日/繁日字幕必须保留语言标记，不能改成同名而互相覆盖。

用户场景：
  [..] Ame to Kimi to [01][Web].JPSC.sup   （简日）
  [..] Ame to Kimi to [01][Web].JPTC.sup   （繁日）
以前两者都被改成「雨与君 S01E01.下雨天.sup」，重名会丢文件。

根因：_lang_suffix 的正则要求 jp 后面紧跟分隔符或结束，
识别不出 JPSC / JPTC 这种「jp+sc/tc」复合标记。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import P115Item
from app.parser import parse_name
from app.planner import FileEntry, MediaRoot, NamingOptions, Planner


class Client:
    def list_dir(self, fid, **k):
        return []

    def list_all(self, fid, **k):
        return []


NAMES = [
    "[Nekomoe kissaten] Ame to Kimi to [01][Web].mkv",
    "[Nekomoe kissaten] Ame to Kimi to [02][Web].mkv",
    "[Nekomoe kissaten] Ame to Kimi to [01][Web].JPSC.sup",
    "[Nekomoe kissaten] Ame to Kimi to [01][Web].JPTC.sup",
    "[Nekomoe kissaten] Ame to Kimi to [02][Web].JPSC.sup",
    "[Nekomoe kissaten] Ame to Kimi to [02][Web].JPTC.sup",
]


def test_lang_suffix():
    """各种语言标记都要能取到。"""
    cases = [
        ("Show [01].JPSC", "JPSC"),
        ("Show [01].JPTC", "JPTC"),
        ("Show.S01E01.chs", "chs"),
        ("Show.S01E01.cht", "cht"),
        ("Show.S01E01.简日", "简日"),
        ("Show.S01E01.繁日", "繁日"),
        ("Show.S01E01.zh-Hans", "zh-Hans"),
        ("Show.S01E01.jpn", "jpn"),
        ("Show.S01E01", ""),
    ]
    for stem, want in cases:
        got = Planner._lang_suffix(stem)
        print(f"{stem[-24:]:26s} → {got!r}")
        assert got == want, (stem, got, want)


def test_no_collision():
    """同一集的简日/繁日字幕不能改成同名。"""
    root = P115Item(fid="root", parent_id="0", name="雨与君", is_dir=True)
    root.ancestors = ["动画", "日番"]
    entries = []
    for i, n in enumerate(NAMES, 1):
        it = P115Item(fid=f"f{i}", parent_id="root", name=n,
                      is_dir=False)
        it.size = 1
        entries.append(FileEntry(item=it, parsed=parse_name(n)))
    mr = MediaRoot(item=root, entries=entries, season_dirs=[],
                   part_dirs=[], subs_dirs=[], nfo_files=[],
                   unsupported="", is_season_root=False, root_season=None)

    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(jp_folder_style="bdremux",
                                 rename_subtitles=True))
    plans = o._build_plans(Client(), mr)
    assert plans, "没有生成任务"
    for plan in plans:
        subs = [op.new_name for op in plan.ops if op.role == "subtitle"]
        dup = {n for n in subs if subs.count(n) > 1}
        assert not dup, f"字幕重名会覆盖文件：{dup}"
        if subs:
            # 每集两种语言都在
            assert any("JPSC" in n for n in subs), subs
            assert any("JPTC" in n for n in subs), subs
            print("字幕名:", subs)


def test_subtitle_name_keeps_title():
    """字幕名 = 视频名（去规格）+ 简洁语言标记（简日/繁日…）。"""
    got = Planner._subtitle_new_name("雨と君と S01E01.下雨天 [1080p HEVC]",
                                     "x [01][Web].JPSC", ".sup")
    print("生成:", got)
    assert got == "雨と君と S01E01.下雨天.简日.sup", got
    assert "1080p" not in got, got
    assert "Web" not in got, got


def test_simple_lang_labels():
    """语言标记统一成简洁中文。"""
    cases = [
        ("x.JPSC", "简日"), ("x.JPTC", "繁日"),
        ("x.简日", "简日"), ("x.繁日", "繁日"),
        ("x.chs", "简体"), ("x.cht", "繁体"),
        ("x.sc", "简体"), ("x.zh-Hans", "简体"),
        ("x.JPN", "日语"), ("x", ""),
    ]
    for stem, want in cases:
        got = Planner._simple_lang_label(stem)
        print(f"  {stem:12s} → {got!r}")
        assert got == want, (stem, got, want)


def main():
    test_lang_suffix()
    test_no_collision()
    test_subtitle_name_keeps_title()
    test_simple_lang_labels()
    print("\nSUBTITLE LANG MARKER OK")


if __name__ == "__main__":
    main()
