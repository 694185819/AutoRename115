# -*- coding: utf-8 -*-
"""命名拼装：按“中文主名称 . <来源副标题> . SxxExx . 副标题 [规格]”组装。

对应设置里的“命名方式”：每个位置都能单独选择来源或开关，顺序固定：

   中文主名称 . 来源名 . SxxExx . 剧集副标题 [规格]

- 中文主名称：固定，取自任务标题（灰色不可编辑）；
- 第一个点号：固定分隔符；
- “来源名”：下拉可选 IMDb / TMDB 英文名、豆瓣 / Bangumi 原名等；
- SxxExx：按文件夹/文件推断，固定；
- “剧集副标题”：按所选来源取（没有就省略这一段）；
- 规格：由“是否写入规格”决定。

本模块只做拼装与清洗，不联网；取数在 planner / metadata 里完成。
"""
from __future__ import annotations

import re
from typing import Optional

from .textnorm import norm_title

# 中间“来源名”的可选值
NAME_SOURCE_LABELS = {
    "none": "不显示",
    "imdb": "IMDb 英文名",
    "tmdb": "TMDB 英文名",
    "douban": "豆瓣 原名",
    "bangumi": "Bangumi 原名",
    "local": "本地英文/罗马音名",
}


# 实现已统一到 naming_template（唯一拼装实现）；这里保留函数名，
# 供既有调用方继续使用，行为完全一致。
from . import naming_template as _tpl

sanitize_segment = _tpl.sanitize_segment
episode_tag = _tpl.episode_tag
build_episode_filename = _tpl.build_episode_filename
build_movie_filename = _tpl.build_movie_filename
