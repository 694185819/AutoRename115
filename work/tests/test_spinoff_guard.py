# -*- coding: utf-8 -*-
"""同系列外传识别：高相似度但不是同一部作品，不能互相顶替。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import decider, scoring
from app.decider import _is_different_work
from app.models import Candidate, ParsedName


def cand(source, title, year=2016, sid="x", kind="tv"):
    c = Candidate(source=source, title=title, original_title=title,
                  year=year, sid=sid, kind=kind)
    c.extra = {}
    return c


def test_detect():
    cases = [
        ("为美好的世界献上祝福！", "为美好的世界献上爆焰！", True),
        ("为美好的世界献上祝福！", "为美好的世界献上祝福！", False),
        ("为美好的世界献上祝福！", "为美好的世界献上祝福！ 第二季", False),
        ("为美好的世界献上祝福！", "为美好的世界献上祝福！ 外传", True),
        ("灵笼", "灵笼 第一季", False),
        ("进击的巨人", "进击的巨人 最终季", False),
    ]
    for a, b, expect in cases:
        got = _is_different_work(a, b)
        assert got == expect, f"{a} vs {b}: {got} != {expect}"
    print("外传识别:", len(cases), "组全通过")


def test_not_primary():
    """豆瓣返回的外传不能被选成主结果。"""
    p = ParsedName(raw="为美好的世界献上祝福", title="为美好的世界献上祝福",
                   queries=["为美好的世界献上祝福"], season=1, year=2016)
    good_bg = cand("bangumi", "为美好的世界献上祝福！", 2016, "135275")
    bad_db = cand("douban", "为美好的世界献上爆焰！", 2023, "35918525")
    for c in (good_bg, bad_db):
        c.score = scoring.score(p, c, "series")
    res = decider.decide(p, "series", "jp_anime",
                         {"bangumi": [good_bg], "douban": [bad_db]},
                         lambda s: None)
    print("  主标题:", res.title_zh)
    print("  豆瓣:", res.douban.title if res.douban else None)
    print("  备注:", [n for n in res.notes if "豆瓣" in n])
    assert res.title_zh == "为美好的世界献上祝福！", res.title_zh
    assert res.douban is None, "外传不应被当成豆瓣结果"
    assert res.bangumi is not None


def test_same_work_kept():
    """正常同作品的不同季仍要保留，不能误杀。"""
    p = ParsedName(raw="灵笼", title="灵笼", queries=["灵笼"], season=1,
                   year=2019)
    db = cand("douban", "灵笼 第一季", 2019, "d1")
    bg = cand("bangumi", "灵笼 上半季", 2019, "b1")
    for c in (db, bg):
        c.score = scoring.score(p, c, "series")
    res = decider.decide(p, "series", "cn_anime",
                         {"douban": [db], "bangumi": [bg]}, lambda s: None)
    print("  灵笼 → 豆瓣:", bool(res.douban), "| Bangumi:", bool(res.bangumi))
    assert res.douban is not None, "同作品的分季不应被拒绝"
    assert res.bangumi is not None, "同作品的分季不应被拒绝"


def main():
    test_detect()
    test_not_primary()
    test_same_work_kept()
    print("SPINOFF GUARD OK")


if __name__ == "__main__":
    main()
