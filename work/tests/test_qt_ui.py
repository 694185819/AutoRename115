# -*- coding: utf-8 -*-
"""Qt 界面：左栏目录树渲染、多选取对象、缩放成本。"""
import queue
import sys
import time

sys.path.insert(0, r"I:\实验\AutoRename115")

from PySide6.QtWidgets import QApplication

from app.gui import App
from app.models import P115Item
from app.qt_ui import MainWindow


def build_items(folders=6, files=60):
    items = {}
    for i in range(folders):
        fid = f"d{i}"
        items[fid] = P115Item(fid=fid, parent_id="0", name=f"目录{i}",
                              is_dir=True)
    for i in range(files):
        fid = f"f{i}"
        items[fid] = P115Item(fid=fid, parent_id="0",
                              name=f"文件{i:03d}.mkv", is_dir=False,
                              size=1024 * 1024)
    return items


def main():
    app = QApplication(sys.argv[:1])
    helper = App.__new__(App)
    helper.plans = []
    helper.q = queue.Queue()
    helper.detail_plan = None
    helper.dir_items = build_items()
    helper.path_stack = [("0", "根目录")]

    win = MainWindow(helper, r"I:\实验\AutoRename115")
    win.show()
    win.render_dir_items()
    for _ in range(5):
        app.processEvents()

    assert win.dir_tree.topLevelItemCount() == 66, \
        win.dir_tree.topLevelItemCount()
    # 文件夹排在文件前面
    assert win.dir_tree.topLevelItem(0).text(1) == "文件夹"
    last = win.dir_tree.topLevelItemCount() - 1
    assert win.dir_tree.topLevelItem(last).text(1) == "文件"

    # 多选能取回业务对象
    win.dir_tree.topLevelItem(0).setSelected(True)
    win.dir_tree.topLevelItem(1).setSelected(True)
    sel = win.selected_dir_items()
    assert len(sel) == 2, sel
    assert all(it.is_dir for it in sel)

    # 缩放：目录树延后刷新，整体保持毫秒级
    costs = []
    bw, bh = win.width(), win.height()
    for i in range(15):
        win.resize(bw - (i % 5) * 20, bh - (i % 3) * 15)
        t0 = time.perf_counter()
        app.processEvents()
        costs.append((time.perf_counter() - t0) * 1000)
    costs.sort()
    median = costs[len(costs) // 2]
    print(f"缩放中位数: {median:.1f}ms")
    assert median < 40, f"Qt 缩放应远快于 Tk（{median:.1f}ms）"

    win.close()
    print("QT DIR PANEL OK")


if __name__ == "__main__":
    main()
