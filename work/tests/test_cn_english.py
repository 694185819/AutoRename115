# -*- coding: utf-8 -*-
"""中国电视剧补充英文名：庆余年 -> Joy of Life。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import Candidate, MatchResult, P115Item
from app.parser import parse_name
from app.planner import NamingOptions, Planner
from app.models import PlanItem


class FakeMeta:
    def tmdb_english_title(self, tmdb_id, kind="tv"):
        # 274493 是“庆余年第二季”，TMDB 英文接口仍只有中文名
        return ""

    def tmdb_english_by_imdb(self, imdb_id, media_type=""):
        if imdb_id == "tt11273352":
            return "Joy of Life"
        return ""


def main():
    parsed = parse_name("庆余年.第二季.S02E01.2160p.WEB-DL.mkv")
    item = P115Item(fid="v1", parent_id="p", name=parsed.raw, is_dir=False)
    match = MatchResult(
        title_zh="庆余年第二季", title_original="庆余年",
        tmdb_id="274493", series_title="庆余年",
        series_year=2019, series_imdb_id="tt11273352",
        tmdb=Candidate(source="tmdb", title="庆余年第二季",
                       original_title="庆余年第二季", year=2024,
                       sid="274493", kind="tv"))
    plan = PlanItem(item=item, media_type="series", parsed=parsed,
                    match=match, title="庆余年", year=2019,
                    category="tv", context={})
    planner = Planner(FakeMeta(), NamingOptions())
    en = planner._english_title(plan)
    print("english:", repr(en))
    assert en == "Joy of Life", en
    print("CN ENGLISH OK")


if __name__ == "__main__":
    main()
