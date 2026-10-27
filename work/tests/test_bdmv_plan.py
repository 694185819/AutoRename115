# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app.models import MatchResult, P115Item
from app.planner import MediaRoot, NamingOptions, Planner
from app.parser import parse_name


class StubMeta:
    def __init__(self, movie=False, title="黑街", year=2015):
        self.movie = movie
        self.title = title
        self.year = year

    def match(self, parsed, media_type, category=""):
        r = MatchResult()
        r.title_zh = self.title
        r.title_original = "ギャングスタ" if not self.movie else self.title
        r.year = self.year
        r.series_year = self.year
        r.series_title = self.title
        r.series_imdb_id = "tt1234567"
        r.imdb_id = "tt1234567"
        r.confidence = 0.9
        return r

    def save_cache(self):
        pass


p = Planner(StubMeta(), NamingOptions())
item = P115Item(fid="1", parent_id="0", is_dir=True,
                name="[黑街][GANGSTA.][ギャングスタ][BDMV][Vol.1-6 Fin]")
mr = MediaRoot(item=item, unsupported="蓝光目录结构（BDMV），暂不支持")
plan = p._bdmv_plan(mr)
print("series title:", plan.title, plan.year, plan.media_type, plan.category)
for op in plan.ops:
    print("  ", op.role, op.old_name, "->", op.new_name)
assert plan.media_type == "series"
assert plan.ops and plan.ops[0].role == "show"
assert plan.ops[0].new_name == "黑街 (2015) [imdbid-tt1234567]"
assert not any("STREAM" in op.new_name for op in plan.ops)

p2 = Planner(StubMeta(movie=True, title="蓦然回首", year=2016), NamingOptions())
item2 = P115Item(fid="2", parent_id="0", is_dir=True,
                 name="[BDMV][MOVIE] 蓦然回首 [Look Back]")
mr2 = MediaRoot(item=item2, unsupported="蓝光目录结构（BDMV），暂不支持")
plan2 = p2._bdmv_plan(mr2)
print("movie title:", plan2.title, plan2.year, plan2.media_type, plan2.category)
for op in plan2.ops:
    print("  ", op.role, op.old_name, "->", op.new_name)
assert plan2.media_type == "movie"
assert plan2.ops and plan2.ops[0].role == "movie"
assert plan2.ops[0].new_name == \
    "[BDMV][MOVIE] 蓦然回首[imdbid-tt1234567] [Look Back]"

print("BDMV OK")
