# -*- coding: utf-8 -*-
"""Qt 命名规则面板：预览随选项变化、配置键与 Tk 版一致、可保存。"""
import queue
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtWidgets import QApplication

from app.gui import App
from app.naming_panel import (JP_FOLDER_OPTIONS, NAME_SOURCE_LABELS,
                              SUBTITLE_LABELS)
from app.qt_ui import MainWindow


def main():
    app = QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.plans = []
    helper.q = queue.Queue()
    helper.detail_plan = None
    helper.dir_items = {}
    helper.path_stack = [("0", "根目录")]
    helper.settings = {}
    helper.options = None

    win = MainWindow(helper, r"I:\实验\AutoRename115")
    win.show()
    for _ in range(5):
        app.processEvents()

    panel = win.naming_panel
    base = panel.preview.text()
    # 默认配置下预览必须展示剧集/日番/电影三类结果
    assert "S01E01" in base and "1080p" in base, base
    assert "日番文件夹" in base and "电影" in base, base

    # 切到“豆瓣 原名”后，来源名那一段应出现
    panel.combo_seg.setCurrentText(NAME_SOURCE_LABELS["douban"])
    app.processEvents()
    assert "灵笼.第一季" in panel.preview.text(), panel.preview.text()

    # 来源名选“不显示” → 该段消失
    panel.combo_seg.setCurrentText(NAME_SOURCE_LABELS["none"])
    app.processEvents()
    assert "第一季" not in panel.preview.text()

    # 规格选“否”
    panel.radio_spec_no.setChecked(True)
    app.processEvents()
    assert "1080p" not in panel.preview.text()

    # 配置键必须与 Tk 版 values() 完全一致，方便共用设置
    vals = panel.values()
    assert set(vals) == {"name_segment_source", "subtitle_source",
                         "include_specs", "jp_folder_style"}, vals
    assert vals["name_segment_source"] == "none"
    assert vals["include_specs"] is False

    # 日番格式切换生效
    panel.combo_jp.setCurrentText(JP_FOLDER_OPTIONS["standard"])
    panel.radio_spec_yes.setChecked(True)
    app.processEvents()
    assert "[BD-REMUX]" not in panel.preview.text().splitlines()[2]

    # 保存写回 settings
    win.save_naming_rule()
    assert helper.settings.get("jp_folder_style") == "standard", \
        helper.settings

    # 下拉项内容完整
    assert panel.combo_sub.count() == len(SUBTITLE_LABELS)
    assert panel.combo_seg.count() == len(NAME_SOURCE_LABELS)

    win.close()
    print("QT NAMING PANEL OK")


if __name__ == "__main__":
    main()
