# -*- coding: utf-8 -*-
"""decider.py 单测：候选集合 → MatchResult，不启动网络与 MetadataClient。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import decider
from app.metadata import norm_title
from app.models import Candidate, ParsedName
from app.textnorm import titles_agree


def cand(source, title, original="", year=2020, sid="1", kind="tv",
         extra=None, score=0.0):
    c = Candidate(source=source, title=title, original_title=original,
                  year=year, sid=sid, kind=kind, score=score)
    c.extra = dict(extra or {})
    return c


def logs():
    out = []
    return out, out.append


def main():
    # 1) 精确同名压过近似番外
    parsed = ParsedName(raw="x", title="女子落语", queries=["女子落语"],
                        year=2012)
    main_c = cand("bangumi", "女子落语", "じょしらく", 2012, "bg-main",
                  extra={"aliases": ["じょしらく"]})
    oad_c = cand("bangumi", "女子落语 OAD 番外", "", 2012, "bg-oad")
    res = decider.decide(parsed, "series", "", {"bangumi": [oad_c, main_c]},
                         lambda s: None)
    assert res.bangumi is not None and res.bangumi.sid == "bg-main", \
        res.bangumi
    assert res.title_zh == "女子落语"
    assert res.title_original == "じょしらく"

    # 2) 锚点过滤：无关候选被丢弃并记录备注
    note_log, log = logs()
    wrong = cand("bangumi", "剧版超能陆战队番外短片", "Big Hero 6", 2018,
                 "bg-wrong")
    res2 = decider.decide(parsed, "series", "", {"bangumi": [wrong]}, log)
    assert res2.bangumi is None, res2.bangumi
    assert any("忽略标题与本地不一致" in n for n in res2.notes), res2.notes
    assert any("剧版超能陆战队" in line for line in note_log), note_log
    assert res2.confidence == 0.0, res2.confidence

    # 3) 跨来源核对：和主结果不一致的 Bangumi 不贡献原名/地区
    parsed3 = ParsedName(raw="x", title="寄生兽：灰色部队",
                         queries=["寄生兽：灰色部队"], year=2024)
    tmdb_c = cand("tmdb", "寄生兽：灰色部队", "Parasyte: The Grey", 2024,
                  "208825", extra={"country": "kr", "animation": False})
    other_bg = cand("bangumi", "寄生兽：灰色部队 动画版", "寄生獣", 2014,
                    "bg-other", extra={"tags": ["动画"],
                                       "country": "jp"})
    # 让 tmdb 成为主结果：拉高分数
    tmdb_c.score = 0.99
    res3 = decider.decide(parsed3, "series", "",
                          {"tmdb": [tmdb_c], "bangumi": [other_bg]},
                          lambda s: None)
    assert res3.tmdb is not None and res3.tmdb.sid == "208825"
    assert res3.bangumi is None, res3.bangumi
    assert not res3.animation, "不一致的 Bangumi 不能标记动画"
    assert res3.country == "kr", res3.country
    assert any("忽略来源不一致" in n for n in res3.notes), res3.notes

    # 4) 主剧还原：季条目找回首播年和主剧 IMDb
    parsed4 = ParsedName(raw="x", title="庆余年 第二季",
                         queries=["庆余年 第二季"], season=2)
    season_c = cand("bangumi", "庆余年 第二季", "庆余年 第二季", 2024,
                    "bg-s2")
    def ident(base):
        assert base == "庆余年", base
        return {"title": "庆余年", "year": 2019, "imdb_id": "tt11273352",
                "country": "cn", "animation": False}
    res4 = decider.decide(parsed4, "series", "", {"bangumi": [season_c]},
                          lambda s: None)
    decider.identify_series(parsed4, "series", res4, ident)
    assert res4.is_season_entry
    assert res4.series_title == "庆余年", res4.series_title
    assert res4.series_year == 2019, res4.series_year
    assert res4.series_imdb_id == "tt11273352", res4.series_imdb_id

    # 5) 无季号时不走主剧还原
    parsed5 = ParsedName(raw="x", title="某剧", queries=["某剧"])
    base_c = cand("bangumi", "某剧", "", 2020, "bg-1")
    res5 = decider.decide(parsed5, "series", "", {"bangumi": [base_c]},
                          lambda s: None)
    called = []
    decider.identify_series(parsed5, "series", res5,
                            lambda b: called.append(b) or {})
    assert not called, called
    assert res5.series_title == "某剧", res5.series_title

    # 6) 电影年份过滤：年份差 >1 的同名候选被排除
    parsed6 = ParsedName(raw="x", title="大海鱼棠", queries=["大海鱼棠"],
                         year=2016)
    near = cand("bangumi", "大海鱼棠", "", 2016, "bg-ok", kind="movie")
    far = cand("bangumi", "大海鱼棠", "", 1999, "bg-old", kind="movie")
    near.score, far.score = 0.9, 0.95
    res6 = decider.decide(parsed6, "movie", "",
                          {"bangumi": [near, far]}, lambda s: None)
    assert res6.bangumi is not None and res6.bangumi.sid == "bg-ok", \
        res6.bangumi

    # 7) dedupe：同来源同 ID 只留高分
    a = cand("bangumi", "某剧", "", 2020, "same", score=0.5)
    b = cand("bangumi", "某剧 修正", "", 2020, "same", score=0.8)
    out = decider.dedupe([a, b])
    assert len(out) == 1 and out[0].score == 0.8

    # 8) 分类偏向：动画目录里明确非动画的条目降权
    anime_folder = cand("tmdb", "降世神通 第二季", "", 2006, "t1",
                        extra={"animation": False}, score=0.9)
    decider.apply_category_bias("us_anime", {"tmdb": [anime_folder]})
    assert anime_folder.score < 0.9, anime_folder.score

    print("DECIDER OK")


if __name__ == "__main__":
    main()
