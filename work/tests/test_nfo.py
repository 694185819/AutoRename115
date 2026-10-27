# -*- coding: utf-8 -*-
"""NFO 生成与已有 NFO/图片跟随改名。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app import nfo
from app.models import (Candidate, MatchResult, P115Item, PlanItem,
                        RenameOp)
from app.parser import parse_name


def main():
    root = P115Item(fid="root", parent_id="0", name="测试剧", is_dir=True)
    m = MatchResult(
        title_zh="测试剧", title_original="Test Show", year=2024,
        tmdb_id="123", imdb_id="tt1234567", series_imdb_id="tt1234567",
        tmdb=Candidate(source="tmdb", title="测试剧", sid="123", kind="tv"),
        confidence=1.0)
    plan = PlanItem(item=root, media_type="series",
                    parsed=parse_name("测试剧", is_dir=True), match=m,
                    title="测试剧", year=2024, category="tv", rename_root=True)
    plan.ops = [
        RenameOp(fid="ep1", parent_id="root",
                 old_name="测试剧.S01E01.mkv",
                 new_name="测试剧.Test.Show.S01E01.第一集 [1080p WEB-DL].mkv",
                 is_dir=False, role="episode"),
        RenameOp(fid="ep2", parent_id="root",
                 old_name="测试剧.S01E02.mkv",
                 new_name="测试剧.Test.Show.S01E02.第二集 [1080p WEB-DL].mkv",
                 is_dir=False, role="episode"),
    ]
    plan.context["mr"] = type("MR", (), {"item": root})()
    details = {
        "title": "测试剧", "year": 2024, "rating": 8.5,
        "overview": "剧情简介", "poster": "", "fanart": "",
        "genres": ["剧情"], "cast": ["演员甲（角色甲）", "演员乙"],
    }
    tv = nfo.build_tvshow_nfo(plan, details).decode("utf-8")
    assert "<title>测试剧</title>" in tv
    assert "<year>2024</year>" in tv
    assert "<rating>8.5</rating>" in tv
    assert 'type="imdb"' in tv and "tt1234567" in tv
    assert "<name>演员甲</name>" in tv and "<role>角色甲</role>" in tv

    eps = nfo.episode_nfos(plan, details)
    assert len(eps) == 2, eps
    names = {x["filename"] for x in eps}
    assert "测试剧.Test.Show.S01E01.第一集 [1080p WEB-DL].nfo" in names, names
    assert all("<episode>" in x["data"].decode("utf-8") for x in eps)

    desired = nfo.desired_files(plan, details, b"poster", b"fanart")
    names = {x["filename"] for x in desired}
    assert "tvshow.nfo" in names
    assert "poster.jpg" in names and "fanart.jpg" in names
    assert len([n for n in names if n.endswith(".nfo")]) == 3

    files = [
        P115Item(fid="n1", parent_id="root", name="测试剧.S01E01.nfo",
                 is_dir=False),
        P115Item(fid="i1", parent_id="root", name="测试剧.S01E01-thumb.jpg",
                 is_dir=False),
        P115Item(fid="p1", parent_id="root", name="poster.jpg",
                 is_dir=False),
        P115Item(fid="t1", parent_id="root", name="tvshow.nfo",
                 is_dir=False),
    ]
    pairs = nfo.sidecar_renames(plan, files)
    got = {it.name: new for it, new in pairs}
    assert got["测试剧.S01E01.nfo"] == \
        "测试剧.Test.Show.S01E01.第一集 [1080p WEB-DL].nfo", got
    assert got["测试剧.S01E01-thumb.jpg"] == \
        "测试剧.Test.Show.S01E01.第一集 [1080p WEB-DL]-thumb.jpg", got
    assert "poster.jpg" not in got and "tvshow.nfo" not in got
    assert nfo.is_info_file("poster.jpg")
    assert not nfo.is_info_file("video.mkv")

    # 电影库根目录：只匹配当前电影，不能碰到同目录另一部电影的 NFO/图片
    movie = PlanItem(item=P115Item(fid="lib", parent_id="0", name="电影库",
                                   is_dir=True),
                     media_type="movie", parsed=parse_name("电影库"),
                     match=MatchResult(title_zh="电影甲", year=2020,
                                       imdb_id="tt1"),
                     title="电影甲", year=2020, category="movie",
                     rename_root=False)
    movie.ops = [RenameOp(
        fid="m1", parent_id="lib", old_name="电影甲.2020.mkv",
        new_name="电影甲[imdbid-tt1].2020.mkv", is_dir=False, role="movie")]
    movie.context["mr"] = type("MR", (), {
        "item": P115Item(fid="lib", parent_id="0", name="电影库", is_dir=True)})()
    lib_files = [
        P115Item(fid="a", parent_id="lib", name="电影甲.2020.nfo", is_dir=False),
        P115Item(fid="b", parent_id="lib", name="电影乙.2019.nfo", is_dir=False),
        P115Item(fid="c", parent_id="lib", name="电影甲.2020-thumb.jpg",
                 is_dir=False),
        P115Item(fid="d", parent_id="lib", name="poster.jpg", is_dir=False),
        P115Item(fid="e", parent_id="lib", name="电影甲.2020.mkv", is_dir=False),
        P115Item(fid="f", parent_id="lib", name="电影乙.2019.mkv", is_dir=False),
    ]
    matched = {x.fid for x in nfo.matching_info_files(movie, lib_files)}
    assert matched == {"a", "c"}, matched
    movie_desired = nfo.desired_files(movie, details, b"poster", b"fanart")
    movie_names = {x["filename"] for x in movie_desired}
    assert "电影甲[imdbid-tt1].2020.nfo" in movie_names, movie_names
    assert "poster.jpg" not in movie_names, movie_names

    # 当前文件夹模式：电影库两部片，共享 poster 不匹配；两部片各自的 NFO 匹配
    root_match = {x.fid for x in nfo.matching_info_files_for_root(lib_files)}
    assert root_match == {"a", "b", "c"}, root_match

    # 当前文件夹模式：剧集根目录多集 + tvshow/poster 视为剧集资料
    series_files = [
        P115Item(fid="s1", parent_id="root", name="剧.S01E01.mkv", is_dir=False),
        P115Item(fid="s2", parent_id="root", name="剧.S01E02.mkv", is_dir=False),
        P115Item(fid="s3", parent_id="root", name="剧.S01E01.nfo", is_dir=False),
        P115Item(fid="s4", parent_id="root", name="tvshow.nfo", is_dir=False),
        P115Item(fid="s5", parent_id="root", name="poster.jpg", is_dir=False),
    ]
    root_series = {x.fid for x in
                   nfo.matching_info_files_for_root(series_files)}
    assert root_series == {"s3", "s4", "s5"}, root_series

    print("NFO OK")


if __name__ == "__main__":
    main()
