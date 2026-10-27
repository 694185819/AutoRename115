# -*- coding: utf-8 -*-
"""自动匹配锚点：候选标题必须和本地标题/别名有真正重合。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient, norm_title
from app.models import Candidate, ParsedName


class StubMeta(MetadataClient):
    def __init__(self, bangumi):
        super().__init__("", use_bangumi=True)
        self.bangumi = bangumi

    def search_bangumi(self, query):
        return [Candidate(**vars(c)) for c in self.bangumi]

    def search_douban(self, query):
        return []

    def search_imdb(self, query):
        return []

    def search_tmdb(self, query, media_type):
        return []

    def _enrich_bangumi(self, cands, limit=2):
        return None

    def save_cache(self):
        pass


def cand(title, original="", year=2019, sid="1", kind="tv"):
    c = Candidate(source="bangumi", title=title, original_title=original,
                  year=year, sid=sid, kind=kind)
    c.extra = {"aliases": []}
    return c


def main():
    meta = MetadataClient("", use_bangumi=False)

    bighero = cand("剧版超能陆战队番外短片", "Big Hero 6: The Series",
                   year=2018, sid="171364")
    # 短锚点“剧版”不能靠前缀命中 Big Hero 6
    assert not meta._candidate_matches_anchor(bighero, ["剧版"])
    # 正常长锚点：中文/英文别名有重合即可
    assert not meta._candidate_matches_anchor(bighero, ["剑尘道魔录之玄劫天锋"])
    assert meta._candidate_matches_anchor(bighero, ["剧版超能陆战队番外短片"])
    overlord = cand("不死者之王", "オーバーロード", year=2015, sid="2")
    assert meta._candidate_matches_anchor(
        overlord, ["不死者之王 Overlord"])
    assert meta._candidate_matches_anchor(
        cand("冰菓", "氷菓"), ["冰菓"])

    # 端到端：Bangumi 同时返回错误 Big Hero 和正确条目，必须只选正确条目
    right = cand("剑尘道魔录之玄劫天锋", year=2019, sid="257162")
    stub = StubMeta([bighero, right])
    parsed = ParsedName(raw="剧版（剑尘道魔录之玄劫天锋 2019）",
                        title="剑尘道魔录之玄劫天锋",
                        queries=["剑尘道魔录之玄劫天锋"], year=2019)
    res = stub.match(parsed, "series")
    assert res.bangumi is not None, res
    assert norm_title(res.bangumi.title) == norm_title("剑尘道魔录之玄劫天锋")
    assert res.bangumi.sid == "257162", res.bangumi.sid
    assert any("忽略标题与本地不一致" in n for n in res.notes), res.notes
    # 预览提示只给数量，不把模糊候选标题列出来，避免误以为采用了它们
    assert not any("超能陆战队" in n for n in res.notes), res.notes

    # 有精确同名条目时，即使模糊候选分数更高，也必须选精确条目
    exact = cand("女子落语", year=2012, sid="exact")
    exact.score = 0.80
    exact.extra = {"anchor_exact": 1, "title_score": 1.0}
    fuzzy = cand("女子落语 OAD", year=2012, sid="fuzzy")
    fuzzy.score = 0.99
    fuzzy.extra = {"anchor_exact": 0, "title_score": 0.9}
    picked = meta._pick_primary([fuzzy, exact], "series")
    assert picked is exact, picked

    imdb_exact = Candidate(source="imdb", title="女子落语", year=2012,
                           sid="tt-exact", kind="tv")
    imdb_exact.score = 0.84
    imdb_exact.extra = {"title_score": 0.9, "imdb_exact": 1}
    imdb_fuzzy = Candidate(source="imdb", title="女子落语 OAD", year=2012,
                           sid="tt-fuzzy", kind="tv")
    imdb_fuzzy.score = 0.99
    imdb_fuzzy.extra = {"title_score": 0.95, "imdb_exact": 0}
    picked = meta._pick_imdb([imdb_fuzzy, imdb_exact], "series", 2012,
                             ("女子落语",))
    assert picked is imdb_exact, picked

    # 只有不相关条目时，宁可返回空结果让上层标“需确认”
    stub2 = StubMeta([bighero])
    res2 = stub2.match(parsed, "series")
    assert res2.bangumi is None, res2.bangumi
    assert res2.confidence == 0.0, res2.confidence

    print("METADATA ANCHOR OK")


if __name__ == "__main__":
    main()
