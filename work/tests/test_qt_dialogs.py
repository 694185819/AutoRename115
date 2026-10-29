# -*- coding: utf-8 -*-
"""Qt 对话框：设置保存、手动搜索结果渲染、季集映射读取。"""
import queue
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtWidgets import QApplication

from app.gui import App
from app.models import Candidate, MatchResult, P115Item, ParsedName, PlanItem
from app.qt_ui import (EpisodeMappingDialog, MainWindow, ManualSearchDialog,
                       SettingsDialog)


def make_plan():
    item = P115Item(fid="root", parent_id="0", name="灵笼", is_dir=True)
    m = MatchResult(title_zh="灵笼", series_title="灵笼", year=2019,
                    tmdb_id="91097", country="cn", animation=True,
                    confidence=1.0)
    m.source_refs = {}
    p = PlanItem(item=item, media_type="series",
                 parsed=ParsedName(raw="灵笼", title="灵笼", season=1),
                 match=m, title="灵笼", year=2019, category="cn_anime")
    video = P115Item(fid="v1", parent_id="root", name="灵笼 S01E01.mp4",
                     is_dir=False, size=10)
    entry = type("E", (), {
        "item": video, "is_video": True,
        "parsed": ParsedName(raw=video.name, title="灵笼", season=1, episode=1),
        "folder_season": None, "container": None})()
    p.context = {"mr": None, "entries": [entry]}
    return p


def main():
    app = QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.plans = []
    helper.q = queue.Queue()
    helper.detail_plan = None
    helper.dir_items = {}
    helper.path_stack = [("0", "根目录")]
    helper.settings = {"imdb_id_style": "jellyfin", "douban_cookie": ""}
    helper.options = None

    win = MainWindow(helper, r"I:\实验\AutoRename115")
    win.show()
    for _ in range(3):
        app.processEvents()

    # 设置：读取现有值 → 修改 → 保存写回 settings
    dlg = SettingsDialog(win, helper)
    assert dlg.combo_id_style.currentText() == "jellyfin"
    dlg.edit_cookie.setText("bid=x; dbcl2=y")
    dlg.chk_bangumi.setChecked(False)
    dlg.save()
    assert helper.settings["douban_cookie"] == "bid=x; dbcl2=y"
    assert helper.settings["use_bangumi"] is False

    # 手动搜索：关键词来自任务；结果按行渲染；选中后可应用
    plan = make_plan()
    sd = ManualSearchDialog(win, helper, plan)
    assert "灵笼" in sd.edit_query.text()
    cands = [
        Candidate(source="douban", title="灵笼 第一季", original_title="灵笼 第一季",
                  year=2019, sid="27121260", kind="tv"),
        Candidate(source="bangumi", title="灵笼 上半季", original_title="灵笼 上半季",
                  year=2019, sid="269537", kind="tv"),
    ]
    sd._show(cands, "")
    assert sd.table.rowCount() == 2
    assert sd.table.item(0, 1).text() == "灵笼 第一季"
    assert sd.table.item(1, 0).text() == "bangumi"
    sd.table.selectRow(0)
    app.processEvents()
    assert sd.btn_apply.isEnabled()

    # 空结果要有提示
    sd._show([], "没有找到结果")
    assert "没有找到结果" in sd.lbl_hint.text()

    # 季集映射：读出文件名与当前季集
    md = EpisodeMappingDialog(win, helper, plan)
    assert md.table.rowCount() == 1
    assert md.table.item(0, 0).text() == "灵笼 S01E01.mp4"
    assert md.table.item(0, 1).text() == "1"
    assert md.table.item(0, 2).text() == "1"

    win.close()
    print("QT DIALOGS OK")


if __name__ == "__main__":
    main()
