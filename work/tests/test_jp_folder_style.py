# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.planner import NamingOptions, Planner


def make_plan(jp="86―エイティシックス―"):
    item = P115Item(fid="1", parent_id="0", name="x", is_dir=True)
    m = MatchResult(title_zh="86 -不存在的战区", title_original=jp,
                    series_title="86 -不存在的战区", year=2021,
                    series_year=2021, series_imdb_id="tt13718450",
                    imdb_id="tt13718450", confidence=0.9)
    return PlanItem(item=item, media_type="series",
                    parsed=ParsedName(raw="x", title="86"),
                    match=m, title="86 -不存在的战区", year=2021,
                    category="jp_anime")


for style in ("standard", "bdremux", "bdremux_suffix", "bdremux_no_year"):
    p = Planner(None, NamingOptions(jp_folder_style=style))
    plan = make_plan()
    name = p._folder_name(plan, plan.title, plan.year, "tt13718450", "")
    print(style, "->", name)

p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
name = p._folder_name(make_plan(jp=""), "86 -不存在的战区", 2021,
                      "tt13718450", "")
print("no jp ->", name)
assert name == "[BD-REMUX]86 -不存在的战区 (2021) [imdbid-tt13718450]"

p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
assert p._folder_name(make_plan(), "86 -不存在的战区", 2021,
                      "tt13718450", "") == \
    "[BD-REMUX]86 -不存在的战区 86―エイティシックス― (2021) [imdbid-tt13718450]"

p = Planner(None, NamingOptions(jp_folder_style="bdremux_suffix"))
assert p._folder_name(make_plan(), "86 -不存在的战区", 2021,
                      "tt13718450", "") == \
    "86 -不存在的战区 86―エイティシックス― (2021) [imdbid-tt13718450] [BD-REMUX]"

# 原目录的 [BDMV] 只是来源说明，仍统一用 [BD-REMUX]
plan = make_plan()
plan.item.name = "[BDMV]86 不存在的战区"
p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
name = p._folder_name(plan, plan.title, plan.year, "tt13718450", "")
print("bdmv tag ->", name)
assert name.startswith("[BD-REMUX]86 -不存在的战区"), name
assert not name.startswith("[BDMV]"), name

# 没有日文名时，用 IMDb 英文名补第二段
plan = make_plan(jp="")
plan.match.imdb = Candidate(source="imdb", title="Hyouka",
                            original_title="Hyouka", year=2021,
                            sid="tt13718450", kind="tv")
p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
name = p._folder_name(plan, plan.title, plan.year, "tt13718450", "")
print("imdb fallback ->", name)
assert name == ("[BD-REMUX]86 -不存在的战区 Hyouka (2021) "
                "[imdbid-tt13718450]"), name

# 没有 IMDb 时用 TMDB 英文原名
plan = make_plan(jp="")
plan.match.tmdb = Candidate(source="tmdb", title="86 -不存在的战区",
                            original_title="Hyouka", year=2021,
                            sid="65329", kind="tv")
p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
name = p._folder_name(plan, plan.title, plan.year, "", "65329")
print("tmdb fallback ->", name)
assert name == ("[BD-REMUX]86 -不存在的战区 Hyouka (2021) "
                "[tmdbid-65329]"), name

# 中文名本身就是英文时不要重复
plan = make_plan(jp="")
plan.title = "Hyouka"
plan.match.series_title = "Hyouka"
plan.match.imdb = Candidate(source="imdb", title="Hyouka",
                            original_title="Hyouka", year=2021,
                            sid="tt13718450", kind="tv")
p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
name = p._folder_name(plan, "Hyouka", 2021, "tt13718450", "")
print("no duplicate ->", name)
assert name == "[BD-REMUX]Hyouka (2021) [imdbid-tt13718450]", name

# [BDRip]/[BDRemux] 统一规范成 [BD-REMUX]
for src in ("[BDRip]86 不存在的战区", "[BDRemux]86 不存在的战区"):
    plan = make_plan()
    plan.item.name = src
    p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
    name = p._folder_name(plan, plan.title, plan.year, "tt13718450", "")
    print("normalize tag ->", name)
    assert name.startswith("[BD-REMUX]86 -不存在的战区"), name

# 长标题仍保留 ID
p = Planner(None, NamingOptions(jp_folder_style="bdremux"))
long_title = "这是一个非常非常长的日本番剧标题" * 12
name = p._folder_name(make_plan(), long_title, 2021, "tt13718450", "")
print("long tail:", name[-40:])
assert name.endswith("[imdbid-tt13718450]")
print("JP FOLDER STYLE OK")
