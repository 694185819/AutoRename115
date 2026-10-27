# -*- coding: utf-8 -*-
"""季目录根任务的剧名后要带 S01/S02，整部剧根目录不要带。"""
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
            title_zh="降世神通：最后的气宗", title_original="Avatar: The Last Airbender",
            year=2005, series_title="降世神通：最后的气宗", series_year=2005,
            country="us", animation=False, confidence=1.0,
            imdb_id="tt0417299", series_imdb_id="tt0417299")

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def video(fid, parent, name):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)


def main():
    planner = Planner(FakeMeta(), NamingOptions(include_imdb_id=True))

    # 单独的季目录：名字后加 S02
    root = P115Item(fid="root", parent_id="0",
                    name="Avatar.The.Last.Airbender.S02.1080p.BluRay",
                    is_dir=True, ancestors=["动画", "欧美"])
    tree = {"root": [
        video("v1", "root", "Avatar.The.Last.Airbender.S02E01.1080p.mkv"),
        video("v2", "root", "Avatar.The.Last.Airbender.S02E02.1080p.mkv"),
    ]}
    plan = planner.analyze(FakeClient(tree), [root])[0]
    show = next(o for o in plan.ops if o.role == "show")
    assert show.new_name == \
        "降世神通：最后的气宗 Avatar The Last Airbender S02 (2005) " \
        "[imdbid-tt0417299]", show.new_name

    # 整部剧根目录（内含多个季子目录）：保持不带 S01
    root = P115Item(fid="show", parent_id="0", name="降世神通：最后的气宗",
                    is_dir=True, ancestors=["动画", "欧美"])
    tree = {"show": [
        P115Item(fid="s1", parent_id="show", name="Season 01", is_dir=True),
        P115Item(fid="s2", parent_id="show", name="Season 02", is_dir=True),
    ], "s1": [
        video("a1", "s1", "Avatar.The.Last.Airbender.S01E01.1080p.mkv"),
    ], "s2": [
        video("a2", "s2", "Avatar.The.Last.Airbender.S02E01.1080p.mkv"),
    ]}
    plan = planner.analyze(FakeClient(tree), [root])[0]
    show = next(o for o in plan.ops if o.role == "show")
    assert show.new_name == \
        "降世神通：最后的气宗 Avatar The Last Airbender (2005) " \
        "[imdbid-tt0417299]", show.new_name

    # 中文“第二季”同样加 S02
    root = P115Item(fid="cn", parent_id="0", name="降世神通 第二季",
                    is_dir=True, ancestors=["动画", "欧美"])
    tree = {"cn": [
        video("c1", "cn", "Avatar.The.Last.Airbender.S02E01.1080p.mkv"),
    ]}
    plan = planner.analyze(FakeClient(tree), [root])[0]
    show = next(o for o in plan.ops if o.role == "show")
    assert show.new_name == \
        "降世神通：最后的气宗 Avatar The Last Airbender S02 (2005) " \
        "[imdbid-tt0417299]", show.new_name

    print("SEASON FOLDER NAMES OK")


if __name__ == "__main__":
    main()
