# -*- coding: utf-8 -*-
"""豆瓣关联 IMDb 编号后，IMDb 候选必须带该条目自己的英文名。

用户截图：目录「将夜 (2018)[imdbid-tt9193596]」，来源名那一段
变成了 imdbid。根因：_apply_douban_related_ids 用豆瓣的中文名
（将夜）建了 IMDb 候选，original_title 还是空，
结果 _name_segment 取不到英文名，退回到文件名里抽英文，
把 [imdbid-tt…] 的 imdbid 当成了名字。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult


class FakeMeta(MetadataClient):
    """按编号回查时返回真实英文名，模拟 IMDb 的行为。"""

    def __init__(self, title="Ever Night", year=2018):
        super().__init__("", use_bangumi=False)
        self._title = title
        self._year = year
        self.details_calls = []

    def media_details(self, source, sid, kind="series"):
        self.details_calls.append((source, sid, kind))
        return {"title": self._title, "original_title": self._title,
                "year": self._year, "rating": 8.1}


def make_res(douban_sid="26848645"):
    res = MatchResult()
    db = Candidate(source="douban", title="将夜", original_title="将夜",
                   year=2018, sid=douban_sid, kind="tv")
    db.extra = {}
    res.douban = db
    return res


def test_imdb_title_backfilled():
    """豆瓣给了编号后，要按编号回查 IMDb 拿英文名。"""
    m = FakeMeta("Ever Night", 2018)
    m._related_cache = {str(26848645): {"imdb_id": "tt9193596"}}
    m.douban_related_ids = lambda sid: {"imdb_id": "tt9193596"}
    res = make_res()
    m._apply_douban_related_ids(res, "series")
    print("IMDb title:", repr(res.imdb.title),
          "| original:", repr(res.imdb.original_title))
    assert res.imdb is not None
    assert res.imdb.sid == "tt9193596"
    assert res.imdb.title == "Ever Night", res.imdb.title
    assert res.imdb.original_title == "Ever Night", res.imdb.original_title
    assert m.details_calls, "应按编号回查一次"


def test_fallback_to_douban_name():
    """回查失败时退回豆瓣名字，不能留空。"""
    class Broken(FakeMeta):
        def media_details(self, *a, **k):
            raise RuntimeError("network down")

    m = Broken()
    m.douban_related_ids = lambda sid: {"imdb_id": "tt9193596"}
    res = make_res()
    m._apply_douban_related_ids(res, "series")
    print("回查失败 →", repr(res.imdb.title))
    assert res.imdb.title == "将夜", res.imdb.title


def test_no_related_ids():
    """读不到编号时不做任何事。"""
    m = FakeMeta()
    m.douban_related_ids = lambda sid: {}
    res = make_res()
    m._apply_douban_related_ids(res, "series")
    assert res.imdb is None


def main():
    test_imdb_title_backfilled()
    test_fallback_to_douban_name()
    test_no_related_ids()
    print("DOUBAN RELATED IMDB TITLE OK")


if __name__ == "__main__":
    main()
