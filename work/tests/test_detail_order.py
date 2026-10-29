# -*- coding: utf-8 -*-
"""详情区顺序 + NFO 行位置：命名规则 之后、影片资料 之前；分类已移除。"""
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
    labels = [str(w.cget("text")) for w in walk(app)
              if w.winfo_class() == "TLabel"]
    assert "分类" not in labels, "详情区不应再有“分类”标签"

    # 详情区内部：元信息 → 季集映射 → 备注
    meta_y = app.meta_label.winfo_rooty()
    map_y = app.map_btn.winfo_rooty()
    note_y = app.note_label.winfo_rooty()
    print(f"详情区：元信息 y={meta_y} | 季集映射 y={map_y} | 备注 y={note_y}")
    assert meta_y < map_y < note_y, (meta_y, map_y, note_y)

    # NFO 行：在命名规则面板之下、影片资料之上
    nfo_y = app.nfo_mode_label.winfo_rooty()
    naming_y = app.naming_panel.winfo_rooty()
    info_label_y = min(w.winfo_rooty() for w in walk(app)
                       if w.winfo_class() == "TLabel"
                       and str(w.cget("text")) == "资料来源")
    print(f"NFO y={nfo_y} | 命名规则 y={naming_y} | 资料来源 y={info_label_y}")
    assert naming_y < nfo_y < info_label_y, (naming_y, nfo_y, info_label_y)

    # NFO 行不在详情区里
    detail = app.map_btn.master.master
    inside = [w for w in walk(detail)
              if w is app.nfo_mode_label or w is app.auto_nfo_var]
    assert not inside, "NFO 行不应留在详情区"

    app.destroy()
    print("DETAIL ORDER OK")


if __name__ == "__main__":
    main()
