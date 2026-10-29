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

    # 纵向顺序：标题行 < 元信息 < NFO/图片 < 季集映射 < 备注
    note_y = app.note_label.winfo_rooty()
    map_y = app.map_btn.winfo_rooty()
    meta_y = app.meta_label.winfo_rooty()
    nfo_y = app.nfo_mode_label.winfo_rooty()
    print(f"元信息 y={meta_y} | NFO y={nfo_y} | 季集映射 y={map_y} | 备注 y={note_y}")
    assert meta_y < nfo_y, "NFO 操作应紧跟元信息"
    assert nfo_y < map_y, "季集映射应在 NFO 操作下方"
    assert map_y < note_y, "备注应在最后"
    print("顺序正确：元信息 → NFO/图片 → 季集映射 → 备注")

    app.destroy()
    print("DETAIL ORDER OK")


if __name__ == "__main__":
    main()
