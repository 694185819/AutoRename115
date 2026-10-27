# -*- coding: utf-8 -*-
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.gui import App, LoginDialog
from app.p115 import parse_cookie_text

print(parse_cookie_text("UID=abc; CID=def; SEID=ghi; KID=jkl"))
print(parse_cookie_text('{"data":{"cookie":{"UID":"a","SEID":"b"}}}'))
assert parse_cookie_text("UID=abc; CID=def") == {"UID": "abc", "CID": "def"}

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()
app.is_demo = True  # 阻止 startup 覆盖 client
app.open_login()
dialogs = [w for w in app.winfo_children() if isinstance(w, LoginDialog)]
assert dialogs, "登录窗口没有创建"
d = dialogs[0]
deadline = time.time() + 20
while time.time() < deadline:
    app.update()
    if d.photo is not None:
        break
    time.sleep(0.1)
print("QR image loaded:", d.photo is not None)
print("status:", d.status_label.cget("text"))
assert d.photo is not None, "二维码没有加载"
d._close()
app.update()
app.destroy()
print("GUI LOGIN OK")
