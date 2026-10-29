# -*- coding: utf-8 -*-
"""启动入口。"""
import os
import sys
import traceback

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _fatal(exc: BaseException) -> None:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
        with open(os.path.join(BASE_DIR, "data", "error.log"),
                  "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    try:
        import tkinter.messagebox as mb
        mb.showerror("启动失败",
                     "程序启动失败，详细信息已写入 data/error.log：\n\n"
                     + str(exc)[:800])
    except Exception:
        print(text)


if __name__ == "__main__":
    try:
        # 界面选择：默认 Tk（成熟稳定）；加 --ui=qt 用新的 Qt 界面。
        # Qt 界面仍在迁移中，两个界面并存，业务逻辑完全共用。
        want_qt = any(a.lower() in ("--ui=qt", "--qt", "-qt")
                      for a in sys.argv[1:])
        demo = "--demo" in sys.argv
        if want_qt:
            try:
                from app.qt_ui import main as qt_main
            except ImportError:
                from tkinter import messagebox
                messagebox.showwarning(
                    "115 海报墙重命名助手",
                    "未安装 PySide6，无法使用 Qt 界面。\n"
                    "请运行：pip install PySide6-Essentials\n\n"
                    "本次将使用默认界面。")
                want_qt = False
        if want_qt:
            raise SystemExit(qt_main(BASE_DIR, demo=demo))
        from app.gui import main
        main(BASE_DIR, demo=demo)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        _fatal(e)
