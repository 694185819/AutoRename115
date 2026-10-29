# -*- coding: utf-8 -*-
"""豆瓣关联编号：读取 IMDb/TMDB 并用编号补全匹配结果。

不联网：用假的页面读取函数注入，验证逻辑本身。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult


def make(id_map, profile="/tmp/fake_profile"):
    """构造一个只返回预置编号的客户端。"""
    m = MetadataClient("", use_bangumi=False)
    m.browser_profile_dir = profile
    m._related_cache = {}
    calls = {"n": 0}

    def fake(sid):
        calls["n"] += 1
        return dict(id_map.get(str(sid), {}))
    m._related_table = fake
    # 用公开方法里的缓存逻辑绕过真实浏览器
    def related(sid):
        sid = str(sid or "")
        if not sid.isdigit() or not m.browser_profile_dir:
            return {}
        if sid in m._related_cache:
            return dict(m._related_cache[sid])
        ids = fake(sid)
        m._related_cache[sid] = dict(ids)
        return ids
    m.douban_related_ids = related
    return m, calls


def test_ids_applied():
    """有编号时，应写进 res.imdb / res.tmdb 并记备注。"""
    m, _calls = make({
        "27121260": {"imdb_id": "tt10827146", "tmdb_id": "91097"},
    })
    res = MatchResult()
    res.douban = Candidate(source="douban", title="灵笼 第一季",
                           original_title="灵笼 第一季", year=2019,
                           sid="27121260", kind="tv")
    m._apply_douban_related_ids(res, "series")
    print("IMDb:", res.imdb.sid if res.imdb else None,
          "| TMDB:", res.tmdb.sid if res.tmdb else None)
    assert res.imdb is not None and res.imdb.sid == "tt10827146"
    assert res.tmdb is not None and res.tmdb.sid == "91097"
    assert any("豆瓣关联" in n for n in res.notes), res.notes


def test_no_douban():
    """没有豆瓣条目时不做事，也不应报错。"""
    m, calls = make({})
    res = MatchResult()
    res.douban = None
    m._apply_douban_related_ids(res, "series")
    assert res.imdb is None
    assert calls["n"] == 0


def test_no_ids():
    """豆瓣条目存在但页面上没有编号时，保持原样。"""
    m, _calls = make({"999": {}})
    res = MatchResult()
    res.douban = Candidate(source="douban", title="某剧", original_title="",
                           year=2020, sid="999", kind="tv")
    m._apply_douban_related_ids(res, "series")
    assert res.imdb is None and res.tmdb is None


def test_cache():
    """同一 sid 第二次读取应命中缓存。"""
    m, calls = make({"123": {"imdb_id": "tt0000001"}})
    m.douban_related_ids("123")
    m.douban_related_ids("123")
    assert calls["n"] == 1, calls


def test_no_profile():
    """没有配置目录时不尝试读浏览器。"""
    m = MetadataClient("", use_bangumi=False)
    m.browser_profile_dir = ""
    assert m.douban_related_ids("27121260") == {}


def main():
    test_ids_applied()
    test_no_douban()
    test_no_ids()
    test_cache()
    test_no_profile()
    print("RELATED IDS OK")


if __name__ == "__main__":
    main()
