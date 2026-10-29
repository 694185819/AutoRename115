# -*- coding: utf-8 -*-
"""设置保存不应递归；未连接 115 时点登录不应弹窗。"""
import queue
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtWidgets import QApplication

from app.gui import App
from app.qt_ui import MainWindow, SettingsDialog


def build():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.data_dir = tempfile.mkdtemp(prefix="arn115_guard_")
    helper.settings = {}
    helper.q = queue.Queue()
    helper.plans = []
    helper.detail_plan = None
    helper.dir_items = {}
    helper.path_stack = [("0", "根目录")]
    helper.app_dir = helper.data_dir
    helper.client = None
    App._init_meta(helper)
    win = MainWindow(helper, helper.app_dir)
    win.show()
    app.processEvents()
    return app, helper, win


def test_save_twice():
    """连续保存两次不应递归，也不应抛异常。"""
    app, helper, win = build()
    for i in range(2):
        dlg = SettingsDialog(win, helper)
        app.processEvents()
        dlg.save()          # 若抛 RecursionError 会在此暴露
        app.processEvents()
    # settings.json 能正常写出
    import json
    import os
    p = os.path.join(helper.data_dir, "settings.json")
    assert os.path.isfile(p)
    json.load(open(p, encoding="utf-8"))
    win.close()


def test_login_without_client():
    """没有客户端时点登录：只写日志/状态，不弹窗。"""
    app, helper, win = build()
    win.open_login()        # 不应阻塞或抛异常
    app.processEvents()
    assert "尚未连接" in win.lbl_status.text(), win.lbl_status.text()
    win.close()


def main():
    test_save_twice()
    test_login_without_client()
    print("QT SETTINGS GUARD OK")


if __name__ == "__main__":
    main()
