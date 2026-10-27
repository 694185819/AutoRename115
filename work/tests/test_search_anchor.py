# -*- coding: utf-8 -*-
"""自动搜索锚点：季目录说明文字/合集名/字幕文件不能带偏整部剧。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import Candidate, MatchResult, P115Item
from app.parser import parse_name
from app.planner import (FileEntry, MediaRoot, NamingOptions, Planner,
                         _is_season_description, _usable_query, is_season_dir)

GB = 1024 ** 3


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def __init__(self, result):
        self.result = result
        self.queries = []
        self.id_calls = []

    def match(self, parsed, media_type, category_hint=""):
        self.queries.append(list(parsed.queries))
        return self.result

    def match_by_ids(self, imdb_id, tmdb_id, media_type, fallback_title=""):
        self.id_calls.append((imdb_id, tmdb_id, fallback_title))
        return self.result

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


class QueryGuardMeta(FakeMeta):
    """模拟真实搜索：只有出现“剧版”这种词时才返回无关的 Big Hero 6。"""

    def __init__(self, wrong, right):
        super().__init__(right)
        self.wrong = wrong
        self.right = right

    def match(self, parsed, media_type, category_hint=""):
        self.queries.append(list(parsed.queries))
        if any("剧版" in q for q in parsed.queries):
            return self.wrong
        return self.right


def item(fid, parent, name, is_dir=False, ancestors=None):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=is_dir,
                    size=GB, ancestors=list(ancestors or []))


def build_show(folder_name, video_names):
    ancestors = ["剧", "布袋戏系列", "其他布袋戏（全系列）", "东离剑游记"]
    folder = item("season", "show", folder_name, True, ancestors)
    videos = [
        item(f"v{i}", "season", name, False, ancestors + [folder_name])
        for i, name in enumerate(video_names, 1)
    ]
    return folder, FakeClient({"season": videos})


def main():
    assert is_season_dir("S1替换双语字幕")
    assert is_season_dir("S1（替换双语字幕）")
    assert _is_season_description(parse_name("S1替换双语字幕", is_dir=True))
    # 带真正剧名的前缀季目录不能把剧名当说明丢掉
    assert not _is_season_description(parse_name("S1东离剑游记", is_dir=True))

    # “剧版（真剧名 年份）”只是版本说明，不能把“剧版”拿去搜索
    for raw in ("剧版《剑尘道魔录之玄劫天锋 2019》",
                "剧版（剑尘道魔录之玄劫天锋 2019）",
                "剧版 剑尘道魔录之玄劫天锋 2019",
                "影版（剑尘道魔录之玄劫天锋 2019）",
                "电影版（剑尘道魔录之玄劫天锋 2019）"):
        dp = parse_name(raw, is_dir=True)
        assert dp.title == "剑尘道魔录之玄劫天锋", (raw, dp.title)
        assert dp.year == 2019, (raw, dp.year)
        assert dp.queries[0] == "剑尘道魔录之玄劫天锋", (raw, dp.queries)
        assert all("剧版" not in q and "影版" not in q and
                   "电影版" not in q for q in dp.queries), (raw, dp.queries)
    assert not _usable_query("剧版")
    assert not _usable_query("影版")
    # 真正的标题以“剧版”开头（后面不是括号标题）时不能被误删
    assert parse_name("剧版画", is_dir=True).title == "剧版画"

    # “影版（2019）”只有年份，不能把“影版”当片名；用上级剧名兜底
    movie_ver = item("mv", "root", "影版（2019）", True,
                     ["剧", "剑尘追魔录之玄劫天锋 (2023)"])
    movie_ver_files = [
        item("mv1", "mv", "01.mkv", False, movie_ver.ancestors + ["影版（2019）"]),
        item("mv2", "mv", "02.mkv", False, movie_ver.ancestors + ["影版（2019）"]),
    ]
    mv_mr = MediaRoot(item=movie_ver, entries=[
        FileEntry(item=x, parsed=parse_name(x.name, is_dir=False))
        for x in movie_ver_files])
    mv_ctx = Planner(None, NamingOptions())._context_parsed(mv_mr)
    assert mv_ctx.title == "剑尘追魔录之玄劫天锋", mv_ctx.title
    assert all("影版" not in q for q in mv_ctx.queries), mv_ctx.queries

    # 模拟截图：搜索词只要出现“剧版”，Bangumi 就返回 Big Hero 6；
    # 现在必须用括号里的真剧名搜索，返回正确条目。
    wrong = MatchResult(
        title_zh="剧版超能陆战队番外短片",
        title_original="Big Hero 6: The Series",
        year=2018, series_title="剧版超能陆战队番外短片",
        series_year=2018, tmdb_id="68665", confidence=0.96)
    right = MatchResult(
        title_zh="剑尘道魔录之玄劫天锋",
        title_original="剑尘道魔录之玄劫天锋",
        year=2019, series_title="剑尘道魔录之玄劫天锋",
        series_year=2019, tmdb_id="257162", confidence=0.95)
    jx = item("jx", "1", "剧版（剑尘道魔录之玄劫天锋 2019）", True,
              ["剧", "布袋戏系列"])
    jx_videos = [
        item("jx1", "jx", "剑尘道魔录之玄劫天锋.S01E01.mkv", False),
        item("jx2", "jx", "剑尘道魔录之玄劫天锋.S01E02.mkv", False),
    ]
    jx_meta = QueryGuardMeta(wrong, right)
    jx_plan = Planner(jx_meta, NamingOptions()).analyze(
        FakeClient({"jx": jx_videos}), [jx])[0]
    assert jx_plan.title == "剑尘道魔录之玄劫天锋", jx_plan.title
    assert jx_plan.status == "auto", jx_plan.note
    assert jx_meta.queries and all(
        "剧版" not in q for q in jx_meta.queries[0]), jx_meta.queries

    folder, client = build_show(
        "S1替换双语字幕",
        ["Friends.1994.S01E01 [tmdbid-1668].mkv", "Friends.1994.S01E02.mkv",
         "Friends.S01E01.chs.ass", "Friends.S01E02.chs.ass"])
    # 直接检查上下文：标题必须来自最近的真实剧名目录
    raw_entries = [
        FileEntry(item=x, parsed=parse_name(x.name, is_dir=False))
        for x in client.tree["season"]
    ]
    mr = MediaRoot(item=folder, entries=raw_entries)
    planner = Planner(None, NamingOptions())
    fp = planner._context_parsed(mr)
    assert fp.title == "东离剑游记", fp.title
    for bad in ("替换", "布袋戏", "全系列", "Friends"):
        assert all(bad not in q for q in fp.queries), (bad, fp.queries)
    sp = planner._search_parsed(mr, mr.videos, fp)
    assert sp.title == "东离剑游记", sp.title
    assert sp.queries[0] == "东离剑游记", sp.queries
    assert sp.year is None, sp.year
    # 字幕文件不参与片名/搜索词，视频文件的 Friends 也被锚点过滤
    assert all("Friends" not in q for q in sp.queries), sp.queries
    assert sp.conflict_titles and sp.conflict_titles[0] == "Friends", \
        sp.conflict_titles

    # 上级目录本身写成 “S1东离剑游记” 时，后缀是真剧名，不能当季说明跳过
    named_season = item("named", "show", "S1东离剑游记", True,
                        ["动画", "S1东离剑游记"])
    named_files = [item("nv1", "named", "东离剑游记.S01E01.mkv", False,
                        ["动画", "S1东离剑游记"])]
    named_mr = MediaRoot(item=named_season, entries=[
        FileEntry(item=x, parsed=parse_name(x.name, is_dir=False))
        for x in named_files])
    assert planner._context_parsed(named_mr).title == "东离剑游记"

    # 元数据只支持上级剧名、不支持文件里的 Friends：必须停下来人工确认
    conflict_match = MatchResult(
        title_zh="Thunderbolt Fantasy 东离剑游记",
        title_original="Thunderbolt Fantasy 東離劍遊紀",
        year=2016, series_title="Thunderbolt Fantasy 东离剑游记",
        series_year=2016, series_imdb_id="tt5649126",
        imdb_id="tt5649126", confidence=0.95,
        imdb=Candidate(source="imdb", title="Thunderbolt Fantasy",
                       original_title="Thunderbolt Fantasy", year=2016,
                       sid="tt5649126", kind="tv"))
    meta = FakeMeta(conflict_match)
    plans = Planner(meta, NamingOptions()).analyze(client, [folder])
    assert len(plans) == 1, plans
    p = plans[0]
    assert meta.queries and meta.queries[0][0] == "东离剑游记", meta.queries
    assert all("Friends" not in q for q in meta.queries[0]), meta.queries
    assert p.status == "review", p.status
    assert not p.selected, p.selected
    assert "不一致" in p.note, p.note
    # Friends 文件里即使带 tmdbid，也不能作为整季的 ID 锚点
    assert not meta.id_calls, meta.id_calls

    # 就算元数据缓存/搜索意外返回了 Friends，也不能自动改名
    friends_match = MatchResult(
        title_zh="老友记", title_original="Friends", year=1994,
        series_title="老友记", series_year=1994,
        series_imdb_id="tt0108778", imdb_id="tt0108778",
        confidence=0.99,
        imdb=Candidate(source="imdb", title="Friends",
                       original_title="Friends", year=1994,
                       sid="tt0108778", kind="tv"))
    p_bad = Planner(FakeMeta(friends_match), NamingOptions()).analyze(
        client, [folder])[0]
    assert p_bad.status == "review", p_bad.note
    assert not p_bad.selected

    # 用户选中的是上级剧集根目录、Friends 在季子目录里时，也要拦住
    root = item("showroot", "0", "东离剑游记", True,
                ["剧", "布袋戏系列", "其他布袋戏（全系列）"])
    season = item("season2", "showroot", "S1替换双语字幕", True,
                  root.ancestors + [root.name])
    root_videos = [
        item(f"rv{i}", "season2", f"Friends.S01E{i:02}.mkv", False,
             season.ancestors + [season.name]) for i in (1, 2)
    ]
    root_client = FakeClient({"showroot": [season], "season2": root_videos})
    root_plans = Planner(FakeMeta(conflict_match), NamingOptions()).analyze(
        root_client, [root])
    assert len(root_plans) == 1, root_plans
    assert root_plans[0].status == "review", root_plans[0].note
    assert not root_plans[0].selected
    assert "不一致" in root_plans[0].note, root_plans[0].note

    # 同一部剧的英文别名能同时对上目录和文件时，不误伤自动匹配
    folder2, client2 = build_show(
        "S1替换双语字幕",
        ["Thunderbolt.Fantasy.S01E01.mkv",
         "Thunderbolt.Fantasy.S01E02.mkv"])
    alias_match = MatchResult(
        title_zh="Thunderbolt Fantasy 东离剑游记",
        title_original="Thunderbolt Fantasy 東離劍遊紀",
        year=2016, series_title="Thunderbolt Fantasy 东离剑游记",
        series_year=2016, series_imdb_id="tt5649126",
        imdb_id="tt5649126", confidence=0.95,
        imdb=Candidate(source="imdb", title="Thunderbolt Fantasy",
                       original_title="Thunderbolt Fantasy", year=2016,
                       sid="tt5649126", kind="tv"))
    p2 = Planner(FakeMeta(alias_match), NamingOptions()).analyze(
        client2, [folder2])[0]
    assert p2.status == "auto", (p2.status, p2.note)
    assert p2.selected, p2.note

    print("SEARCH ANCHOR OK")


if __name__ == "__main__":
    main()
