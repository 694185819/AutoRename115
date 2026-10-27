# -*- coding: utf-8 -*-
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.gui import App
from app.models import MatchResult, P115Item, ParsedName, PlanItem

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()
app.is_demo = True

p1 = PlanItem(item=P115Item(fid="1", parent_id="0", name="旧1", is_dir=True),
              media_type="series",
              parsed=ParsedName(raw="旧1", title="剧1"),
              match=MatchResult(), title="剧1", year=2020,
              status="auto", selected=True)
p2 = PlanItem(item=P115Item(fid="2", parent_id="0", name="旧2", is_dir=True),
              media_type="series",
              parsed=ParsedName(raw="旧2", title="剧2"),
              match=MatchResult(), title="剧2", year=2021,
              status="review", selected=False)
app.plans = [p1, p2]
app._render_plans()
app.deiconify()
app.update()
print("rows:", app.plan_tree.get_children())
assert len(app.plan_tree.get_children()) == 2

labels = []
for i in range(app.plan_menu.index("end") + 1):
    if app.plan_menu.type(i) != "separator":
        labels.append(app.plan_menu.entrycget(i, "label"))
print("menu:", labels)
assert "从等待列表移除" in labels
assert "清空等待列表" in labels

# 右键处理器（不真正弹出菜单）
app.plan_menu.tk_popup = lambda *a, **k: None
x, y, w, h = app.plan_tree.bbox("p0")
ev = SimpleNamespace(x=x + 10, y=y + h // 2, x_root=0, y_root=0)
app._plan_context(ev)
app.update()
assert app.plan_tree.selection() == ("p0",)

# 移除当前项
app.remove_current_plan()
app.update()
print("after remove:", [p.title for p in app.plans])
assert [p.title for p in app.plans] == ["剧2"]
assert len(app.plan_tree.get_children()) == 1

# 清空
app.clear_plans()
app.update()
assert app.plans == []
assert not app.plan_tree.get_children()
assert app.title_var.get() == ""

app.destroy()
print("GUI CONTEXT OK")
