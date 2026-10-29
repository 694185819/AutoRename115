# -*- coding: utf-8 -*-
"""按来源命名：单集副标题与特别篇顺序必须跟随所选来源，不混用 TMDB。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import Candidate, MatchResult, P115Item
from app.planner import NamingOptions, Planner


class FakeMeta:
    """TMDB 和 Bangumi 给出不同的单集标题 / 特别篇列表。"""

    def __init__(self):
        self.calls = []

    def match(self, parsed, media_type, category_hint=""):
        m = MatchResult(
            title_zh="灵笼", title_original="Ling Cage", year=2019,
            series_title="灵笼", series_year=2019,
            tmdb_id="91097", imdb_id="tt10827146",
            country="cn", animation=True, confidence=1.0)
        m.tmdb = Candidate(source="tmdb", title="灵笼", sid="91097",
                           kind="tv", year=2019)
        m.imdb = Candidate(source="imdb", title="Ling Cage",
                           sid="tt10827146", kind="tv", year=2019)
        m.source_refs = {
            "tmdb": {"id": "91097", "title": "灵笼", "year": 2019},
            "imdb": {"id": "tt10827146", "title": "Ling Cage", "year": 2019},
        }
        return m

    def source_episode_titles(self, source, sid, season):
        self.calls.append((source, sid, int(season)))
        season = int(season)
        if source == "tmdb":
            if season == 1:
                # TMDB 把特别篇也排进第一季
                return {1: "第0话 特别篇", 2: "第一集", 3: "第二集"}
            if season == 0:
                return {1: "TMDB特别篇一", 2: "TMDB特别篇二"}
        if source == "imdb":
            if season == 1:
                return {1: "Episode One", 2: "Episode Two"}
            return {}
        return {}

    def season_episode_titles(self, tmdb_id, season):
        """兼容“自动命名”走的旧接口。"""
        return self.source_episode_titles("tmdb", tmdb_id, season)

    def save_cache(self):
        pass


def build(files):
    root = P115Item(fid="show", parent_id="0", name="灵笼", is_dir=True,
                    ancestors=["动画"])
    items = [
        P115Item(fid=f"v{i}", parent_id="show", name=name, is_dir=False,
                 size=1000 + i)
        for i, name in enumerate(files, 1)
    ]

    class Client:
        def list_dir(self, cid, page_size=500):
            return items if cid == "show" else []

    return root, Client()


def episode_ops(plan):
    return {op.old_name: op.new_name for op in plan.ops
            if op.role == "episode"}


def test_default_uses_tmdb():
    root, client = build(["灵笼 S01E01.mp4", "灵笼 S01E02.mp4"])
    meta = FakeMeta()
    plan = Planner(meta, NamingOptions()).analyze(client, [root])[0]
    eps = episode_ops(plan)
    assert any(("tmdb", "91097", 1) == c for c in meta.calls), meta.calls
    # 默认行为不变：TMDB 第 1 季第 1 集是“第0话”，就按 TMDB 命名
    assert any("第0话" in v for v in eps.values()), eps


def test_naming_source_switches_to_imdb():
    root, client = build(["灵笼 S01E01.mp4"])
    meta = FakeMeta()
    planner = Planner(meta, NamingOptions())
    plan = planner.analyze(client, [root])[0]

    meta.calls.clear()
    plan.name_source = "imdb"
    planner.rebuild(plan)
    eps = episode_ops(plan)
    assert any(("imdb", "tt10827146", 1) == c for c in meta.calls), \
        meta.calls
    assert any("Episode.One" in v or "Episode One" in v
               for v in eps.values()), eps
    assert not any(c[0] == "tmdb" for c in meta.calls), \
        f"不应再查 TMDB：{meta.calls}"
    assert "命名来源：IMDb" in plan.note, plan.note


def test_back_to_auto_restores_tmdb():
    root, client = build(["灵笼 S01E01.mp4"])
    meta = FakeMeta()
    planner = Planner(meta, NamingOptions())
    plan = planner.analyze(client, [root])[0]
    plan.name_source = "imdb"
    planner.rebuild(plan)

    meta.calls.clear()
    plan.name_source = ""
    plan.title = "灵笼"          # 相当于取消来源后恢复自动标题
    planner.rebuild(plan)
    assert any(c[0] == "tmdb" for c in meta.calls), meta.calls


def test_specials_follow_source():
    """特别篇目录：命名来源为 IMDb（无特别篇数据）时，不能借用 TMDB 的顺序。"""
    root = P115Item(fid="show", parent_id="0", name="灵笼", is_dir=True,
                    ancestors=["动画"])
    oad = P115Item(fid="oad", parent_id="show", name="特别篇", is_dir=True)
    files = [P115Item(fid=f"s{i}", parent_id="oad", name=name, is_dir=False,
                      size=100)
             for i, name in enumerate(["灵笼 OVA 前篇.mkv",
                                       "灵笼 OVA 后篇.mkv"], 1)]

    class Client:
        def list_dir(self, cid, page_size=500):
            return {"show": [oad], "oad": files}.get(cid, [])

    meta = FakeMeta()
    planner = Planner(meta, NamingOptions())
    plan = planner.analyze(Client(), [root])[0]
    assert any(c[0] == "tmdb" and c[2] == 0 for c in meta.calls), \
        f"默认应借助 TMDB 第 0 季：{meta.calls}"

    meta.calls.clear()
    plan.name_source = "imdb"
    planner.rebuild(plan)
    assert not any(c[0] == "tmdb" and c[2] == 0 for c in meta.calls), \
        f"IMDb 来源不应查 TMDB 第 0 季：{meta.calls}"
    assert plan.status == "review", plan.status


def main():
    test_default_uses_tmdb()
    test_naming_source_switches_to_imdb()
    test_back_to_auto_restores_tmdb()
    test_specials_follow_source()
    print("NAMING SOURCE OK")


if __name__ == "__main__":
    main()
