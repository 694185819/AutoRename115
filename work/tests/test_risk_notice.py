# -*- coding: utf-8 -*-
"""首次使用风控提醒：默认只显示一次，可取消后每次启动提示。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App, RiskNoticeDialog

BASE = r"I:\实验\AutoRename115"


def main():
    app = App(BASE)
    app.withdraw()
    app.start_demo = True
    app.enable_demo()
    app.start_demo = False
    app.update()
    original = app.settings.get("risk_notice_dismissed", False)

    # 默认勾选“只显示一次”
    app.settings["risk_notice_dismissed"] = False
    dlg = RiskNoticeDialog(app)
    app.update()
    assert dlg.once_var.get() is True
    dlg._ok()
    app.update()
    assert app.settings["risk_notice_dismissed"] is True, app.settings
    assert not dlg.winfo_exists()

    # 取消勾选后保存为 False，下次启动仍会提示
    app.settings["risk_notice_dismissed"] = False
    dlg2 = RiskNoticeDialog(app)
    app.update()
    dlg2.once_var.set(False)
    dlg2._ok()
    app.update()
    assert app.settings["risk_notice_dismissed"] is False, app.settings
    assert not dlg2.winfo_exists()

    # 演示/本地模式不弹出 115 登录提醒
    opened = []
    app.open_login = lambda: opened.append(1)
    app.settings["risk_notice_dismissed"] = False
    app.is_demo = True
    app._open_login_after_notice()
    assert opened == [], opened
    app.is_demo = False

    # 首次启动流程：未关闭提醒时先弹提醒，关掉后才打开登录窗口

    def close_notice():
        for child in app.winfo_children():
            if isinstance(child, RiskNoticeDialog):
                child._ok()
                return
        app.after(50, close_notice)

    app.after(100, close_notice)
    app._open_login_after_notice()
    app.update()
    assert opened == [1], opened
    assert app.settings["risk_notice_dismissed"] is True

    # 已选择只显示一次：直接打开登录窗口，不再弹提醒
    app.settings["risk_notice_dismissed"] = True
    app._open_login_after_notice()
    assert opened == [1, 1], opened

    app.settings["risk_notice_dismissed"] = original
    app._save_settings()
    app.destroy()
    print("RISK NOTICE OK")


if __name__ == "__main__":
    main()
