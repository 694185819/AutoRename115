# -*- coding: utf-8 -*-
"""验证：超长备注不会把详情区撑高，且可在框内滚动。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App

LONG = "；".join([f"第{i}条说明：这里是一段很长的备注文字，用于测试限高滚动" 
                  for i in range(1, 40)])


def main() -> None:
    app = App(tempfile.mkdtemp(prefix="arn115_note_"))
    app.deiconify()
    for _ in range(20):
        app.update()
    detail = app.note_label.master.master
    h_short_before = detail.winfo_reqheight()
    app._set_note("短备注")
    for _ in range(5):
        app.update()
    h_short = detail.winfo_height()

    app._set_note(LONG)
    for _ in range(10):
        app.update()
    h_long = detail.winfo_height()
    note_h = app.note_label.winfo_height()
    print(f"详情区 短备注={h_short}px | 长备注={h_long}px | 备注框={note_h}px")
    assert h_long - h_short < 40, (h_short, h_long)

    # 内容确实超出可视区域（可滚动）
    first, last = app.note_label.yview()
    print("yview:", first, last)
    assert last < 1.0, "长备注应超出可视区，可在框内滚动"

    # 滚轮滚动
    class E:
        delta = -120
    app._on_note_wheel(E())
    app.update()
    print("滚动后 yview:", app.note_label.yview())
    assert app.note_label.yview()[0] > 0, "滚轮应能滚动备注框"

    # 文本是只读的
    assert str(app.note_label.cget("state")) == "disabled"

    app.destroy()
    print("NOTE BOX OK")


if __name__ == "__main__":
    main()
