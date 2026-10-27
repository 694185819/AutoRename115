# -*- coding: utf-8 -*-
"""右窗口临时改名：真实改名后的任务状态更新。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app import gui
from app.gui import App, TempRenameDialog
from app.models import (MatchResult, P115Item, ParsedName, PlanItem, RenameOp)
from app.p115 import RenameResult

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()
app.is_demo = True
app.undo.record = lambda *a, **k: None  # 不写测试环境的 undo.json

show_item = P115Item(fid="show", parent_id="0", name="旧剧名", is_dir=True)
p = PlanItem(item=show_item, media_type="series",
             parsed=ParsedName(raw="旧剧名", title="测试剧"),
             match=MatchResult(), title="测试剧", year=2020,
             status="auto", selected=True)
show_op = RenameOp(fid="show", old_name="旧剧名", new_name="新剧名",
                   is_dir=True, role="show", parent_id="0")
ep_op = RenameOp(fid="ep", old_name="旧 01.mkv", new_name="新剧名 S01E01.mkv",
                 is_dir=False, role="episode", parent_id="show")
sub_op = RenameOp(fid="sub", old_name="01.ass", new_name="新剧名 S01E01.ass",
                  is_dir=False, role="subtitle", parent_id="show")
p.ops = [show_op, ep_op, sub_op]
p.context = {"mr": None, "entries": []}
app.plans = [p]
app._render_plans()
app.deiconify()
app.update()

# 1) 临时改名一集：该集和对应字幕从任务移除，其余保留
new_ep = RenameOp(fid="ep", old_name="旧 01.mkv",
                  new_name="自定义 01.mkv", is_dir=False,
                  role="episode", parent_id="show")
res = RenameResult(fid="ep", old_name="旧 01.mkv",
                   new_name="自定义 01.mkv", ok=True)
app._after_temp_rename(p, ep_op, new_ep, [res])
app.update()
print("remaining:", [(o.role, o.new_name) for o in p.ops])
assert [o.role for o in p.ops] == ["show"]
assert p.ops[0].new_name == "新剧名"

# 2) 临时改名剧集文件夹：更新当前名称并移除该操作
new_show = RenameOp(fid="show", old_name="旧剧名",
                    new_name="手动剧名", is_dir=True,
                    role="show", parent_id="0")
res2 = RenameResult(fid="show", old_name="旧剧名",
                    new_name="手动剧名", ok=True)
app._after_temp_rename(p, show_op, new_show, [res2])
app.update()
assert show_item.name == "手动剧名"
assert p.ops == []
assert app.plans == []
assert not app.plan_tree.get_children()

# 3) 扩展名不能被临时改名改掉
bad = RenameOp(fid="ep2", old_name="x.mkv", new_name="x.avi",
               is_dir=False, role="episode", parent_id="show")
problem = app._validate_ops([bad])
assert "扩展名不一致" in problem, problem

# 4) 对话框选择/提交
p2 = PlanItem(item=P115Item(fid="f2", parent_id="0", name="旧名",
                            is_dir=True),
              media_type="movie",
              parsed=ParsedName(raw="旧名", title="电影"),
              match=MatchResult(), title="电影", year=2020,
              status="auto", selected=True)
p2.ops = [RenameOp(fid="f2", old_name="旧名", new_name="电影 (2020)",
                   is_dir=True, role="movie", parent_id="0")]
picked = []
gui.messagebox.askyesno = lambda *a, **k: True
dlg = TempRenameDialog(app, p2, lambda plan, op, name: picked.append(
    (plan, op, name)))
app.update()
dlg.name_var.set("手动电影名")
dlg._submit()
app.update()
assert picked and picked[0][2] == "手动电影名", picked

# 5) 真实调用 Mock 115 接口改名
import time
from app.p115 import MockP115Client
c = MockP115Client()
fid = c._add("0", "旧文件.mkv", False, 10)
p3 = PlanItem(item=c._items[fid], media_type="movie",
              parsed=ParsedName(raw="旧文件", title="旧文件"),
              match=MatchResult(), title="旧文件", year=2020,
              status="auto", selected=True)
p3.ops = [RenameOp(fid=fid, old_name="旧文件.mkv",
                   new_name="计划名.mkv", is_dir=False,
                   role="movie", parent_id="0")]
app.client = c
app.current_cid = "0"
app.plans = [p3]
app._render_plans()
app.update()
app._start_temp_rename(p3, p3.ops[0], "真正改名.mkv")
deadline = time.time() + 10
while time.time() < deadline:
    app.update()
    if c._items[fid].name == "真正改名.mkv" and not app.busy:
        break
    time.sleep(0.05)
print("mock renamed:", c._items[fid].name, "ops", len(p3.ops))
assert c._items[fid].name == "真正改名.mkv"
assert p3.ops == []
assert app.plans == []

app.destroy()
print("GUI TEMP RENAME OK")
