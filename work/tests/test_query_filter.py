# -*- coding: utf-8 -*-
"""搜索词过滤：单字容器名（“剧”）和裸豆瓣号不能进入元数据搜索。

回归案例：寄生兽：灰色部队_35954429 位于根目录“剧”下，
之前会用“剧”去搜 Bangumi/TMDB，命中“剧场版 城市猎人”“宝可梦剧场版”
“喜剧之王单口季”等完全不相关的条目。
"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
sys.path.insert(0, r"I:\实验\AutoRename115\work\tests")

from app.metadata import MetadataClient
from app.models import Candidate, ParsedName, P115Item
from app.parser import parse_name

FOLDER = ("寄生兽：灰色部队_35954429[全6集][简繁英字幕]"
          "Parasyte.The.Grey.S01.2024.2160p.NF.WEB-DL.DDP5.1.Atmos.HDR.H.265-LelveTV")
FILE = ("Parasyte.The.Grey.S01E01.2024.2160p.NF.WEB-DL."
        "DDP5.1.Atmos.HDR.H.265-LelveTV.mkv")


def main():
    p = parse_name(FOLDER, is_dir=True)
    assert "35954429" not in p.title, p.title
    assert all("35954429" not in q for q in p.queries), p.queries

    # 根目录“剧”不能再被当成片名/搜索词
    from app.planner import _is_generic_dir, _usable_query
    for word in ("剧", "番", "片", "影", "电视剧", "动画"):
        assert _is_generic_dir(word), word
        assert not _usable_query(word), word
    assert _usable_query("寄生兽:灰色部队")
    assert _usable_query("Parasyte The Grey")
    # 01.m2ts/02 m2ts 这类纯文件名，以及 01/02 序号，不能当片名搜索
    for word in ("01.m2ts", "02.m2ts", "01 m2ts", "01", "02", "001.m2ts"):
        assert not _usable_query(word), word
    # 数字本身可能是片名，不能一刀切
    for word in ("86", "1917", "SAC 2045"):
        assert _usable_query(word), word

    # planner 最终交给元数据的搜索词里不能有“剧”/裸豆瓣号
    from app.planner import Planner, MediaRoot, FileEntry
    folder = P115Item(fid="p", parent_id="0", name=FOLDER, is_dir=True,
                      ancestors=["剧"])
    video = P115Item(fid="v1", parent_id="p", name=FILE, is_dir=False)
    mr = MediaRoot(item=folder, entries=[FileEntry(video, parse_name(FILE))])
    planner = Planner(None)
    fp = planner._context_parsed(mr)
    search = planner._search_parsed(mr, mr.entries, fp)
    assert "剧" not in search.queries, search.queries
    assert all("35954429" not in q for q in search.queries), search.queries
    assert any("寄生兽" in q for q in search.queries), search.queries
    assert any("Parasyte" in q for q in search.queries), search.queries

    # 单字查询不再靠 partial_ratio 拿到接近 1.0 的标题分
    meta = MetadataClient("", use_bangumi=False)
    parsed = ParsedName(raw="剧", title="剧", queries=["剧"])
    cand = Candidate(source="tmdb", title="剧场版 城市猎人 新宿私家侦探 真人版",
                     year=2023, kind="movie")
    meta._score(parsed, cand, "movie")
    assert cand.extra["title_score"] < 0.5, cand.extra

    # 正常的长标题仍然能拿到高分
    parsed2 = ParsedName(raw=FOLDER, title="寄生兽:灰色部队",
                         queries=["寄生兽:灰色部队", "Parasyte The Grey"],
                         year=2024)
    good = Candidate(source="tmdb", title="寄生兽：灰色部队",
                     original_title="기생수: 더 그레이", year=2024, kind="tv")
    meta._score(parsed2, good, "series")
    assert good.extra["title_score"] >= 0.9, good.extra

    print("OK query filter")


if __name__ == "__main__":
    main()
