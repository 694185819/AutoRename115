# -*- coding: utf-8 -*-
"""命名规则面板：按“中文主名称 . 来源名 . SxxExx . 副标题 [规格]”可视化配置。

界面上：
- 中文主名称、点号、SxxExx 都是灰色只读，表示固定；
- “来源名”是下拉框，选哪个来源就用哪个来源的名字；
- 规格改成“是/否”开关；
- 底部实时预览一条示例文件名。

配置写回 NamingOptions，并持久化到 settings.json。
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .naming_rule import NAME_SOURCE_LABELS, build_episode_filename

GREY = "#8a8a8a"
FIXED_BG = "#eeeeee"

SUBTITLE_LABELS = {
    "auto": "自动（所选来源的剧集名）",
    "name_source": "与命名来源一致",
    "imdb": "IMDb 剧集名",
    "tmdb": "TMDB 剧集名",
    "douban": "豆瓣 本集中文名",
    "bangumi": "Bangumi 分集名",
    "keyword": "只取原文件名里的标题",
}

EXAMPLE_TITLE = "灵笼"
EXAMPLE_SEGMENTS = {
    "none": "",
    "imdb": "Ling Cage",
    "tmdb": "Ling Cage",
    "douban": "灵笼 第一季",
    "bangumi": "Ling Cage",
    "local": "Ling Cage",
}
EXAMPLE_SUBTITLES = {
    "auto": "灯塔和光影会",
    "name_source": "灯塔和光影会",
    "keyword": "灯塔和光影会",
}

# 日番文件夹格式（与 gui.JP_FOLDER_LABELS 保持一致的取值）
JP_FOLDER_OPTIONS = {
    "bdremux": "[BD-REMUX]中文名 日文名 (年份) [ID]",
    "standard": "标准：中文名 (年份) [ID]",
    # 不使用专门的日番规则：识别为日番时也按普通剧集规则命名
    "none": "不使用（日番按普通规则命名）",
}

# 电影命名：目前只有这一种写法
MOVIE_STYLES = {
    "title_year": "中文名 (年份) [ID]",
}
MOVIE_LABELS = dict(MOVIE_STYLES)

# 日番规则说明：鼠标悬浮在「日番」二字或下拉框上时显示
JP_STYLE_TOOLTIP = (
    "检测到日番类型时，会默认按这里的规则命名（例如加上 [BD-REMUX]、"
    "用日文名等），这是自动生效的。\n\n"
    "如果不希望套用这条规则，把下拉选为「不使用（日番按普通规则命名）」，"
    "日番就会和其它剧集一样按普通规则命名。"
)


def _attach_tooltip(widget, text, delay: int = 450,
                    dynamic: bool = False) -> None:
    """给任意 Tk 控件加悬浮提示（Tk 没有内置 tooltip，自己画一个小窗）。

    鼠标停留 delay 毫秒后弹出，移开立刻消失；不会抢焦点，也不影响点击。
    dynamic=True 时 text 是一个返回字符串的函数，每次悬停现取，
    这样示范能跟着下拉选择实时变化。
    """
    state: dict = {"tip": None, "after": None}

    def _text() -> str:
        if dynamic and callable(text):
            try:
                return str(text() or "")
            except Exception:
                return ""
        return str(text or "")

    def hide(_event=None) -> None:
        if state["after"] is not None:
            try:
                widget.after_cancel(state["after"])
            except Exception:
                pass
            state["after"] = None
        tip = state["tip"]
        state["tip"] = None
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass

    def show() -> None:
        state["after"] = None
        if state["tip"] is not None:
            return
        try:
            import tkinter as _tk
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 6
            tip = _tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
            label = _tk.Label(tip, text=_text(), justify="left",
                              background="#ffffe1", foreground="#333",
                              relief="solid", borderwidth=1,
                              font=("Microsoft YaHei UI", 9),
                              wraplength=420, padx=8, pady=6)
            label.pack()
            state["tip"] = tip
        except Exception:
            state["tip"] = None

    def schedule(_event=None) -> None:
        hide()
        try:
            state["after"] = widget.after(delay, show)
        except Exception:
            state["after"] = None

    widget.bind("<Enter>", schedule, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<ButtonPress>", hide, add="+")



EPISODE_TOOLTIP = (
    "剧集命名规则：\n"
    "  中文主名称 —— 取自任务标题（可在上方详情里改）\n"
    "  英文名段   —— 选「不显示」则不加；也可双击下拉框自己填\n"
    "  S01E01     —— 按文件名推断，固定\n"
    "  副标题     —— 选来源的分集名；也可双击自己填\n"
    "  规格       —— 是否保留 1080p、WEB-DL 等画质标记\n\n"
    "示例会随选择实时变化。双击任意下拉框可输入自定义值。"
)

MOVIE_TOOLTIP = (
    "电影命名规则：中文名 (年份) [ID]\n\n"
    "电影没有季集和副标题，所以单独一行。\n"
    "双击下拉框可输入自定义写法。"
)

class _EditableCombo(ttk.Frame):
    """下拉 + 输入的组合控件。

    为什么不用 ttk.Combobox：它的类绑定会吞掉第二次点击，
    <Double-1> 在本机根本触发不了，双击改输入做不出来。

    这里换成 Entry + ▼ 按钮：
      · Entry 平时只读
      · ▼ 按钮展开原生菜单，从预设选项里挑
      · editable=True 时，双击 Entry 可变成自定义输入（浅黄底），
        鼠标移上去会提示「双击可自定义」

    只有「英文名段」需要自定义输入，所以其余三个传 editable=False，
    它们就是纯粹的下拉框。
    """

    NORMAL_BG = "#f4f4f4"
    EDIT_BG = "#fff7d6"

    def __init__(self, parent, textvariable, values, width=20,
                 on_change=None, editable: bool = False, **kw):
        super().__init__(parent, **kw)
        self.var = textvariable
        self._values = list(values)
        self._on_change = on_change
        self._custom = False
        self._editing = False
        self._before = ""
        self._editable = bool(editable)

        self.entry = ttk.Entry(self, textvariable=textvariable,
                               width=width, state="readonly")
        self.entry.pack(side="left", fill="x", expand=True)
        # 只读状态下拖动/双击会选中文字，看起来像可输入，误导用户。
        # 纯下拉的几项直接禁用文本选择；可编辑的那项保留选择能力。
        if not self._editable:
            for seq in ("<Button-1>", "<Double-1>", "<Triple-1>",
                        "<B1-Motion>", "<Control-Button-1>"):
                self.entry.bind(seq, lambda e: "break")
            try:
                self.entry.configure(cursor="arrow")
            except Exception:      # noqa: BLE001
                pass
        self.btn = ttk.Button(self, text="▾", width=2,
                              command=self._open_menu)
        self.btn.pack(side="left")

        if self._editable:
            # 可双击自定义的那一个，外观要和其他纯下拉明显不同，
            # 否则用户会以为旁边几个也能输入：
            #   · 左侧 ✎ 图标
            #   · 浅蓝底色的专用 ttk 样式
            try:
                style = ttk.Style()
                style.configure("Editable.TEntry",
                                fieldbackground="#eaf3fd",
                                foreground="#123f6d")
                self.entry.configure(style="Editable.TEntry")
            except Exception:      # noqa: BLE001
                pass
            self._icon = tk.Label(self, text="✎", foreground="#2a6fb0",
                                  background="#eaf3fd",
                                  font=("Segoe UI", 9, "bold"),
                                  padx=2)
            self._icon.pack(side="left", before=self.entry)
            # 图标本身也能双击进入编辑（用户常点在它上面）
            self._icon.bind("<Double-1>", self._enter_edit)
            try:
                self._icon.configure(cursor="xterm")
            except Exception:      # noqa: BLE001
                pass
            _attach_tooltip(
                self._icon,
                "双击右侧输入框可自定义输入\n"
                "（直接打字替换，回车保存、Esc 取消）", delay=350)
            # 双击 Entry 进入编辑（Entry 是原生控件，双击一定触发）
            self.entry.bind("<Double-1>", self._enter_edit)
            self.entry.bind("<F2>", self._enter_edit)
            self.entry.bind("<Return>", self.commit)
            self.entry.bind("<KP_Enter>", self.commit)
            self.entry.bind("<Escape>", self.cancel)
            self.entry.bind("<FocusOut>", lambda e: self.commit())
            # 鼠标一移上来就提示「可以双击自定义」
            _attach_tooltip(
                self.entry,
                "双击可自定义输入\n"
                "（直接打字替换当前选项，回车保存、Esc 取消）",
                delay=350)
            try:
                self.entry.configure(cursor="xterm")
            except Exception:      # noqa: BLE001
                pass

    # ---------------- 兼容旧接口
    def get(self) -> str:
        return str(self.var.get())

    def set(self, value) -> None:
        self.var.set(value)

    def is_editing(self) -> bool:
        return bool(self._editing)

    def is_custom(self) -> bool:
        return bool(self._custom)

    def set_values(self, values) -> None:
        self._values = list(values)

    def cget(self, key):          # 让外部 cget("state") 之类不报错
        return self.entry.cget(key)

    def configure(self, **kw):    # noqa: D401
        return self.entry.configure(**kw)

    def config(self, **kw):       # noqa: D401
        return self.entry.configure(**kw)

    # ---------------- 交互
    def _open_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0)
        for v in self._values:
            menu.add_command(label=v,
                             command=lambda x=v: self._pick(x))
        try:
            x = self.btn.winfo_rootx()
            y = self.btn.winfo_rooty() + self.btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except Exception:      # noqa: BLE001
                pass

    def _pick(self, value: str) -> None:
        self.var.set(value)
        if callable(self._on_change):
            self._on_change()

    def _enter_edit(self, _event=None):
        if not self._editable:
            return None
        if self._editing:
            return "break"
        self._before = self.get()
        self._editing = True
        try:
            self.entry.configure(state="normal", background=self.EDIT_BG)
            self.entry.focus_set()
            self.entry.select_range(0, "end")
            self.entry.icursor("end")
        except Exception:      # noqa: BLE001
            pass
        return "break"

    def commit(self, _event=None):
        if not self._editing:
            return None
        text = str(self.get() or "").strip()
        if text:
            if text not in self._values:
                self._values = [text] + self._values
            self._custom = True
        else:
            self.var.set(self._before)
        self._editing = False
        try:
            self.entry.configure(state="readonly",
                                 background=self.NORMAL_BG)
        except Exception:      # noqa: BLE001
            pass
        if callable(self._on_change):
            self._on_change()
        return "break"

    def cancel(self, _event=None):
        if not self._editing:
            return None
        self.var.set(self._before)
        self._editing = False
        try:
            self.entry.configure(state="readonly",
                                 background=self.NORMAL_BG)
        except Exception:      # noqa: BLE001
            pass
        return "break"


class NamingRulePanel(ttk.LabelFrame):
    """主界面的“命名规则”面板：剧集、日番、电影各占一行。"""

    def __init__(self, parent, options_getter, options_setter):
        super().__init__(parent, text="命名规则", padding=8)
        self._get_options = options_getter
        self._set_options = options_setter
        opts = options_getter()
        self.seg_var = tk.StringVar(
            value=NAME_SOURCE_LABELS.get(
                getattr(opts, "name_segment_source", "imdb"),
                NAME_SOURCE_LABELS["imdb"]))
        self.sub_var = tk.StringVar(
            value=SUBTITLE_LABELS.get(
                getattr(opts, "subtitle_source", "auto"),
                SUBTITLE_LABELS["auto"]))
        self.spec_var = tk.BooleanVar(
            value=bool(getattr(opts, "include_specs", True)))
        self.jp_var = tk.StringVar(value=JP_FOLDER_OPTIONS.get(
            getattr(opts, "jp_folder_style", "bdremux"),
            JP_FOLDER_OPTIONS["bdremux"]))
        self.movie_var = tk.StringVar(
            value=MOVIE_LABELS.get(getattr(opts, "movie_style",
                                           "title_year"),
                                   MOVIE_LABELS["title_year"]))
        self._build()
        self._applied_snapshot = dict(self.values())
        self._refresh_preview()

    # ---------------- 界面
    def _build(self) -> None:
        # ① 剧集规则：中文主名称 · 英文名段 · S01E01 · 副标题 · 规格
        ep = ttk.Frame(self)
        ep.pack(fill="x", pady=(0, 3))
        ttk.Label(ep, text="剧集", width=4).pack(side="left")
        self._fixed_label(ep, "中文主名称")
        # 只有这一项支持双击自定义输入（用户明确要求）
        self.seg_combo = _EditableCombo(
            ep, self.seg_var, list(NAME_SOURCE_LABELS.values()),
            width=16, on_change=self._refresh, editable=True)
        self.seg_combo.pack(side="left", padx=(2, 6))
        self._fixed_label(ep, ". S01E01 .")
        self.sub_combo = _EditableCombo(
            ep, self.sub_var, list(SUBTITLE_LABELS.values()),
            width=20, on_change=self._refresh, editable=False)
        self.sub_combo.pack(side="left", padx=(2, 6))
        ttk.Label(ep, text="规格").pack(side="left", padx=(4, 2))
        ttk.Radiobutton(ep, text="是", value=True, variable=self.spec_var,
                        command=self._refresh).pack(side="left")
        ttk.Radiobutton(ep, text="否", value=False, variable=self.spec_var,
                        command=self._refresh).pack(side="left", padx=(2, 4))
        # 只有行尾的圆圈问号显示整行说明与示范。不要把提示绑到整行
        # 容器上：否则鼠标经过任意控件都会弹出，还会叠成两个框。
        self._help_badge(ep, self._episode_tooltip)

        # ② 日番规则
        jp = ttk.Frame(self)
        jp.pack(fill="x", pady=(0, 3))
        ttk.Label(jp, text="日番", width=4).pack(side="left")
        self.jp_box = _EditableCombo(
            jp, self.jp_var, list(JP_FOLDER_OPTIONS.values()),
            width=34, on_change=self._refresh, editable=False)
        self.jp_box.pack(side="left", padx=(2, 6))
        self._help_badge(jp, self._jp_tooltip)

        # ③ 电影规则
        mv = ttk.Frame(self)
        mv.pack(fill="x", pady=(0, 3))
        ttk.Label(mv, text="电影", width=4).pack(side="left")
        self.movie_box = _EditableCombo(
            mv, self.movie_var,
            [MOVIE_LABELS[k] for k in MOVIE_STYLES],
            width=34, on_change=self._refresh, editable=False)
        self.movie_box.pack(side="left", padx=(2, 6))
        self._help_badge(mv, self._movie_tooltip)

        # 界面上不再保留示范区：示范统一放进各自问号的悬浮提示里，
        # 这样「命名规则」模块能上下收紧成三行。
        self.dirty_label = ttk.Label(self, text="", foreground="#b26a00")
        self.dirty_label.pack(fill="x", anchor="w")

    @staticmethod
    def _fixed_label(parent, text: str) -> ttk.Label:
        lab = ttk.Label(parent, text=text, foreground=GREY,
                        background=FIXED_BG, padding=(4, 1))
        lab.pack(side="left")
        return lab

    @staticmethod
    def _help_badge(parent, tooltip_getter) -> ttk.Label:
        """行尾的圆圈问号：悬停显示该行规则的说明与当前示范。

        tooltip_getter 是个函数，每次悬停时现取文案，这样示范能跟着
        下拉选择实时变化，而不用在界面上留一块示范区。
        """
        lab = ttk.Label(parent, text="?", cursor="question_arrow",
                        foreground="#ffffff", background="#2a6fb0",
                        padding=(4, 0),
                        font=("Segoe UI", 9, "bold"))
        lab.pack(side="left", padx=(6, 0))
        _attach_tooltip(lab, tooltip_getter, dynamic=True)
        return lab

    # ---------------- 数据
    def _source_key(self) -> str:
        label = self.seg_var.get()
        for key, val in NAME_SOURCE_LABELS.items():
            if val == label:
                return key
        return str(label or "imdb")

    def _subtitle_key(self) -> str:
        label = self.sub_var.get()
        for key, val in SUBTITLE_LABELS.items():
            if val == label:
                return key
        return str(label or "auto")

    def _jp_key(self) -> str:
        label = self.jp_var.get()
        for key, val in JP_FOLDER_OPTIONS.items():
            if val == label:
                return key
        return str(label or "bdremux")

    def _movie_key(self) -> str:
        label = self.movie_var.get()
        for key, val in MOVIE_LABELS.items():
            if val == label:
                return key
        return str(label or "title_year")

    # ---------------- 悬浮说明（示范随选择实时变化）
    def _episode_tooltip(self) -> str:
        seg_key = self._source_key()
        sample = build_episode_filename(
            EXAMPLE_TITLE, 1, 1, ext=".mp4",
            name_segment=EXAMPLE_SEGMENTS.get(seg_key, ""),
            subtitle="灯塔和光影会",
            specs="1080p WEB-DL" if self.spec_var.get() else "")
        return (
            "剧集命名规则（当前示范）\n"
            f"  {sample}\n\n"
            "  中文主名称 —— 取自任务标题（可在上方详情里改）\n"
            "  英文名段   —— 选「不显示」则不加；也可双击下拉框自己填\n"
            "  S01E01     —— 按文件名推断，固定\n"
            "  副标题     —— 选来源的分集名；也可双击自己填\n"
            "  规格       —— 是否保留 1080p、WEB-DL 等画质标记\n\n"
            "双击任意下拉框可输入自定义值。")

    def _jp_tooltip(self) -> str:
        if self._jp_key() == "bdremux":
            sample = ("[BD-REMUX]86 -不存在的战区 "
                      "86―エイティシックス― (2021) [imdbid-tt13718450]")
        elif self._jp_key() == "standard":
            sample = "86 -不存在的战区 (2021) [imdbid-tt13718450]"
        else:
            sample = "不套用日番专用规则，按上面的剧集规则命名"
        return (f"日番文件夹（当前示范）\n  {sample}\n\n"
                + JP_STYLE_TOOLTIP)

    def _movie_tooltip(self) -> str:
        return ("电影命名（当前示范）\n  朝花夕拾 (2018) [imdbid-tt9691596]\n\n"
                + MOVIE_TOOLTIP)

    def _refresh_preview(self) -> None:
        # 界面上没有示范区了（示范在问号悬浮里），这里只负责
        # 把面板上的选择同步到 NamingOptions 并更新「已改未应用」提示。
        self._apply()
        self._update_dirty_hint()

    def _update_dirty_hint(self) -> None:
        lbl = getattr(self, "dirty_label", None)
        if lbl is None:
            return
        applied = getattr(self, "_applied_snapshot", None) or {}
        cur = self.values()
        labels = {"name_segment_source": "英文名段",
                  "subtitle_source": "副标题",
                  "jp_folder_style": "日番格式",
                  "movie_style": "电影格式",
                  "include_specs": "规格"}
        changed = [labels[k] for k in labels
                   if k in applied and applied[k] != cur.get(k)]
        if changed:
            lbl.configure(
                text=f"● 已改：{'、'.join(changed)}"
                     " —— 点右下「保存为默认并重建当前任务」才会用到任务上")
        else:
            lbl.configure(text="")

    def mark_applied(self) -> None:
        self._applied_snapshot = dict(self.values())
        self._update_dirty_hint()

    def _refresh(self) -> None:
        self._refresh_preview()

    def _apply(self) -> None:
        opts = self._get_options()
        opts.name_segment_source = self._source_key()
        opts.subtitle_source = self._subtitle_key()
        opts.include_specs = bool(self.spec_var.get())
        opts.jp_folder_style = self._jp_key()
        try:
            opts.movie_style = self._movie_key()
        except Exception:
            pass
        self._set_options(opts)

    def reload(self) -> None:
        opts = self._get_options()
        self.seg_var.set(NAME_SOURCE_LABELS.get(
            getattr(opts, "name_segment_source", "imdb"),
            NAME_SOURCE_LABELS["imdb"]))
        self.sub_var.set(SUBTITLE_LABELS.get(
            getattr(opts, "subtitle_source", "auto"),
            SUBTITLE_LABELS["auto"]))
        self.spec_var.set(bool(getattr(opts, "include_specs", True)))
        self.jp_var.set(JP_FOLDER_OPTIONS.get(
            getattr(opts, "jp_folder_style", "bdremux"),
            JP_FOLDER_OPTIONS["bdremux"]))
        self.movie_var.set(MOVIE_LABELS.get(
            getattr(opts, "movie_style", "title_year"),
            MOVIE_LABELS["title_year"]))
        self._refresh_preview()

    def values(self) -> dict:
        return {
            "name_segment_source": self._source_key(),
            "subtitle_source": self._subtitle_key(),
            "include_specs": bool(self.spec_var.get()),
            "jp_folder_style": self._jp_key(),
            "movie_style": self._movie_key(),
        }
