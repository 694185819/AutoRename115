# -*- coding: utf-8 -*-
"""手动套用 IMDb 英文条目后，中文主名称必须保留。

用户截图：手动搜索选了 IMDb 的「Ever Night 2」，
结果文件名变成 Ever.Night.2.Ever.Night.S02E01…，
中文名「将夜」丢失、英文还重复了一遍。

根因三处：
  1. m.title_zh = cand.title or ...（cand.title 是英文）
  2. m.series_title = base（base 也是英文）
  3. p.title = base（最终文件名用的是它）
  4. 来源名与主标题相同时没有去重
"""
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem


class MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="将夜",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def make_plan(title_zh="将夜"):
    match = MatchResult(title_zh=title_zh, series_title=title_zh,
                        year=2018, country="cn", confidence=0.9)
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="将夜",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="将夜", title="将夜", season=2),
                    match=match, title=title_zh, year=2018,
                    category="cn_anime")
    v = P115Item(fid="v1", parent_id="root",
                 name="将夜II.Ever.Night.S02E01.2160p.WEB-DL.H264.mkv",
                 is_dir=False, size=10)
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": v, "is_video": True,
        "parsed": ParsedName(raw=v.name, title="将夜", season=2, episode=1),
        "folder_season": None, "container": None})()]}
    return plan


def _destroy(app):
    """先取消挂起的 after 任务再销毁，否则 Tk 会报 set_sash 之类残留错误。"""
    try:
        for aid in app.tk.splitlist(app.tk.call("after", "info")):
            try:
                app.after_cancel(aid)
            except Exception:
                pass
    except Exception:
        pass
    try:
        app.update()
    except Exception:
        pass
    app.destroy()


def build_app():
    app = App(tempfile.mkdtemp(prefix="arn115_mc_"))
    app.withdraw()
    app.settings["name_segment_source"] = "imdb"
    app._init_meta()
    app.is_demo = True
    app.busy = False
    return app


def test_chinese_kept():
    """手动选英文 IMDb 条目后，主标题和文件名仍是中文。"""
    app = build_app()
    plan = make_plan()
    app.plans = [plan]
    app._render_plans()
    app.update()

    cand = Candidate(source="imdb", title="Ever Night 2",
                     original_title="", year=2020, sid="tt10856380",
                     kind="tv")
    cand.extra = {}
    app._apply_manual_candidate(plan, cand,
                                {"imdb_id": "tt10856380", "tmdb_id": ""})

    assert plan.match.title_zh == "将夜", plan.match.title_zh
    assert plan.title == "将夜", plan.title
    assert plan.match.series_title == "将夜", plan.match.series_title
    eps = [o.new_name for o in plan.ops if o.role == "episode"]
    assert eps and eps[0].startswith("将夜"), eps[:1]
    _destroy(app)


def test_english_not_duplicated():
    """来源名不能和主标题重复（Ever.Night.2.Ever.Night）。"""
    app = build_app()
    plan = make_plan()
    app.plans = [plan]
    app._render_plans()
    app.update()

    cand = Candidate(source="imdb", title="Ever Night 2",
                     original_title="", year=2020, sid="tt10856380",
                     kind="tv")
    cand.extra = {}
    app._apply_manual_candidate(plan, cand,
                                {"imdb_id": "tt10856380", "tmdb_id": ""})
    eps = [o.new_name for o in plan.ops if o.role == "episode"]
    name = eps[0]
    print("剧集名:", name)
    assert name.count("Ever") <= 1, name
    _destroy(app)


def test_english_only_stays_english():
    """本地本来就没有中文名时，允许用英文，不能强行变空。"""
    app = build_app()
    plan = make_plan(title_zh="")
    plan.title = ""
    app.plans = [plan]
    app._render_plans()
    app.update()

    cand = Candidate(source="imdb", title="Ever Night 2",
                     original_title="", year=2020, sid="tt10856380",
                     kind="tv")
    cand.extra = {}
    app._apply_manual_candidate(plan, cand,
                                {"imdb_id": "tt10856380", "tmdb_id": ""})
    assert plan.title, "不应为空"
    _destroy(app)


def main():
    test_chinese_kept()
    test_english_not_duplicated()
    test_english_only_stays_english()
    print("MANUAL MATCH KEEPS CHINESE OK")


if __name__ == "__main__":
    main()
