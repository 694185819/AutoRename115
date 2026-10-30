# -*- coding: utf-8 -*-
"""测试环境引导：QMessageBox / QDialog.exec 一律不弹窗、不阻塞。

放在 work/tests/ 下，由各测试文件显式 import；
每次运行测试前由 run_all 自动注入（见 work/tests/run_all.py）。
"""
import sys

_POPUPS: list = []
_DONE = False


def install() -> None:
    """把 Qt 的模态弹窗全部替换成“记录并立即返回”。"""
    global _DONE
    if _DONE:
        return
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox
    except Exception:       # 没有 Qt 的环境（纯 Tk 测试）不用管
        _DONE = True
        return

    def _make(kind):
        def fake(parent=None, title="", text="", *a, **k):
            _POPUPS.append(f"[{kind}] {title}: {text}")
            return QMessageBox.Ok
        return staticmethod(fake)

    for kind in ("information", "warning", "critical", "about", "question"):
        setattr(QMessageBox, kind, _make(kind))

    # 任何对话框的 exec()/open() 都立刻返回，避免事件循环卡死
    def _exec(self, *a, **k):
        _POPUPS.append(f"[exec] {type(self).__name__}")
        return QDialog.Accepted

    def _open(self, *a, **k):
        _POPUPS.append(f"[open] {type(self).__name__}")

    QDialog.exec = _exec
    QDialog.open = _open
    _DONE = True


def popups() -> list:
    """被拦截下来的弹窗记录（调试用）。"""
    return list(_POPUPS)


install()
