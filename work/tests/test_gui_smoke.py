# -*- coding: utf-8 -*-
import sys
import traceback

sys.path.insert(0, r"I:\实验\AutoRename115")
import app.gui as gui
from app.gui import AboutDialog, App, QQChannelDialog
from app import qq_channel, updater

warnings = []
gui.messagebox.showwarning = lambda *a, **k: warnings.append(
    a[1] if len(a) > 1 else a)
gui.messagebox.showerror = lambda *a, **k: warnings.append(
    a[1] if len(a) > 1 else a)

BASE = r"I:\实验\AutoRename115"
app = App(BASE)
app.withdraw()


def fail(exc, val, tb):
    traceback.print_exception(exc, val, tb)
    app.destroy()


app.report_callback_exception = fail
app.enable_demo()
import time
deadline = time.time() + 5
while time.time() < deadline:
    app.update()
    if not app.busy:
        break
    time.sleep(0.05)

# 进度条已经移动到“等待处理的任务”同一行
texts = []
for w in app.progress.master.winfo_children():
    try:
        texts.append(str(w.cget("text")))
    except Exception:
        pass
assert "等待处理的任务" in texts, texts

status_before = app.status_var.get()
app._handle("progress", (3, 10, "正在重命名…"))
app.update()
assert int(float(app.progress.cget("value"))) == 3
assert int(float(app.progress.cget("maximum"))) == 10
assert app.progress_label.cget("text") == "3/10"
assert "正在重命名" in app.progress_stage.cget("text")
# 详细阶段只在上方进度区，不能重复写到底部状态栏
assert app.status_var.get() == status_before, app.status_var.get()

# 总数未知时只换阶段文字，不把已有进度清掉/重新抽动
app._handle("progress", (0, 0, "正在获取影片资料…"))
app.update()
assert int(float(app.progress.cget("value"))) == 3
assert "正在获取影片资料" in app.progress_stage.cget("text")
assert app.status_var.get() == status_before

# 115 的 405/WAF 错误只给“疑似风控、稍后再试”的提醒
warnings.clear()
app._show_task_error(
    "115 应用接口返回异常（HTTP 405）：Expecting value: line 1 column 1")
assert warnings and "疑似触发 115 风控" in warnings[-1], warnings
assert "HTTP 405" not in warnings[-1], warnings
assert "Expecting value" not in warnings[-1], warnings

app._set_busy(False)
assert int(float(app.progress.cget("value"))) == 0
assert app.progress_stage.cget("text") == ""

# 关于窗口显示版本和仓库地址
about = AboutDialog(app)
app.update()
assert updater.APP_VERSION in about.version_label.cget("text")
assert updater.REPO_URL in about.repo_link.cget("text")
assert qq_channel.QQ_CHANNEL_NAME in about.qq_link.cget("text")

# 频道按钮优先唤起 QQ；QQ 不可用时才回退默认浏览器
old_qq_open = qq_channel.open_in_qq
old_browser_open = gui.webbrowser.open
opened = []
try:
    qq_channel.open_in_qq = lambda: opened.append("qq") or True
    gui.webbrowser.open = (
        lambda url: opened.append(("browser", url)) or True)
    about._open_qq()
    assert opened == ["qq"], opened

    qq = QQChannelDialog(app)
    app.update()
    assert qq.photo is not None
    opened.clear()
    qq._open()
    assert opened == ["qq"], opened
    qq.destroy()

    opened.clear()
    qq_channel.open_in_qq = lambda: False
    about._open_qq()
    assert opened == [("browser", qq_channel.QQ_CHANNEL_URL)], opened
finally:
    qq_channel.open_in_qq = old_qq_open
    gui.webbrowser.open = old_browser_open
about.destroy()

app.after(2500, app.destroy)
app.mainloop()
print("GUI SMOKE OK")
