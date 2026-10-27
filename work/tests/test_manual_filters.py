# -*- coding: utf-8 -*-
"""手动搜索结果筛选：类型 / 动画-真人 / 地区 / 未知项。"""
import sys
import tkinter as tk

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.manual_search import (ManualSearchDialog, candidate_animation,
                               candidate_country, candidate_kind)
from app.metadata import MetadataClient
from app.models import Candidate


class EnrichMeta(MetadataClient):
    def __init__(self):
        pass

    def bangumi_detail(self, sid):
        return {"country": "us", "platform": "剧场版",
                "tags": ["美国", "剧场版"]}


def main():
    anime = Candidate(
        source="tmdb", title="动画剧", original_title="Anime Show",
        year=2020, sid="1", kind="tv",
        extra={"country": "jp", "animation": True})
    live = Candidate(
        source="tmdb", title="真人剧", original_title="Live Show",
        year=2021, sid="2", kind="tv",
        extra={"country": "us", "animation": False})
    bgm = Candidate(
        source="bangumi", title="番剧", original_title="Bangumi Show",
        year=2019, sid="3", kind="tv",
        extra={"tags": ["动画"]})
    douban = Candidate(
        source="douban", title="日本动画电影", original_title="Anime Movie",
        year=2018, sid="4", kind="movie",
        extra={"labels": ["2018", "日本", "动画", "电影"]})
    imdb = Candidate(
        source="imdb", title="Unknown Movie", original_title="Unknown Movie",
        year=2017, sid="tt5", kind="movie", extra={"qid": "movie"})
    unknown = Candidate(
        source="douban", title="未知类型", original_title="Unknown Kind",
        year=2016, sid="6", kind="", extra={})

    assert candidate_country(anime) == "jp"
    assert candidate_country(live) == "us"
    assert candidate_country(douban) == "jp"
    assert candidate_country(bgm) == ""
    assert candidate_animation(anime) is True
    assert candidate_animation(live) is False
    assert candidate_animation(bgm) is True
    assert candidate_animation(douban) is True
    assert candidate_animation(imdb) is None
    assert candidate_kind(anime) == "tv"
    assert candidate_kind(bgm) == "tv"
    assert candidate_kind(douban) == "movie"
    assert candidate_kind(unknown) == ""
    assert MetadataClient.normalize_country("法国") == "west"
    assert MetadataClient.normalize_country("fr") == "west"
    assert MetadataClient._tmdb_country(["FR"], "fr") == "west"
    assert MetadataClient._tmdb_country(["US", "FR"], "en") == "us"

    # Bangumi 详情补齐：地区 + 剧场版类型
    enrich_meta = EnrichMeta()
    enrich_meta.enrich_bangumi([bgm], limit=1)
    assert candidate_country(bgm) == "us", bgm.extra
    assert candidate_kind(bgm) == "movie", (bgm.kind, bgm.extra)

    root = tk.Tk()
    root.withdraw()
    dlg = ManualSearchDialog(root, None, "", "series", lambda c, i: None)
    root.update()
    dlg._last_query = "测试"
    dlg._last_queries = ["测试"]
    # 恢复上一段测试改过的 Bangumi 信息，保持筛选场景独立
    bgm.kind = "tv"
    bgm.extra = {"tags": ["动画"]}
    dlg._show_results(
        [anime, live, bgm, douban, imdb, unknown], ["测试 6"])
    root.update()
    assert len(dlg.tree.get_children()) == 6
    assert "共 6 条结果" in dlg.status_var.get(), dlg.status_var.get()

    # 四个来源固定显示，按钮上带结果数
    assert "(6)" in dlg.source_tabs["all"].cget("text")
    assert "(2)" in dlg.source_tabs["douban"].cget("text")
    assert "(1)" in dlg.source_tabs["bangumi"].cget("text")
    assert "(1)" in dlg.source_tabs["imdb"].cget("text")
    assert "(2)" in dlg.source_tabs["tmdb"].cget("text")

    # 点 IMDb 只显示 IMDb，不重新搜索
    dlg.source_filter_var.set("imdb")
    dlg._apply_filters()
    root.update()
    assert [dlg.by_iid[r].title for r in dlg.tree.get_children()] == \
        ["Unknown Movie"]
    assert "IMDb 共 1 条结果" in dlg.status_var.get(), dlg.status_var.get()
    assert "地区未知 1 条" in dlg.filter_hint_var.get(), \
        dlg.filter_hint_var.get()

    # 回到全部来源，再测内容/地区筛选
    dlg.source_filter_var.set("all")
    dlg._apply_filters()
    root.update()

    # 内容=动画：已知真人/未知被排除，并提示隐藏的未知项
    dlg.content_filter_var.set("动画")
    dlg._apply_filters()
    root.update()
    rows = dlg.tree.get_children()
    titles = {dlg.by_iid[r].title for r in rows}
    assert titles == {"动画剧", "番剧", "日本动画电影"}, titles
    assert "筛选后显示 3/6" in dlg.status_var.get(), dlg.status_var.get()
    assert "内容未知 2 条" in dlg.filter_hint_var.get(), \
        dlg.filter_hint_var.get()
    assert "地区未知 3 条" in dlg.filter_hint_var.get(), \
        dlg.filter_hint_var.get()

    # 内容=真人：只保留明确标记为真人的结果
    dlg.content_filter_var.set("真人")
    dlg._apply_filters()
    root.update()
    assert [dlg.by_iid[r].title for r in dlg.tree.get_children()] == ["真人剧"]

    # 内容=未知：只剩没有明确动画/真人标记的结果
    dlg.content_filter_var.set("未知")
    dlg._apply_filters()
    root.update()
    titles = {dlg.by_iid[r].title for r in dlg.tree.get_children()}
    assert titles == {"Unknown Movie", "未知类型"}, titles

    # 地区=日本 + 类型=电影：只剩豆瓣动画电影
    dlg.content_filter_var.set("全部")
    dlg.region_filter_var.set("日本")
    dlg.media_filter_var.set("电影")
    dlg._apply_filters()
    root.update()
    rows = dlg.tree.get_children()
    assert len(rows) == 1, rows
    assert dlg.by_iid[rows[0]].title == "日本动画电影"
    values = dlg.tree.item(rows[0], "values")
    assert values[5] == "动画" and values[6] == "日本", values

    # 地区=未知：显示 Bangumi、IMDb 和类型未知的豆瓣条目
    dlg.media_filter_var.set("全部")
    dlg.region_filter_var.set("未知")
    dlg._apply_filters()
    root.update()
    titles = {dlg.by_iid[r].title for r in dlg.tree.get_children()}
    assert titles == {"番剧", "Unknown Movie", "未知类型"}, titles

    # 类型=未知
    dlg.region_filter_var.set("全部")
    dlg.media_filter_var.set("未知")
    dlg._apply_filters()
    root.update()
    assert [dlg.by_iid[r].title for r in dlg.tree.get_children()] == \
        ["未知类型"]

    # 详情会明确标注来源未提供的字段
    dlg.media_filter_var.set("全部")
    dlg._apply_filters()
    root.update()
    row = next(r for r in dlg.tree.get_children()
               if dlg.by_iid[r].sid == "tt5")
    dlg.tree.selection_set(row)
    dlg._update_detail()
    assert "地区未知" in dlg.detail_var.get(), dlg.detail_var.get()
    assert "内容未知" in dlg.detail_var.get(), dlg.detail_var.get()

    # 重置
    dlg._reset_filters()
    root.update()
    assert len(dlg.tree.get_children()) == 6
    assert "共 6 条结果" in dlg.status_var.get(), dlg.status_var.get()

    dlg._close()
    root.destroy()
    print("MANUAL FILTERS OK")


if __name__ == "__main__":
    main()
