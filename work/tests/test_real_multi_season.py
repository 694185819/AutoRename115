# -*- coding: utf-8 -*-
"""父目录下有多个「带剧名的季目录」时，必须合成一个任务并改名为 Season。

用户现象：从「庆余年」目录分析，两个季目录（名字里带剧名和规格）
被拆成两个独立任务，各自重命名整个目录，没有 Season 01/02。

根因：_discover 判断“这些子目录是不是同一部剧的季目录”时，
要求解析出的剧名归一化后完全相同：
  庆余年 第2季[…][国语音轨]Joy.of.Life.2.S02… → 庆余年 Joy.of.Life.2
  庆余年.第1季.Joy.of.Life.S01.2019…          → 庆余年
两者写法不同 → 不认为是同一部剧 → 拆成两个任务。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, P115Item
from app.planner import NamingOptions, Planner

S2 = ("庆余年 第2季[迪士尼无广告版][全36集][国语音轨+繁体字幕]"
      "Joy.of.Life.2.S02.1080p.DSNP.WEB-DL.AAC.2.0.H.265-BlackTV")
S1 = "庆余年.第1季.Joy.of.Life.S01.2019.V3.SUBBED.2160p.WEB-DL.H265.AAC-FLTTH"


def _i(fid, name, parent):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=True)


def _v(fid, name, parent):
    it = P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)
    it.size = 100
    return it


class FakeClient:
    def __init__(self):
        self.tree = {
            "root": [_i("s2", S2, "root"), _i("s1", S1, "root")],
            "s2": [_v("v21", "庆余年.第二季.Joy.of.Life.2.S02E01.1080p."
                             "DSNP.WEB-DL.AAC.2.0.H.265-BlackTV.mkv", "s2")],
            "s1": [_v("v11", "庆余年.第1季.Joy.of.Life.S01E01.2160p."
                             "WEB-DL.H265.AAC-FLTTH.mkv", "s1")],
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

    def season_episode_titles(self, *a, **k):
        return {}

    def source_episode_titles(self, *a, **k):
        return {}

    def match(self, parsed, media_type, category=""):
        from app.decider import decide
        c = self.search_imdb(parsed.title)[0]
        pools = {"bangumi": [], "douban": [], "imdb": [c], "tmdb": []}
        return decide(parsed, media_type, category, pools, self.log)


def discover():
    p = Planner(FakeMeta(), NamingOptions(name_segment_source="imdb"))
    client = FakeClient()
    roots = p._discover(client, _i("root", "庆余年", "0"))
    return p, client, roots


def test_single_root():
    """两个季目录 → 一个 MediaRoot。"""
    _p, _c, roots = discover()
    assert len(roots) == 1, [r.item.name[:20] for r in roots]


def test_both_seasons_collected():
    """两个季目录都被登记为 season_dirs，视频都收进来。"""
    _p, _c, roots = discover()
    mr = roots[0]
    assert len(mr.season_dirs) == 2, [d.name[:20] for d in mr.season_dirs]
    assert len(mr.entries) == 2, len(mr.entries)
    seasons = sorted({e.folder_season for e in mr.entries})
    assert seasons == [1, 2], seasons


def test_season_dirs_renamed():
    """两个季目录改名为 Season 01 / Season 02。"""
    p, client, roots = discover()
    plans = []
    for mr in roots:
        plans += p._build_plans(client, mr)
    assert len(plans) == 1, len(plans)
    names = {o.new_name for o in plans[0].ops if o.role == "season"}
    print("季目录改名:", names)
    assert names == {"Season 01", "Season 02"}, names


def test_episodes_in_one_task():
    """两季视频都在同一个任务的预览里。"""
    p, client, roots = discover()
    plans = []
    for mr in roots:
        plans += p._build_plans(client, mr)
    eps = [o.new_name for o in plans[0].ops if o.role == "episode"]
    print("视频:", eps)
    assert any("S01E01" in n for n in eps), eps
    assert any("S02E01" in n for n in eps), eps
    assert not any("BlackTV" in n for n in eps), eps


def main():
    test_single_root()
    test_both_seasons_collected()
    test_season_dirs_renamed()
    test_episodes_in_one_task()
    print("REAL MULTI-SEASON OK")


if __name__ == "__main__":
    main()
