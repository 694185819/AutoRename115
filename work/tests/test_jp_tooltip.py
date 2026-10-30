# -*- coding: utf-8 -*-
"""「日番 ⓘ」悬浮提示：说明日番会自动套用规则，可改「不使用」跳过。"""
import queue
import sys
import tempfile
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.naming_panel import JP_STYLE_TOOLTIP


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def test_text():
    """提示文案要点明“自动生效”和“可选择不使用跳过”。"""
    assert "自动" in JP_STYLE_TOOLTIP, JP_STYLE_TOOLTIP
    assert "不使用" in JP_STYLE_TOOLTIP, JP_STYLE_TOOLTIP
    assert "日番" in JP_STYLE_TOOLTIP


def test_tk_tooltip():
    """Tk：标签带 ⓘ，悬浮后真的弹出提示窗。"""
    app = App(tempfile.mkdtemp(prefix="arn115_tip_"))
    app.deiconify()
    app.update()
    panel = app.naming_panel
    assert panel is not None

    labels = [w for w in walk(panel)
              if w.winfo_class() == "TLabel"
              and str(w.cget("text")) == "日番"]
    assert labels, "应有「日番」标签"
    lab = labels[0]
    assert lab.bind("<Enter>"), "标签应绑定 Enter"

    lab.event_generate("<Enter>")
    app.update()
    time.sleep(0.8)
    app.update()

    tips = [w for w in walk(app)
            if w is not app and w.winfo_class() == "Toplevel"
            and w.winfo_ismapped()]
    assert tips, "悬浮后应弹出提示窗"
    found = False
    for t in tips:
        for inner in walk(t):
            try:
                txt = str(inner.cget("text"))
            except Exception:
                continue
            if "不使用" in txt:
                found = True
    assert found, "提示窗里应有说明文字"

    lab.event_generate("<Leave>")
    app.update()
    app.destroy()


def test_qt_tooltip():
    """Qt：标签与下拉框都带 tooltip。"""
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel

    from app.qt_ui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.data_dir = tempfile.mkdtemp(prefix="arn115_qtip_")
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
    panel = win.naming_panel

    labels = [l for l in panel.findChildren(QLabel)
              if (l.text() or "") == "日番"]
    assert labels, "Qt 应有「日番」标签"
    assert "不使用" in labels[0].toolTip(), labels[0].toolTip()

    combos = [c for c in panel.findChildren(QComboBox)
              if "BD-REMUX" in (c.currentText() or "")]
    assert combos, "Qt 应有日番下拉框"
    assert "不使用" in combos[0].toolTip(), combos[0].toolTip()
    win.close()


def main():
    test_text()
    test_tk_tooltip()
    test_qt_tooltip()
    print("JP TOOLTIP OK")


if __name__ == "__main__":
    main()
