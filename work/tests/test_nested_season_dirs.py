# -*- coding: utf-8 -*-
"""合集根目录里混放电影和未标 Sxx 的季目录：两者都要分析。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner

S1 = "[希德尼娅的骑士][Knights of Sidonia][シドニアの騎士][BDMV][Vol.01-06 Fin]"
S2 = ("[希德尼亞的騎士 第九行星戰役][Knights of Sidonia Battle for Planet Nine]"
      "[シドニアの騎士 第九惑星戦役][BDMV][Vol.1-Vol.6 Fin]")


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        if media_type == "movie":
            return MatchResult(
                title_zh=parsed.title or "剧场版",
                title_original=parsed.title or "Movie",
                year=2015, tmdb_id="427593", imdb_id="tt12642574",
                confidence=1.0)
        return MatchResult(
            title_zh="希德尼娅的骑士", title_original="シドニアの騎士",
            year=2014, series_title="希德尼娅的骑士", series_year=2014,
            tmdb_id="60831", series_imdb_id="tt3398976",
            country="jp", animation=True, confidence=1.0)

    def tmdb_tv_structure(self, tmdb_id):
        return {"seasons": [
            {"season_number": 1, "episode_count": 12},
            {"season_number": 2, "episode_count": 12},
        ]}

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def main():
    root = P115Item(
        fid="root", parent_id="jp",
        name="[BD-REMUX]希德尼娅的骑士 [シドニアの騎士]", is_dir=True,
        ancestors=["动画", "2、日本"])
    d1 = P115Item(fid="s1", parent_id="root", name=S1, is_dir=True)
    d2 = P115Item(fid="s2", parent_id="root", name=S2, is_dir=True)
    fonts = P115Item(fid="fonts", parent_id="root", name="所需字体Fonts",
                     is_dir=True)
    tree = {
        "root": [
            d1, d2, fonts,
            P115Item(fid="m1", parent_id="root",
                     name="[希德尼娅的骑士 剧场版 2015][日版原盘].iso",
                     is_dir=False, size=1000),
            P115Item(fid="m2", parent_id="root",
                     name="[希德尼娅的骑士 织爱之星][LOVE WOVEN].iso",
                     is_dir=False, size=1000),
        ],
        "s1": [
            P115Item(fid="a1", parent_id="s1",
                     name="シドニアの騎士 S1E01.m2ts", is_dir=False),
            P115Item(fid="a2", parent_id="s1",
                     name="シドニアの騎士 S1E02.m2ts", is_dir=False),
        ],
        "s2": [
            P115Item(fid="b1", parent_id="s2",
                     name="シドニアの騎士 第九惑星戦役 S2E01.m2ts",
                     is_dir=False),
            P115Item(fid="b2", parent_id="s2",
                     name="シドニアの騎士 第九惑星戦役 S2E02.m2ts",
                     is_dir=False),
            P115Item(fid="subs2", parent_id="s2", name="字幕",
                     is_dir=True),
        ],
        "subs2": [
            P115Item(
                fid="sub2", parent_id="subs2",
                name="[VCB-Studio] Sidonia no Kishi Daikyuu Wakusei "
                     "Seneki [02(New Angle Ver.)]"
                     "[Ma10p_1080p][x265_flac].ass",
                is_dir=False),
        ],
        "fonts": [],
    }
    plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), [root])
    for p in plans:
        print(p.media_type, p.item.name, "seasons", p.seasons,
              "status", p.status)
        for op in p.ops:
            if op.is_dir:
                print("  DIR", op.old_name, "->", op.new_name)
    series = [p for p in plans if p.media_type == "series"]
    movies = [p for p in plans if p.media_type == "movie"]
    assert len(series) == 2, len(series)
    assert len(movies) == 2, len(movies)
    s1p = next(p for p in series if p.seasons == [1])
    s2p = next(p for p in series if p.seasons == [2])
    show1 = next(o.new_name for o in s1p.ops if o.role == "show")
    show2 = next(o.new_name for o in s2p.ops if o.role == "show")
    assert " S01 " in show1, show1
    assert " S02 " in show2, show2
    assert any("S01E01" in o.new_name for o in s1p.ops
               if o.role == "episode")
    assert any("S02E01" in o.new_name for o in s2p.ops
               if o.role == "episode")
    sub_ops = [o.new_name for o in s2p.ops if o.role == "subtitle"]
    assert any("S02E02" in n for n in sub_ops), sub_ops
    assert not any(o.is_dir and o.fid == "root" for p in plans for o in p.ops)
    print("NESTED SEASON DIRS OK")


if __name__ == "__main__":
    main()
