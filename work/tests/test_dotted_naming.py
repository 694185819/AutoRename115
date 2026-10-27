# -*- coding: utf-8 -*-
"""电视剧/国产动画/欧美动画：中文名.英文名.SxxExx.副标题 [规格]。

美国动画按现行规则归“美漫”（us_anime），英/加/其他欧美动画为
west_anime；两者使用同一套点分隔命名格式。
"""
import json
import os
import sys
import tempfile
import time
sys.path.insert(0, r"I:\实验\AutoRename115")
sys.path.insert(0, r"I:\实验\AutoRename115\work\tests")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, ParsedName
from app.planner import (NamingOptions, Planner, _dotted_episode_name,
                         _episode_name)
from test_ancestor_context import FakeClient, item, GB


class Meta:
    def __init__(self, result, season_titles=None):
        self.result = result
        self.season_titles = season_titles or {}
        self.called = 0

    def match(self, parsed, media_type, category_hint=""):
        self.called += 1
        return self.result

    def season_episode_titles(self, tmdb_id, season):
        return self.season_titles.get(int(season), {})

    def save_cache(self):
        pass


def make_show(cid, name, files):
    folder = item(cid, "1", name, True, ancestors=["动画"])
    entries = [item(f"{cid}_{i}", cid, fn, False, 800 * GB,
                    ["动画", name]) for i, fn in enumerate(files, 1)]
    return folder, FakeClient({cid: entries})


