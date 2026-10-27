# -*- coding: utf-8 -*-
"""TMDB 季集结构：集数校验、总集编号保护。

参考网易爆米花的 Season(total_episodes/season_episodes) 与
Episode(season index/total index) 设计：
- 有 Sxx 标记但集号超出 TMDB 该季集数：提示核对；
- 没有 Sxx 标记且集号超过第一季集数：暂停集数改名，避免硬写成 S01E13。
"""
import os
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def __init__(self, seasons):
        self.seasons = seasons

    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="测试番", title_original="Test Show",
            year=2020, series_title="测试番", series_year=2020,
            tmdb_id="100", series_imdb_id="tt1234567",
            country="jp", animation=True, confidence=1.0)

    def tmdb_tv_structure(self, tmdb_id):
        return {"seasons": [
            {"season_number": num, "episode_count": count}
            for num, count in self.seasons.items()
        ]}

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def video(fid, parent, name):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)


def root_item(fid="show", name="测试番", ancestors=("动画", "日番")):
    return P115Item(fid=fid, parent_id="jp", name=name, is_dir=True,
                    ancestors=list(ancestors))


def main():
    # 1) 没有季标记：E01-E13，TMDB S01 只有 12 集 -> 暂停集数改名
    root = root_item()
    tree = {"show": [
        video(f"v{i}", "show", f"Test.Show.E{i:02d}.1080p.mkv")
        for i in range(1, 14)
    ]}
    planner = Planner(FakeMeta({1: 12, 2: 12}), NamingOptions())
    plan = planner.analyze(FakeClient(tree), [root])[0]
    assert plan.season_confirmed is False, plan.season_confirmed
    assert plan.status == "review", plan.status
    assert not [o for o in plan.ops if o.role == "episode"], plan.ops
    assert "总集编号" in plan.note, plan.note
    assert any(o.role == "show" for o in plan.ops), plan.ops
    rows = planner.infer_episode_rows(plan)
    assert len(rows) == 13, len(rows)
    assert rows[11]["season"] == 1 and rows[11]["episode"] == 12
    assert rows[12]["season"] is None, rows[12]
    assert rows[12]["source"] == "待分季", rows[12]

    # 手动把 E13 映射到 S02E01 后，应该能正常生成集数操作
    plan.season_confirmed = True
    plan.episode_overrides = {"v13": (2, 1)}
    planner.rebuild(plan)
    assert plan.season_confirmed is True
    ep_ops = [o for o in plan.ops if o.role == "episode"]
    assert len(ep_ops) == 13, ep_ops
    assert any(o.fid == "v13" and "S02E01" in o.new_name
               for o in ep_ops), ep_ops

    # 2) 明确写了 S01，但 E13 超过 TMDB S01 的 12 集：提示但不阻止
    root = root_item("s1root", "Season 01", ("动画", "日番", "测试番"))
    tree = {"s1root": [
        video(f"s{i}", "s1root", f"Test.Show.S01E{i:02d}.1080p.mkv")
        for i in range(1, 14)
    ]}
    plan = Planner(FakeMeta({1: 12, 2: 12}),
                   NamingOptions()).analyze(
        FakeClient(tree), [root])[0]
    assert plan.season_confirmed is True
    assert "TMDB 第 1 季共 12 集" in plan.note, plan.note
    assert len([o for o in plan.ops if o.role == "episode"]) == 13, plan.ops

    # 3) 单季 24 集：不触发总集编号保护
    root = root_item()
    tree = {"show": [
        video(f"v{i}", "show", f"Test.Show.E{i:02d}.1080p.mkv")
        for i in range(1, 25)
    ]}
    plan = Planner(FakeMeta({1: 24}), NamingOptions()).analyze(
        FakeClient(tree), [root])[0]
    assert plan.season_confirmed is True
    assert plan.status == "auto", plan.status
    assert len([o for o in plan.ops if o.role == "episode"]) == 24

    # 4) TMDB detail 解析季列表与集数
    class DetailMeta(MetadataClient):
        def _get_json(self, url, source, params=None, referer="",
                      headers=None):
            return {
                "id": 100, "name": "测试番", "original_name": "Test Show",
                "first_air_date": "2020-01-01", "origin_country": ["JP"],
                "original_language": "ja", "genres": [{"name": "Animation"}],
                "number_of_seasons": 2, "number_of_episodes": 24,
                "seasons": [
                    {"season_number": 1, "name": "第 1 季",
                     "episode_count": 12, "air_date": "2020-01-01"},
                    {"season_number": 2, "name": "第 2 季",
                     "episode_count": 12, "air_date": "2021-01-01"},
                ],
                "external_ids": {"imdb_id": "tt1234567"},
            }

    cache = os.path.join(tempfile.gettempdir(), "test_tmdb_season_check.json")
    try:
        os.remove(cache)
    except OSError:
        pass
    meta = DetailMeta(cache, tmdb_key="test")
    structure = meta.tmdb_tv_structure("100")
    assert structure["number_of_seasons"] == 2
    assert structure["number_of_episodes"] == 24
    assert [(s["season_number"], s["episode_count"])
            for s in structure["seasons"]] == [(1, 12), (2, 12)]
    info = meta.tmdb_detail("100", "tv")
    assert info and info["year"] == 2020 and info["country"] == "jp"

    # 5) TMDB 搜索结果带上地区/首播/简介/评分，供手动搜索判断
    class SearchMeta(DetailMeta):
        def _get_json(self, url, source, params=None, referer="",
                      headers=None):
            return {"results": [{
                "id": 100, "name": "测试番", "original_name": "Test Show",
                "first_air_date": "2020-01-01", "origin_country": ["JP"],
                "original_language": "ja", "genre_ids": [16],
                "overview": "简介", "vote_average": 8.1,
                "poster_path": "/x.jpg",
            }]}

    s_meta = SearchMeta(cache, tmdb_key="test")
    c = s_meta.search_tmdb("测试番", "series")[0]
    assert c.extra["country"] == "jp", c.extra
    assert c.extra["first_air_date"] == "2020-01-01", c.extra
    assert c.extra["overview"] == "简介", c.extra
    assert c.extra["vote_average"] == 8.1, c.extra
    print("TMDB SEASON CHECK OK")


if __name__ == "__main__":
    main()
