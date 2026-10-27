# -*- coding: utf-8 -*-
"""上级目录回溯 + 原盘纯编号文件（00001.m2ts）识别测试。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner, _is_meaningless_title

GB = 1024 ** 3


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return [c for c in self.tree.get(cid, [])]


class FakeMeta:
    def __init__(self, title, original, year, imdb_id):
        self.title = title
        self.original = original
        self.year = year
        self.imdb_id = imdb_id
        self.queries = []

    def match(self, parsed, media_type, category_hint=""):
        self.queries.append(list(parsed.queries))
        return MatchResult(
            title_zh=self.title, title_original=self.original,
            year=self.year, series_title=self.title,
            series_original_title=self.original, series_year=self.year,
            series_imdb_id=self.imdb_id, imdb_id=self.imdb_id,
            country="jp", confidence=0.95)

    def save_cache(self):
        pass


def item(fid, parent, name, is_dir=False, size=0, ancestors=None):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=is_dir,
                    size=size, ancestors=list(ancestors or []))


def build_raw_bd_show():
    show = item("show", "1", "[末日后酒店][Apocalypse Hotel][アポカリプスホテル]",
                True, ancestors=["动画"])
    files = [item(f"v{i:02d}", "show", f"{i:05d}.m2ts", False, 1200 * GB,
                  ["动画", show.name]) for i in range(1, 13)]
    ass = [item(f"a{i:02d}", "ass", f"{i:05d}.ass", False, 30000,
                ["动画", show.name, "ass"]) for i in range(1, 13)]
    sup = [item(f"s{i:02d}", "sup", f"{i:05d}.sup", False, 20000000,
                ["动画", show.name, "sup"]) for i in range(1, 13)]
    tree = {
        "show": files + [
            item("ass", "show", "ass", True, ancestors=["动画", show.name]),
            item("sup", "show", "sup", True, ancestors=["动画", show.name]),
        ],
        "ass": ass,
        "sup": sup,
    }
    return show, FakeClient(tree)


def main():
    # “86”是合法片名，不能被当成纯编号丢掉
    assert not _is_meaningless_title("86")
    assert not _is_meaningless_title("1917")
    assert _is_meaningless_title("00001")
    assert _is_meaningless_title("Season 2")

    # 1) 番剧目录里只剩下 00001.m2ts：靠目录名识别成 12 集，而不是 12 部电影
    show, client = build_raw_bd_show()
    meta = FakeMeta("末日后酒店", "アポカリプスホテル", 2025, "tt32906586")
    planner = Planner(meta, NamingOptions(jp_folder_style="standard"))
    plans = planner.analyze(client, [show])
    assert len(plans) == 1, len(plans)
    p = plans[0]
    assert p.media_type == "series", p.media_type
    assert p.category == "jp_anime", p.category
    assert p.episodes == list(range(1, 13)), p.episodes
    ep_ops = [o for o in p.ops if o.role == "episode"]
    assert len(ep_ops) == 12, len(ep_ops)
    assert "アポカリプスホテル S01E01.m2ts" in [o.new_name for o in ep_ops]
    assert "アポカリプスホテル S01E12.m2ts" in [o.new_name for o in ep_ops]
    show_ops = [o for o in p.ops if o.role == "show"]
    assert show_ops and show_ops[0].new_name == \
        "末日后酒店 (2025) [imdbid-tt32906586]", show_ops
    sub_names = {o.new_name for o in p.ops if o.role == "subtitle"}
    assert "アポカリプスホテル S01E01.ass" in sub_names, sorted(sub_names)[:4]
    assert "アポカリプスホテル S01E12.sup" in sub_names, sorted(sub_names)[-4:]
    q = meta.queries[0]
    assert "末日后酒店" in q and "Apocalypse Hotel" in q
    assert "アポカリプスホテル" in q
    assert "00001" not in q, q

    # 2) 直接进入 Season 2：片名/年份来自上级目录，季号保持 2
    season = item("season2", "show2", "Season 2", True,
                  ancestors=["动画", "[某作品][Some Anime]"])
    sfiles = [item(f"sv{i}", "season2", f"{i:05d}.m2ts", False, 900 * GB,
                   ["动画", "[某作品][Some Anime]", "Season 2"])
              for i in range(1, 4)]
    meta2 = FakeMeta("某作品", "あるアニメ", 2020, "tt1234567")
    planner2 = Planner(meta2, NamingOptions())
    plans2 = planner2.analyze(FakeClient({"season2": sfiles}), [season])
    assert len(plans2) == 1
    p2 = plans2[0]
    assert p2.seasons == [2], p2.seasons
    assert p2.episodes == [1, 2, 3], p2.episodes
    names = [o.new_name for o in p2.ops if o.role == "episode"]
    assert names == ["あるアニメ S02E01.m2ts", "あるアニメ S02E02.m2ts",
                     "あるアニメ S02E03.m2ts"], names
    assert not [o for o in p2.ops if o.role == "show"]
    assert "某作品" in meta2.queries[0]

    # 3) 当前目录只是“动画”，上级才有片名
    generic = item("g", "1", "动画", True, ancestors=["[旧番]测试作品"])
    gfiles = [item(f"gv{i}", "g", f"{i:05d}.m2ts", False, 700 * GB,
                   ["动画", "[旧番]测试作品"]) for i in range(1, 3)]
    meta3 = FakeMeta("测试作品", "テスト", 2018, "tt7654321")
    plans3 = Planner(meta3, NamingOptions()).analyze(
        FakeClient({"g": gfiles}), [generic])
    assert len(plans3) == 1
    p3 = plans3[0]
    assert p3.title == "测试作品", p3.title
    assert [o.new_name for o in p3.ops if o.role == "episode"] == \
        ["テスト S01E01.m2ts", "テスト S01E02.m2ts"]
    assert not [o for o in p3.ops if o.role == "show"]  # 容器目录不改名

    # 4) 编号文件里混着 SP/menu：只给正片编号，花絮跳过
    folder = item("sp", "1", "[混剪测试]", True, ancestors=["动画"])
    spfiles = [item(f"sp{i}", "sp", f"{i:05d}.m2ts", False, 800 * GB,
                    ["动画", "[混剪测试]"]) for i in range(1, 4)]
    spfiles.append(item("spx", "sp", "SP.m2ts", False, 60 * GB,
                        ["动画", "[混剪测试]"]))
    meta4 = FakeMeta("混剪测试", "テスト", 2024, "tt0000001")
    p4 = Planner(meta4, NamingOptions()).analyze(
        FakeClient({"sp": spfiles}), [folder])[0]
    assert p4.media_type == "series", p4.media_type
    assert [o.new_name for o in p4.ops if o.role == "episode"] == \
        ["テスト S01E01.m2ts", "テスト S01E02.m2ts",
         "テスト S01E03.m2ts"]
    assert "SP.m2ts" in p4.note, p4.note

    print("ANCESTOR CONTEXT OK")


if __name__ == "__main__":
    main()
