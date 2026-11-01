# -*- coding: utf-8 -*-
"""元数据缓存可手动清除。

用户遇到：TMDb 条目被恶意刷成广告（标题变成「淫片网…」），
软件抓取并缓存了；之后 TMDb 已改回正常，但缓存要 7 天才过期，
软件一直读旧数据，看起来「改了也不生效」。

解决：设置里加「清除缓存并重新获取」按钮。
"""
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from tkinter import messagebox

from app.gui import App, SettingsDialog

messagebox.askyesno = lambda *a, **k: True
messagebox.showinfo = lambda *a, **k: "ok"


def pump(app, sec=2):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="arn115_cache_test_")
    app = App(tmp)
    app.withdraw()
    app.is_demo = True
    app.busy = False
    pump(app, 2)

    # 造几条假缓存
    app.meta.cache = {f"k{i}": {"t": 1, "data": {}} for i in range(7)}

    dlg = SettingsDialog(app)
    pump(app, 0.5)
    print("缓存信息:", repr(dlg._cache_info_var.get()))
    assert "7 条" in dlg._cache_info_var.get(), dlg._cache_info_var.get()

    dlg._clear_metadata_cache()
    pump(app, 0.5)

    n = len(app.meta.cache or {})
    print("清除后:", n, "条")
    assert n == 0, n
    assert "0 条" in dlg._cache_info_var.get()

    dlg.destroy()
    app.destroy()
    print("\nCACHE CLEAR BUTTON OK")


if __name__ == "__main__":
    main()
