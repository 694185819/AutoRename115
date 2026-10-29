# -*- coding: utf-8 -*-
"""命名规则面板统一配置日番格式（设置里不再重复）与电影命名。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import json
import tempfile

from app.gui import App
from app.naming_panel import JP_FOLDER_OPTIONS, MOVIE_LABELS


def main():
    tmp = tempfile.mkdtemp(prefix="arn115_jp_")
    app = App(tmp)
    app.deiconify()
    for _ in range(15):
        app.update()
    panel = app.naming_panel
    assert panel is not None
    assert "BD-REMUX" in panel.jp_var.get()

    panel.jp_var.set(JP_FOLDER_OPTIONS["standard"])
    panel._refresh_preview()
    app.update()
    jp_line = panel.preview.cget("text").split("日番文件夹：")[1].split("\n")[0]
    assert "[BD-REMUX]" not in jp_line, jp_line

    app.apply_naming_rule()
    app.update()
    s = json.load(open(tmp + "/data/settings.json", encoding="utf-8"))
    assert s.get("jp_folder_style") == "standard", s.get("jp_folder_style")
    assert app.options.jp_folder_style == "standard"

    # 电影只有一种命名写法
    assert panel.movie_var.get() == MOVIE_LABELS["title_year"]
    assert len(MOVIE_LABELS) == 1

    app.destroy()
    print("JP STYLE OK")


if __name__ == "__main__":
    main()
