# -*- coding: utf-8 -*-
"""预览窗口的「新名称」列可就地编辑（整合原「预览改名」功能）。

用户要求：
  · 不需要额外弹窗/输入框
  · 输入位置就在每行「新名称」列预填的自动命名上
  · 单击只选中；再点同一行 → 进入编辑
"""
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

import tkinter as tk

from app.gui import App
from app.models import P115Item, ParsedName, PlanItem, RenameOp


def pump(app, sec=3):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        time.sleep(0.04)


def make_plan():
    p = PlanItem(item=P115Item(fid="r", parent_id="0", name="Show",
                               is_dir=True),
                 media_type="series",
                 parsed=ParsedName(raw="Show", title="Show", season=1),
                 title="Show", year=2024, category="jp_anime")
    p.ops = [
        RenameOp(fid="v1", old_name="Show S01E01.mkv",
                 new_name="幼女戦記 S01E01.第一集.mkv", is_dir=False,
                 role="episode", parent_id="r"),
        RenameOp(fid="v2", old_name="Show S01E02.mkv",
                 new_name="幼女戦記 S01E02.第二集.mkv", is_dir=False,
                 role="episode", parent_id="r"),
    ]
    return p


def find_tree(widget):
    if widget.winfo_class() == "Treeview":
        return widget
    for c in widget.winfo_children():
        r = find_tree(c)
        if r is not None:
            return r
    return None


def editors(tree):
    return [c for c in tree.winfo_children() if c.winfo_class() == "TEntry"]


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="arn115_inline_test_")
    app = App(tmp)
    app.is_demo = True
    app.busy = False
    pump(app, 2)

    p = make_plan()
    app.plans = [p]
    app.detail_plan = p
    app._render_plans()
    app.preview_ops()
    pump(app, 2)

    top = None
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and "重命名预览" in w.title():
            top = w
    assert top is not None, "预览窗口没打开"
    top.lift()
    pump(app, 1)

    # 菜单里不再有独立的「预览改名」项
    labels = []
    try:
        for i in range(app.plan_menu.index("end") + 1):
            if app.plan_menu.type(i) == "command":
                labels.append(app.plan_menu.entrycget(i, "label"))
    except Exception:      # noqa: BLE001
        pass
    print("菜单(含改名):", [x for x in labels if "改名" in x])
    assert not any("预览改名" in x for x in labels), labels

    tree = find_tree(top)
    items = tree.get_children()
    assert len(items) == 2, items
    tree.selection_set(items[0])
    top.update_idletasks()

    bbox = tree.bbox(items[0], "new")
    assert bbox, "单元格没有显示"
    x, y, w, h = bbox
    cx, cy = x + w // 2, y + h // 2

    # 第 1 次点击：只选中，不弹输入框
    tree.event_generate("<Button-1>", x=cx, y=cy)
    pump(app, 0.3)
    print("单击后输入框:", len(editors(tree)))
    assert len(editors(tree)) == 0, "单击不应进入编辑"

    # 第 2 次点同一行：进入编辑，且预填当前新名称
    tree.event_generate("<Button-1>", x=cx, y=cy)
    pump(app, 0.5)
    eds = editors(tree)
    assert eds, "再点同一行没有进入编辑"
    print("输入框预填:", eds[0].get())
    assert eds[0].get() == p.ops[0].new_name, eds[0].get()

    # 编辑并且回车提交
    eds[0].delete(0, "end")
    eds[0].insert(0, "改好的名字.mkv")
    eds[0].event_generate("<Return>")
    pump(app, 0.5)
    print("提交后:", p.ops[0].new_name)
    assert p.ops[0].new_name == "改好的名字.mkv", p.ops[0].new_name
    assert tree.set(items[0], "new") == "改好的名字.mkv"

    # 第 2 行不受影响
    assert p.ops[1].new_name == "幼女戦記 S01E02.第二集.mkv"

    # Escape 取消不保存
    bbox2 = tree.bbox(items[1], "new")
    x2, y2, w2, h2 = bbox2
    tree.event_generate("<Button-1>", x=x2 + w2 // 2, y=y2 + h2 // 2)
    pump(app, 0.2)
    tree.event_generate("<Button-1>", x=x2 + w2 // 2, y=y2 + h2 // 2)
    pump(app, 0.4)
    eds = editors(tree)
    if eds:
        eds[0].delete(0, "end")
        eds[0].insert(0, "不该保存的名字.mkv")
        eds[0].event_generate("<Escape>")
        pump(app, 0.4)
        print("Escape 后:", p.ops[1].new_name)
        assert p.ops[1].new_name == "幼女戦記 S01E02.第二集.mkv", \
            "Escape 应该取消修改"

    top.destroy()
    app.destroy()
    print("\nPREVIEW INLINE EDIT OK")


if __name__ == "__main__":
    main()
