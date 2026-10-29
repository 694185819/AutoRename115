# -*- coding: utf-8 -*-
"""主界面高度：右栏各区块必须完整显示，不能被压缩到看不见。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App


def main():
    app = App(tempfile.mkdtemp(prefix="arn115_h_"))
    app.deiconify()
    for _ in range(25):
        app.update()

    screen_h = app.winfo_screenheight()
    print("屏幕高:", screen_h, "| 窗口:", app.winfo_width(),
          "x", app.winfo_height())
    assert app.winfo_height() <= screen_h - 40, "窗口不应超出屏幕"

    right = app.paned.winfo_children()[-1]
    sections = [w for w in right.winfo_children()
                if w.winfo_class() == "TLabelframe"]
    assert sections, "右栏应有多个区块"
    for w in sections:
        text = str(w.cget("text"))[:16]
        print(f"  {text}: 实际 {w.winfo_height()} / 需要 {w.winfo_reqheight()}")
        assert w.winfo_height() >= min(w.winfo_reqheight(), 80), (
            text, w.winfo_height(), w.winfo_reqheight())

    # 命名规则面板与运行日志不能被压成一条
    panel = app.naming_panel
    assert panel is not None and panel.winfo_height() >= 60, "命名规则面板被压扁"
    logs = [w for w in sections
            if "运行日志" in str(w.cget("text"))]
    assert logs and logs[0].winfo_height() >= 60, "运行日志被压扁"

    # 右栏整体够高
    assert right.winfo_height() >= right.winfo_reqheight() * 0.95, (
        right.winfo_height(), right.winfo_reqheight())

    app.destroy()
    print("MAIN LAYOUT OK")


if __name__ == "__main__":
    main()
