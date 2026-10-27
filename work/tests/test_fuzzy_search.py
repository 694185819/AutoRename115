# -*- coding: utf-8 -*-
"""模糊搜索：主标题/英文名/季号变体，以及季号评分。"""
import os
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import (MetadataClient, candidate_season, douban_title_parts,
                          fuzzy_queries)
from app.models import Candidate, MatchResult, ParsedName
from app.planner import NamingOptions, Planner


def main():
    queries = fuzzy_queries(
        ["降世神通：科拉传奇", "The Legend of Korra"],
        "series", 4, 2014, limit=8)
    assert queries[:3] == [
        "降世神通：科拉传奇",
        "降世神通：科拉传奇 第四季",
        "降世神通：科拉传奇 第4季",
    ], queries
    assert "The Legend of Korra" in queries
    assert "The Legend of Korra Season 4" in queries
    assert "The Legend of Korra S04" in queries

    # 电影不生成季号变体
    movie_q = fuzzy_queries(["朝花夕拾"], "movie", 4, 2018)
    assert all("季" not in q and "Season" not in q for q in movie_q), movie_q

    c3 = Candidate(source="douban", title="降世神通：科拉传奇 第三季",
                   original_title="The Legend of Korra", year=2014,
                   sid="3", kind="tv")
    c4 = Candidate(source="douban", title="降世神通：科拉传奇 第四季",
                   original_title="The Legend of Korra", year=2014,
                   sid="4", kind="tv")
    cbook = Candidate(source="bangumi", title="The Legend of Korra Book Four: Balance",
                      original_title="The Legend of Korra", year=2014,
                      sid="114184", kind="tv")
    cmain = Candidate(source="tmdb", title="降世神通：科拉传奇",
                      original_title="The Legend of Korra", year=2012,
                      sid="33880", kind="tv")
    assert candidate_season(c3) == 3
    assert candidate_season(c4) == 4
    assert candidate_season(cbook) == 4
    assert candidate_season(cmain) is None

    # 豆瓣搜索页的混合标题拆成中文名/原名/年份
    parts = douban_title_parts(
        "降世神通：科拉传奇 第四季 The Legend of Korra Season 4‎ (2014)")
    assert parts == ("降世神通：科拉传奇 第四季",
                     "The Legend of Korra Season 4", 2014), parts

    cache = os.path.join(tempfile.gettempdir(), "test_fuzzy_meta.json")
    meta = MetadataClient(cache, use_bangumi=False, tmdb_key="")
    parsed = ParsedName(raw="Korra S04", title="降世神通：科拉传奇",
                        queries=["降世神通：科拉传奇"], year=2012, season=4)
    for c in (c3, c4, cmain):
        c.extra = {}
    s3 = meta._score(parsed, c3, "series")
    s4 = meta._score(parsed, c4, "series")
    assert s4 > s3 + 0.15, (s3, s4)
    assert c4.extra["season_score"] == 1.0
    assert c3.extra["season_score"] == 0.0

    # 没写季号时，主条目要压过同名的番外/小剧场
    main = Candidate(source="bangumi", title="葬送的芙莉莲",
                     original_title="葬送のフリーレン", year=2023,
                     sid="400602", kind="tv")
    special = Candidate(source="bangumi", title="葬送的芙莉莲 ～●●的魔法～",
                        original_title="葬送のフリーレン ～●●の魔法～",
                        year=2023, sid="459283", kind="tv")
    p_main = ParsedName(raw="葬送的芙莉莲", title="葬送的芙莉莲",
                        queries=["葬送的芙莉莲"], year=2023)
    main.extra = {}
    special.extra = {}
    assert meta._score(p_main, main, "series") > \
        meta._score(p_main, special, "series")

    # 目录里残留了别的剧的 TMDB ID 时，不能拿它当锚点
    class FakeById(MetadataClient):
        def tmdb_detail(self, sid, kind):
            return {"title": "假如是爱", "original_title": "假如是爱",
                    "year": 2022, "imdb_id": "", "id": sid,
                    "kind": kind, "country": "cn", "animation": False}

    fake = FakeById(cache, use_bangumi=False, tmdb_key="")
    assert fake.match_by_ids(
        "", "208452", "series", "假如...? What If") is None
    # “假如”不能因为前缀相同就认可“假如是爱”
    assert fake.match_by_ids(
        "", "208452", "series", "假如...?") is None
    print("FUZZY SEARCH OK")


if __name__ == "__main__":
    main()
