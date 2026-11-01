# -*- coding: utf-8 -*-
"""双击右侧任务行直接打开重命名预览窗口。

用户要求：在「等待处理的任务」列表里双击某一行，
直接进入该任务的「重命名预览」窗口。
「选」列留给勾选，双击它不触发预览。
"""
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

import tkinter as tk

from app.gui import App
from app.models import MatchResult, P115Item, ParsedName, PlanItem, RenameOp


def pump(app, sec=1):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def make_plan(i=1):
    it = P115Item(fid=f"r{i}", parent_id="0", name=f"魔道祖师 S{i}",
                  is_dir=True)
    p = PlanItem(item=it, media_type="series",
                 parsed=ParsedName(raw="x", title="魔道祖师", season=i),
                 match=MatchResult(title_zh="魔道祖师", tmdb_id="80732",
                                   year=2018, confidence=1.0),
                 title="魔道祖师", year=2018, category="cn_anime",
                 confidence=1.0)
    p.status = "auto"
    p.selected = True
    p.ops = [RenameOp(fid=f"v{i}", old_name=f"a{i}.m2ts",
                      new_name=f"魔道祖师 S0{i}E01.m2ts", is_dir=False,
                      role="episode", parent_id=f"r{i}")]
    return p


def previews(app):
    return [w for w in app.winfo_children()
            if isinstance(w, tk.Toplevel) and w.winfo_exists()
            and "重命名预览" in w.title()]


def double_click(tree, row, column, app, pad=10):
    bbox = tree.bbox(row, column)
    if not bbox:
        return False
    x = bbox[0] + pad
    y = bbox[1] + bbox[3] // 2
    for _ in (1, 2):
        tree.event_generate("<ButtonPress-1>", x=x, y=y)
        tree.event_generate("<ButtonRelease-1>", x=x, y=y)
        pump(app, 0.05)
    pump(app, 1.2)
    return True


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="arn115_dblprev_test_")
    app = App(tmp)
    app.is_demo = True
    app.busy = False
    pump(app, 2)

    app.plans = [make_plan(1), make_plan(2), make_plan(3)]
    app._render_plans()
    pump(app, 1)

    tree = app.plan_tree
    rows = tree.get_children()
    print("任务行数:", len(rows))
    assert len(rows) == 3
    assert not previews(app), "初始不该有预览窗口"

    # 双击第 2 行 → 打开预览
    ok = double_click(tree, rows[1], "#4", app)
    assert ok, "单元格不可见"
    wins = previews(app)
    print("双击后预览窗口:", len(wins), "| 标题:", wins[0].title() if wins else "")
    assert wins, "双击任务行没有打开预览窗口"
    assert "魔道祖师" in wins[0].title()

    # 关掉，再验证「选」列不触发
    wins[0].destroy()
    pump(app, 0.5)
    before = len(previews(app))
    double_click(tree, rows[0], "#1", app, pad=5)
    after = len(previews(app))
    print("双击「选」列:", before, "→", after)
    assert after == before, "双击「选」列不该打开预览"
    # 双击那一列会切两次勾选，先恢复到已知状态再做单击验证
    app.plans[0].selected = True

    # 「选」列的勾选逻辑仍然有效（直接调用处理函数，避免坐标模拟干扰）
    app.plans[0].selected = True
    sel_bbox = tree.bbox(rows[0], "#1")

    class _E:
        x = sel_bbox[0] + 5
        y = sel_bbox[1] + sel_bbox[3] // 2

    before_sel = app.plans[0].selected
    app._plan_click(_E())
    pump(app, 0.3)
    print("单击「选」列勾选状态:", before_sel, "→", app.plans[0].selected)
    assert app.plans[0].selected != before_sel, "「选」列应能切换勾选"

    app.destroy()
    print("\nDOUBLE CLICK TASK PREVIEW OK")


if __name__ == "__main__":
    main()
