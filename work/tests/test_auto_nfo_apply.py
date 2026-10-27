# -*- coding: utf-8 -*-
"""应用重命名时的可选自动 NFO：成功后自动保存，失败有提示。"""
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import app.gui as gui
from app.gui import App
from app.models import MatchResult, ParsedName, PlanItem, RenameOp
from app.p115 import MockP115Client

BASE = r"I:\实验\AutoRename115"
infos = []
warnings = []
gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showinfo = lambda *a, **k: infos.append(a[1] if len(a) > 1 else a)
gui.messagebox.showwarning = lambda *a, **k: warnings.append(
    a[1] if len(a) > 1 else a)
gui.messagebox.showerror = lambda *a, **k: warnings.append(
    a[1] if len(a) > 1 else a)


def pump(app, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        if not app.busy:
            return
        time.sleep(0.05)


def make_plan(client, fid, title="电影"):
    item = client._items[fid]
    p = PlanItem(item=item, media_type="movie",
                 parsed=ParsedName(raw=item.name, title="旧电影"),
                 match=MatchResult(title_zh=title, tmdb_id="123",
                                   confidence=1.0),
                 title=title, year=2020, selected=True)
    p.ops = [RenameOp(fid=fid, old_name=item.name,
                      new_name=title + " (2020) [tmdbid-123].mkv",
                      is_dir=False, role="movie", parent_id="0")]
    p.context = {"mr": None, "entries": []}
    return p


def main():
    app = App(BASE)
    app.withdraw()
    app.undo.record = lambda *a, **k: None
    app._save_settings = lambda: None

    # 勾选“改名后自动存 NFO/图片”
    app.auto_nfo_var.set(True)
    app._on_auto_nfo_toggle()
    assert app.settings["auto_nfo_after_rename"] is True

    client = MockP115Client()
    fid = client._add("0", "旧电影.mkv", False, 10)
    p = make_plan(client, fid)
    app.client = client
    app.is_demo = False
    app.busy = False
    app.plans = [p]
    app._render_plans()
    app.update()

    calls = []

    real_batch = app._save_nfo_batch

    def fake_batch(plans, progress=None, phase_label="2/2", **kwargs):
        calls.extend(plans)
        if progress:
            progress(0, 1, f"阶段 {phase_label}：准备 NFO/图片")
            progress(1, 1, f"阶段 {phase_label}：上传完成")
        return [{"plan": plan, "uploads": 2, "renames": 1,
                 "deleted": 0, "skipped": 0, "units": 1}
                for plan in plans]

    app._save_nfo_batch = fake_batch
    app.apply_selected()
    pump(app, 15)
    assert client._items[fid].name == "电影 (2020) [tmdbid-123].mkv", \
        client._items[fid].name
    assert calls == [p], calls
    assert infos and "自动保存 NFO/图片" in infos[-1], infos
    assert "上传 2" in infos[-1], infos
    assert app.plans == [], "apply should clear tasks after auto NFO"

    # 自动 NFO 失败：要保留错误提示，且改名本身仍然成功
    infos.clear()
    warnings.clear()
    fid2 = client._add("0", "旧电影2.mkv", False, 10)
    p2 = make_plan(client, fid2, title="电影2")
    app.plans = [p2]
    app._render_plans()
    app.update()

    original_batch = app._save_nfo_batch

    def boom(plans, progress=None, phase_label="2/2", **kwargs):
        raise RuntimeError("上传失败")

    app._save_nfo_batch = boom
    app.apply_selected()
    pump(app, 15)
    assert client._items[fid2].name.startswith("电影2 (2020)"), \
        client._items[fid2].name
    assert warnings and "自动保存 NFO/图片失败" in warnings[-1], warnings
    assert "上传失败" in warnings[-1], warnings
    assert app.plans == [], "apply should still clear tasks after NFO error"

    # 批量 NFO 进度聚合：两个任务、共 4 个文件，最终必须走到 4/4
    app._save_nfo_batch = real_batch

    def fake_prepare(plan, progress=None):
        if progress:
            progress(0, 0, "正在获取影片资料…")
        return {"plan": plan, "mode": "rename", "pairs": [],
                "info_files": [], "files": [],
                "desired": [{"cid": "0", "filename": f"{plan.title}.nfo",
                             "data": b"x"}] * 2}

    def fake_finish(prep, progress=None):
        n = len(prep["desired"])
        for i in range(1, n + 1):
            if progress:
                progress(i, n, f"正在上传 NFO/图片 {i}/{n}")
        return {"plan": prep["plan"], "uploads": n, "renames": 0,
                "deleted": 0, "skipped": 0, "units": n}

    app._prepare_nfo_task = fake_prepare
    app._finish_nfo_task = fake_finish
    events = []
    batch_infos = app._save_nfo_batch(
        [p, p2], progress=lambda d, t, m: events.append((d, t, m)))
    assert len(batch_infos) == 2, batch_infos
    assert events[-1][0] == events[-1][1] == 4, events[-1]
    assert any("阶段 2/2" in e[2] for e in events), events
    assert all(e[0] <= e[1] for e in events), events

    app.destroy()
    print("AUTO NFO APPLY OK")


if __name__ == "__main__":
    main()
