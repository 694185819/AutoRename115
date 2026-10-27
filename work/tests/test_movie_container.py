# -*- coding: utf-8 -*-
"""分类目录里的散装电影：手动搜索词必须是片名，不能是“1、国内”。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.parser import parse_name
from app.planner import NamingOptions, Planner

MOVIES = [
    "大海鱼棠.Big.Fish.and.Begonia.2016.GBR.1080p.Blu-ray.AVC.DTS-HD.MA.5.1-Huan@HDsky.mkv",
    "山海经之再见怪兽.2022.[国语].1080p.mkv",
    "浪浪山小妖怪.2025.2160p.mkv",
    "[深海.2023][2160p].mkv",
    "聊斋：兰若寺.2025.2160p.mkv",
    "风云决.2008.1080p.mkv",
]


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(notes=["no match"])

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def tree_for(folder_name, names):
    root = P115Item(fid="root", parent_id="0", name=folder_name,
                    is_dir=True, ancestors=["根目录", "动画"])
    tree = {"root": []}
    for i, name in enumerate(names):
        tree["root"].append(P115Item(
            fid=f"f{i}", parent_id="root", name=name, is_dir=False,
            ancestors=["根目录", "动画", folder_name]))
    return root, tree


def main():
    # 发布地区码、末尾问号和发布组不能留在片名/搜索词里
    p = parse_name(MOVIES[0])
    assert p.title == "大海鱼棠", p.title
    assert p.year == 2016, p.year
    assert p.queries[0] == "大海鱼棠", p.queries
    # 完整中英名保留为搜索候选，便于手动搜索/模糊匹配
    assert "大海鱼棠 Big Fish and Begonia" in p.queries, p.queries
    # 不能误伤片名里本来就有的连字符
    sp = parse_name("Spider-Man.2002.1080p.BluRay.x264-HDSky.mkv")
    assert sp.title == "Spider-Man", sp.title

    root, tree = tree_for("1、国内", MOVIES)
    plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), [root])
    assert len(plans) == len(MOVIES), len(plans)
    titles = [p.title for p in plans]
    assert titles == ["大海鱼棠", "山海经之再见怪兽", "浪浪山小妖怪",
                      "深海", "聊斋:兰若寺", "风云决"], titles
    for p in plans:
        assert p.media_type == "movie", p.media_type
        assert all(q != "1、国内" for q in p.parsed.queries), p.parsed.queries
        assert p.display_title != "1、国内", p.display_title

    # 分类目录里只有一部电影时，也不能把目录名当片名
    root, tree = tree_for("1、国内", MOVIES[:1])
    plans = Planner(FakeMeta(), NamingOptions()).analyze(
        FakeClient(tree), [root])
    assert len(plans) == 1
    assert plans[0].title == "大海鱼棠", plans[0].title
    assert plans[0].display_title == "大海鱼棠", plans[0].display_title
    assert plans[0].rename_root is False

    # 其他叫法的分类目录同样适用
    for folder in ("2、欧美", "01.动画", "3-电影"):
        root, tree = tree_for(folder, MOVIES[:2])
        plans = Planner(FakeMeta(), NamingOptions()).analyze(
            FakeClient(tree), [root])
        assert [p.title for p in plans] == ["大海鱼棠", "山海经之再见怪兽"], \
            (folder, [p.title for p in plans])
        assert all(folder not in p.parsed.queries for p in plans)

    print("MOVIE CONTAINER OK")


if __name__ == "__main__":
    main()
