# -*- coding: utf-8 -*-
"""左侧文件/文件夹右键改名：菜单、校验、立即生效、任务同步。"""
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import app.gui as gui
from app.gui import App, DirRenameDialog
from app.models import P115Item, ParsedName, PlanItem, RenameOp

BASE = r"I:\实验\AutoRename115"
errors = []
infos = []
gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showerror = lambda *a, **k: errors.append(a[1] if len(a) > 1 else a)
gui.messagebox.showinfo = lambda *a, **k: infos.append(a[1] if len(a) > 1 else a)
gui.messagebox.showwarning = lambda *a, **k: None


def pump(app, seconds=10, stop=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        if stop is None:
            if not app.busy:
                return
        elif stop():
            return
        time.sleep(0.05)


def main():
    app = App(BASE)
    app.withdraw()
    app.enable_demo()
    pump(app, 10, lambda: bool(app.dir_items) and not app.busy)
    assert app.dir_items, "demo listing failed"

    # 右键菜单存在，包含“重命名”和“进入文件夹”
    assert app.dir_tree.bind("<Button-3>"), "left tree has no right-click binding"
    labels = []
    for i in range(app.dir_menu.index("end") + 1):
        try:
            labels.append(app.dir_menu.entrycget(i, "label"))
        except Exception:
            labels.append("")
    assert any("重命名" in x for x in labels), labels
    assert any("进入文件夹" in x for x in labels), labels

    folder = next(it for it in app.dir_items.values()
                  if it.is_dir and it.name == "日番")

    # 文件夹改名对话框：确认后把新名字交给回调
    picked = []
    dlg = DirRenameDialog(app, folder, lambda it, n: picked.append((it, n)))
    app.update()
    dlg.name_var.set("日番改名")
    dlg._submit()
    app.update()
    assert picked == [(folder, "日番改名")], picked

    # 文件：没写扩展名时自动补回原扩展名
    file_item = P115Item(fid="f1", parent_id="0",
                         name="Show.S01E01.mkv", is_dir=False)
    picked = []
    dlg = DirRenameDialog(app, file_item, lambda it, n: picked.append((it, n)))
    app.update()
    dlg.name_var.set("新的单集")
    dlg._submit()
    app.update()
    assert picked and picked[-1][1] == "新的单集.mkv", picked

    # 文件：换扩展名必须被拦下
    errors.clear()
    picked = []
    dlg = DirRenameDialog(app, file_item, lambda it, n: picked.append((it, n)))
    app.update()
    dlg.name_var.set("新的单集.txt")
    dlg._submit()
    app.update()
    assert errors and "扩展名" in str(errors[-1]), errors
    assert not picked
    dlg.destroy()

    # 直接调用改名执行路径：演示客户端立即返回成功
    app._start_dir_rename(folder, "日番改名")
    pump(app, 15, lambda: (not app.busy and
                           any(it.name == "日番改名"
                               for it in app.dir_items.values())))
    assert folder.name == "日番改名", folder.name
    assert app.client._items[folder.fid].name == "日番改名"
    assert app.undo.last_undoable() is not None

    # 右侧等待任务里的旧名称要同步，避免之后按旧名应用失败
    plan = PlanItem(item=folder, media_type="series",
                    parsed=ParsedName(raw="日番", title="日番"),
                    title="日番")
    plan.ops = [RenameOp(fid=folder.fid, old_name="日番改名",
                         new_name="最终名字", is_dir=True, parent_id="0")]
    app.plans = [plan]
    app._render_plans()
    app.update()
    app._sync_renamed_item(folder, folder.fid, "日番改名", "日番最终")
    assert plan.item.name == "日番最终", plan.item.name
    assert plan.ops[0].old_name == "日番最终", plan.ops[0].old_name

    app.destroy()
    print("DIR RENAME OK")


if __name__ == "__main__":
    main()
