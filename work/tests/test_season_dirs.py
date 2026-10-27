# -*- coding: utf-8 -*-
"""带备注的季目录：S01 [全52集] / S02 [全54集] / S03 [全59集]。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="一念永恒", title_original="A Will Eternal",
            year=2020, series_title="一念永恒", series_year=2020,
            country="cn", animation=True, confidence=1.0)

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def main():
    root = P115Item(fid="show", parent_id="1", name="一念永恒",
                    is_dir=True, ancestors=["动画", "1、国内"])
    specs = [(1, "[全52集]", 2), (2, "[全54集]", 2),
             (3, "[全59集]", 2), (4, "", 2)]
    tree = {"show": []}
    for season, tag, count in specs:
        name = f"S{season:02d} {tag}".strip()
        sid = f"s{season}"
        tree["show"].append(P115Item(
            fid=sid, parent_id="show", name=name, is_dir=True,
            ancestors=["动画", "1、国内", "一念永恒"]))
        tree[sid] = [
            P115Item(fid=f"v{season}_{ep}", parent_id=sid,
                     name=f"A.Will.Eternal.S{season:02d}E{ep:02d}."
                          f"2020.2160p.WEB-DL.mkv", is_dir=False)
            for ep in range(1, count + 1)
        ]
    plan = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), [root])[0]
    assert plan.seasons == [1, 2, 3, 4], plan.seasons
    seasons = [o for o in plan.ops if o.role == "season"]
    assert len(seasons) == 4, seasons
    assert [(o.old_name, o.new_name) for o in seasons] == [
        ("S01 [全52集]", "Season 01"),
        ("S02 [全54集]", "Season 02"),
        ("S03 [全59集]", "Season 03"),
        ("S04", "Season 04"),
    ], seasons
    eps = [o for o in plan.ops if o.role == "episode"]
    assert len(eps) == 8, len(eps)

    # “S2-美版暂无日语字幕”这种季号+说明的目录，也要并进同一部剧，
    # 不能让说明文字变成第二个剧名/第二条任务。
    root2 = P115Item(fid="sac", parent_id="1", name="攻壳机动队 SAC 2045",
                     is_dir=True, ancestors=["动画", "2、日本"])
    tree2 = {"sac": []}
    for sid, name in (("sac1", "S1"),
                      ("sac2", "S2-美版暂无日语字幕sup")):
        tree2["sac"].append(P115Item(
            fid=sid, parent_id="sac", name=name, is_dir=True,
            ancestors=["动画", "2、日本", "攻壳机动队 SAC 2045"]))
        tree2[sid] = [
            P115Item(fid=f"{sid}v{ep}", parent_id=sid,
                     name=f"{ep:02d}.m2ts", is_dir=False)
            for ep in (1, 2)
        ]
    plans2 = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree2), [root2])
    assert len(plans2) == 1, [p.item.name for p in plans2]
    plan2 = plans2[0]
    assert plan2.seasons == [1, 2], plan2.seasons
    assert plan2.parsed.title == "攻壳机动队 SAC 2045", plan2.parsed.title
    season_ops = [(o.old_name, o.new_name) for o in plan2.ops
                  if o.role == "season"]
    assert season_ops == [("S1", "Season 01"),
                          ("S2-美版暂无日语字幕sup", "Season 02")], season_ops
    s2_eps = [o.new_name for o in plan2.ops
              if o.role == "episode" and "S02E01" in o.new_name]
    assert s2_eps and "美版" not in s2_eps[0], s2_eps
    print("SEASON DIRS OK")


if __name__ == "__main__":
    main()
