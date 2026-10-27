# -*- coding: utf-8 -*-
"""OAD/SP 特别篇：没有集数时匹配 TMDB 第 0 季或按文件名补号。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner

NAMES = [
    "[南家三姐妹 久候多时][Minami-ke Omatase][みなみけ おまたせ][OAD].mkv",
    "[南家三姐妹 惬意假期][Minami-ke Natsuyasumi][みなみけ 夏やすみ][OAD].mkv",
    "[南家三姐妹 甜品别腹][Minami-ke Betsubara][みなみけ べつばら][OAD].mkv",
]


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def __init__(self, titles):
        self.titles = titles

    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="南家三姐妹", title_original="みなみけ",
            year=2007, series_title="南家三姐妹", series_year=2007,
            tmdb_id="56354", series_imdb_id="tt1142743",
            country="jp", animation=True, confidence=1.0)

    def tmdb_tv_structure(self, tmdb_id):
        return {"seasons": [{"season_number": 1, "episode_count": 13}]}

    def season_episode_titles(self, tmdb_id, season):
        return dict(self.titles) if int(season) == 0 else {}

    def save_cache(self):
        pass


def build(titles, names=None):
    root = P115Item(
        fid="show", parent_id="jp",
        name="[BD-REMUX]南家三姐妹 [みなみけ]", is_dir=True,
        ancestors=["动画", "2、日本"])
    oad = P115Item(fid="oad", parent_id="show", name="OAD", is_dir=True)
    files = [
        P115Item(fid=f"v{i}", parent_id="oad", name=name, is_dir=False,
                 size=1000 + i)
        for i, name in enumerate(names or NAMES, 1)
    ]
    return root, FakeClient({"show": [oad], "oad": files})


def episode_map(plan):
    return {op.old_name: op.new_name for op in plan.ops
            if op.role == "episode"}


def main():
    titles = {
        1: "南家三姐妹 甜品别腹",
        2: "南家三姐妹 久候多时",
        3: "南家三姐妹 夏日假期",
    }
    root, client = build(titles)
    plan = Planner(FakeMeta(titles), NamingOptions()).analyze(
        client, [root])[0]
    print("NOTE:", plan.note)
    print("EPS:", episode_map(plan))
    assert plan.seasons == [0], plan.seasons
    assert plan.episodes == [1, 2, 3], plan.episodes
    assert plan.status == "auto", plan.status
    assert "没有识别到集数" not in plan.note, plan.note
    eps = episode_map(plan)
    by_old = {old: new for old, new in eps.items()}
    assert "S00E01" in next(v for k, v in by_old.items() if "甜品别腹" in k)
    assert "S00E02" in next(v for k, v in by_old.items() if "久候多时" in k)
    assert "S00E03" in next(v for k, v in by_old.items() if "惬意假期" in k)
    # 在线特别篇标题去重剧名后作为副标题
    assert any(n.endswith("S00E01.甜品别腹.mkv") for n in by_old.values()), \
        by_old
    assert any(o.role == "season" and o.new_name == "Specials"
               for o in plan.ops), plan.ops

    # 只剩一个未匹配文件、一个未用 TMDB 集号：编号唯一，保持自动
    real_names = [
        NAMES[0],
        NAMES[1].replace("惬意假期", "惬意暑假"),
        NAMES[2],
    ]
    root, client = build(titles, real_names)
    plan = Planner(FakeMeta(titles), NamingOptions()).analyze(
        client, [root])[0]
    print("FORCED NOTE:", plan.note)
    print("FORCED EPS:", episode_map(plan))
    assert plan.status == "auto", plan.status
    assert "唯一剩余" in plan.note, plan.note
    eps = episode_map(plan)
    assert "S00E03" in next(v for k, v in eps.items() if "惬意暑假" in k)

    # TMDB 没有特别篇标题：按文件名顺序补号并降为需确认
    root, client = build({})
    plan = Planner(FakeMeta({}), NamingOptions()).analyze(
        client, [root])[0]
    print("FALLBACK NOTE:", plan.note)
    print("FALLBACK EPS:", episode_map(plan))
    assert plan.episodes == [1, 2, 3], plan.episodes
    assert plan.status == "review", plan.status
    assert "按文件名顺序" in plan.note, plan.note
    eps = episode_map(plan)
    assert "S00E01" in next(v for k, v in eps.items() if "久候多时" in k)
    assert "S00E02" in next(v for k, v in eps.items() if "惬意假期" in k)
    assert "S00E03" in next(v for k, v in eps.items() if "甜品别腹" in k)

    print("SPECIALS OK")


if __name__ == "__main__":
    main()
