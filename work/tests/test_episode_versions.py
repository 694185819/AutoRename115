# -*- coding: utf-8 -*-
"""同集多文件：合理多版本与疑似重复/错集的区分。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.episode_versions import analyze_episode_versions
from app.models import MatchResult, P115Item
from app.nfo import _episode_title
from app.parser import parse_name
from app.planner import (FileEntry, NamingOptions, Planner,
                        _dotted_episode_name, _episode_name)


class Entry:
    def __init__(self, fid, name, size=0):
        self.item = P115Item(fid=fid, parent_id="show", name=name,
                             is_dir=False, size=size)
        self.parsed = parse_name(name)


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="测试剧", title_original="Test Show",
            year=2020, series_title="测试剧", series_year=2020,
            tmdb_id="100", series_imdb_id="tt1234567",
            country="cn", animation=False, confidence=1.0)

    def tmdb_tv_structure(self, tmdb_id):
        return {"seasons": [{"season_number": 1, "episode_count": 24}]}

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def main():
    # 1) 规格不同：合理多版本，按画质排序，第二个加 v2
    rows = [
        (Entry("a", "Test.Show.S01E01.1080p.WEB-DL.mkv", 1000), 1, 1),
        (Entry("b", "Test.Show.S01E01.2160p.BluRay.mkv", 2000), 1, 1),
    ]
    a = analyze_episode_versions(rows)
    assert len(a.groups) == 1 and a.groups[0].kind == "multi_version", a
    assert a.version_numbers == {"b": 0, "a": 2}, a.version_numbers
    assert "2 个版本" in a.groups[0].note, a.groups[0].note
    assert "2160p BluRay" in a.groups[0].note, a.groups[0].note

    # 2) 规格和大小都相同：疑似重复，键名带大小判断
    rows = [
        (Entry("c", "Test.Show.S01E02.1080p.WEB-DL.mkv", 500), 1, 2),
        (Entry("d", "Test.Show.S01E02.1080p.WEB-DL.mp4", 500), 1, 2),
    ]
    a = analyze_episode_versions(rows)
    assert a.groups[0].kind == "duplicate", a.groups[0]
    assert "规格和大小都相同" in a.groups[0].note, a.groups[0].note
    assert "Test.Show.S01E02.1080p.WEB-DL.mp4" in a.groups[0].note

    # 3) 规格相同但大小不同：仍按疑似重复，提示可能是不同剪辑
    rows = [
        (Entry("e", "Test.Show.S01E03.1080p.WEB-DL.mkv", 500 * 1024 * 1024),
         1, 3),
        (Entry("f", "Test.Show.S01E03.1080p.WEB-DL.mp4", 900 * 1024 * 1024),
         1, 3),
    ]
    a = analyze_episode_versions(rows)
    assert a.groups[0].kind == "duplicate", a.groups[0]
    assert "规格相同但大小不同" in a.groups[0].note, a.groups[0].note

    # 4) 显式 v2：即使其它规格相同也算多版本
    rows = [
        (Entry("g", "Test.Show.S01E04.1080p.WEB-DL.mkv", 500), 1, 4),
        (Entry("h", "Test.Show.S01E04v2.1080p.WEB-DL.mkv", 500), 1, 4),
    ]
    a = analyze_episode_versions(rows)
    assert a.groups[0].kind == "multi_version", a.groups[0]
    assert a.version_numbers.get("h") == 2, a.version_numbers

    # 5) 一边没有规格：证据不足，按疑似重复处理
    rows = [
        (Entry("i", "Test.Show.S01E05.mkv", 500), 1, 5),
        (Entry("j", "Test.Show.S01E05.1080p.WEB-DL.mkv", 500), 1, 5),
    ]
    a = analyze_episode_versions(rows)
    assert a.groups[0].kind == "duplicate", a.groups[0]

    # 6) 日番命名也支持 v2，且不丢规格逻辑
    assert _episode_name("测试番", 1, 1, None, ".mkv", "", "", "v2") == \
        "测试番 S01E01v2.mkv"
    assert _episode_name("测试番", 1, 1, None, ".mkv", "1080p WEB-DL",
                         "副标题", "v2") == \
        "测试番 S01E01v2.副标题 [1080p WEB-DL].mkv"
    assert _episode_title(
        "测试剧.Test.Show.S01E01v2.副标题 [1080p WEB-DL].mkv", 1) == "副标题"

    # 长副标题不能被固定的 80 字节上限截断；总长度才决定是否省略
    long_sub = "楽屋の富 / 三塔起請 / 風邪娘（后台财富 / 三塔损一两 / 感冒少女）"
    jp_name = _episode_name("じょしらく", 1, 2, None, ".m2ts", "", long_sub)
    assert "感冒少女" in jp_name, jp_name
    assert jp_name.endswith(".m2ts"), jp_name
    assert len(jp_name.encode("utf-8")) <= 235, jp_name
    tv_name = _dotted_episode_name(
        "女子落语", "Joshiraku", 1, 2, None, long_sub,
        "1080p WEB-DL", ".mkv")
    assert "感冒少女" in tv_name, tv_name
    assert tv_name.endswith(".mkv"), tv_name
    assert len(tv_name.encode("utf-8")) <= 235, tv_name

    # 结尾是“真田小ZOO）”这类含大写字母/括号的副标题，不能被当成发布组删掉
    raw = ("じょしらく S01E03.無情澡堂 / 淺草參拜 / 真田小ZOO"
           "（无情澡堂 / 浅草参拜 / 真田小ZOO）.m2ts")
    entry = FileEntry(
        item=P115Item(fid="sub", parent_id="show", name=raw, is_dir=False),
        parsed=parse_name(raw))
    sub = Planner(None)._episode_subtitle(entry)
    assert sub.endswith("真田小ZOO）"), sub
    group_entry = FileEntry(
        item=P115Item(fid="group", parent_id="show",
                      name="Show.S01E01.Subtitle GROUP.mkv", is_dir=False),
        parsed=parse_name("Show.S01E01.Subtitle GROUP.mkv"))
    assert Planner(None)._episode_subtitle(group_entry) == "Subtitle"

    # 7) Planner 集成：多版本保持自动；出现疑似重复后降级需确认且不勾选
    root = P115Item(fid="show", parent_id="tv", name="测试剧",
                    is_dir=True, ancestors=["电视剧"])
    files = [
        P115Item(fid="v1", parent_id="show",
                 name="Test.Show.S01E01.1080p.WEB-DL.mkv",
                 is_dir=False, size=1000),
        P115Item(fid="v2", parent_id="show",
                 name="Test.Show.S01E01.2160p.BluRay.mkv",
                 is_dir=False, size=2000),
        P115Item(fid="v3", parent_id="show",
                 name="Test.Show.S01E02.1080p.WEB-DL.mkv",
                 is_dir=False, size=500),
        P115Item(fid="v4", parent_id="show",
                 name="Test.Show.S01E02.1080p.WEB-DL.mp4",
                 is_dir=False, size=500),
    ]
    plan = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient({"show": files}), [root])[0]
    assert plan.category == "tv", plan.category
    assert len(plan.version_groups) == 2, plan.version_groups
    assert sum(g.is_duplicate for g in plan.version_groups) == 1
    assert plan.status == "review", plan.status
    assert plan.selected is False, plan.selected
    assert "疑似重复" in plan.note, plan.note
    ep_names = [o.new_name for o in plan.ops if o.role == "episode"]
    assert any("S01E01v2" in n for n in ep_names), ep_names
    assert any("S01E02v2" in n for n in ep_names), ep_names
    # 主版本优先 2160p，1080p 作为 v2
    assert any("S01E01 [2160p BluRay]" in n for n in ep_names), ep_names
    assert any("S01E01v2 [1080p WEB-DL]" in n for n in ep_names), ep_names

    # 8) 通过季集映射修正疑似重复后，状态恢复自动
    plan.episode_overrides = {"v4": (1, 3)}
    Planner(FakeMeta(), NamingOptions()).rebuild(plan)
    assert plan.status == "auto", plan.status
    assert plan.selected is True, plan.selected
    assert len(plan.version_groups) == 1, plan.version_groups
    assert not any(g.is_duplicate for g in plan.version_groups)
    assert "疑似重复" not in plan.note, plan.note
    assert "2 个版本" in plan.note, plan.note

    print("EPISODE VERSIONS OK")


if __name__ == "__main__":
    main()
