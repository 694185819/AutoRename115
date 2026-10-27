# -*- coding: utf-8 -*-
"""返回上一级时，文件夹列表要恢复原来的选中项和滚动位置。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.models import P115Item

BASE = r"I:\实验\AutoRename115"


def items(prefix, count):
    return [P115Item(fid=f"{prefix}{i}", parent_id="0",
                     name=f"{prefix.upper()} 文件夹 {i:02d}",
                     is_dir=True, size=0) for i in range(count)]


def main():
    app = App(BASE)
    app.withdraw()
    app.update_idletasks()
    try:
        root = items("r", 20)
        child = items("c", 5)

        app.path_stack = [("0", "根目录")]
        app.current_cid = "0"
        app._fill_dir_tree(root)
        app.dir_tree.selection_set("d12")
        app.dir_tree.focus("d12")
        app.dir_tree.yview_moveto(0.45)
        app.update_idletasks()
        saved_top = app.dir_tree.yview()[0]
        app._save_dir_view()

        # 进入子文件夹
        app.path_stack.append(("child", "子文件夹"))
        app.current_cid = "child"
        app._fill_dir_tree(child)
        app.dir_tree.selection_set("d2")
        app._save_dir_view()

        # 返回上一级：重新加载父目录后应恢复选中项和滚动位置
        app.path_stack.pop()
        app.current_cid = "0"
        app._fill_dir_tree(root)
        app.update_idletasks()
        assert app.dir_tree.selection() == ("d12",), app.dir_tree.selection()
        assert app.dir_tree.focus() == "d12", app.dir_tree.focus()
        assert abs(app.dir_tree.yview()[0] - saved_top) < 1e-6, (
            saved_top, app.dir_tree.yview())

        # 再进子文件夹时，子文件夹自己的状态也要恢复
        app.path_stack.append(("child", "子文件夹"))
        app.current_cid = "child"
        app._fill_dir_tree(child)
        assert app.dir_tree.selection() == ("d2",), app.dir_tree.selection()
    finally:
        app.destroy()
    print("DIR VIEW STATE OK")


if __name__ == "__main__":
    main()
