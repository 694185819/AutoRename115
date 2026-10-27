# -*- coding: utf-8 -*-
"""scoring.py 单测：不启动 MetadataClient，只测打分/锚点/挑选规则。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import scoring
from app.models import Candidate, ParsedName
from app.textnorm import norm_title
from rapidfuzz import fuzz


def cand(title, original="", year=2019, sid="1", kind="tv",
         extra=None, score=0.0, rank=0):
    c = Candidate(source="bangumi", title=title, original_title=original,
                  year=year, sid=sid, kind=kind, score=score, rank=rank)
    c.extra = dict(extra or {})
    return c


def test_anchor_titles_split():
    parsed = ParsedName(raw="x", title="异国日记",
                        queries=["异国日记", "IkokuNikki"])
    anchors = scoring.anchor_titles(parsed)
    assert "异国日记" in anchors and "IkokuNikki" in anchors, anchors
    assert scoring.candidate_matches_anchor(
        cand("异国日记", "異国日記", extra={"aliases": ["Ikoku Nikki"]}),
        anchors)


def test_weak_anchor_rejected():
    """“剧版”这种发布说明不能当锚点命中 Big Hero 6。"""
    bighero = cand("剧版超能陆战队番外短片", "Big Hero 6: The Series", 2018)
    assert not scoring.candidate_matches_anchor(bighero, ["剧版"])
    assert not scoring.candidate_matches_anchor(
        bighero, ["剑尘道魔录之玄劫天锋"])


def test_short_anchor_needs_exact():
    """2 字锚点只认完全同名，不能靠包含关系命中。"""
    assert scoring.candidate_matches_anchor(cand("冰菓"), ["冰菓"])
    assert not scoring.candidate_matches_anchor(cand("冰菓 第二季"), ["冰菓"])
    # 3 字以上允许“官方名包含本地简称”
    assert scoring.candidate_matches_anchor(
        cand("女子落语 じょしらく"), ["女子落语"])


def test_oad_downgraded():
    """番外条目不能只靠 partial 相似度抢走主条目。"""
    parsed = ParsedName(raw="x", title="女子落语", queries=["女子落语"],
                        year=2012)
    main = cand("女子落语", year=2012, sid="main")
    oad = cand("女子落语 OAD 番外", year=2012, sid="oad")
    sm = scoring.score(parsed, main, "series")
    so = scoring.score(parsed, oad, "series")
    assert sm > so, (sm, so)
    picked = scoring.pick_primary([oad, main], "series")
    assert picked.sid == "main", picked.sid


def test_partial_discounted_for_short_candidate():
    """候选名明显长于匹配段时，partial 分会被打折。

    注意 WRatio 本身仍可能给出高分（“女子落语”对“女子落语OAD番外”
    ≈0.9），真正把这类条目压下去的是“非精确 + 番外降权 + 精确优先”。
    """
    assert scoring._title_similarity("女子落语", "女子落语") == (1.0, True)
    longer_name = norm_title("女子落语OAD番外")
    value, exact = scoring._title_similarity("女子落语", longer_name)
    assert not exact
    # 长度比 9/4 > 1.67，partial 只算 0.6 折：1.0*0.6=0.6，
    # 低于不打折时 raw partial 会给到的 1.0。
    raw_partial = fuzz.partial_ratio("女子落语", longer_name) / 100.0
    assert raw_partial == 1.0
    shorter, _ = scoring._title_similarity("女子落语", longer_name)
    assert shorter < raw_partial, (shorter, raw_partial)


def test_season_weight():
    """季号明确时，第三季不能抢第四季的任务。"""
    parsed = ParsedName(raw="x", title="科拉传奇", queries=["科拉传奇"],
                        year=2012, season=4)
    s3 = cand("降世神通：科拉传奇 第三季", year=2014, sid="s3")
    s4 = cand("降世神通：科拉传奇 第四季", year=2014, sid="s4")
    assert scoring.score(parsed, s4, "series") > \
        scoring.score(parsed, s3, "series")
    assert s4.extra["season_score"] == 1.0
    assert s3.extra["season_score"] == 0.0


def test_file_season_drops_season_aliases():
    """本地没写季号、季号来自文件名时，“第一季”类别名不作锚点。"""
    parsed = ParsedName(raw="x", title="某剧", queries=["某剧", "第一季"],
                        file_season=2)
    anchors = scoring.anchor_titles(parsed)
    assert "第一季" not in anchors, anchors
    assert scoring.season_alias("第一季")
    assert scoring.season_alias("Season 3")
    assert not scoring.season_alias("某剧 第一季")


def test_pick_imdb_prefers_exact():
    exact = cand("女子落语", year=2012, sid="tt-exact")
    exact.score = 0.84
    exact.extra = {"title_score": 0.9, "imdb_exact": 1}
    fuzzy = cand("女子落语 OAD", year=2012, sid="tt-fuzzy")
    fuzzy.score = 0.99
    fuzzy.extra = {"title_score": 0.95, "imdb_exact": 0}
    picked = scoring.pick_imdb([fuzzy, exact], "series", 2012, ("女子落语",))
    assert picked.sid == "tt-exact", picked.sid


def test_animation_flag():
    assert scoring.candidate_is_animation(
        cand("x", extra={"animation": True}))
    assert scoring.candidate_is_animation(
        Candidate(source="bangumi", title="x", extra={"tags": ["动画"]}))
    assert not scoring.candidate_is_animation(cand("x"))


def main():
    test_anchor_titles_split()
    test_weak_anchor_rejected()
    test_short_anchor_needs_exact()
    test_oad_downgraded()
    test_partial_discounted_for_short_candidate()
    test_season_weight()
    test_file_season_drops_season_aliases()
    test_pick_imdb_prefers_exact()
    test_animation_flag()
    print("SCORING OK")


if __name__ == "__main__":
    main()
