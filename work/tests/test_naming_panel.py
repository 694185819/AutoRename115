# -*- coding: utf-8 -*-
"""命名规则在主界面：面板可见、改设置后同步、保存为默认并重建。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import json
import tempfile

from app.gui import App, SettingsDialog
from app.naming_rule import NAME_SOURCE_LABELS


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def main():
    tmp = tempfile.mkdtemp(prefix="arn115_panel_")
    app = App(tmp)
    app.deiconify()
    app.update()

    # 主界面必须有命名规则面板，且窗口里能找到
    panel = app.naming_panel
    assert panel is not None, "主界面未加载命名规则面板"
    found = any(w is panel for w in walk(app))
    assert found, "命名规则面板不在主窗口里"
    print("主界面预览:", panel.preview.cget("text"))
    assert "S01E01" in panel.preview.cget("text")

    # 设置窗口不再重复放置面板
    dlg = SettingsDialog(app)
    app.update()
    dup = any(isinstance(w, type(panel)) and w is not panel for w in walk(dlg))
    assert not dup, "设置窗口不应重复放置命名规则面板"
    dlg.destroy()
    app.update()

    # 改来源 → 预览变化 → 保存为默认
    panel.seg_var.set(NAME_SOURCE_LABELS["none"])
    panel._refresh_preview()
    app.update()
    assert "Ling.Cage" not in panel.preview.cget("text")

    app.apply_naming_rule()
    app.update()
    s = json.load(open(tmp + "/data/settings.json", encoding="utf-8"))
    assert s.get("name_segment_source") == "none", s.get("name_segment_source")
    assert app.options.name_segment_source == "none"

    # 外部改设置后，面板能同步回来
    app.apply_settings({"name_segment_source": "tmdb",
                        "include_specs": False})
    app.update()
    assert panel.seg_var.get() == NAME_SOURCE_LABELS["tmdb"], \
        panel.seg_var.get()
    assert panel.spec_var.get() is False

    app.destroy()
    print("NAMING PANEL OK")


if __name__ == "__main__":
    main()
