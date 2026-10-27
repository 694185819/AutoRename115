# -*- coding: utf-8 -*-
"""自动搜索精准度回归：混合中英文本地名、近似番外、文件名季号。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient, norm_title
from app.models import Candidate, MatchResult, P115Item, ParsedName
from app.planner import NamingOptions, Planner


class StubMeta(MetadataClient):
    """按搜索词返回预设候选，模拟 Bangumi/TMDB 的真实返回形态。"""

    def __init__(self, bangumi_by_query, tmdb_by_query=None):
        super().__init__("", use_bangumi=True)
        self.bangumi_by_query = bangumi_by_query
        self.tmdb_by_query = tmdb_by_query or {}

    def search_bangumi(self, query):
        return [Candidate(**vars(c)) for c in
                self.bangumi_by_query.get(query, [])]

    def search_douban(self, query):
        return []

    def search_imdb(self, query):
        return []

    def search_tmdb(self, query, media_type):
        return [Candidate(**vars(c)) for c in
                self.tmdb_by_query.get(query, [])]

    def _enrich_bangumi(self, cands, limit=2):
        return None

    def save_cache(self):
        pass


def cand(title, original, year, sid, aliases=(), kind="tv",
         source="bangumi"):
    c = Candidate(source=source, title=title, original_title=original,
                  year=year, sid=sid, kind=kind)
    c.extra = {"aliases": list(aliases)}
    return c


def test_mixed_name_anchor():
    """目录“异国日记 Ikoku Nikki”要能用英文别名匹配到官方条目。"""
    meta = MetadataClient("", use_bangumi=False)
    parsed = ParsedName(raw="[BD-REMUX]异国日记 [Ikoku Nikki]",
                        title="异国日记", queries=["异国日记", "Ikoku Nikki"])
    anchors = meta._anchor_titles(parsed)
    assert "Ikoku Nikki" in anchors, anchors
    official = cand("异国日记", "異国日記", 2026, "official",
                    aliases=["Ikoku Nikki", "異国日記"])
    assert meta._candidate_matches_anchor(official, anchors)
    # 完全无关的候选仍然必须被淘汰
    wrong = cand("剧场版 城市猎人 新宿私家侦探", "City Hunter", 2019, "x")
    assert not meta._candidate_matches_anchor(wrong, anchors)


def test_match_picks_official_over_fuzzy():
    """同名番外/近似条目不能抢走主条目；混合名也能进自动。"""
    years = 2026
    main = cand("异国日记", "異国日記", years, "main",
                aliases=["Ikoku Nikki"])
    oad = cand("异国日记 OAD 番外", "異国日記 OAD", years, "oad")
    stub = StubMeta({"异国日记": [oad, main], "Ikoku Nikki": [main]})
    parsed = ParsedName(raw="[BD-REMUX]异国日记 [Ikoku Nikki]",
                        title="异国日记", queries=["异国日记", "Ikoku Nikki"],
                        year=years)
    res = stub.match(parsed, "series")
    assert res.bangumi is not None, res.notes
    assert norm_title(res.bangumi.title) == norm_title("异国日记"), \
        res.bangumi.title
    assert res.confidence > 0.6, res.confidence

    # 只有无关候选时宁可空结果（上层标需确认），不能硬选
    stub2 = StubMeta({"异国日记": [cand("城市猎人", "City Hunter", 2019,
                                        "other")]})
    res2 = stub2.match(parsed, "series")
    assert res2.bangumi is None, res2.bangumi


def test_file_season_used():
    """目录名没写季号、文件名写 S2E01 时，季号要参与搜索。"""
    parsed = ParsedName(raw="某剧", title="某剧", queries=["某剧"])
    seen = {}

    class SeasonMeta(MatchResult):
        pass

    class Meta:
        def match(self, parsed, media_type, category_hint=""):
            seen["season"] = parsed.season
            return MatchResult(title_zh=parsed.title, series_title=parsed.title,
                               year=2020, tmdb_id="1", confidence=1.0)

        def save_cache(self):
            pass

        def season_episode_titles(self, *a, **k):
            return {}

    def item(fid, parent, name, is_dir):
        return P115Item(fid=fid, parent_id=parent, name=name, is_dir=is_dir,
                        size=100)

    class Client:
        def list_dir(self, cid, page_size=500):
            if cid == "root":
                return [item(f"v{i}", "root", f"某剧.S2E{i:02d}.mkv", False)
                        for i in (1, 2, 3)]
            return []

    root = P115Item(fid="root", parent_id="0", name="某剧", is_dir=True,
                    ancestors=["动画"])
    Planner(Meta(), NamingOptions()).analyze(Client(), [root])
    assert seen.get("season") == 2, seen


def test_container_not_split_for_season_variants():
    """目录“X”里是“X 第二季”文件时，仍是一部剧的目录而不是合集。"""
    calls = []

    class Meta:
        def match(self, parsed, media_type, category_hint=""):
            calls.append((parsed.title, parsed.season))
            return MatchResult(title_zh="某剧", series_title="某剧", year=2020,
                               tmdb_id="1", confidence=1.0)

        def save_cache(self):
            pass

        def season_episode_titles(self, *a, **k):
            return {}

    class Client:
        def list_dir(self, cid, page_size=500):
            if cid == "root":
                names = ["某剧 S01E01.mkv", "某剧 S01E02.mkv",
                         "某剧 第二季 S02E01.mkv", "某剧 第二季 S02E02.mkv"]
                return [P115Item(fid=f"v{i}", parent_id="root", name=n,
                                 is_dir=False, size=10)
                        for i, n in enumerate(names)]
            return []

    root = P115Item(fid="root", parent_id="0", name="某剧", is_dir=True,
                    ancestors=["动画"])
    plans = Planner(Meta(), NamingOptions()).analyze(Client(), [root])
    assert len(plans) == 1, [(p.media_type, p.item.name) for p in plans]
    assert plans[0].rename_root, plans[0].rename_root
    print("SEARCH PRECISION OK")


if __name__ == "__main__":
    test_mixed_name_anchor()
    test_match_picks_official_over_fuzzy()
    test_file_season_used()
    test_container_not_split_for_season_variants()
