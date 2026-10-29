# -*- coding: utf-8 -*-
"""详情区顺序：元信息 → 季集映射 → NFO → 备注；分类下拉已移除。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import tempfile

from app.gui import App


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def main():
    app = App(tempfile.mkdtemp(prefix="arn115_order_"))
    app.deiconify()
    for _ in range(20):
        app.update()

    # 分类下拉必须已移除
    assert not hasattr(app, "category_var"), "分类下拉应已移除"
    assert not hasattr(app, "category_box"), "分类下拉应已移除"
    labels = [str(w.cget("text")) for w in walk(app)
              if w.winfo_class() == "TLabel"]
    assert "分类" not in labels, "详情区不应再有“分类”标签"
    print("分类已移除")

    # 备注框在季集映射/NFO 之后
    note_y = app.note_label.winfo_rooty()
    map_y = app.map_btn.winfo_rooty()
    print("季集映射 y:", map_y, "| 备注 y:", note_y)
    assert map_y < note_y, "备注应排在季集映射之下"

    # 详情区纵向顺序：标题行 < 元信息 < 季集映射 < 备注
    meta_y = app.meta_label.winfo_rooty()
    assert meta_y < map_y < note_y, (meta_y, map_y, note_y)
    print("顺序正确：标题行 → 元信息 → 季集映射/NFO → 备注")

    app.destroy()
    print("DETAIL ORDER OK")


if __name__ == "__main__":
    main()
