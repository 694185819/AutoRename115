# -*- coding: utf-8 -*-
"""启动/运行中自动更新：顶部提示、忽略版本、关于窗口预载版本。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import app.gui as gui
from app import updater
from app.gui import AboutDialog, App

gui.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.showinfo = lambda *a, **k: None
gui.messagebox.showwarning = lambda *a, **k: None
gui.messagebox.showerror = lambda *a, **k: None


def release(tag, notes="更新说明"):
    return {
        "tag": tag,
        "name": tag,
        "url": "https://example.invalid/release",
        "notes": notes,
        "asset": {
            "name": "AutoRename115-portable.zip",
            "browser_download_url": "https://example.invalid/a.zip",
            "size": 4,
        },
    }


def main():
    with tempfile.TemporaryDirectory() as tmp:
        app = App(os.path.join(tmp, "app"))
        app.withdraw()
        try:
            assert app._update_after_id is not None

            rel = release("v9.9", "## 本次更新\n- 测试更新")
            app._handle("update_check", (rel, ""))
            assert app.update_banner.winfo_manager(), "更新提示条没有显示"
            assert app._update_banner_tag == "v9.9"
            assert "v9.9" in app.update_banner_label.cget("text")
            assert app._update_release is rel

            about = AboutDialog(app, release=rel)
            app.update()
            assert str(about.install_btn.cget("state")) == "normal"
            assert "v9.9" in about.install_btn.cget("text")
            about.destroy()

            app._ignore_update()
            assert not app.update_banner.winfo_manager()
            assert app.settings.get("update_ignored_version") == "v9.9"
            app._handle("update_check", (rel, ""))
            assert not app.update_banner.winfo_manager()

            rel2 = release("v9.10", "第二个版本")
            app._handle("update_check", (rel2, ""))
            assert app.update_banner.winfo_manager()
            assert app._update_banner_tag == "v9.10"

            # 关闭自动检查后，不再保留定时器或提示条
            app.apply_settings({"auto_check_updates": False})
            assert app._update_after_id is None
            assert not app.update_banner.winfo_manager()

            # 重新开启会恢复检查节奏
            app.apply_settings({"auto_check_updates": True})
            assert app._update_after_id is not None

            # 真正走一次后台检查路径（不发网络请求）
            if app._update_after_id:
                app.after_cancel(app._update_after_id)
                app._update_after_id = None
            old_fetch = updater.fetch_latest_release
            old_viewable = app.winfo_viewable
            updater.fetch_latest_release = lambda: release(
                "v9.11", "后台检查发现")
            app.winfo_viewable = lambda: True
            try:
                app._update_banner_tag = ""
                app._auto_update_tick()
                end = time.time() + 8
                while time.time() < end and \
                        app._update_banner_tag != "v9.11":
                    app.update()
                    time.sleep(0.03)
                assert app._update_banner_tag == "v9.11"
                assert app.update_banner.winfo_manager()
            finally:
                updater.fetch_latest_release = old_fetch
                app.winfo_viewable = old_viewable
        finally:
            app.destroy()

    print("UPDATE PUSH OK")


if __name__ == "__main__":
    main()
