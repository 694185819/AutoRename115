# -*- coding: utf-8 -*-
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")
import app.gui as gui
from app import nfo
from app.gui import App

# 屏蔽确认框
gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showinfo = lambda *a, **k: None
gui.messagebox.showwarning = lambda *a, **k: None
gui.messagebox.showerror = lambda *a, **k: print("ERRORBOX:", a)

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()
# 这个用例验证标准日番文件夹格式，不依赖本机设置里选的是哪种风格。
app.settings["jp_folder_style"] = "standard"
app._init_meta()
app.enable_demo()

deadline = time.time() + 10
while time.time() < deadline:
    app.update()
    if app.dir_items:
        break
    time.sleep(0.05)
anime = next(it for it in app.dir_items.values() if it.name == "日番")
app._analyze([anime])
deadline = time.time() + 180
while time.time() < deadline:
    app.update()
    if not app.busy and app.plans:
        break
    time.sleep(0.05)

frieren = next(p for p in app.plans if "芙莉莲" in p.title)
frieren.selected = True
for p in app.plans:
    if p is not frieren:
        p.selected = False
show_fid = frieren.item.fid if frieren.rename_root else None
ep_fids = [op.fid for op in frieren.ops if op.role == "episode"]
print("show_fid", show_fid, "ep_fids", ep_fids, "ops", len(frieren.ops))

app.apply_selected()
deadline = time.time() + 60
while time.time() < deadline:
    app.update()
    if not app.busy and not app.plans:
        break
    time.sleep(0.05)

client = app.client
print("after apply:", client._items[show_fid].name)
for fid in ep_fids:
    print("  ", client._items[fid].name)
assert client._items[show_fid].name.startswith("葬送的芙莉莲 (2023)")
assert all("S01E0" in client._items[fid].name for fid in ep_fids)

app.undo_last()
deadline = time.time() + 60
while time.time() < deadline:
    app.update()
    if not app.busy:
        break
    time.sleep(0.05)
print("after undo:", client._items[show_fid].name)
for fid in ep_fids:
    print("  ", client._items[fid].name)
assert client._items[show_fid].name.startswith("[喵萌奶茶屋&LoliHouse]")
assert all(client._items[fid].name.startswith("[喵萌") for fid in ep_fids)

app.after(300, app.destroy)
app.mainloop()
print("GUI APPLY/UNDO OK")
