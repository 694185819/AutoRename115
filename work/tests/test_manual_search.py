# -*- coding: utf-8 -*-
"""手动搜索：应用搜索结果、补齐 ID、结果列表。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
sys.path.insert(0, r"I:\实验\AutoRename115\work\tests")

from app.gui import App
from app.manual_search import ManualSearchDialog
from app.metadata import MetadataClient
from app.models import Candidate, MatchResult, P115Item, PlanItem
from app.parser import parse_name
from test_ancestor_context import (FakeClient, FakeMeta, build_raw_bd_show,
                                   NamingOptions, Planner)

BASE = r"I:\实验\AutoRename115"


class ResolveMeta(MetadataClient):
    def __init__(self):
        self.tmdb_key = ""
        self.calls = []

    def bangumi_detail(self, sid):
        self.calls.append(("bangumi_detail", sid))
        return {"aliases": ["Hyouka", "冰菓"], "country": "jp", "tags": []}

    def search_imdb(self, query):
        self.calls.append(("imdb", query))
        c = Candidate(source="imdb", title="Hyouka", year=2012,
                      sid="tt2340841", kind="tv")
        c.extra = {"aliases": [], "qid": "tvSeries"}
        return [c]

    def search_tmdb(self, query, media_type):
        return []


def main():
    # resolve_ids：从 Bangumi 选择补齐 IMDb
    rm = ResolveMeta()
    ids = rm.resolve_ids(
        Candidate(source="bangumi", title="冰菓", original_title="氷菓",
                  year=2012, sid="400602", kind="tv"), "series")
    assert ids["imdb_id"] == "tt2340841", ids
    assert ids["imdb_title"] == "Hyouka", ids
    assert ids["country"] == "jp", ids
    assert any(q == "Hyouka" for kind, q in rm.calls if kind == "imdb"), \
        rm.calls

    # 应用到任务
    show, client = build_raw_bd_show()
    meta = FakeMeta("末日后酒店", "アポカリプスホテル", 2025, "tt32906586")
    p = Planner(meta, NamingOptions()).analyze(client, [show])[0]
    assert p.media_type == "series" and len(p.episodes) == 12

    app = App(BASE)
    app.withdraw()
    app.is_demo = True
    app.plans = [p]
    app._render_plans()
    app.update()
    keywords = app._manual_keywords(p)
    assert keywords, keywords
    assert app._manual_season(p) == 1, app._manual_season(p)
    app._apply_manual_candidate(
        p,
        Candidate(source="bangumi", title="冰菓", original_title="氷菓",
                  year=2012, sid="400602", kind="tv"),
        {"imdb_id": "tt2340841", "tmdb_id": "", "country": "jp"})
    app.wait_for_rebuild()
    app.update()
    assert p.title == "冰菓", p.title
    assert p.year == 2012, p.year
    assert p.match.series_imdb_id == "tt2340841", p.match.series_imdb_id
    assert p.confidence == 1.0
    assert p.category == "jp_anime", p.category
    show_ops = [o for o in p.ops if o.role == "show"]
    assert show_ops and show_ops[0].new_name == \
        "[BD-REMUX]冰菓 氷菓 (2012) [imdbid-tt2340841]", show_ops
    assert [o.new_name for o in p.ops if o.role == "episode"][:2] == \
        ["氷菓 S01E01.m2ts", "氷菓 S01E02.m2ts"]
    assert app.title_var.get() == "冰菓", app.title_var.get()
    assert "手动搜索" in p.note, p.note

    # 结果列表排序/选择
    picked = []
    dlg = ManualSearchDialog(app, rm, "", "series",
                             lambda c, i: picked.append((c, i)))
    app.update()
    dlg._last_query = "冰菓"
    dlg._show_results([
        Candidate(source="imdb", title="Hyouka", year=2012,
                  sid="tt2340841", kind="tv"),
        Candidate(source="bangumi", title="时间的彼端", year=2025,
                  sid="536603", kind="tv"),
        Candidate(source="bangumi", title="冰菓", original_title="氷菓",
                  year=2012, sid="400602", kind="tv",
                  extra={"country": "jp", "first_air_date": "2012-04-22",
                         "overview": "测试简介", "vote_average": 8.2}),
    ], ["IMDb 1", "Bangumi 2"])
    app.update()
    rows = dlg.tree.get_children()
    assert len(rows) == 3, rows
    first = dlg.by_iid[rows[0]]
    assert first.source == "bangumi" and first.title == "冰菓", first
    dlg.tree.selection_set(rows[0])
    dlg._update_detail()
    assert dlg._selected_candidate().sid == "400602"
    assert "日本" in dlg.detail_var.get(), dlg.detail_var.get()
    assert "首播 2012-04-22" in dlg.detail_var.get(), dlg.detail_var.get()
    assert "测试简介" in dlg.detail_var.get(), dlg.detail_var.get()
    assert "共 3 条结果" in dlg.status_var.get()
    dlg._close()

    # 模糊搜索：带季号的关键词和结果排序
    dlg2 = ManualSearchDialog(
        app, rm, "", "series", lambda c, i: None,
        keywords=["降世神通：科拉传奇", "降世神通：科拉传奇 第四季",
                  "The Legend of Korra Season 4"],
        season=4, year=2012)
    app.update()
    dlg2._last_query = "降世神通：科拉传奇"
    dlg2._last_queries = ["降世神通：科拉传奇",
                          "降世神通：科拉传奇 第四季"]
    dlg2._show_results([
        Candidate(source="douban", title="降世神通：科拉传奇 第三季",
                  original_title="The Legend of Korra", year=2014,
                  sid="3", kind="tv"),
        Candidate(source="douban", title="降世神通：科拉传奇 第四季",
                  original_title="The Legend of Korra", year=2014,
                  sid="4", kind="tv"),
        Candidate(source="tmdb", title="降世神通：科拉传奇",
                  original_title="The Legend of Korra", year=2012,
                  sid="33880", kind="tv"),
    ], ["豆瓣 2"])
    app.update()
    rows = dlg2.tree.get_children()
    assert dlg2.by_iid[rows[0]].sid == "4", dlg2.by_iid[rows[0]]
    assert "模糊 2 组" in dlg2.status_var.get(), dlg2.status_var.get()
    dlg2._close()

    # 关键词拆解：本地目录名优先，自动匹配的错误别名不能混进来
    sac_item = P115Item(
        fid="sac", parent_id="p", name="攻壳机动队 SAC 2045", is_dir=True,
        ancestors=["动画", "2、日本", "[BD-REMUX]攻壳机动队"])
    sac_parsed = parse_name(sac_item.name, is_dir=True)
    assert sac_parsed.title == "攻壳机动队 SAC 2045", sac_parsed.title
    sac_plan = PlanItem(
        item=sac_item, media_type="series", parsed=sac_parsed,
        match=MatchResult(
            title_zh="攻壳机动队 THE GHOST IN THE SHELL",
            title_original="攻殻機動隊 THE GHOST IN THE SHELL",
            bangumi=Candidate(
                source="bangumi", title="攻壳机动队 SAC_2045",
                original_title="攻殻機動隊 SAC_2045", year=2020,
                sid="212610", kind="tv",
                extra={"aliases": ["SAC", "攻壳机动队 SAC_2045"]}),
            tmdb_id="1095", confidence=1.0),
        title="攻壳机动队 THE GHOST IN THE SHELL",
        year=2026, season=1, seasons=[1])
    sac_kw = app._manual_keywords(sac_plan)
    assert sac_kw[0] == "攻壳机动队 SAC 2045", sac_kw
    assert "攻壳机动队" in sac_kw, sac_kw
    assert not any("THE GHOST" in k for k in sac_kw), sac_kw
    assert not any(".m2ts" in k for k in sac_kw), sac_kw
    assert "SAC" not in sac_kw, sac_kw

    # 季目录/说明目录：用上级作品名，不拿说明文字当片名
    s2_item = P115Item(
        fid="s2", parent_id="p", name="S2-美版暂无日语字幕sup", is_dir=True,
        ancestors=["动画", "2、日本", "[BD-REMUX]攻壳机动队",
                   "攻壳机动队 SAC 2045"])
    s2_plan = PlanItem(
        item=s2_item, media_type="series",
        parsed=parse_name(s2_item.name, is_dir=True),
        title="美版暂无日语字幕sup", year=2026, season=2, seasons=[2])
    s2_kw = app._manual_keywords(s2_plan)
    assert s2_kw[0] == "攻壳机动队 SAC 2045", s2_kw
    assert not any("美版暂无日语字幕" in k for k in s2_kw), s2_kw

    # 关键词是普通文字（带 · 分隔），不是按钮
    dlg3 = ManualSearchDialog(
        app, rm, "", "series", lambda c, i: None,
        keywords=sac_kw, season=1)
    app.update()
    shown = dlg3.keyword_text.get("1.0", "end-1c")
    assert "攻壳机动队 SAC 2045" in shown, shown
    assert "·" in shown, shown
    # Text 不能禁用（禁用后标签点击不触发），但要拦住键盘编辑
    assert str(dlg3.keyword_text.cget("state")) == "normal"
    assert dlg3.keyword_text.bind("<Key>"), "keyword Text should be read-only"
    app.deiconify()
    dlg3.deiconify()
    app.update()
    clicked = []
    dlg3._search_keyword = lambda t: clicked.append(t)
    bbox = dlg3.keyword_text.bbox("1.0")
    assert bbox, "keyword Text should be visible in test"
    dlg3.keyword_text.event_generate(
        "<Motion>", x=bbox[0] + 2, y=bbox[1] + 2)
    dlg3.keyword_text.event_generate(
        "<Button-1>", x=bbox[0] + 2, y=bbox[1] + 2)
    app.update()
    assert clicked == ["攻壳机动队 SAC 2045"], clicked
    dlg3._close()

    app.destroy()
    print("MANUAL SEARCH OK")


if __name__ == "__main__":
    main()
