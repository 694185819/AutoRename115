# -*- coding: utf-8 -*-
"""窗口缩放：拖动时收起右栏降低重排开销，停手后完整恢复。"""
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

    right = app.paned.winfo_children()[-1]
    before = [w.winfo_height() for w in right.winfo_children()
              if w.winfo_manager() == "pack"]
    assert before, "右栏应有多个区块"
    assert not app._right_hidden

    # 改变窗口尺寸 → 右栏应被临时收起
    bw, bh = app.winfo_width(), app.winfo_height()
    app.geometry(f"{bw + 80}x{bh + 50}")
    app.update()
    assert app._right_hidden, "拖动时应收起右栏"
    assert len(app._right_packed) == len(before), (
        len(app._right_packed), len(before))
    assert not [w for w in right.winfo_children()
                if w.winfo_manager() == "pack"], "右栏区块应已从布局移除"

    # 停手后恢复
    deadline = time.time() + 3
    while time.time() < deadline and app._right_hidden:
        app.update()
        time.sleep(0.02)
    assert not app._right_hidden, "停手后应恢复布局"

    after = [w.winfo_height() for w in right.winfo_children()
             if w.winfo_manager() == "pack"]
    assert len(after) == len(before), (after, before)
    assert all(h > 0 for h in after), after
    print("恢复后区块高度:", after)

    # 数据未被破坏：任务表与备注仍可用
    assert app.plan_tree.winfo_exists()
    assert app.note_label.winfo_exists()
    assert str(app.note_label.cget("state")) == "disabled"

    app.destroy()
    print("RESIZE SUSPEND OK")


if __name__ == "__main__":
    main()
