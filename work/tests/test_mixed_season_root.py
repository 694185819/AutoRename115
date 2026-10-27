# -*- coding: utf-8 -*-
"""剧集根目录同时有季目录和剧场版时，不能整体误判成电影。

回归：Overlord 根目录里有 S01-S04 子目录，还放了一个剧场版 ISO；
之前只分析出电影，四个季目录完全没被读取。
"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.planner import (NamingOptions, Planner, looks_like_season_dir,
                         season_from_dir)


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        if media_type == "movie":
            return MatchResult(
                title_zh="剧场版 OVERLORD 圣王国篇",
                title_original="劇場版 オーバーロード 聖王国編",
                year=2024, imdb_id="tt14603848",
                confidence=1.0)
        return MatchResult(
            title_zh="不死者之王", title_original="オーバーロード",
            year=2015, series_title="不死者之王", series_year=2015,
            series_imdb_id="tt1234567", imdb_id="tt1234567",
            country="jp", animation=True, confidence=1.0)

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def video(fid, parent, name):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)


def main():
    assert season_from_dir(
        "Overlord 2015 S01 JPN Blu-ray 1080p AVC LPCM 2.0") == 1
    assert season_from_dir("Show Season II") == 2
    assert season_from_dir("Show 第2季") == 2
    assert not looks_like_season_dir("S1m0ne")
    assert not looks_like_season_dir("Show S01E01")

    root = P115Item(
        fid="show", parent_id="jp", name="[BD-REMUX]不死者之王 Overlord",
        is_dir=True, ancestors=["动画", "2、日本"])
    tree = {"show": [
        video("movie", "show",
              "[不死者之王 剧场版 圣王国篇 2024][自封双语字幕]"
              "[Gekijouban Overlord Sei Oukoku Hen][BDMV][Movie].iso"),
    ]}
    seasons = [
        ("s1", "Overlord 2015 S01 JPN Blu-ray 1080p AVC LPCM 2.0", 2015),
        ("s2", "Overlord 2018 S02 JPN Blu-ray 1080p AVC LPCM 2.0", 2018),
        ("s3", "Overlord 2018 S03 JPN Blu-ray 1080p AVC LPCM 2.0", 2018),
        ("s4", "Overlord 2022 S04 JPN Blu-ray 1080p AVC LPCM 2.0", 2022),
    ]
    for fid, name, year in seasons:
        tree["show"].append(P115Item(
            fid=fid, parent_id="show", name=name, is_dir=True,
            ancestors=["动画", "2、日本", root.name]))
        tree[fid] = [video(
            f"{fid}_v", fid,
            f"Overlord {year} S{int(fid[1:]):02d}E01.m2ts")]

    plans = Planner(
        FakeMeta(),
        NamingOptions(jp_folder_style="bdremux")).analyze(
        FakeClient(tree), [root])

    series = next(p for p in plans if p.media_type == "series")
    assert series.category == "jp_anime", series.category
    assert series.seasons == [1, 2, 3, 4], series.seasons
    show = next(o for o in series.ops if o.role == "show")
    assert show.new_name == \
        "[BD-REMUX]不死者之王 Overlord (2015) [imdbid-tt1234567]", \
        show.new_name
    season_ops = [o for o in series.ops if o.role == "season"]
    assert [(o.old_name, o.new_name) for o in season_ops] == [
        (seasons[i][1], f"Season {i + 1:02d}") for i in range(4)
    ], season_ops
    assert len([o for o in series.ops if o.role == "episode"]) == 4

    movies = [p for p in plans if p.media_type == "movie"]
    assert len(movies) == 1, plans
    assert movies[0].item.fid == "movie", movies[0].item.fid
    assert movies[0].rename_root is False
    assert any("[imdbid-tt14603848]" in o.new_name
               for o in movies[0].ops)
    print("MIXED SEASON ROOT OK")


if __name__ == "__main__":
    main()
