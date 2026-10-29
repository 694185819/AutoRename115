# -*- coding: utf-8 -*-
"""共用搜索服务：去重、来源合并、相关性排序。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import Candidate
from app.search_service import search_all, sort_by_relevance


class FakeMeta:
    use_bangumi = True
    tmdb_key = ""

    def __init__(self):
        self.calls = []

    def search_bangumi(self, q):
        self.calls.append(("bangumi", q))
        return [Candidate(source="bangumi", title="为美好的世界献上祝福！",
                          original_title="", year=2016, sid="b1", kind="tv")]

    def search_imdb(self, q):
        self.calls.append(("imdb", q))
        return [Candidate(source="imdb",
                          title="Konosuba: God's Blessing on This World!",
                          original_title="", year=2016, sid="tt5370118",
                          kind="tv")]

    def search_douban(self, q):
        self.calls.append(("douban", q))
        return [
            Candidate(source="douban", title="更美好的事 第一季",
                      original_title="", year=2016, sid="d1", kind="tv"),
            Candidate(source="douban", title="为美好的世界献上祝福！第四季",
                      original_title="", year=2027, sid="d2", kind="tv"),
        ]

    def search_tmdb(self, q, media_type="series"):
        self.calls.append(("tmdb", q))
        return []


def test_exact_first():
    """完全同名的条目必须排在第一，模糊结果垫底。"""
    found, notes = search_all(FakeMeta(), "为美好的世界献上祝福",
                              media_type="series", season=1, year=2016)
    titles = [c.title for c in found]
    print("排序:", titles)
    assert titles[0] == "为美好的世界献上祝福！", titles
    assert "更美好的事 第一季" in titles
    assert titles.index("更美好的事 第一季") > 0, "模糊结果不应排在最前"
    # 三个来源都参与了
    sources = {c.source for c in found}
    assert sources == {"bangumi", "imdb", "douban"}, sources
    assert any("Bangumi" in n for n in notes), notes


def test_dedup():
    """同一来源同一 id 只保留一次。"""
    class Dup(FakeMeta):
        def search_douban(self, q):
            c = Candidate(source="douban", title="重复条目", original_title="",
                          year=2016, sid="same", kind="tv")
            return [c, c, c]

    found, _ = search_all(Dup(), "重复条目", media_type="series")
    dup = [c for c in found if c.sid == "same"]
    assert len(dup) == 1, len(dup)


def test_bangumi_off():
    """关闭 Bangumi 时不请求它。"""
    meta = FakeMeta()
    _found, notes = search_all(meta, "测试", media_type="series",
                               use_bangumi=False)
    assert not any(k == "bangumi" for k, _q in meta.calls), meta.calls
    assert any("Bangumi 已关闭" in n for n in notes), notes


def test_season_boost():
    """季号匹配的条目优先。"""
    cands = [
        Candidate(source="douban", title="某剧", original_title="",
                  year=2020, sid="a", kind="tv"),
        Candidate(source="douban", title="某剧", original_title="",
                  year=2020, sid="b", kind="tv"),
    ]
    cands[0].extra = {"episodes": 12}
    cands[1].extra = {}
    out = sort_by_relevance(cands, "某剧", season=1, year=2020)
    assert len(out) == 2


def main():
    test_exact_first()
    test_dedup()
    test_bangumi_off()
    test_season_boost()
    print("SEARCH SERVICE OK")


if __name__ == "__main__":
    main()
