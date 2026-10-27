# -*- coding: utf-8 -*-
import os
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.metadata import MetadataClient
from app.p115 import MockP115Client
from app.planner import NamingOptions, Planner
from app.undo import UndoManager

CACHE = r"I:\实验\AutoRename115\work\metadata_cache.json"
meta = MetadataClient(CACHE, log=lambda s: print("  META:", s))
planner = Planner(meta, NamingOptions(include_imdb_id=True), log=print)
c = MockP115Client()

# 多季剧
show = c._add("0", "测试剧", True)
s1 = c._add(show, "第一季", True)
s2 = c._add(show, "Season 2", True)
e1 = c._add(s1, "测试剧 - 01.mkv", False, 1000)
e2 = c._add(s2, "测试剧 - 01.mkv", False, 1000)
# 电影目录
movie_dir = c._add("0", "某电影.2019.1080p", True)
mv = c._add(movie_dir, "某电影.2019.1080p.BluRay.mkv", False, 2000)

root = c._items[show]
plans = planner.analyze(c, [root], progress=lambda a, b, m: None)
print("multi-season plans:", len(plans))
for p in plans:
    print("PLAN", p.title, p.year, p.seasons, p.episodes, p.status, p.category)
    for op in p.ops:
        print("  ", op.role, op.old_name, "->", op.new_name)

assert plans and plans[0].seasons == [1, 2], plans[0].seasons
ops = plans[0].ops
roles = {op.role for op in ops}
assert "season" in roles, roles
assert sum(1 for op in ops if op.role == "episode") == 2, ops

# 应用 + 撤销（演示客户端）
results = c.rename_many(ops)
print("apply:", [(r.ok, r.message) for r in results])
assert all(r.ok for r in results), results
new_names = {c._items[e1].name, c._items[e2].name}
print("after apply:", new_names)
assert any("S01E01" in n for n in new_names)
assert any("S02E01" in n for n in new_names)

tmp = tempfile.mkdtemp(prefix="autorename_undo_")
um = UndoManager(tmp)
um.record(ops, results)
um.undo_last(c)
print("after undo:", c._items[e1].name, c._items[e2].name,
      c._items[s1].name, c._items[s2].name)
assert c._items[e1].name == "测试剧 - 01.mkv"
assert c._items[e2].name == "测试剧 - 01.mkv"
assert c._items[s1].name == "第一季"
assert c._items[s2].name == "Season 2"

# 电影
plans2 = planner.analyze(c, [c._items[movie_dir]], progress=lambda a, b, m: None)
print("movie plans:", len(plans2))
for p in plans2:
    print("PLAN", p.media_type, p.title, p.year, p.status)
    for op in p.ops:
        print("  ", op.role, op.old_name, "->", op.new_name)
assert plans2 and plans2[0].media_type == "movie"
# 中文电影没有匹配到 IMDb/TMDB 标识时，保留原名和规格，不强行改名
assert plans2[0].ops == [], plans2[0].ops
assert plans2[0].status == "skip", plans2[0].status

print("PLANNER CASES OK")
meta.save_cache()
