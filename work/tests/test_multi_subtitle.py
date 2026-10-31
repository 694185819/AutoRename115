# -*- coding: utf-8 -*-
"""多字幕机制：单份自动、多份交给用户确认。

规则（用户要求）：
  - 某集只有 1 份字幕 → 默认自动重命名
  - 某集有 2 份及以上 → 不自动重命名，登记到 plan.multi_subs，
    由预览窗口提示用户确认
  - 自动识别模式：简繁双语 / 简繁双体 / 三字幕 / 其它
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import P115Item
from app.parser import parse_name
from app.planner import FileEntry, MediaRoot, NamingOptions, Planner


class _Client:
    def list_dir(self, fid, **k):
        return []

    def list_all(self, fid, **k):
        return []


def run(names):
    root = P115Item(fid="root", parent_id="0", name="Show", is_dir=True)
    entries = []
    for i, n in enumerate(names, 1):
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
    plans = o._build_plans(_Client(), mr)
    return plans[0] if plans else None


def test_sub_kind():
    """语言标记分类必须准确。"""
    cases = [
        ("x.JPSC", "jp_s"), ("x.JPTC", "jp_t"),
        ("x.简日", "jp_s"), ("x.繁日", "jp_t"),
        ("x.chs", "zh_s"), ("x.cht", "zh_t"),
        ("x.JPN", "ja_only"), ("x", "unknown"),
    ]
    for stem, want in cases:
        got = Planner._subtitle_kind(stem)
        assert got == want, (stem, got, want)
        print(f"  {stem:10s} → {got}")


def test_single_auto():
    """单份字幕照常自动重命名。"""
    p = run(["Show [01].mkv", "Show [02].mkv",
             "Show [01].chs.sup", "Show [02].chs.sup"])
    subs = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("单份:", subs)
    assert len(subs) == 2, subs
    assert not p.multi_subs, p.multi_subs


def test_multi_not_renamed():
    """同集两份字幕不重命名，只登记。"""
    p = run(["Show [01].mkv", "Show [01].JPSC.sup",
             "Show [01].JPTC.sup"])
    subs = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("多份 已改名:", subs, "| 待确认:", len(p.multi_subs),
          "| 模式:", p.multi_sub_mode)
    assert subs == [], f"多份字幕不该自动改名: {subs}"
    assert len(p.multi_subs) == 2, p.multi_subs
    assert p.multi_sub_mode == "jp_bilingual", p.multi_sub_mode


def test_triple_mode():
    """简日+繁日+纯日语 → triple。"""
    p = run(["Show [01].mkv", "Show [01].JPSC.sup",
             "Show [01].JPTC.sup", "Show [01].JPN.sup"])
    print("三字幕 模式:", p.multi_sub_mode,
          "份数:", len(p.multi_subs))
    assert p.multi_sub_mode == "triple", p.multi_sub_mode
    assert len(p.multi_subs) == 3


def test_zh_bilingual():
    p = run(["Show [01].mkv", "Show [01].chs.sup",
             "Show [01].cht.sup"])
    print("简繁 模式:", p.multi_sub_mode)
    assert p.multi_sub_mode == "zh_bilingual", p.multi_sub_mode


def test_mixed_episodes():
    """01 单份自动，02 两份待确认。"""
    p = run(["Show [01].mkv", "Show [02].mkv",
             "Show [01].chs.sup",
             "Show [02].JPSC.sup", "Show [02].JPTC.sup"])
    subs = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("混合 已改名:", subs, "| 待确认:", len(p.multi_subs))
    assert len(subs) == 1, subs
    assert "E01" in subs[0], subs
    assert len(p.multi_subs) == 2, p.multi_subs


def test_same_language_not_multi():
    """同一种语言的不同写法（sc / zh-Hans 都是简体）不算多份字幕。"""
    p = run(["Show [01].mkv", "Show [01].sc.sup",
             "Show [01].zh-Hans.ass"])
    subs = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("同语言不同写法 已改名:", subs, "| 待确认:", len(p.multi_subs))
    assert len(subs) == 2, subs
    assert not p.multi_subs, p.multi_subs


def test_different_language_is_multi():
    """sc 与 cht 是不同语言 → 待确认。"""
    p = run(["Show [01].mkv", "Show [01].sc.sup",
             "Show [01].cht.ass"])
    subs = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("不同语言 已改名:", subs, "| 待确认:", len(p.multi_subs))
    assert subs == [], subs
    assert len(p.multi_subs) == 2
    assert p.multi_sub_mode == "zh_bilingual", p.multi_sub_mode


def main():
    test_sub_kind()
    test_single_auto()
    test_multi_not_renamed()
    test_triple_mode()
    test_zh_bilingual()
    test_mixed_episodes()
    test_same_language_not_multi()
    test_different_language_is_multi()
    print("\nMULTI SUBTITLE MECHANISM OK")


if __name__ == "__main__":
    main()
