# -*- coding: utf-8 -*-
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.gui import App

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()
app.enable_demo()

deadline = time.time() + 10
while time.time() < deadline:
    app.update()
    if app.dir_items:
        break
    time.sleep(0.05)
anime = next(it for it in app.dir_items.values() if it.name == "日番")
app._analyze([anime])
deadline = time.time() + 120
while time.time() < deadline:
    app.update()
    if not app.busy and app.plans:
        break
    time.sleep(0.05)

# 找到进击的巨人，设置季 = 4
rows = app.plan_tree.get_children()
for iid in rows:
    p = app.plan_rows[iid]
    if "进击" in p.title:
        app.plan_tree.selection_set(iid)
        app.update()
        app.season_var.set("4")
        app.rebuild_detail()
        app.update()
        print("AoT title:", app.title_var.get(), "season:", app.season_var.get(),
              "selected:", p.selected, "status:", p.status)
        for op in p.ops:
            print("  ", op.role, op.old_name, "->", op.new_name)
        assert any("S04E01" in op.new_name for op in p.ops), p.ops
        break

# 芙莉莲改成电视剧，应带规格
for iid in rows:
    p = app.plan_rows[iid]
    if "芙莉莲" in p.title:
        app.plan_tree.selection_set(iid)
        app.update()
        app.category_var.set("电视剧（中英+副标题）")
        app.rebuild_detail()
        app.update()
        print("Frieren category:", p.category)
        for op in p.ops:
            print("  ", op.role, op.new_name)
        assert any("1080p" in op.new_name for op in p.ops), p.ops
        break

app.after(500, app.destroy)
app.mainloop()
print("GUI EDIT OK")
