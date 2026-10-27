# -*- coding: utf-8 -*-
import sys
import time
import traceback

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.gui import App

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()


def fail(exc, val, tb):
    traceback.print_exception(exc, val, tb)
    app.destroy()


app.report_callback_exception = fail
app.enable_demo()

# 等目录加载完
deadline = time.time() + 10
while time.time() < deadline:
    app.update()
    if app.dir_items:
        break
    time.sleep(0.05)

anime = next((it for it in app.dir_items.values() if it.name == "日番"), None)
print("anime root:", anime)
assert anime, "演示目录未加载"
app._analyze([anime])

deadline = time.time() + 120
while time.time() < deadline:
    app.update()
    if not app.busy and app.plans:
        break
    time.sleep(0.05)

print("plans:", len(app.plans))
for p in app.plans:
    print("-", p.media_type, p.category, p.status, p.selected, p.title,
          p.year, p.seasons, p.episodes, len(p.ops))
    for op in p.ops:
        print("   ", op.role, op.old_name, "->", op.new_name)

print("table rows:", len(app.plan_tree.get_children()))
if app.plan_tree.get_children():
    app.plan_tree.selection_set(app.plan_tree.get_children()[0])
    app.update()
    print("detail title:", app.title_var.get(), "year:", app.year_var.get(),
          "season:", app.season_var.get(), "category:", app.category_var.get())
    print("meta:", app.meta_label.cget("text"))

app.after(1000, app.destroy)
app.mainloop()
print("GUI ANALYZE OK")
