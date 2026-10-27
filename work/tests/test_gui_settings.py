# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app.gui import App, SettingsDialog

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()
app.is_demo = True
d = SettingsDialog(app)
app.update()
print("jp style:", d.jp_style_var.get())
print("login app:", d.login_app_var.get())
assert d.jp_style_var.get()
d.destroy()
app.destroy()
print("SETTINGS OK")
