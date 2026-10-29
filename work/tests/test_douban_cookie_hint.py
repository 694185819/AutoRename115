# -*- coding: utf-8 -*-
"""设置里的豆瓣 Cookie：输入框预置模板，下方写明获取路径。"""
import queue
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from app.gui import DOUBAN_COOKIE_HINT, DOUBAN_COOKIE_TEMPLATE, App
from app.qt_ui import MainWindow, SettingsDialog


def test_constants():
    """模板与提示文案必须包含用户要求的关键信息。"""
    assert DOUBAN_COOKIE_TEMPLATE == \
        "dbcl2=这里填dbcl2的值; bid=这里填bid的值; ck=这里填ck的值", \
        DOUBAN_COOKIE_TEMPLATE
    for key in ("Application", "Cookies", "https://movie.douban.com"):
        assert key in DOUBAN_COOKIE_HINT, key
    assert "dbcl2" in DOUBAN_COOKIE_HINT and "bid" in DOUBAN_COOKIE_HINT
    assert "ck" in DOUBAN_COOKIE_HINT


def test_qt_settings():
    """Qt 设置里应有预置模板的输入框与获取提示。"""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.plans = []
    helper.q = queue.Queue()
    helper.detail_plan = None
    helper.dir_items = {}
    helper.path_stack = [("0", "根目录")]
    helper.settings = {}
    helper.options = None
    helper.app_dir = tempfile.mkdtemp(prefix="arn115_hint_")

    win = MainWindow(helper, tempfile.mkdtemp(prefix="arn115_hint_"))
    win.show()
    dlg = SettingsDialog(win, helper)
    app.processEvents()

    cookies = [e for e in dlg.findChildren(QLineEdit)
               if "dbcl2=" in (e.text() or "")]
    assert cookies, "输入框应预置 Cookie 模板"
    assert cookies[0].text() == DOUBAN_COOKIE_TEMPLATE

    hints = [l.text() for l in dlg.findChildren(QLabel)
             if "Application" in (l.text() or "")]
    assert hints, "应显示获取提示"
    assert "Cookies" in hints[0] and "这里填dbcl2的值" in hints[0]
    win.close()


def main():
    test_constants()
    test_qt_settings()
    print("SETTINGS HINT OK")


if __name__ == "__main__":
    main()
