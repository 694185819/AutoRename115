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
        from app.gui import main
        main(BASE_DIR, demo="--demo" in sys.argv)
    except Exception as e:  # noqa: BLE001
        _fatal(e)
