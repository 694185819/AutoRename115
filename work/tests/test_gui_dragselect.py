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
rows = app.dir_tree.get_children()
print("rows:", rows)
assert len(rows) >= 3
app.dir_tree.selection_set(())
app.update()
assert not app.dir_tree.selection()


def pt(iid):
    x, y, w, h = app.dir_tree.bbox(iid)
    return x + 20, y + h // 2


x0, y0 = pt(rows[0])
x2, y2 = pt(rows[2])
app.dir_tree.event_generate("<Button-1>", x=x0, y=y0, state=0)
app.update()
app.dir_tree.event_generate("<B1-Motion>", x=x2, y=y2, state=0x0100)
app.update()
app.dir_tree.event_generate("<ButtonRelease-1>", x=x2, y=y2, state=0)
app.update()
sel = set(app.dir_tree.selection())
print("drag selected:", sorted(sel))
assert sel == set(rows[:3]), sel
assert "已选 3 项" in app.dir_sel_label.cget("text")

# Ctrl 单击第 2 行：取消
x1, y1 = pt(rows[1])
app.dir_tree.event_generate("<Button-1>", x=x1, y=y1, state=0x0004)
app.dir_tree.event_generate("<ButtonRelease-1>", x=x1, y=y1, state=0x0004)
app.update()
sel = set(app.dir_tree.selection())
print("after ctrl-off:", sorted(sel))
assert sel == {rows[0], rows[2]}, sel

# Ctrl 再点：恢复
app.dir_tree.event_generate("<Button-1>", x=x1, y=y1, state=0x0004)
app.dir_tree.event_generate("<ButtonRelease-1>", x=x1, y=y1, state=0x0004)
app.update()
sel = set(app.dir_tree.selection())
print("after ctrl-on:", sorted(sel))
assert sel == set(rows[:3]), sel

app.destroy()
print("GUI DRAG SELECT OK")
