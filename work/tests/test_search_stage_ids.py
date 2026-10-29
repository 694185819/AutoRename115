# -*- coding: utf-8 -*-
"""搜索阶段的静默编号补强：逻辑正确性（不依赖真实网络）。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, ParsedName


class Fake( MetadataClient):
    """只实现编号读取的假客户端。"""

    def __init__(self, table):
        super().__init__("", use_bangumi=False)
        self.browser_profile_dir = "/fake"
        self._table = table
        self._related_cache = {}

    def douban_related_ids(self, sid):
        return dict(self._table.get(str(sid), {}))


def d(sid, title, year=2023, season_hint=None):
    c = Candidate(source="douban", title=title, original_title="",
                  year=year, sid=sid, kind="tv")
    c.extra = {}
    c.score = 0.9
    return c


def main():
    parsed = ParsedName(raw="葬送的芙莉莲", title="葬送的芙莉莲",
                        queries=["葬送的芙莉莲"], season=1, year=2023)

    # 第一季条目没有季号，应被当成第 1 季优先读取
    table = {
        "111": {"imdb_id": "tt111", "tmdb_id": "1111"},   # 第一季（无季号）
        "222": {"imdb_id": "tt222", "tmdb_id": "2222"},   # 第二季
        "333": {"imdb_id": "tt333"},                      # 外传
    }
    m = Fake(table)
    pools = {"bangumi": [], "douban": [], "imdb": [], "tmdb": []}
    douban = [d("222", "葬送的芙莉莲 第二季"),
              d("111", "葬送的芙莉莲"),
              d("333", "葬送的芙莉莲 ～魔法～")]
    m._add_ids_from_douban(douban, pools, parsed, "series")

    imdb_ids = [c.sid for c in pools["imdb"]]
    tmdb_ids = [c.sid for c in pools["tmdb"]]
    print("IMDb 候选:", imdb_ids, "| TMDB 候选:", tmdb_ids)
    # 只应读第一季的编号
    assert "tt111" in imdb_ids, imdb_ids
    assert "tt222" not in imdb_ids, "不应把第二季的编号当成第一季"
    assert "tt333" not in imdb_ids, "不应读外传"
    assert "1111" in tmdb_ids, tmdb_ids

    # 没有配置目录时不做事
    m2 = Fake(table)
    m2.browser_profile_dir = ""
    pools2 = {"bangumi": [], "douban": [], "imdb": [], "tmdb": []}
    m2._add_ids_from_douban(douban, pools2, parsed, "series")
    assert not pools2["imdb"] and not pools2["tmdb"]

    # 已有同号候选时不重复添加
    pools3 = {"bangumi": [], "douban": [], "imdb": [
        Candidate(source="imdb", title="x", original_title="", year=2023,
                  sid="tt111", kind="tv")], "tmdb": []}
    pools3["imdb"][0].extra = {}
    m3 = Fake(table)
    m3._add_ids_from_douban(douban, pools3, parsed, "series")
    assert len([c for c in pools3["imdb"] if c.sid == "tt111"]) == 1

    print("SEARCH STAGE IDS OK")


if __name__ == "__main__":
    main()
