# -*- coding: utf-8 -*-
"""字幕放进了独立子目录时，一律不参与改名。

用户场景（真实结构）：
  [BD-REMUX]俺物语!! [Ore Monogatari!!][Vol.1-Vol.8 Fin]/
      ├─ 字幕/                              ← 字幕单独归档
      │    └─ 俺物语!!Ore Monogatari!! S01E01.SC.sup …
      ├─ 俺物语!!Ore Monogatari!! S01E01.m2ts
      └─ …（24 个视频）

以前即使视频在根目录，「字幕/」里的 9 份字幕仍被收集并改名。
用户明确要求：视频文件夹里没有字幕文件，就不要动字幕文件夹。

规则：
  · 字幕与视频**同一文件夹** → 跟随改名
  · 字幕在独立的子目录（字幕/、ass/、sup/…）→ 一律不参与
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import P115Item
from app.planner import NamingOptions, Planner

FOLDER = "[BD-REMUX]俺物语!! [Ore Monogatari!!][Vol.1-Vol.8 Fin]"
BASE = "俺物语!!Ore Monogatari!!"


def mk(fid, name, parent, is_dir=False):
    it = P115Item(fid=fid, parent_id=parent, name=name, is_dir=is_dir)
    it.size = None if is_dir else 1000
    return it


class C:
    def __init__(s, t):
        s.t = t

    def list_dir(s, f, **k):
        return list(s.t.get(f, []))

    def list_all(s, f, **k):
        return list(s.t.get(f, []))


def discover(tree):
    root = mk("root", FOLDER, "jp", True)
    root.ancestors = ["2. 日本", "动画"]
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(jp_folder_style="bdremux"))
    return o._discover(C(tree), root)[0]


def test_same_folder_collected():
    """字幕与视频同文件夹 → 正常收集。"""
    tree = {"root": [
        mk(f"v{i}", f"{BASE} S01E{i:02d}.m2ts", "root")
        for i in range(1, 4)
    ] + [
        mk(f"s{i}", f"{BASE} S01E{i:02d}.ass", "root")
        for i in range(1, 4)
    ]}
    mr = discover(tree)
    print(f"同层：视频 {len(mr.videos)} | 字幕 {len(mr.sidecars)}")
    assert len(mr.sidecars) == 3, len(mr.sidecars)


def test_subdir_not_collected():
    """字幕在「字幕/」子目录 → 不收集（用户的核心诉求）。"""
    tree = {
        "root": [mk("sub", "字幕", "root", True)]
        + [mk(f"v{i}", f"{BASE} S01E{i:02d}.m2ts", "root")
           for i in range(1, 25)],
        "sub": [mk(f"s{i}", f"{BASE} S01E{i:02d}.SC.sup", "sub")
                for i in range(1, 10)],
    }
    mr = discover(tree)
    print(f"字幕/ 子目录：视频 {len(mr.videos)} | 字幕 {len(mr.sidecars)}")
    assert len(mr.videos) == 24, len(mr.videos)
    assert len(mr.sidecars) == 0, [s.item.name for s in mr.sidecars]


def test_subs_dir_inside_season_not_collected():
    """Season 01/字幕/ 这种嵌套同样不收集。"""
    tree = {
        "root": [mk("s01", "Season 01", "root", True)],
        "s01": [mk("sub", "字幕", "s01", True)]
        + [mk(f"v{i}", f"{BASE} S01E{i:02d}.m2ts", "s01")
           for i in range(1, 4)],
        "sub": [mk(f"s{i}", f"{BASE} S01E{i:02d}.ass", "sub")
                for i in range(1, 4)],
    }
    mr = discover(tree)
    print(f"季目录内字幕目录：视频 {len(mr.videos)} | "
          f"字幕 {len(mr.sidecars)}")
    assert len(mr.sidecars) == 0, [s.item.name for s in mr.sidecars]


def main():
    test_same_folder_collected()
    test_subdir_not_collected()
    test_subs_dir_inside_season_not_collected()
    print("\nSUBTITLE DIR EXCLUSION OK")


if __name__ == "__main__":
    main()
