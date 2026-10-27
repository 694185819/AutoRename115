# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app.models import MatchResult
from app.p115 import MockP115Client
from app.planner import NamingOptions, Planner


class StubMeta:
    def match(self, parsed, media_type, category=""):
        r = MatchResult()
        r.title_zh = parsed.title
        r.title_original = parsed.title
        r.year = parsed.year
        r.confidence = 0.9
        r.series_title = parsed.title
        r.series_year = parsed.year
        return r

    def save_cache(self):
        pass


planner = Planner(StubMeta(), NamingOptions(), log=print)
c = MockP115Client()

show = c._add("0", "字幕测试剧.2019", True)
s1 = c._add(show, "Season 1", True)
s2 = c._add(show, "Season 2", True)
v1 = c._add(s1, "字幕测试剧 - 01.mkv", False, 100)
v2 = c._add(s2, "字幕测试剧 - 01.mkv", False, 100)
sd1 = c._add(s1, "Subs", True)
sd2 = c._add(s2, "Subs", True)
sub1 = c._add(sd1, "01.chs.ass", False, 1)
sub2 = c._add(sd2, "01.cht.ass", False, 1)

plans = planner.analyze(c, [c._items[show]])
for p in plans:
    print("PLAN", p.title, p.seasons, p.episodes, p.status)
    for op in p.ops:
        print("  ", op.role, op.old_name, "->", op.new_name)
ops = {op.old_name: op.new_name for p in plans for op in p.ops}
assert ops.get("01.chs.ass") == "字幕测试剧.S01E01.chs.ass", ops
assert ops.get("01.cht.ass") == "字幕测试剧.S02E01.cht.ass", ops
assert ops.get("字幕测试剧.2019") == "字幕测试剧 (2019)", ops
print("SUBS OK")
