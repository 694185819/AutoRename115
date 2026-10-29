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
}

# 电影命名：目前只有这一种写法
MOVIE_STYLES = {
    "title_year": "中文名 (年份) [ID]",
}
MOVIE_LABELS = dict(MOVIE_STYLES)


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
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(0, 6))

        # 原先把“中文主名称 / . / . / S01E01 / .”做成 5 个独立 Label，
        # 它们只是展示固定位置；合并成一个标签，少 4 个控件，
        # 窗口缩放时 Tk 要遍历的节点更少。
        self._fixed_label(row, "中文主名称 .")
        self.seg_combo = ttk.Combobox(
            row, textvariable=self.seg_var, state="readonly", width=18,
            values=list(NAME_SOURCE_LABELS.values()))
        self.seg_combo.pack(side="left")
        self.seg_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self._fixed_label(row, ". S01E01 .")
        self.sub_combo = ttk.Combobox(
            row, textvariable=self.sub_var, state="readonly", width=22,
            values=list(SUBTITLE_LABELS.values()))
        self.sub_combo.pack(side="left")
        self.sub_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        ttk.Label(row, text="规格").pack(side="left", padx=(10, 2))
        ttk.Radiobutton(row, text="是", value=True,
                        variable=self.spec_var,
                        command=self._refresh).pack(side="left")
        ttk.Radiobutton(row, text="否", value=False,
                        variable=self.spec_var,
                        command=self._refresh).pack(side="left", padx=(2, 0))

        # 预览行同时承担原来那条“灰色为固定内容”的说明，省掉一个静态标签。
        self.preview = ttk.Label(self, text="", foreground="#176b33",
                                 wraplength=560, justify="left")
        self.preview.pack(anchor="w", pady=(4, 0))

        # 日番与电影也在这里统一配置，避免散落到设置窗口。
        extra = ttk.Frame(self)
        extra.pack(fill="x", pady=(6, 0))
        ttk.Label(extra, text="日番文件夹格式").pack(side="left")
        self.jp_box = ttk.Combobox(
            extra, textvariable=self.jp_var, state="readonly", width=26,
            values=list(JP_FOLDER_OPTIONS.values()))
        self.jp_box.pack(side="left", padx=(4, 12))
        self.jp_box.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        ttk.Label(extra, text="电影").pack(side="left")
        self.movie_box = ttk.Combobox(
            extra, textvariable=self.movie_var, state="readonly", width=26,
            values=[MOVIE_LABELS[k] for k in MOVIE_STYLES])
        self.movie_box.pack(side="left", padx=(4, 0))
        self.movie_box.bind("<<ComboboxSelected>>", lambda e: self._refresh())

    @staticmethod
    def _fixed_label(parent, text: str) -> ttk.Label:
        lab = ttk.Label(parent, text=text, foreground=GREY,
                        background=FIXED_BG, padding=(4, 1))
        lab.pack(side="left")
        return lab

    @staticmethod
    def _dot(parent) -> None:
        ttk.Label(parent, text=".", foreground=GREY,
                  background=FIXED_BG, padding=(3, 1),
                  font=("Segoe UI", 10, "bold")).pack(side="left")

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
