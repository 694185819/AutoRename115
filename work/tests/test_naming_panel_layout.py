# -*- coding: utf-8 -*-
"""命名规则面板：剧集/日番/电影各占一行，行尾带 ? 提示，下拉可双击自定义。

用户要求：
  · 「TMDB 剧集名」「规格」「中文主名称」都属于一般剧集的规则，
    应该在**同一行**，不另起一行
  · 日番、电影各占一行
  · 每行末尾一个 ? 圆圈，显示该行规则的示范
  · 双击下拉框可变成自定义输入（双击速度与平常双击一致）
"""
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.naming_panel import JP_FOLDER_OPTIONS, MOVIE_LABELS


def pump(app, sec=2):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        time.sleep(0.04)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="arn115_np_test_")
    app = App(tmp)
    app.is_demo = True
    app.busy = False
    pump(app, 2)

    panel = app.naming_panel
    assert panel is not None, "命名规则面板没有加载"

    # 1) 配置项齐全（含 movie_style）
    vals = panel.values()
    print("配置:", vals)
    for k in ("name_segment_source", "subtitle_source", "include_specs",
              "jp_folder_style", "movie_style"):
        assert k in vals, k

    # 2) 三个下拉都在，且默认只读
    combos = {
        "英文名段": panel.seg_combo,
        "副标题": panel.sub_combo,
        "日番": panel.jp_box,
        "电影": panel.movie_box,
    }
    for name, c in combos.items():
        st = str(c.cget("state"))
        print(f"  {name:6s} 初始 state={st}")
        assert st == "readonly", (name, st)

    # 3) 剧集行的控件在同一父容器里（不另起一行）
    ep_parent = panel.seg_combo.master
    same = (panel.sub_combo.master is ep_parent)
    print("副标题与英文名段同一行:", same)
    assert same, "副标题应与英文名段在同一个容器"

    # 4) 日番、电影各自独立一行
    assert panel.jp_box.master is not ep_parent, "日番应独占一行"
    assert panel.movie_box.master is not ep_parent, "电影应独占一行"
    assert panel.jp_box.master is not panel.movie_box.master, \
        "日番与电影不能挤同一行"

    # 5) 每行末尾有 ? 提示，且不与其它控件重复绑定
    def find_q(w):
        out = []
        for c in w.winfo_children():
            try:
                if c.winfo_class() == "TLabel" and \
                        c.cget("text") in ("？", "?"):
                    out.append(c)
            except Exception:      # noqa: BLE001
                pass
            out += find_q(c)
        return out

    qs = find_q(panel)
    print("? 提示数量:", len(qs))
    assert len(qs) == 3, f"应为 3 个（剧集/日番/电影），实际 {len(qs)}"
    # 每个 ? 都要真的绑定了悬停显示（有 Enter 绑定）
    for q in qs:
        binds = " ".join(str(b) for b in q.bind())
        assert "Enter" in binds, f"? 没有绑定悬停: {binds}"
    print("  3 个 ? 都已绑定悬停 ✅")

    # 6) 只有「英文名段」双击可进入自定义输入（用户明确要求）
    def real_double_click(box):
        en = box.entry
        en.focus_force()
        pump(app, 0.25)
        x = en.winfo_width() // 2
        y = en.winfo_height() // 2
        for _ in (1, 2):
            en.event_generate("<ButtonPress-1>", x=x, y=y)
            en.event_generate("<ButtonRelease-1>", x=x, y=y)
            pump(app, 0.06)
        pump(app, 0.3)

    # 英文名段：可编辑，且有「双击可自定义」的悬浮提示
    assert panel.seg_combo._editable is True, "英文名段应支持双击自定义"
    binds = " ".join(str(b) for b in panel.seg_combo.entry.bind())
    assert "Enter" in binds, "英文名段应有悬停提示"
    assert "Double-Button-1" in binds, "英文名段应绑定双击"
    # 外观必须和其余三个明显不同，否则用户会以为那几个也能输入
    assert hasattr(panel.seg_combo, "_icon"), "可编辑项应有 ✎ 图标"
    assert str(panel.seg_combo.entry.cget("style")) == "Editable.TEntry", \
        "可编辑项应使用专用样式"

    real_double_click(panel.seg_combo)
    print(f"  双击 英文名段 → state={panel.seg_combo.cget('state')} "
          f"编辑中={panel.seg_combo.is_editing()}")
    assert panel.seg_combo.is_editing(), "英文名段双击后应进入编辑"
    assert str(panel.seg_combo.cget("state")) == "normal"

    panel.seg_combo.entry.delete(0, "end")
    panel.seg_combo.entry.insert(0, "我的自定义名")
    panel.seg_combo.entry.event_generate("<Return>")
    pump(app, 0.3)
    got = panel.values()["name_segment_source"]
    print("自定义后:", got)
    assert got == "我的自定义名", got
    assert str(panel.seg_combo.cget("state")) == "readonly"

    # Esc 取消恢复原值
    real_double_click(panel.seg_combo)
    panel.seg_combo.entry.delete(0, "end")
    panel.seg_combo.entry.insert(0, "临时不改")
    panel.seg_combo.entry.event_generate("<Escape>")
    pump(app, 0.3)
    print("Esc 后:", panel.seg_combo.get())
    assert panel.seg_combo.get() == "我的自定义名", "Esc 应恢复原值"

    # 其余三个是纯下拉：不可编辑、无悬停提示、且不能选中文字
    for name, box in (("副标题", panel.sub_combo), ("日番", panel.jp_box),
                      ("电影", panel.movie_box)):
        assert box._editable is False, f"{name} 不应支持自定义输入"
        nb = " ".join(str(b) for b in box.entry.bind())
        # 不绑定「可自定义」的悬停提示
        assert "Enter" not in nb, f"{name} 不应有自定义悬停提示"
        # 文字不能被选中，否则看起来像可输入
        assert box.entry.bind("<Button-1>"), f"{name} 应拦截点击"
        assert str(box.entry.cget("cursor")) == "arrow", \
            f"{name} 光标应为箭头"
        real_double_click(box)
        print(f"  双击 {name:6s} → 编辑中={box.is_editing()}（应为 False）")
        assert not box.is_editing(), f"{name} 不应进入编辑"

    # 7c) 自定义值必须真的被命名器使用（不能被当成未知来源而回退）
    import app.planner as _P
    from app.models import (MatchResult as _MR, P115Item as _IT,
                            ParsedName as _PN, PlanItem as _PI)
    it = _IT(fid="r", parent_id="0", name="Show", is_dir=True)
    pl = _PI(item=it, media_type="series",
             parsed=_PN(raw="x", title="魔道祖师", season=1),
             match=_MR(title_zh="魔道祖师", tmdb_id="80732",
                       year=2018, confidence=1.0),
             title="魔道祖师", year=2018, category="cn_anime",
             confidence=1.0)
    o = _P.Planner(None, _P.NamingOptions(name_segment_source="我的自定义名"))
    seg = o._name_segment(pl)
    print("命名器使用的英文名段:", repr(seg))
    assert seg == "我的自定义名", f"自定义值未生效: {seg}"

    # 8) 电影格式能读（纯下拉，从预设里挑）
    panel.movie_var.set(MOVIE_LABELS["title_year"])
    panel._refresh()
    pump(app, 0.2)
    print("电影格式:", panel.values()["movie_style"])
    assert panel.values()["movie_style"] == "title_year"

    # 9) 界面里不再有示范区（示范统一放进问号悬浮）
    assert not hasattr(panel, "preview"), "不应再有 preview 示范区"
    body = panel.preview.cget("text") if hasattr(panel, "preview") else ""
    print("无示范区 ✅")

    # 10) 三个悬浮各自带示范，且示范随选择变化
    ep_tip = panel._episode_tooltip()
    jp_tip = panel._jp_tooltip()
    mv_tip = panel._movie_tooltip()
    print("剧集悬浮:", ep_tip.splitlines()[1].strip()[:60])
    print("日番悬浮:", jp_tip.splitlines()[1].strip()[:60])
    print("电影悬浮:", mv_tip.splitlines()[1].strip()[:60])
    assert "灵笼.S01E01" in ep_tip, ep_tip[:120]
    assert "BD-REMUX" in jp_tip, jp_tip[:120]
    assert "朝花夕拾" in mv_tip, mv_tip[:120]

    # 改规格后，剧集示范应跟着变（只看示范那一行，说明里仍会提到 1080p）
    panel.spec_var.set(False)
    panel._refresh()
    pump(app, 0.2)
    ep_tip2 = panel._episode_tooltip()
    line2 = ep_tip2.splitlines()[1]
    print("关掉规格后:", line2.strip()[:60])
    assert "1080p" not in line2, line2
    assert "1080p" in ep_tip.splitlines()[1], "原示范应含规格"

    # 日番换个格式，示范应跟着变
    panel.jp_var.set(JP_FOLDER_OPTIONS["standard"])
    panel._refresh()
    pump(app, 0.2)
    jp_tip2 = panel._jp_tooltip()
    print("换标准日番后:", jp_tip2.splitlines()[1].strip()[:60])
    assert "[BD-REMUX]" not in jp_tip2.splitlines()[1], jp_tip2[:120]

    app.destroy()
    print("\nNAMING PANEL LAYOUT OK")


if __name__ == "__main__":
    main()
