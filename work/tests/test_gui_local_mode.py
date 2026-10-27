# -*- coding: utf-8 -*-
"""界面上的本地文件模式：切换、列目录、单项改名和撤销。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import app.gui as gui
from app.gui import App

gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showinfo = lambda *a, **k: None
gui.messagebox.showwarning = lambda *a, **k: None
gui.messagebox.showerror = lambda *a, **k: None

BASE = r"I:\实验\AutoRename115"


def wait_until(app, cond, timeout=12.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.03)
    return False


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "媒体库")
        season = os.path.join(root, "Show", "Season 01")
        os.makedirs(season)
        with open(os.path.join(season, "01.mkv"), "wb") as f:
            f.write(b"video")

        app = App(os.path.join(tmp, "app"))
        app.withdraw()
        try:
            assert app._enter_local(root)
            assert wait_until(
                app, lambda: not app.busy and len(app.dir_items) >= 1)
            assert app.is_local
            assert app.mode_var.get() == "local"
            assert str(app.choose_local_btn.cget("state")) != "disabled"
            assert str(app.login_btn.cget("state")) == "disabled"
            names = {x.name for x in app.dir_items.values()}
            assert names == {"Show"}, names

            show = next(x for x in app.dir_items.values() if x.name == "Show")
            app._start_dir_rename(show, "新剧名")
            assert wait_until(app, lambda: not app.busy)
            assert os.path.isdir(os.path.join(root, "新剧名"))
            assert not os.path.exists(os.path.join(root, "Show"))
            assert app._undo_scope().startswith("local:")
            assert app.undo.last_undoable("cloud") is None

            app.undo_last()
            assert wait_until(app, lambda: not app.busy)
            assert os.path.isdir(os.path.join(root, "Show"))
            assert not os.path.exists(os.path.join(root, "新剧名"))
            assert app.undo.last_undoable(app._undo_scope()) is None

            # 返回网盘只做状态切换，不触发网络（未登录时也不会自动请求）
            app._enter_cloud(check_login=False)
            assert not app.is_local
            assert app.mode_var.get() == "cloud"
            assert str(app.choose_local_btn.cget("state")) == "disabled"
        finally:
            app.destroy()

    print("GUI LOCAL MODE OK")


if __name__ == "__main__":
    main()
