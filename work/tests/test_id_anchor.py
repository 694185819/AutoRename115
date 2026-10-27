# -*- coding: utf-8 -*-
"""原文件名已有 ID：只用 ID 查元数据，最终仍按规则生成改名操作。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
sys.path.insert(0, r"I:\实验\AutoRename115\work\tests")

from app.models import MatchResult
from app.planner import NamingOptions, Planner
from test_ancestor_context import FakeClient, item, GB


class AnchorMeta:
    def __init__(self, result):
        self.result = result
        self.match_calls = 0
        self.id_calls = []

    def match(self, parsed, media_type, category_hint=""):
        self.match_calls += 1
        return MatchResult()

    def match_by_ids(self, imdb_id, tmdb_id, media_type,
                     fallback_title=""):
        self.id_calls.append((imdb_id, tmdb_id, media_type, fallback_title))
        return self.result

    def season_episode_titles(self, tmdb_id, season):
        return {1: "The Boy in the Iceberg"}

    def save_cache(self):
        pass


def main():
    # 剧集：文件夹里已有 IMDb 号，用 ID 查到的结果做元数据；仍然生成改名操作
    folder = item("a", "1", "[降世神通][imdbid-tt0417299]", True,
                  ancestors=["动画"])
    video = item("av", "a",
                 "降世神通.S01E01.The.Boy.in.the.Iceberg.1080p.BluRay.REMUX.AVC.FLAC.mkv",
                 False, 8 * GB, ["动画", "降世神通"])
    result = MatchResult(
        title_zh="降世神通：最后的气宗",
        title_original="Avatar: The Last Airbender",
        year=2005, series_title="降世神通：最后的气宗",
        series_year=2005, series_imdb_id="tt0417299",
        imdb_id="tt0417299", tmdb_id="246", country="us",
        animation=True, confidence=1.0)
    meta = AnchorMeta(result)
    p = Planner(meta, NamingOptions()).analyze(
        FakeClient({"a": [video]}), [folder])[0]
    print("ID calls:", meta.id_calls, "normal match:", meta.match_calls)
    assert meta.id_calls and meta.id_calls[0][0] == "tt0417299"
    assert meta.match_calls == 0
    assert p.category == "us_anime", p.category
    show = [o.new_name for o in p.ops if o.role == "show"]
    eps = [o.new_name for o in p.ops if o.role == "episode"]
    print("show:", show, "ep:", eps)
    assert show and not show[0].startswith("[BD-REMUX]")
    assert eps and eps[0].startswith(
        "降世神通：最后的气宗.Avatar.The.Last.Airbender.S01E01.")
    assert "[1080p BluRay REMUX AVC FLAC]" in eps[0]

    # 电影：有 ID 仍按“ID 放中文名后、保留规格”的规则改名
    folder2 = item("m", "1", "朝花夕拾[imdbid-tt1234567]", True,
                   ancestors=["电影"])
    video2 = item("mv", "m", "朝花夕拾.2018.1080p.BluRay.mkv", False,
                  8 * GB, ["电影", "朝花夕拾[imdbid-tt1234567]"])
    result2 = MatchResult(
        title_zh="朝花夕拾", title_original="Maquia",
        year=2018, imdb_id="tt1234567", country="jp",
        confidence=1.0)
    meta2 = AnchorMeta(result2)
    p2 = Planner(meta2, NamingOptions()).analyze(
        FakeClient({"m": [video2]}), [folder2])[0]
    print("movie ID calls:", meta2.id_calls, "normal:", meta2.match_calls)
    assert meta2.id_calls and meta2.id_calls[0][0] == "tt1234567"
    assert meta2.match_calls == 0
    names = {o.old_name: o.new_name for o in p2.ops if o.role == "movie"}
    print(names)
    # 文件夹名已经符合“中文名后带 ID”的规则，不需要再改；
    # 视频文件仍会按规则补上 ID，改名没有被跳过。
    assert "朝花夕拾[imdbid-tt1234567]" not in names
    assert names.get("朝花夕拾.2018.1080p.BluRay.mkv") == \
        "朝花夕拾[imdbid-tt1234567].2018.1080p.BluRay.mkv"

    print("ID ANCHOR OK")


if __name__ == "__main__":
    main()
