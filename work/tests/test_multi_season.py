# -*- coding: utf-8 -*-
"""一个剧目录下有多个季子文件夹时：一个任务、季目录改名、视频改名。

用户要求：左边点一个剧目录分析后，右边只显示一行；
预览里能看到各季文件夹预备改名为 Season 01/02，
然后是具体视频文件的改名。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, P115Item
from app.planner import NamingOptions, Planner


def _i(fid, name, parent):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=True)


def _v(fid, name, parent):
    it = P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)
    it.size = 100
    return it


class FakeClient:
    """庆余年/ ├─ 庆余年.S01/ ├─ 庆余年.S02/"""

    def __init__(self):
        self.tree = {
            "root": [_i("s1", "庆余年.S01", "root"),
                     _i("s2", "庆余年.S02", "root")],
            "s1": [_v("v11", "庆余年.S01E01.初入京都.mkv", "s1")],
            "s2": [_v("v21", "庆余年.S02E01.再入京都.mkv", "s2")],
        }

    def list_dir(self, fid, **k):
        return list(self.tree.get(fid, []))

    def list_all(self, fid, **k):
        return list(self.tree.get(fid, []))


class FakeMeta(MetadataClient):
    def __init__(self):
        super().__init__("", use_bangumi=False)
        self.delays = {k: 0.0 for k in self.delays}

    def search_douban(self, q):
        return []

    def search_imdb(self, q):
        c = Candidate(source="imdb", title="Joy of Life",
                      original_title="", year=2019,
                      sid="tt11273352", kind="tv")
        c.extra = {"title_score": 1.0, "alias_title_score": 1.0,
                   "title_exact": True, "anchor_exact": True,
                   "aliases": ["庆余年"]}
        c.score = 0.98
        return [c]

    def search_bangumi(self, q):
        return []

    def search_tmdb(self, *a, **k):
        return []

    def season_episode_titles(self, tmdb_id, season):
        return {}

    def source_episode_titles(self, *a, **k):
        return {}

    def match(self, parsed, media_type, category=""):
        from app.decider import decide
        c = self.search_imdb(parsed.title)[0]
        pools = {"bangumi": [], "douban": [], "imdb": [c], "tmdb": []}
        return decide(parsed, media_type, category, pools, self.log)


def build():
    p = Planner(FakeMeta(), NamingOptions(name_segment_source="imdb"))
    client = FakeClient()
    roots = p._discover(client, _i("root", "庆余年", "0"))
    plans = []
    for mr in roots:
        plans += p._build_plans(client, mr)
    return plans


def test_single_task():
    """两个季子文件夹 → 只产出一个任务。"""
    plans = build()
    assert len(plans) == 1, [p.title for p in plans]


def test_both_seasons_present():
    """任务里包含两季。"""
    plan = build()[0]
    assert sorted(plan.seasons) == [1, 2], plan.seasons


def test_season_dirs_renamed():
    """季目录改名为 Season 01 / Season 02。"""
    plan = build()[0]
    seasons = {o.old_name: o.new_name for o in plan.ops
               if o.role == "season"}
    print("季目录:", seasons)
    assert seasons.get("庆余年.S01") == "Season 01", seasons
    assert seasons.get("庆余年.S02") == "Season 02", seasons


def test_episodes_renamed():
    """各季视频文件也要出现在预览里。"""
    plan = build()[0]
    eps = [o.new_name for o in plan.ops if o.role == "episode"]
    print("视频:", eps)
    assert len(eps) == 2, eps
    assert any("S01E01" in n for n in eps), eps
    assert any("S02E01" in n for n in eps), eps


def test_show_folder_renamed():
    """剧目录本身也改名（带年份与 ID）。"""
    plan = build()[0]
    show = [o.new_name for o in plan.ops if o.role == "show"]
    print("剧目录:", show)
    assert show and "tt11273352" in show[0], show


def main():
    test_single_task()
    test_both_seasons_present()
    test_season_dirs_renamed()
    test_episodes_renamed()
    test_show_folder_renamed()
    print("MULTI SEASON OK")


if __name__ == "__main__":
    main()
