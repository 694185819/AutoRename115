# -*- coding: utf-8 -*-
"""路径里已有编号时，不再做标题搜索（省掉一整轮网络请求）。

用户要求：分析文件与文件夹链路时，只要链路里有需要的字段，
就不需要额外查询成本，只剩对 ID 的查找填写。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import metadata as M
from app.metadata import MetadataClient
from app.models import P115Item
from app.parser import parse_name
from app.planner import MediaRoot, NamingOptions, Planner

CALLS: list = []
_INSTALLED = False


def _install():
    global _INSTALLED
    if _INSTALLED:
        return
    for name in ("search_douban", "search_imdb", "search_bangumi",
                 "search_tmdb", "match_by_ids"):
        orig = getattr(M.MetadataClient, name, None)
        if orig is None:
            continue

        def make(n, o):
            def f(self, *a, **k):
                CALLS.append(n)
                return o(self, *a, **k)
            return f
        setattr(M.MetadataClient, name, make(name, orig))
    _INSTALLED = True


def _entry(fid, name, parent):
    e = type("E", (), {})()
    it = P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)
    it.size = 100
    e.item = it
    e.is_video = True
    e.parsed = parse_name(name, is_dir=False)
    e.folder_season = None
    e.container = None
    return e


def run(folder, files=("庆余年.S01E01.mkv",)):
    _install()
    it = P115Item(fid="x", parent_id="0", name=folder, is_dir=True)
    it.ancestors = ["剧"]
    entries = [_entry(f"f{i}", n, "x") for i, n in enumerate(files, 1)]
    mr = MediaRoot(item=it, entries=entries, season_dirs=[], part_dirs=[],
                   subs_dirs=[], nfo_files=[], unsupported="",
                   is_season_root=False, root_season=None)

    m = MetadataClient("", use_bangumi=True, log=lambda s: None)
    m.delays = {k: 0.0 for k in m.delays}
    p = Planner(m, NamingOptions())
    fp = p._context_parsed(mr)
    parsed = p._search_parsed(mr, entries, fp, False)

    CALLS.clear()
    try:
        m.search_pool(parsed, "series")
    except Exception:
        pass
    return parsed, list(CALLS)


def test_chain_id_parsed():
    """目录里的编号要进入 ParsedName。"""
    parsed, _calls = run("庆余年 (2019) [imdbid-tt11273352]")
    assert parsed.imdb_id == "tt11273352", parsed.imdb_id


def test_no_title_search_with_id():
    """有编号时不做任何标题搜索，只查一次编号。"""
    _parsed, calls = run("庆余年 (2019) [imdbid-tt11273352]")
    print("有编号 →", calls)
    assert calls == ["match_by_ids"], calls


def test_title_search_without_id():
    """没有编号时才走标题搜索（对照组）。"""
    _parsed, calls = run("庆余年 (2019)")
    print("无编号 →", len(calls), "次")
    assert "match_by_ids" not in calls
    assert any(c.startswith("search_") for c in calls), calls


def main():
    test_chain_id_parsed()
    test_no_title_search_with_id()
    test_title_search_without_id()
    print("SKIP SEARCH WITH ID OK")


if __name__ == "__main__":
    main()
