# -*- coding: utf-8 -*-
"""窗口缩放：界面全程可见、不闪烁；尺寸事件不会重复触发收尾。"""
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App


def main():
    app = App(tempfile.mkdtemp(prefix="arn115_rs_"))
    app.deiconify()
    for _ in range(20):
        app.update()

    right = app._right_frame
    kids = [w for w in right.winfo_children() if w.winfo_manager() == "pack"]
    assert kids, "右栏应有多个区块"
    count_before = len(kids)

    # 拖动过程中：右栏必须始终可见（不能消失、不能闪烁）
    bw, bh = app.winfo_width(), app.winfo_height()
    for i in range(6):
        app.geometry(f"{bw + (i % 4) * 20}x{bh + (i % 3) * 15}")
        app.update_idletasks()
        visible = [w for w in right.winfo_children()
                   if w.winfo_manager() == "pack" and w.winfo_ismapped()]
        assert len(visible) == count_before, (
            "拖动中右栏区块不应消失", len(visible), count_before)

    # 不应存在任何隐藏/冻结右侧的状态字段
    assert not hasattr(app, "_right_hidden"), "不应残留隐藏状态"
    assert not hasattr(app, "_right_frozen"), "不应残留冻结状态"

    # 停手后尺寸归位，各区块高度正常
    deadline = time.time() + 2
    while time.time() < deadline and app._resize_job is not None:
        app.update()
        time.sleep(0.02)
    heights = [w.winfo_height() for w in right.winfo_children()
               if w.winfo_manager() == "pack"]
    print("恢复后区块高度:", heights)
    assert len(heights) == count_before
    assert all(h > 0 for h in heights), heights

    # 数据未被破坏
    assert app.plan_tree.winfo_exists()
    assert str(app.note_label.cget("state")) == "disabled"

    app.destroy()
    print("RESIZE VISIBLE OK")


if __name__ == "__main__":
    main()
