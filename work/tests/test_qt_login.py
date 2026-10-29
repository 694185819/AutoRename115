# -*- coding: utf-8 -*-
"""Qt 登录：扫码流程（伪客户端）与 Cookie 对话框。"""
import queue
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.gui import App
from app.qt_ui import CookieDialog, LoginDialog, MainWindow


class FakeClient:
    """模拟 115 客户端：第 2 次查询返回“已扫码”，第 3 次返回“确认”。"""

    def __init__(self):
        self.calls = 0
        self.logged_in = False

    def qr_token(self):
        return {"uid": "u1"}

    def qr_image(self, uid):
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(0)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        return bytes(ba)

    def qr_status(self, token):
        self.calls += 1
        if self.calls >= 3:
            return 2
        return 0 if self.calls == 1 else 1

    def qr_login(self, uid, app="ios"):
        self.logged_in = True
        return True

    def is_logged_in(self, force=False):
        return True

    def set_cookie_text(self, text):
        self._cookie = text


def pump(app, seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.02)
    return False


def main():
    app = QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.plans = []
    helper.q = queue.Queue()
    helper.detail_plan = None
    helper.dir_items = {}
    helper.path_stack = [("0", "根目录")]
    helper.settings = {}
    helper.options = None
    fake = FakeClient()
    helper.client = fake

    win = MainWindow(helper, r"I:\实验\AutoRename115")
    win.show()
    pump(app, 0.1)

    dlg = LoginDialog(win, helper, fake)
    dlg.show()
    ok = pump(app, 6, until=lambda: fake.logged_in and dlg.result() != 0)
    assert ok, "扫码流程应在限定时间内完成"
    assert dlg.token is not None, "应拿到二维码 token"
    assert not dlg.qr_label.pixmap().isNull(), "二维码应显示出来"

    # Cookie 对话框
    cd = CookieDialog(win, helper, fake)
    cd.text.setPlainText("UID=1_CID=2_SEID=3_KID=4")
    cd.save()
    assert pump(app, 3, until=lambda: cd.result() == 1), "有效 Cookie 应关闭"

    # 无客户端时点登录应给出提示，不应崩溃
    helper.client = None
    win.open_login()

    win.close()
    print("QT LOGIN OK")


if __name__ == "__main__":
    main()
