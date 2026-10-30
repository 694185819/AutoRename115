# -*- coding: utf-8 -*-
"""路径链路取名：只取可信片名，不混入上层分类与格式说明。

用户反馈：搜索时会拿“仲夏夜之梦”“小狗三国之将星”这类上层分类/合集
名反复乱搜。根因是 _context_parsed 把每一级祖先目录名都塞进搜索词。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import P115Item
from app.planner import MediaRoot, NamingOptions, Planner, _usable_query


def mk(name, ancestors):
    it = P115Item(fid="x", parent_id="0", name=name, is_dir=True)
    it.ancestors = list(ancestors)
    return MediaRoot(item=it, entries=[], season_dirs=[], part_dirs=[],
                     subs_dirs=[], nfo_files=[], unsupported="",
                     is_season_root=False, root_season=None)


def parse(mr):
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    return Planner(m, NamingOptions())._context_parsed(mr)


def test_only_title_used():
    """作品目录能给出片名时，只用它，不把「剧」「国漫」也当搜索词。"""
    p = parse(mk("将夜", ["剧", "国漫"]))
    assert p.title == "将夜", p.title
    assert p.queries == ["将夜"], p.queries


def test_format_descriptor_ignored():
    """目录名带容量/集数说明时，说明部分不能进搜索词。"""
    p = parse(mk("将夜[国语-外挂简繁字幕-无水印][4K][125.93GB-61集全]",
                 ["剧", "国漫"]))
    assert p.title == "将夜", p.title
    assert p.queries == ["将夜"], p.queries


def test_walk_up_until_title():
    """当前是季目录时逐级向上，直到找到片名；上层分类仍不参与。"""
    for name in ("Season 2", "S02", "第二季"):
        p = parse(mk(name, ["剧", "国漫", "将夜"]))
        assert p.title == "将夜", (name, p.title)
        assert p.queries == ["将夜"], (name, p.queries)


def test_double_season_dir():
    """两层季目录（S1/S2）也要继续向上找到片名。"""
    p = parse(mk("S2", ["剧", "国漫", "将夜", "S1"]))
    assert p.title == "将夜", p.title
    assert p.queries == ["将夜"], p.queries


def test_usable_query_filters():
    """格式说明片段不能当搜索词，真片名要能通过。"""
    for bad in ("125.93GB-61集全", "4K", "1080p", "61集", "无水印"):
        assert not _usable_query(bad), bad
    for good in ("将夜", "Ever Night", "葬送的芙莉莲"):
        assert _usable_query(good), good


def main():
    test_only_title_used()
    test_format_descriptor_ignored()
    test_walk_up_until_title()
    test_double_season_dir()
    test_usable_query_filters()
    print("PATH QUERY SOURCE OK")


if __name__ == "__main__":
    main()
