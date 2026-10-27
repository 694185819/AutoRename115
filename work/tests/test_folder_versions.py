# -*- coding: utf-8 -*-
"""同一部剧/电影的额外版本目录：文件夹标 V2，视频文件正常命名。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item, PlanItem
from app.parser import parse_name
from app.planner import NamingOptions, Planner


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        if media_type == "movie":
            return MatchResult(
                title_zh="测试电影", title_original="Test Movie",
                year=2021, tmdb_id="200", imdb_id="tt7654321",
                confidence=1.0)
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


def root(fid, name):
    return P115Item(fid=fid, parent_id="lib", name=name, is_dir=True,
                    ancestors=["电视剧"])


def video(fid, parent, name, size):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=False,
                    size=size)


def main():
    # 1) 同一部剧的两个版本目录：4K 作为主版本，1080p 标 V2。
    roots = [root("r1080", "测试剧 1080p"), root("r4k", "测试剧 4K")]
    tree = {
        "r1080": [video("a", "r1080",
                        "Test.Show.S01E01.1080p.WEB-DL.mkv", 1000)],
        "r4k": [video("b", "r4k",
                      "Test.Show.S01E01.2160p.BluRay.mkv", 2000)],
    }
    plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), roots)
    assert len(plans) == 2, plans
    by_root = {p.item.fid: p for p in plans}
    assert by_root["r4k"].folder_version == 0
    assert by_root["r1080"].folder_version == 2
    show4k = next(o.new_name for o in by_root["r4k"].ops
                  if o.role == "show")
    show1080 = next(o.new_name for o in by_root["r1080"].ops
                    if o.role == "show")
    print("SHOW 4K:", show4k)
    print("SHOW 1080:", show1080)
    assert "V2" not in show4k, show4k
    assert " V2 [tmdbid-100]" in show1080, show1080
    assert "同片额外版本目录" in by_root["r1080"].note
    # 视频文件正常命名，不带 v2
    ep1080 = next(o.new_name for o in by_root["r1080"].ops
                  if o.role == "episode")
    assert "S01E01" in ep1080 and "v2" not in ep1080.lower(), ep1080

    # 2) 已经带 V2 的目录保留原编号，不再重复加版本
    roots = [root("main", "测试剧"), root("v2", "测试剧 4K V2")]
    tree = {
        "main": [video("c", "main",
                       "Test.Show.S01E01.1080p.WEB-DL.mkv", 1000)],
        "v2": [video("d", "v2",
                     "Test.Show.S01E01.2160p.BluRay.mkv", 2000)],
    }
    plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), roots)
    by_root = {p.item.fid: p for p in plans}
    assert by_root["main"].folder_version == 0
    assert by_root["v2"].folder_version == 2
    show_v2 = next(o.new_name for o in by_root["v2"].ops
                   if o.role == "show")
    assert show_v2.count("V2") == 1, show_v2
    assert " V2 [tmdbid-100]" in show_v2, show_v2

    # 3) 不同季的目录不能因为 TMDB ID 相同就标 V2
    roots = [root("s1", "测试剧 S01"), root("s2", "测试剧 S02")]
    tree = {
        "s1": [video("e", "s1",
                     "Test.Show.S01E01.1080p.WEB-DL.mkv", 1000)],
        "s2": [video("f", "s2",
                     "Test.Show.S02E01.1080p.WEB-DL.mkv", 1000)],
    }
    plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), roots)
    assert all(p.folder_version == 0 for p in plans), \
        [(p.item.name, p.folder_version) for p in plans]

    # 4) 电影版本目录：同样只给文件夹加 V2
    movie_roots = [
        P115Item(fid="m1080", parent_id="lib", name="测试电影 1080p",
                 is_dir=True, ancestors=["电影"]),
        P115Item(fid="m4k", parent_id="lib", name="测试电影 4K",
                 is_dir=True, ancestors=["电影"]),
    ]
    movie_tree = {
        "m1080": [video("m1", "m1080",
                        "Test.Movie.2021.1080p.WEB-DL.mkv", 1000)],
        "m4k": [video("m2", "m4k",
                      "Test.Movie.2021.2160p.BluRay.mkv", 2000)],
    }
    movie_plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(movie_tree), movie_roots)
    by_root = {p.item.fid: p for p in movie_plans}
    assert by_root["m4k"].folder_version == 0
    assert by_root["m1080"].folder_version == 2
    folder_op = next(o for o in by_root["m1080"].ops if o.is_dir)
    print("MOVIE FOLDER:", folder_op.new_name)
    assert " V2 [" in folder_op.new_name, folder_op.new_name
    movie_op = next(o for o in by_root["m1080"].ops
                    if o.role == "movie" and not o.is_dir)
    assert "v2" not in movie_op.new_name.lower(), movie_op.new_name

    # 5) 电影文件夹：V2 必须放在 ID 之前
    planner = Planner(FakeMeta(), NamingOptions())
    movie = PlanItem(
        item=P115Item(fid="m", parent_id="lib", name="测试电影",
                      is_dir=True),
        media_type="movie", parsed=parse_name("测试电影"), title="测试电影",
        year=2021, folder_version=2,
        match=MatchResult(title_zh="测试电影", title_original="Test Movie",
                          year=2021, tmdb_id="200", imdb_id="tt7654321"),
        context={"tmdb_id": "200", "imdb_id": "tt7654321"})
    name = planner._versioned_folder_name("测试电影 (2021) [tmdbid-200]",
                                          movie)
    assert name == "测试电影 (2021) V2 [tmdbid-200]", name
    series_name = planner._folder_name(
        PlanItem(
            item=P115Item(fid="s", parent_id="lib", name="测试剧",
                          is_dir=True),
            media_type="series", parsed=parse_name("测试剧"), title="测试剧",
            year=2020, category="tv", folder_version=2,
            match=MatchResult(title_zh="测试剧", title_original="Test Show",
                              year=2020, series_title="测试剧",
                              series_year=2020, tmdb_id="100",
                              series_imdb_id="tt1234567"),
            context={"tmdb_id": "100", "imdb_id": "tt1234567"}),
        "测试剧", 2020, "tt1234567", "100")
    assert " V2 [tmdbid-100]" in series_name, series_name

    # 6) 日番 bdremux 风格同样把 V2 放在 ID 之前
    jp = PlanItem(
        item=P115Item(fid="j", parent_id="lib", name="测试番",
                      is_dir=True),
        media_type="series", parsed=parse_name("测试番"), title="测试番",
        year=2020, category="jp_anime", folder_version=2,
        match=MatchResult(title_zh="测试番", title_original="テスト番",
                          year=2020, series_title="测试番",
                          series_year=2020, tmdb_id="100",
                          series_imdb_id="tt1234567", country="jp",
                          animation=True),
        context={"tmdb_id": "100", "imdb_id": "tt1234567"})
    options = NamingOptions(jp_folder_style="bdremux")
    jp_name = Planner(FakeMeta(), options)._folder_name(
        jp, "测试番", 2020, "tt1234567", "100")
    print("JP:", jp_name)
    assert " V2 [tmdbid-100]" in jp_name, jp_name

    print("FOLDER VERSIONS OK")


if __name__ == "__main__":
    main()
