# -*- coding: utf-8 -*-
"""统一媒体身份：PlanItem.identity 汇总 match/context/人工覆盖。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item, PlanItem
from app.nfo import _unique_ids
from app.parser import parse_name


def main():
    item = P115Item(fid="1", parent_id="0", name="测试剧", is_dir=True)
    match = MatchResult(
        title_zh="测试剧", title_original="Test Show",
        year=2020, series_title="测试剧", series_year=2020,
        tmdb_id="111", imdb_id="tt111", series_imdb_id="tt111")
    plan = PlanItem(item=item, media_type="series", parsed=parse_name("测试剧"),
                    match=match, title="测试剧", year=2020,
                    series_imdb_id="tt111")
    plan.context = {"tmdb_id": "222", "imdb_id": "tt222"}
    ident = plan.identity
    assert ident.tmdb_id == "222", ident
    assert ident.imdb_id == "tt111", ident
    assert ident.title == "测试剧", ident
    assert ident.year == 2020, ident

    # 人工标题/年份覆盖优先
    plan.title_override = "人工剧名"
    plan.year_override = 2021
    ident = plan.identity
    assert ident.title == "人工剧名", ident
    assert ident.year == 2021, ident

    # 电影：context 中的 ID 是最终 ID
    movie = PlanItem(
        item=P115Item(fid="m", parent_id="0", name="电影", is_dir=True),
        media_type="movie", parsed=parse_name("电影"),
        match=MatchResult(title_zh="电影", title_original="Movie",
                          year=2019, tmdb_id="333", imdb_id="tt333"),
        title="电影", year=2019)
    movie.context = {"tmdb_id": "444", "imdb_id": "tt444"}
    ident = movie.identity
    assert ident.tmdb_id == "444", ident
    assert ident.imdb_id == "tt444", ident
    assert ident.original_title == "Movie", ident
    ids = dict(_unique_ids(movie))
    assert ids["tmdb"] == "444" and ids["imdb"] == "tt444", ids
    print("IDENTITY OK")


if __name__ == "__main__":
    main()
