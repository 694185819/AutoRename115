# -*- coding: utf-8 -*-
"""命名规则面板：预览随选项变化，保存后写入设置并重建 NamingOptions。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

import json
import tempfile

from app.gui import App, SettingsDialog
from app.naming_rule import NAME_SOURCE_LABELS


def main():
    tmp = tempfile.mkdtemp(prefix="arn115_panel_")
    app = App(tmp)
    app.deiconify()
    app.update()
    dlg = SettingsDialog(app)
    app.update()

    panel = dlg.naming_panel
    assert panel is not None, "命名规则面板未加载"
    base = panel.preview.cget("text")
    assert "S01E01" in base, base
    assert "Ling.Cage" in base, base
    assert "1080p" in base, base

    panel.seg_var.set(NAME_SOURCE_LABELS["none"])
    panel._refresh_preview()
    app.update()
    no_seg = panel.preview.cget("text")
    assert "Ling.Cage" not in no_seg, no_seg

    panel.spec_var.set(False)
    panel._refresh_preview()
    app.update()
    no_spec = panel.preview.cget("text")
    assert "1080p" not in no_spec, no_spec

    # 保存后：设置文件与运行时 options 都更新
    dlg.save()
    app.update()
    s = json.load(open(tmp + "/data/settings.json", encoding="utf-8"))
    assert s.get("name_segment_source") == "none", s.get("name_segment_source")
    assert s.get("include_specs") is False, s.get("include_specs")
    assert app.options.include_specs is False
    assert app.options.name_segment_source == "none"

    app.destroy()
    print("NAMING PANEL OK")


if __name__ == "__main__":
    main()
