# -*- coding: utf-8 -*-
"""命名规则面板：切换来源名后保存，已有任务必须自动重建。

此前 save_naming_rule 只写设置不重建，用户改了“TMDB 英文名 /
自动（所选来源的剧集名）”却看不到文件名变化，以为选项没生效。
"""
import queue
import sys
import tempfile
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtWidgets import QApplication

from app.gui import App
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.naming_panel import NAME_SOURCE_LABELS
from app.qt_ui import MainWindow


class MR:
    def __init__(self):
        self.item = P115Item(fid="root", parent_id="0", name="灵笼",
                             is_dir=True)
        self.sidecars = []
        self.season_dirs = []
        self.unsupported = ""
        self.is_season_root = False
        self.root_season = None


def make_plan():
    match = MatchResult(title_zh="灵笼", series_title="灵笼", year=2019,
                        tmdb_id="91097", country="cn", animation=True,
                        confidence=1.0)
    cand = Candidate(source="tmdb", title="Ling Cage",
                     original_title="Ling Cage", year=2019, sid="91097",
                     kind="tv")
    cand.extra = {}
    cand.score = 1.0
    match.tmdb = cand
    match.source_refs = {"tmdb": {"id": "91097", "title": "Ling Cage",
                                  "year": 2019}}
    plan = PlanItem(item=P115Item(fid="root", parent_id="0", name="灵笼",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="灵笼", title="灵笼", season=1),
                    match=match, title="灵笼", year=2019, category="cn_anime")
    video = P115Item(fid="v1", parent_id="root", name="灵笼 S01E01.mkv",
                     is_dir=False, size=10)
    plan.context = {"mr": MR(), "entries": [type("E", (), {
        "item": video, "is_video": True,
        "parsed": ParsedName(raw=video.name, title="灵笼", season=1,
                             episode=1),
        "folder_season": None, "container": None})()]}
    return plan


def ep_names(plan):
    return [o.new_name for o in plan.ops if o.role == "episode"]


def wait_until(app, cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def main():
    app = QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.data_dir = tempfile.mkdtemp(prefix="arn115_auto_")
    helper.settings = {}
    helper.q = queue.Queue()
    helper.plans = []
    helper.detail_plan = None
    helper.dir_items = {}
    helper.path_stack = [("0", "根目录")]
    helper.app_dir = helper.data_dir
    App._init_meta(helper)

    win = MainWindow(helper, helper.app_dir)
    win.show()
    app.processEvents()

    plan = make_plan()
    helper.plans = [plan]
    win.render_plans()
    app.processEvents()

    panel = win.naming_panel
    # 1) 选“TMDB 英文名”后保存 → 自动重建，文件名带上英文名
    panel.combo_seg.setCurrentText(NAME_SOURCE_LABELS["tmdb"])
    app.processEvents()
    win.save_naming_rule()
    ok = wait_until(app, lambda: ep_names(plan) and
                    "Ling" in ep_names(plan)[0])
    assert ok, ep_names(plan)

    # 2) 选“不显示”后保存 → 自动重建，英文名消失
    panel.combo_seg.setCurrentText(NAME_SOURCE_LABELS["none"])
    app.processEvents()
    win.save_naming_rule()
    ok = wait_until(app, lambda: ep_names(plan) and
                    "Ling" not in ep_names(plan)[0])
    assert ok, ep_names(plan)

    # 设置也同步写入了
    assert helper.settings.get("name_segment_source") == "none", \
        helper.settings.get("name_segment_source")

    win.close()
    print("NAMING AUTO REBUILD OK")


if __name__ == "__main__":
    main()
