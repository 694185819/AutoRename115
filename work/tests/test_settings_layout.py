# -*- coding: utf-8 -*-
"""设置窗口：日番文件夹格式只保留两种；底部按钮不被挤压。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App, JP_FOLDER_LABELS, SettingsDialog


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def main():
    # 只保留“标准”和“你的风格”两种写法
    assert set(JP_FOLDER_LABELS) == {"standard", "bdremux"}, JP_FOLDER_LABELS
    labels = list(JP_FOLDER_LABELS.values())
    assert not any("标签在后" in v or v.endswith("[BD-REMUX]") or
                   "日文名 [ID]" in v for v in labels), labels

    app = App(tempfile.mkdtemp(prefix="arn115_settings_"))
    app.deiconify()
    app.update()
    dlg = SettingsDialog(app)
    app.update()

    combos = [w for w in walk(dlg) if w.winfo_class() == "TCombobox"]
    jp = [c for c in combos if len(c.cget("values")) == len(JP_FOLDER_LABELS)]
    assert jp, "找不到日番格式下拉框"
    assert list(jp[0].cget("values")) == labels, \
        jp[0].cget("values")

    # 旧配置值 bdremux_suffix 落到默认“你的风格”，不会显示空白
    app.settings["jp_folder_style"] = "bdremux_suffix"
    dlg2 = SettingsDialog(app)
    app.update()
    combos2 = [w for w in walk(dlg2)
               if w.winfo_class() == "TCombobox"
               and len(w.cget("values")) == len(JP_FOLDER_LABELS)]
    assert combos2 and combos2[0].get() == \
        JP_FOLDER_LABELS["bdremux"], combos2[0].get() if combos2 else None
    dlg2.destroy()

    # 按钮区恢复正常高度（被挤压时约 16px，正常约 27px）
    buttons = [w for w in walk(dlg)
               if w.winfo_class() == "TButton" and w.winfo_manager()]
    heights = {w.cget("text"): w.winfo_height() for w in buttons}
    for text in ("关于…", "保存", "取消"):
        assert heights.get(text), f"缺少按钮 {text}"
    assert min(heights.values()) >= 24, heights
    outer = dlg.winfo_children()[0]
    assert dlg.winfo_height() >= outer.winfo_reqheight(), (
        dlg.winfo_height(), outer.winfo_reqheight())

    dlg.destroy()
    app.destroy()
    print("SETTINGS LAYOUT OK")


if __name__ == "__main__":
    main()
