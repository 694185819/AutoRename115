# -*- coding: utf-8 -*-
"""设置窗口：日番格式已移到主界面命名规则面板；底部按钮不被挤压。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App, SettingsDialog
from app.naming_panel import JP_FOLDER_OPTIONS


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def main():
    app = App(tempfile.mkdtemp(prefix="arn115_settings_"))
    app.deiconify()
    app.update()

    # 主界面的命名规则面板里应该有日番格式下拉框
    panel = app.naming_panel
    assert panel is not None
    jp_boxes = [w for w in walk(panel)
                if w.winfo_class() == "TCombobox"
                and set(w.cget("values")) == set(JP_FOLDER_OPTIONS.values())]
    assert jp_boxes, "主界面面板应提供日番文件夹格式"
    print("主界面日番选项:", list(jp_boxes[0].cget("values")))

    # 设置窗口不应再有日番下拉框
    dlg = SettingsDialog(app)
    app.update()
    dup = [w for w in walk(dlg)
           if w.winfo_class() == "TCombobox"
           and set(w.cget("values")) == set(JP_FOLDER_OPTIONS.values())]
    assert not dup, "设置窗口不应重复提供日番格式"
    # 设置窗口也不应再重复命名规则面板
    assert not any(isinstance(w, type(panel)) for w in walk(dlg)), \
        "设置窗口不应重复放置命名规则面板"

    # 底部按钮高度正常（不被挤压）
    buttons = [w for w in walk(dlg)
               if w.winfo_class() == "TButton" and w.winfo_manager()]
    heights = {w.cget("text"): w.winfo_height() for w in buttons}
    print("按钮高度:", heights)
    for text in ("关于…", "保存", "取消"):
        assert heights.get(text, 0) >= 24, (text, heights.get(text))
    outer = dlg.winfo_children()[0]
    assert dlg.winfo_height() >= outer.winfo_reqheight()

    dlg.destroy()
    app.destroy()
    print("SETTINGS LAYOUT OK")


if __name__ == "__main__":
    main()
