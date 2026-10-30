# -*- coding: utf-8 -*-
"""已有 IMDb 编号时，第一次分析就必须用上它（不能退回标题搜索）。

用户现象：目录「四方馆 Go East」第一次分析文件夹没带 ID，
二次分析才补上。

根因两层（都在 MetadataClient.match_by_ids）：
  1. 整个函数只走 TMDB：没配 TMDB key → 直接返回 None
  2. 就算走到校验，IMDb 给的「Go East」与本地「四方馆」
     被判为“标题不一致”，ID 被丢弃
"""
import re
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient


class FakeMeta(MetadataClient):
    """不联网：模拟 IMDb 按编号只给出英文名。"""

    def __init__(self, title="Go East", year=2024):
        super().__init__("", use_bangumi=False)
        self.tmdb_key = ""          # 没有 TMDB key
        self._t = title
        self._y = year

    def tmdb_detail(self, tmdb_id, kind="tv"):
        return None

    def tmdb_find_by_imdb(self, imdb_id, media_type):
        return None

    def media_details(self, source, sid, kind="tv", **k):
        if source != "imdb":
            return {}
        return {"title": self._t, "year": self._y}


def test_id_used_without_tmdb():
    """没有 TMDB key 时，IMDb 编号仍然可用。"""
    m = FakeMeta()
    res = m.match_by_ids("tt28288752", "", "series", "四方馆")
    assert res is not None, "有 IMDb 编号却返回 None"
    assert res.series_imdb_id == "tt28288752", res.series_imdb_id
    assert res.imdb_id == "tt28288752", res.imdb_id


def test_chinese_title_kept():
    """IMDb 只有英文名时，中文主名称不能被顶掉。"""
    m = FakeMeta()
    res = m.match_by_ids("tt28288752", "", "series", "四方馆")
    assert res.title_zh == "四方馆", res.title_zh
    assert res.series_title == "四方馆", res.series_title
    assert "Go East" in (res.title_original or ""), res.title_original


def test_cross_language_accepted():
    """中/英不同语言不算“标题不一致”，ID 要采用。"""
    m = FakeMeta()
    res = m.match_by_ids("tt28288752", "", "series", "四方馆")
    assert any("不同语言" in n for n in res.notes), res.notes


def test_really_different_still_rejected():
    """真正不同的作品（同为中文）仍然要拒绝。"""
    m = FakeMeta(title="另一部完全不同的剧", year=2024)
    res = m.match_by_ids("tt28288752", "", "series", "四方馆")
    assert res is None, "标题不符的 ID 不应被采用"


def test_invalid_id_returns_none():
    """无效编号返回 None，不抛异常。"""
    m = FakeMeta()
    assert m.match_by_ids("", "", "series", "四方馆") is None


def main():
    test_id_used_without_tmdb()
    test_chinese_title_kept()
    test_cross_language_accepted()
    test_really_different_still_rejected()
    test_invalid_id_returns_none()
    print("BY-ID MATCH OK")


if __name__ == "__main__":
    main()
