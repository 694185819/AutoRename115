# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app.gui import App, SettingsDialog

app = App(r"I:\实验\AutoRename115")
app.withdraw()
app.is_demo = True
d = SettingsDialog(app)
app.update()
print("login app:", d.login_app_var.get())
assert d.login_app_var.get()
# 日番格式已移到主界面命名规则面板
assert app.naming_panel is not None
print("主界面日番格式:", app.naming_panel.jp_var.get())
assert app.naming_panel.jp_var.get()
d.destroy()
app.destroy()
print("SETTINGS OK")
