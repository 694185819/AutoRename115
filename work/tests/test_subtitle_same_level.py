# -*- coding: utf-8 -*-
"""字幕必须与视频同层才参与命名。

用户场景（真实结构）：
  [BD-REMUX]大叔转生恶役大小姐 .../
      ├─ Season 01/        ← 视频在这里
      ├─ ass/              ← 简日/繁日字幕归档
      ├─ sup/              ← sup 字幕归档
      ├─ fanart.jpg / poster.jpg / tvshow.nfo
      └─ xxx.7z

以前 ass/sup 里的 36 份字幕被收进任务，触发了多字幕确认区。
用户明确要求：字幕文件夹没有视频，为什么要参与？

规则：
  · 视频与字幕在**同一层** → 字幕跟着视频改名
  · 字幕在**独立目录**（ass/sup/subs…）而视频在季子目录 → 不参与
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import P115Item
from app.planner import NamingOptions, Planner

SHOW = "[BD-REMUX]大叔转生恶役大小姐 悪役令嬢転生おじさん"
BASE = "Akuyaku Reijou Tensei Ojisan CheeseAni"


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


def _run(tree, name=SHOW):
    r = mk("show", name, "jp", True)
    r.ancestors = ["动画", "2. 日本"]
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(jp_folder_style="bdremux",
                                 rename_subtitles=True))
    return o.analyze(C(tree), [r])


def test_same_level_subtitles_follow():
    """字幕与视频同层 → 跟随改名。"""
    tree = {"show": [mk(f"v{i}", f"{BASE} S01E{i:02d}.mkv", "show")
                     for i in range(1, 4)]
            + [mk(f"a{i}", f"{BASE} S01E{i:02d}.zh-Hans.ass", "show")
               for i in range(1, 4)]}
    plans = _run(tree)
    assert plans, "没有任务"
    p = plans[0]
    subs = [o for o in p.ops if o.role == "subtitle"]
    print("同层字幕改名:", len(subs))
    assert len(subs) == 3, subs
    assert all("简体" in s.new_name for s in subs), subs


def test_archive_subs_dir_ignored():
    """视频在 Season 01、字幕在独立 ass/ → 字幕不参与。"""
    tree = {
        "show": [mk("s01", "Season 01", "show", True),
                 mk("ass", "ass", "show", True),
                 mk("sup", "sup", "show", True),
                 mk("j1", "fanart.jpg", "show"),
                 mk("j2", "poster.jpg", "show"),
                 mk("n1", "tvshow.nfo", "show"),
                 mk("z1", f"{BASE} Subs.7z", "show")],
        "s01": [mk(f"v{i}", f"{BASE} S01E{i:02d}.mkv", "s01")
                for i in range(1, 13)],
        "ass": [mk(f"a{i}", f"{BASE} S01E{i:02d}.zh-Hans.ass", "ass")
                for i in range(1, 13)]
               + [mk(f"at{i}", f"{BASE} S01E{i:02d}.zh-Hant.ass", "ass")
                  for i in range(1, 13)],
        "sup": [mk(f"p{i}", f"{BASE} S01E{i:02d}.zh-Hans.sup", "sup")
                for i in range(1, 13)],
    }
    plans = _run(tree)
    assert len(plans) == 1, len(plans)
    p = plans[0]
    subs = [o for o in p.ops if o.role == "subtitle"]
    eps = [o for o in p.ops if o.role == "episode"]
    print(f"独立 ass/sup：视频改名 {len(eps)}，字幕改名 {len(subs)}，"
          f"multi_subs={len(p.multi_subs)}")
    assert not subs, f"归档字幕被改名了: {[s.old_name for s in subs]}"
    assert not p.multi_subs, f"不该触发多字幕: {len(p.multi_subs)}"
    assert p.multi_sub_mode == "", p.multi_sub_mode
    # 视频照常处理（12 集应都有操作或至少列出来）
    assert p.episodes, "视频没被识别"


def test_subs_dir_not_season():
    """ass/sup 不能被当成季目录。"""
    tree = {
        "show": [mk("s01", "Season 01", "show", True),
                 mk("ass", "ass", "show", True),
                 mk("sup", "sup", "show", True)],
        "s01": [mk(f"v{i}", f"{BASE} S01E{i:02d}.mkv", "s01")
                for i in range(1, 3)],
        "ass": [mk("a1", f"{BASE} S01E01.zh-Hans.ass", "ass")],
        "sup": [mk("p1", f"{BASE} S01E01.zh-Hans.sup", "sup")],
    }
    plans = _run(tree)
    for p in plans:
        names = [o.old_name for o in p.ops if o.role == "season"]
        print("季目录改名:", names)
        assert "ass" not in names and "sup" not in names, names


def main():
    test_same_level_subtitles_follow()
    test_archive_subs_dir_ignored()
    test_subs_dir_not_season()
    print("\nSAME-LEVEL SUBTITLE RULE OK")


if __name__ == "__main__":
    main()
