# -*- coding: utf-8 -*-
"""主结果来自 IMDb 时，中文主名称不能变成纯英文。

用户截图：主名称选「IMDb 英文名」，文件名全部变成
Ever.Night.S01E01…，「将夜」这个中文名整段消失。
根因：decide() 在 primary.source == "imdb" 时直接把
primary.title（只有英文）赋给 title_zh。
"""
import re
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.decider import _chinese_title_for
from app.models import Candidate, ParsedName


def cand(src, title, orig="", extra=None):
    c = Candidate(source=src, title=title, original_title=orig,
                  year=2018, sid="x", kind="tv")
    c.extra = extra or {}
    return c


def has_cjk(s):
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def test_local_chinese_wins():
    """本地是中文、IMDb 只有英文 → 用本地中文名。"""
    parsed = ParsedName(raw="将夜", title="将夜")
    got = _chinese_title_for(parsed, None, None, cand("imdb", "Ever Night"))
    assert got == "将夜", got


def test_douban_chinese_used():
    """本地是英文时，用豆瓣的中文名。"""
    parsed = ParsedName(raw="Ever Night", title="Ever Night")
    got = _chinese_title_for(parsed, cand("douban", "将夜"), None,
                             cand("imdb", "Ever Night"))
    assert got == "将夜", got


def test_bangumi_chinese_used():
    """本地是英文时，用 Bangumi 的中文名。"""
    parsed = ParsedName(raw="Ever Night", title="Ever Night")
    got = _chinese_title_for(parsed, None, cand("bangumi", "将夜"),
                             cand("imdb", "Ever Night"))
    assert got == "将夜", got


def test_imdb_alias_chinese():
    """只有 IMDb 别名带中文时也能用。"""
    parsed = ParsedName(raw="Ever Night", title="Ever Night")
    got = _chinese_title_for(
        parsed, None, None,
        cand("imdb", "Ever Night", extra={"aliases": ["将夜"]}))
    assert got == "将夜", got


def test_no_chinese_falls_back():
    """实在没有中文时才用英文，但绝不能返回空。"""
    parsed = ParsedName(raw="Ever Night", title="Ever Night")
    got = _chinese_title_for(parsed, None, None, cand("imdb", "Ever Night"))
    assert got == "Ever Night", got


def test_end_to_end_no_cjk_lost():
    """走完整 decide()：IMDb 单独命中时主标题仍是中文。"""
    from app.decider import decide
    from app.models import Candidate as C

    parsed = ParsedName(raw="将夜", title="将夜", queries=["将夜"],
                        season=1, year=2018)
    c = C(source="imdb", title="Ever Night", original_title="",
          year=2018, sid="tt9193596", kind="tv")
    c.extra = {"title_score": 1.0, "alias_title_score": 1.0,
               "title_exact": True, "anchor_exact": True}
    c.score = 0.98
    pools = {"bangumi": [], "douban": [], "imdb": [c], "tmdb": []}
    res = decide(parsed, "series", "cn_anime", pools, lambda s: None)
    assert has_cjk(res.title_zh), f"中文主名称丢失：{res.title_zh!r}"


def main():
    test_local_chinese_wins()
    test_douban_chinese_used()
    test_bangumi_chinese_used()
    test_imdb_alias_chinese()
    test_no_chinese_falls_back()
    test_end_to_end_no_cjk_lost()
    print("CHINESE MAIN TITLE OK")


if __name__ == "__main__":
    main()
