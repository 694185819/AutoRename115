# -*- coding: utf-8 -*-
"""重命名预览勾选：默认全选，可单独取消，应用时只改勾选项。"""
import sys
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, r"I:\实验\AutoRename115")

import app.gui as gui
from app.gui import App
from app.models import MatchResult, ParsedName, PlanItem, RenameOp

BASE = r"I:\实验\AutoRename115"
gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showinfo = lambda *a, **k: None
gui.messagebox.showwarning = lambda *a, **k: None
gui.messagebox.showerror = lambda *a, **k: None


def pump(app, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        if not app.busy:
            return
        time.sleep(0.05)


def find_tree(widget):
    if isinstance(widget, ttk.Treeview):
        return widget
    for child in widget.winfo_children():
        found = find_tree(child)
        if found is not None:
            return found
    return None


def main():
    app = App(BASE)
    app.withdraw()
    app.undo.record = lambda *a, **k: None
    app.enable_demo()
    pump(app, 10)
    app.auto_nfo_var.set(False)
    client = app.client
    fid1 = client._add("0", "第一集.mkv", False, 10)
    fid2 = client._add("0", "第二集.mkv", False, 10)
    plan = PlanItem(
        item=client._items[fid1], media_type="movie",
        parsed=ParsedName(raw="测试电影", title="测试电影"),
        match=MatchResult(title_zh="测试电影"), title="测试电影",
        selected=True)
    plan.ops = [
        RenameOp(fid=fid1, old_name="第一集.mkv",
                 new_name="测试电影.01.mkv", is_dir=False,
                 role="movie", parent_id="0"),
        RenameOp(fid=fid2, old_name="第二集.mkv",
                 new_name="测试电影.02.mkv", is_dir=False,
                 role="movie", parent_id="0"),
    ]
    app.plans = [plan]
    app._render_plans()
    app.update()
    assert all(op.selected for op in plan.ops), "default should be all selected"

    app.deiconify()
    app.preview_ops()
    app.update()
    dialogs = [w for w in app.winfo_children()
               if isinstance(w, tk.Toplevel) and w.winfo_exists()]
    assert dialogs, "preview window missing"
    dlg = dialogs[-1]
    dlg.deiconify()
    app.update()
    tree = find_tree(dlg)
    assert tree is not None
    rows = tree.get_children()
    assert len(rows) == 2, rows
    assert "sel" in tree["columns"], tree["columns"]
    assert tree.set(rows[0], "sel") == "☑"
    assert tree.set(rows[1], "sel") == "☑"

    # 点击“选”列可以取消/恢复
    bbox = tree.bbox(rows[0], "sel")
    assert bbox, "checkbox cell should be visible"
    tree.event_generate("<Button-1>", x=bbox[0] + 2, y=bbox[1] + 2)
    app.update()
    assert plan.ops[0].selected is False, plan.ops[0].selected
    bbox = tree.bbox(rows[0], "sel")
    tree.event_generate("<Button-1>", x=bbox[0] + 2, y=bbox[1] + 2)
    app.update()
    assert plan.ops[0].selected is True, plan.ops[0].selected

    # 取消第一项（键盘空格）
    tree.selection_set(rows[0])
    tree.focus(rows[0])
    tree.focus_set()
    tree.event_generate("<space>")
    app.update()
    assert plan.ops[0].selected is False, plan.ops[0].selected
    assert tree.set(rows[0], "sel") == "☐"
    assert tree.set(rows[1], "sel") == "☑"
    dlg.destroy()
    app.withdraw()

    # 应用时只改勾选的第二项
    app.apply_selected()
    pump(app, 15)
    assert client._items[fid1].name == "第一集.mkv", client._items[fid1].name
    assert client._items[fid2].name == "测试电影.02.mkv", \
        client._items[fid2].name

    app.destroy()
    print("PREVIEW SELECTION OK")


if __name__ == "__main__":
    main()
