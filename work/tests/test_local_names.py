# -*- coding: utf-8 -*-
"""原始目录名优先：中文名 + 日/英文名 + 年份 + ID 时不再联网取名。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
sys.path.insert(0, r"I:\实验\AutoRename115\work\tests")

from app.models import Candidate, MatchResult
from app.planner import NamingOptions, Planner, _episode_name
from test_ancestor_context import FakeClient, item, GB


class TrackingMeta:
    def __init__(self, result=None):
        self.called = 0
        self.result = result or MatchResult(
            title_zh="冰菓", title_original="氷菓", year=2012,
            series_title="冰菓", series_year=2012,
            series_imdb_id="tt2340841", imdb_id="tt2340841",
            country="jp", confidence=0.95)

    def match(self, parsed, media_type, category_hint=""):
        self.called += 1
        return self.result

    def save_cache(self):
        pass


def make_show(name, cid="show", n=3):
    show = item(cid, "1", name, True, ancestors=["动画"])
    files = [item(f"{cid}_{i}", cid, f"{i:05d}.m2ts", False, 900 * GB,
                  ["动画", name]) for i in range(1, n + 1)]
    return show, FakeClient({cid: files})


def main():
    # 1) 原目录已有中文 + 日文 + 年份 + ID：完全不调用元数据
    name = "[末日后酒店][Apocalypse Hotel][アポカリプスホテル][2025][tmdbid-65329]"
    show, client = make_show(name)
    meta = TrackingMeta()
    p = Planner(meta, NamingOptions(jp_folder_style="bdremux")).analyze(
        client, [show])[0]
    assert meta.called == 0, "本应完全离线"
    show_ops = [o for o in p.ops if o.role == "show"]
    print("offline:", show_ops[0].new_name if show_ops else None)
    assert show_ops and show_ops[0].new_name == \
        "[BD-REMUX]末日后酒店 アポカリプスホテル (2025) [tmdbid-65329]"
    assert "未联网" in p.note, p.note

    # 2) 原目录只有中文 + 英文：英文名优先于联网查到的日文名
    name2 = "[冰菓][Hyouka][2012][imdbid-tt2340841]"
    show2, client2 = make_show(name2, "show2")
    meta2 = TrackingMeta()
    p2 = Planner(meta2, NamingOptions(jp_folder_style="bdremux")).analyze(
        client2, [show2])[0]
    assert meta2.called == 1, "有英文名但没有日文名，仍需联网补年份/ID"
    show2_ops = [o for o in p2.ops if o.role == "show"]
    print("local en:", show2_ops[0].new_name if show2_ops else None)
    assert show2_ops and show2_ops[0].new_name == \
        "[BD-REMUX]冰菓 Hyouka (2012) [imdbid-tt2340841]"

    # 3) 原目录有中文 + 日文，但缺年份/ID：联网只补年份/ID，日文名用本地的
    name3 = "[冰菓][氷菓]"
    show3, client3 = make_show(name3, "show3")
    meta3 = TrackingMeta()
    p3 = Planner(meta3, NamingOptions(jp_folder_style="bdremux")).analyze(
        client3, [show3])[0]
    assert meta3.called == 1
    show3_ops = [o for o in p3.ops if o.role == "show"]
    print("local jp:", show3_ops[0].new_name if show3_ops else None)
    assert show3_ops and show3_ops[0].new_name == \
        "[BD-REMUX]冰菓 氷菓 (2012) [imdbid-tt2340841]"

    # 4) 原目录没有第二语言名：仍然走联网日文名
    show4, client4 = make_show("[冰菓]", "show4")
    meta4 = TrackingMeta()
    p4 = Planner(meta4, NamingOptions(jp_folder_style="bdremux")).analyze(
        client4, [show4])[0]
    assert meta4.called == 1
    show4_ops = [o for o in p4.ops if o.role == "show"]
    print("online jp:", show4_ops[0].new_name if show4_ops else None)
    assert show4_ops and show4_ops[0].new_name == \
        "[BD-REMUX]冰菓 氷菓 (2012) [imdbid-tt2340841]"

    # 5) 没有日文名：视频文件用原目录的英文/罗马音
    name5 = "[冰菓][Hyouka][2012][imdbid-tt2340841]"
    show5, client5 = make_show(name5, "show5")
    meta5 = TrackingMeta(MatchResult(
        title_zh="冰菓", title_original="", year=2012,
        series_title="冰菓", series_year=2012,
        series_imdb_id="tt2340841", imdb_id="tt2340841",
        country="jp", confidence=0.95))
    p5 = Planner(meta5, NamingOptions(jp_folder_style="bdremux")).analyze(
        client5, [show5])[0]
    eps5 = [o.new_name for o in p5.ops if o.role == "episode"]
    print("local romaji:", eps5[:2])
    assert eps5[:2] == ["Hyouka S01E01.m2ts", "Hyouka S01E02.m2ts"]

    # 6) 没有日文名、原目录也没有英文：用 IMDb 的英文/罗马音
    show6, client6 = make_show("[冰菓]", "show6")
    meta6 = TrackingMeta(MatchResult(
        title_zh="冰菓", title_original="", year=2012,
        series_title="冰菓", series_year=2012,
        series_imdb_id="tt2340841", imdb_id="tt2340841",
        country="jp", confidence=0.95,
        imdb=Candidate(source="imdb", title="Hyouka",
                       original_title="Hyouka", year=2012,
                       sid="tt2340841", kind="tv")))
    p6 = Planner(meta6, NamingOptions(jp_folder_style="bdremux")).analyze(
        client6, [show6])[0]
    eps6 = [o.new_name for o in p6.ops if o.role == "episode"]
    print("online romaji:", eps6[:2])
    assert eps6[:2] == ["Hyouka S01E01.m2ts", "Hyouka S01E02.m2ts"]

    # 超长日文标题也不能把 SxxExx 截掉
    long_name = _episode_name("長" * 300, 1, 1, None, ".mkv", "")
    assert long_name.endswith(" S01E01.mkv"), long_name[-20:]
    assert len(long_name.encode("utf-8")) <= 235, len(long_name.encode("utf-8"))

    print("LOCAL NAMES OK")


if __name__ == "__main__":
    main()