def main():
    result = MatchResult(
        title_zh="降世神通：最后的气宗",
        title_original="Avatar: The Last Airbender",
        year=2005, series_title="降世神通：最后的气宗",
        series_year=2005, series_imdb_id="tt0417299",
        imdb_id="tt0417299", tmdb_id="246",
        country="us", animation=True, confidence=0.95,
        imdb=Candidate(source="imdb", title="Avatar: The Last Airbender",
                       original_title="Avatar: The Last Airbender",
                       year=2005, sid="tt0417299", kind="tv"))
    meta = Meta(result, {1: {
        2: "The Avatar Returns",
        3: "The Southern Air Temple",
    }})
    folder, client = make_show("avatar", "降世神通 最后的气宗", [
        "Avatar.The.Last.Airbender.S01E01.The.Boy.in.the.Iceberg.1080p.BluRay.REMUX.AVC.FLAC.2.0-NOGRP.mkv",
        "Avatar.The.Last.Airbender.S01E02.1080p.BluRay.REMUX.AVC.FLAC.2.0-NOGRP.mkv",
        "Avatar.The.Last.Airbender.S01E03.The.Southern.Air.Temple.1080p.BluRay.REMUX.AVC.FLAC.2.0-NOGRP.mkv",
    ])
    p = Planner(meta, NamingOptions()).analyze(client, [folder])[0]
    # 美国动画（country=us + animation）现行规则归入“美漫”；
    # 英/加/其他欧美动画仍是 west_anime。两者命名格式相同。
    assert p.category == "us_anime", p.category
    show_ops = [o.new_name for o in p.ops if o.role == "show"]
    print("SHOW:", show_ops)
    assert show_ops and not show_ops[0].startswith("[BD-REMUX]"), show_ops
    eps = [o.new_name for o in p.ops if o.role == "episode"]
    for n in eps:
        print("EP:", n)
    assert eps[0] == (
        "降世神通：最后的气宗.Avatar.The.Last.Airbender.S01E01."
        "The.Boy.in.the.Iceberg [1080p BluRay REMUX AVC FLAC 2.0].mkv"), eps[0]
    # 原文件名没有副标题 -> 用 TMDB 单集标题
    assert eps[1] == (
        "降世神通：最后的气宗.Avatar.The.Last.Airbender.S01E02."
        "The.Avatar.Returns [1080p BluRay REMUX AVC FLAC 2.0].mkv"), eps[1]
    assert eps[2] == (
        "降世神通：最后的气宗.Avatar.The.Last.Airbender.S01E03."
        "The.Southern.Air.Temple [1080p BluRay REMUX AVC FLAC 2.0].mkv"), eps[2]

    # 国产剧 / 电视剧也使用同样的点分隔格式
    result2 = MatchResult(
        title_zh="庆余年", title_original="Joy of Life", year=2019,
        series_title="庆余年", series_year=2019,
        series_imdb_id="tt11273352", imdb_id="tt11273352",
        country="cn", animation=False, confidence=0.95,
        imdb=Candidate(source="imdb", title="Joy of Life",
                       original_title="Joy of Life", year=2019,
                       sid="tt11273352", kind="tv"))
    meta2 = Meta(result2)
    folder2, client2 = make_show("qyn", "庆余年", [
        "庆余年.S02E01.初入京都.2160p.WEB-DL.mkv",
    ])
    p2 = Planner(meta2, NamingOptions()).analyze(client2, [folder2])[0]
    assert p2.category == "tv", p2.category
    eps2 = [o.new_name for o in p2.ops if o.role == "episode"]
    print("TV:", eps2[0] if eps2 else None)
    assert eps2 and eps2[0] == \
        "庆余年.Joy.of.Life.S02E01.初入京都 [2160p WEB-DL].mkv", eps2

    # 日番视频：日文名 + SxxExx + .副标题（不写规格）
    result3 = MatchResult(
        title_zh="葬送的芙莉莲", title_original="葬送のフリーレン",
        year=2023, series_title="葬送的芙莉莲", series_year=2023,
        series_imdb_id="tt22248376", imdb_id="tt22248376",
        tmdb_id="209867", country="jp", confidence=0.95)
    meta3 = Meta(result3, {1: {
        1: "旅立ちの町",
        2: "勇者と魔法使い",
    }})
    folder3, client3 = make_show("frieren", "葬送的芙莉莲", [
        "葬送的芙莉莲 - 01 - 旅立ちの町 [1080p].mkv",
        "葬送的芙莉莲 - 02 [1080p].mkv",
    ])
    p3 = Planner(meta3, NamingOptions()).analyze(client3, [folder3])[0]
    assert p3.category == "jp_anime", p3.category
    eps3 = [o.new_name for o in p3.ops if o.role == "episode"]
    print("JP:", eps3)
    assert eps3[0] == "葬送のフリーレン S01E01.旅立ちの町.mkv", eps3
    assert eps3[1] == "葬送のフリーレン S01E02.勇者と魔法使い.mkv", eps3

    # 长标题不截 SxxExx
    long_ep = _dotted_episode_name("长" * 300, "Very Long English Title" * 10,
                                   2, 3, None, "副标题" * 20,
                                   "2160p WEB-DL", ".mkv")
    assert long_ep.endswith(" S02E03.mkv") or "S02E03" in long_ep, long_ep
    assert len(long_ep.encode("utf-8")) <= 235, len(long_ep.encode("utf-8"))

    # 地区优先：美漫目录里带日文别名，也不能判成日番
    pl = Planner(None)
    us = MatchResult(country="us", animation=True,
                     title_original="Avatar: The Last Airbender")
    assert pl._detect_category(
        "series", us, ParsedName(raw="x", title="降世神通"),
        "动画 / [降世神通][アバター]") == "us_anime"
    jp = MatchResult(country="jp", title_original="葬送のフリーレン")
    assert pl._detect_category(
        "series", jp, ParsedName(raw="x", title="葬送的芙莉莲"),
        "动画") == "jp_anime"

    # 旧 Bangumi 缓存没有 country 时，用 tags 补出 us
    tmp = tempfile.mkdtemp(prefix="auto_meta_")
    cache = os.path.join(tmp, "cache.json")
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"bgm_detail:1": {
            "t": time.time(),
            "data": {"aliases": [], "country": "",
                     "tags": ["欧美", "美国", "TV"], "platform": "TV"},
        }}, f, ensure_ascii=False)
    meta = MetadataClient(cache)
    assert meta.bangumi_detail("1")["country"] == "us"

    print("DOTTED NAMING OK")


if __name__ == "__main__":
    main()
