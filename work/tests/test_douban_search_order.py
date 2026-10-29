# -*- coding: utf-8 -*-
"""豆瓣搜索：主路径改为网页搜索（结果多、标题准），联想补全只做兜底。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import metadata as meta_mod
from app.metadata import MetadataClient
from app.models import Candidate


def make_client(fake_html=None, fake_suggest=None):
    m = MetadataClient("", use_bangumi=False)
    m.delays = {k: 0.0 for k in m.delays}
    calls = {"html": 0, "suggest": 0}

    def html_search(q):
        calls["html"] += 1
        return list(fake_html or [])

    def get_json(url, key, params=None, **kw):
        calls["suggest"] += 1
        return list(fake_suggest or [])

    m._douban_html_search = html_search
    m._get_json = get_json
    return m, calls


def test_html_first():
    """网页搜索有结果时，直接采用，不再调用联想补全。"""
    cands = [Candidate(source="douban", title="为美好的世界献上祝福！",
                       original_title="", year=2016, sid="26628250",
                       kind="tv")]
    m, calls = make_client(fake_html=cands, fake_suggest=[
        {"id": "1", "title": "更美好的事", "year": "2016", "episode": "1"}])
    out = m.search_douban("为美好的世界献上祝福")
    print("网页搜索优先 →", [c.title for c in out], "| 调用:", calls)
    assert out and out[0].title == "为美好的世界献上祝福！"
    assert calls["suggest"] == 0, "网页搜索成功时不应再走补全"


def test_suggest_fallback():
    """网页搜索无结果时才退回联想补全。"""
    m, calls = make_client(fake_html=[], fake_suggest=[
        {"id": "2", "title": "兜底条目", "year": "2020", "episode": "12"}])
    out = m.search_douban("某个冷门片名")
    print("兜底联想 →", [c.title for c in out], "| 调用:", calls)
    assert out and out[0].title == "兜底条目"
    assert calls["suggest"] == 1


def test_html_error_fallback():
    """网页搜索抛异常时也不能返回空，要退到补全。"""
    m = MetadataClient("", use_bangumi=False)
    m.delays = {k: 0.0 for k in m.delays}

    def boom(q):
        raise RuntimeError("HTTP 403")

    m._douban_html_search = boom
    m._get_json = lambda *a, **k: [
        {"id": "3", "title": "异常兜底", "year": "2021", "episode": "24"}]
    out = m.search_douban("另一个片名")
    print("异常兜底 →", [c.title for c in out])
    assert out and out[0].title == "异常兜底"


def test_relevance_ranking():
    """精确同名排最前，模糊命中垫底。"""
    cands = [
        Candidate(source="douban", title="更美好的事 第一季", original_title="",
                  year=2016, sid="1", kind="tv"),
        Candidate(source="douban", title="为美好的世界献上祝福！ 第三季 OVA",
                  original_title="", year=2025, sid="2", kind="tv"),
        Candidate(source="douban", title="为美好的世界献上祝福！",
                  original_title="この素晴らしい世界に祝福を！",
                  year=2016, sid="3", kind="tv"),
        Candidate(source="douban", title="为美好的世界献上祝福！第四季",
                  original_title="", year=2027, sid="4", kind="tv"),
        Candidate(source="douban", title="去他的世界 第一季", original_title="",
                  year=2017, sid="5", kind="tv"),
    ]
    m, _calls = make_client(fake_html=cands)
    out = m.search_douban("为美好的世界献上祝福")
    print("排序:", [c.title for c in out])
    assert out[0].title == "为美好的世界献上祝福！", out[0].title
    assert out[-1].title in ("更美好的事 第一季", "去他的世界 第一季"), \
        out[-1].title


def main():
    test_html_first()
    test_suggest_fallback()
    test_html_error_fallback()
    test_relevance_ranking()
    print("DOUBAN SEARCH ORDER OK")


if __name__ == "__main__":
    main()
