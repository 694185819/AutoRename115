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
app.deiconify()
app.update()
row = app.dir_tree.get_children()[0]
x, y, w, h = app.dir_tree.bbox(row)
x += 20
y += h // 2
print("before path:", len(app.path_stack), app.path_stack)
app.dir_tree.event_generate("<Button-1>", x=x, y=y)
app.dir_tree.event_generate("<ButtonRelease-1>", x=x, y=y)
app.update()
time.sleep(0.08)
app.dir_tree.event_generate("<Button-1>", x=x, y=y)
app.dir_tree.event_generate("<ButtonRelease-1>", x=x, y=y)
app.update()
time.sleep(0.5)
app.update()
print("after path:", len(app.path_stack), app.path_stack)
assert len(app.path_stack) >= 2, "double click did not navigate"
app.destroy()
print("DOUBLE CLICK OK")
