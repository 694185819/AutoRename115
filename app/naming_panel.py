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


def _attach_tooltip(widget, text: str, delay: int = 450) -> None:
    """给任意 Tk 控件加悬浮提示（Tk 没有内置 tooltip，自己画一个小窗）。

    鼠标停留 delay 毫秒后弹出，移开立刻消失；不会抢焦点，也不影响点击。
    """
    state: dict = {"tip": None, "after": None}

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
            label = _tk.Label(tip, text=text, justify="left",
                              background="#ffffe1", foreground="#333",
                              relief="solid", borderwidth=1,
                              font=("Microsoft YaHei UI", 9),
                              wraplength=380, padx=8, pady=6)
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


class NamingRulePanel(ttk.LabelFrame):
    """主界面的“命名规则”面板：剧集、日番、电影都由它统一配置。"""

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
        self._refresh_preview()

    # ---------------- 界面
    def _build(self) -> None:
        # 第一行：把“中文主名称 / 点号 / S01E01”这些固定展示合并成两个标签，
        # 并且不再额外套一层 Frame —— Tk 重排成本与布局节点数近似线性，
        # 每省一层容器，拖动缩放时都要快一点。
        first = ttk.Frame(self)
        first.pack(fill="x", pady=(0, 2))
        self._fixed_label(first, "中文主名称 .")
        self.seg_combo = ttk.Combobox(
            first, textvariable=self.seg_var, state="readonly", width=18,
            values=list(NAME_SOURCE_LABELS.values()))
        self.seg_combo.pack(side="left")
        self.seg_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self._fixed_label(first, ". S01E01 .")
        self.sub_combo = ttk.Combobox(
            first, textvariable=self.sub_var, state="readonly", width=22,
            values=list(SUBTITLE_LABELS.values()))
        self.sub_combo.pack(side="left")
        self.sub_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        # 第二行：规格开关 + 日番格式 + 电影（都放在同一行，省一层容器）
        second = ttk.Frame(self)
        second.pack(fill="x", pady=(2, 2))
        ttk.Label(second, text="规格").pack(side="left", padx=(0, 2))
        ttk.Radiobutton(second, text="是", value=True,
                        variable=self.spec_var,
                        command=self._refresh).pack(side="left")
        ttk.Radiobutton(second, text="否", value=False,
                        variable=self.spec_var,
                        command=self._refresh).pack(side="left", padx=(2, 12))
        # 「日番」二字本身就带悬浮提示（鼠标移上去显示说明）
        jp_label = ttk.Label(second, text="日番", cursor="question_arrow")
        jp_label.pack(side="left")
        _attach_tooltip(jp_label, JP_STYLE_TOOLTIP)
        self.jp_box = ttk.Combobox(
            second, textvariable=self.jp_var, state="readonly", width=24,
            values=list(JP_FOLDER_OPTIONS.values()))
        self.jp_box.pack(side="left", padx=(4, 12))
        _attach_tooltip(self.jp_box, JP_STYLE_TOOLTIP)
        self.jp_box.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        ttk.Label(second, text="电影").pack(side="left")
        self.movie_box = ttk.Combobox(
            second, textvariable=self.movie_var, state="readonly", width=22,
            values=[MOVIE_LABELS[k] for k in MOVIE_STYLES])
        self.movie_box.pack(side="left", padx=(4, 0))
        self.movie_box.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        # 预览行：同时承担“灰色为固定内容”的说明，省掉一个纯静态标签。
        self.preview = ttk.Label(self, text="", foreground="#176b33",
                                 wraplength=560, justify="left")
        self.preview.pack(anchor="w", pady=(2, 0))

    @staticmethod
    def _fixed_label(parent, text: str) -> ttk.Label:
        lab = ttk.Label(parent, text=text, foreground=GREY,
                        background=FIXED_BG, padding=(4, 1))
        lab.pack(side="left")
        return lab

    # ---------------- 数据
    def _source_key(self) -> str:
        label = self.seg_var.get()
        for key, val in NAME_SOURCE_LABELS.items():
            if val == label:
                return key
        return "imdb"

    def _subtitle_key(self) -> str:
        label = self.sub_var.get()
        for key, val in SUBTITLE_LABELS.items():
            if val == label:
                return key
        return "auto"

    def _jp_key(self) -> str:
        label = self.jp_var.get()
        for key, val in JP_FOLDER_OPTIONS.items():
            if val == label:
                return key
        return "bdremux"

    def _refresh_preview(self) -> None:
        seg_key = self._source_key()
        sample = build_episode_filename(
            EXAMPLE_TITLE, 1, 1, ext=".mp4",
            name_segment=EXAMPLE_SEGMENTS.get(seg_key, ""),
            subtitle="灯塔和光影会",
            specs="1080p WEB-DL" if self.spec_var.get() else "")
        if self._jp_key() == "bdremux":
            jp_example = "[BD-REMUX]86 -不存在的战区 86―エイティシックス― (2021) [imdbid-tt13718450]"
        else:
            jp_example = "86 -不存在的战区 (2021) [imdbid-tt13718450]"
        movie_example = "朝花夕拾 (2018) [imdbid-tt9691596]"
        self.preview.configure(
            text=f"灰色为固定项（中文主名称取自任务标题，SxxExx 按文件推断）\n"
                 f"剧集：{sample}\n日番文件夹：{jp_example}\n"
                 f"电影：{movie_example}（目前只有这一种写法）")
        self._apply()

    def _refresh(self) -> None:
        self._refresh_preview()

    def _apply(self) -> None:
        opts = self._get_options()
        opts.name_segment_source = self._source_key()
        opts.subtitle_source = self._subtitle_key()
        opts.include_specs = bool(self.spec_var.get())
        opts.jp_folder_style = self._jp_key()
        self._set_options(opts)

    def reload(self) -> None:
        """按当前 NamingOptions 重新同步界面（设置被外部改动后调用）。"""
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
        self._refresh_preview()

    def values(self) -> dict:
        """给设置对话框保存用的配置字典。"""
        return {
            "name_segment_source": self._source_key(),
            "subtitle_source": self._subtitle_key(),
            "include_specs": bool(self.spec_var.get()),
            "jp_folder_style": self._jp_key(),
        }
