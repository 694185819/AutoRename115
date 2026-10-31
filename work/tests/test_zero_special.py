# -*- coding: utf-8 -*-
"""SxxE00 与 [Special] ISO：映射到 TMDB 第 0 季特别篇。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner

SHOW = "ロード・エルメロイⅡ世の事件簿 魔眼蒐集列車 Grace note"
FILES = [
    f"{SHOW} S1E00.m2ts",
    f"{SHOW} S1E00.zh-Hans.ass",
    f"{SHOW} S1E01.m2ts",
    "[君主·埃尔梅罗二世事件簿 魔眼蒐集列車 Grace note—"
    "[BDMV][1080p][Special][JP].iso",
]
SUBS = [
    "[ReinForce] Lord El-Melloi II-sei no Jikenbo ~Rail Zeppelin "
    "Grace Note~ 00 (BDRip 1920x1080 x264 FLAC).sc.sup",
    "[ReinForce] Lord El-Melloi II-sei no Jikenbo ~Rail Zeppelin "
    "Grace Note~ 01 (BDRip 1920x1080 x264 FLAC).sc.sup",
]


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="君主·埃尔梅罗二世事件簿 魔眼蒐集列車 Grace note",
            title_original=SHOW, year=2019,
            series_title="君主·埃尔梅罗二世事件簿 魔眼蒐集列車 Grace note",
            series_year=2019, tmdb_id="99999",
            series_imdb_id="tt1234567", country="jp",
            animation=True, confidence=1.0)

    def tmdb_tv_structure(self, tmdb_id):
        return {"seasons": [
            {"season_number": 0, "episode_count": 2},
            {"season_number": 1, "episode_count": 13},
        ]}

    def season_episode_titles(self, tmdb_id, season):
        if int(season) == 0:
            return {1: "第0话 守墓人与猫与魔术师",
                    2: "特别篇 韦伯的同学聚会与幻灯机"}
        return {}

    def save_cache(self):
        pass


def main():
    root = P115Item(
        fid="show", parent_id="jp",
        name="[BD-REMUX]君主·埃尔梅罗二世事件簿 魔眼蒐集列車 Grace note",
        is_dir=True, ancestors=["动画", "2、日本"])
    files = [
        P115Item(fid=f"v{i}", parent_id="show", name=name, is_dir=False,
                 size=6000 + i)
        for i, name in enumerate(FILES, 1)
    ]
    subs = P115Item(fid="subs", parent_id="show", name="字幕",
                    is_dir=True)
    sub_files = [
        P115Item(fid=f"s{i}", parent_id="subs", name=name, is_dir=False,
                 size=100)
        for i, name in enumerate(SUBS, 1)
    ]
    plan = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient({"show": [subs, *files],
                    "subs": sub_files}), [root])[0]
    print("NOTE:", plan.note)
    for op in plan.ops:
        print(op.role, "|", op.old_name, "->", op.new_name)
    assert plan.seasons == [0, 1], plan.seasons
    assert plan.episodes == [1, 2], plan.episodes
    assert plan.status == "auto", plan.status
    by_old = {op.old_name: op.new_name for op in plan.ops}
    assert "S00E01" in by_old[f"{SHOW} S1E00.m2ts"]
    sub = by_old[f"{SHOW} S1E00.zh-Hans.ass"]
    # 字幕语言标记统一成简洁中文（zh-Hans → 简体）
    assert "S00E01" in sub and sub.endswith(".简体.ass"), sub
    iso = next(v for k, v in by_old.items() if k.endswith(".iso"))
    assert "S00E02" in iso, iso
    assert "S01E01" in by_old[f"{SHOW} S1E01.m2ts"]
    sub_ops = {op.old_name: op.new_name for op in plan.ops
               if op.role == "subtitle"}
    zero_sub = next(v for k, v in sub_ops.items() if " 00 (" in k)
    main_sub = next(v for k, v in sub_ops.items() if " 01 (" in k)
    assert "S00E01" in zero_sub and zero_sub.endswith(".简体.sup"), zero_sub
    assert "S01E01" in main_sub and main_sub.endswith(".简体.sup"), main_sub
    assert "第 0 集" in plan.note, plan.note
    assert "唯一剩余" in plan.note, plan.note
    assert "集号是 0" not in plan.note, plan.note

    print("ZERO SPECIAL OK")


if __name__ == "__main__":
    main()
