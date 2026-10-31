# -*- coding: utf-8 -*-
"""预览窗口布局：字幕很多时能滚动，按钮不被挡住。

用户现象：24 份字幕时，多字幕设置区超出窗口，
看不全、滚动不了，「按选择命名」按钮被掩盖。
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

import tkinter as tk

from app.gui import App
from app.metadata import MetadataClient
from app.models import P115Item
from app.parser import parse_name
from app.planner import (FileEntry, MediaRoot, NamingOptions, Planner)


class _Client:
    def list_dir(self, fid, **k):
        return []

    def list_all(self, fid, **k):
        return []


def make_plan(n_eps=24):
    names = []
    for ep in range(1, n_eps + 1):
        names.append(f"Show S01E{ep:02d}.m2ts")
        names.append(f"[Group] Show [{ep:02d}][Web].JPSC.sup")
        names.append(f"[Group] Show [{ep:02d}][Web].JPTC.sup")
    root = P115Item(fid="root", parent_id="0", name="Show", is_dir=True)
    entries = []
    for i, nm in enumerate(names, 1):
        it = P115Item(fid=f"f{i}", parent_id="root", name=nm,
                      is_dir=False)
        it.size = 1
        entries.append(FileEntry(item=it, parsed=parse_name(nm)))
    mr = MediaRoot(item=root, entries=entries, season_dirs=[],
                   part_dirs=[], subs_dirs=[], nfo_files=[],
                   unsupported="", is_season_root=False, root_season=None)
    m = MetadataClient("", use_bangumi=False, log=lambda s: None)
    o = Planner(m, NamingOptions(jp_folder_style="bdremux",
                                 rename_subtitles=True))
    return o._build_plans(_Client(), mr)[0]


def collect(top, cls):
    out = []

    def walk(w):
        if w.winfo_class() == cls:
            out.append(w)
        for c in w.winfo_children():
            walk(c)

    walk(top)
    return out


def main() -> None:
    p = make_plan(24)
    assert len(p.multi_subs) == 48, len(p.multi_subs)

    app = App(r"I:\实验\AutoRename115")
    app.is_demo = True
    app.busy = False
    for _ in range(40):
        app.update()
        time.sleep(0.05)
    app.plans = [p]
    app.detail_plan = p
    app._render_plans()
    app.preview_ops()
    for _ in range(40):
        app.update()
        time.sleep(0.05)
    time.sleep(0.4)
    app.update()

    top = None
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and "重命名预览" in w.title():
            top = w
    assert top is not None

    h = top.winfo_height()
    print(f"窗口高 {h}px")
    # 窗口必须足够高（内容多时自动放大）
    assert h >= 600, h

    btns = {b.cget("text"): b for b in collect(top, "TButton")}
    for name in ("按选择命名", "全部保留并命名", "关闭", "全选"):
        b = btns.get(name)
        assert b is not None, f"缺少按钮 {name}"
        by = b.winfo_rooty() - top.winfo_rooty()
        bh = b.winfo_height()
        print(f"  {name}: y={by} h={bh}")
        assert by + bh <= h, f"{name} 被挡住（y={by}, 窗口 {h}）"

    # 多字幕区必须有滚动条
    sbs = collect(top, "TScrollbar")
    assert len(sbs) >= 1, "没有滚动条"
    print(f"滚动条 {len(sbs)} 个")

    # 所有字幕复选框都在（可滚动查看）
    cbs = collect(top, "TCheckbutton")
    assert len(cbs) == 48, len(cbs)

    top.destroy()
    app.destroy()
    print("\nPREVIEW LAYOUT OK")


if __name__ == "__main__":
    main()
