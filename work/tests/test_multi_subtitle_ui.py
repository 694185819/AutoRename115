# -*- coding: utf-8 -*-
"""预览窗口的多字幕设置区（三重锁的 ②③）。

① 自动检测：planner 完成，plan.multi_sub_mode / multi_subs
② 人为确认：勾选要保留的字幕
③ 预览修改：新名称实时写回 p.ops 并显示在表格
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
from app.planner import FileEntry, MediaRoot, NamingOptions, Planner


class _Client:
    def list_dir(self, fid, **k):
        return []

    def list_all(self, fid, **k):
        return []


NAMES = [
    "Show [01][Web].mkv",
    "Show [02][Web].mkv",
    "Show [01][Web].JPSC.sup",
    "Show [01][Web].JPTC.sup",
    "Show [02][Web].JPSC.sup",
    "Show [02][Web].JPTC.sup",
]


def make_plan():
    root = P115Item(fid="root", parent_id="0", name="Show", is_dir=True)
    entries = []
    for i, n in enumerate(NAMES, 1):
        it = P115Item(fid=f"f{i}", parent_id="root", name=n,
                      is_dir=False)
        it.size = 1
        entries.append(FileEntry(item=it, parsed=parse_name(n)))
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
    p = make_plan()
    assert p.multi_subs, "没有触发多字幕机制"
    assert p.multi_sub_mode == "jp_bilingual", p.multi_sub_mode
    print("检测:", p.multi_sub_mode, "| 登记", len(p.multi_subs), "份")

    app = App(r"I:\实验\AutoRename115")
    app.withdraw()
    app.is_demo = True
    app.busy = False
    for _ in range(40):
        app.update()
        time.sleep(0.05)
    app.plans = [p]
    app.detail_plan = p
    app._render_plans()
    app.preview_ops()
    for _ in range(30):
        app.update()
        time.sleep(0.05)

    top = None
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and "重命名预览" in w.title():
            top = w
    assert top is not None, "预览窗口没打开"

    # ① 界面上必须出现多字幕设置区
    labels = [str(w.cget("text")) for w in collect(top, "TLabelframe")]
    hit = [t for t in labels if "多字幕设置" in t]
    print("设置区标题:", hit)
    assert hit, labels

    checks = collect(top, "TCheckbutton")
    assert len(checks) == 4, [c.cget("text") for c in checks]

    btns = {b.cget("text"): b for b in collect(top, "TButton")}

    # ② 只保留 01 简日 + 02 繁日
    keep = ["[01][Web].JPSC", "[02][Web].JPTC"]
    for c in checks:
        want = any(k in str(c.cget("text")) for k in keep)
        app.setvar(str(c.cget("variable")), 1 if want else 0)
    app.update()
    btns["按选择命名"].invoke()
    app.update()

    subs = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("按选择后:", subs)
    assert len(subs) == 2, subs
    assert any("E01" in s and "简日" in s for s in subs), subs
    assert any("E02" in s and "繁日" in s for s in subs), subs
    assert not {n for n in subs if subs.count(n) > 1}

    # ③ 全部保留
    btns["全部保留并命名"].invoke()
    app.update()
    subs2 = [o.new_name for o in p.ops if o.role == "subtitle"]
    print("全部保留后:", len(subs2), "条")
    assert len(subs2) == 4, subs2
    assert not {n for n in subs2 if subs2.count(n) > 1}, subs2

    top.destroy()
    app.destroy()
    print("\nMULTI SUB UI OK")


if __name__ == "__main__":
    main()
