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


def sanitize_segment(text: str, max_bytes: int = 120,
                     colon_to_dot: bool = True) -> str:
    """把一个名字段清洗成可放进文件名的形式（不含点号分隔）。"""
    t = str(text or "")
    # 去掉文件名非法字符
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", t)
    if colon_to_dot:
        t = t.replace(":", ".").replace("：", ".")
    t = re.sub(r"[\s]+", ".", t.strip())
    t = re.sub(r"\.{2,}", ".", t)
    t = t.strip(" .-_·")
    if len(t.encode("utf-8")) > max_bytes:
        data = t.encode("utf-8")[:max_bytes]
        t = data.decode("utf-8", "ignore").rstrip(" .-_")
    return t


def episode_tag(season: int, ep: int, ep_end: Optional[int] = None,
                version: str = "") -> str:
    """S01E02 / S01E02-E03 / 带 v2。"""
    tag = f"S{int(season):02d}E{int(ep):02d}"
    if ep_end and int(ep_end) != int(ep):
        tag += f"-E{int(ep_end):02d}"
    return tag + (version or "")


def build_episode_filename(
        title: str,
        season: int,
        ep: int,
        *,
        ext: str = "",
        name_segment: str = "",
        subtitle: str = "",
        specs: str = "",
        ep_end: Optional[int] = None,
        version: str = "",
        budget: int = 235,
        colon_to_dot: bool = True) -> str:
    """按固定顺序拼装剧集文件名。

    `name_segment` 是“来源名”那一段（选“不显示”时传空），
    `subtitle` 是 SxxExx 后面的剧集副标题（没有传空）。
    中文主名称按原名保留（全角冒号等不改成点号），
    来源名/副标题仍会把冒号换成点号以符合命名惯例。
    """
    tag = episode_tag(season, ep, ep_end, version)
    cn = sanitize_segment(title, budget, colon_to_dot=False)
    seg = sanitize_segment(name_segment, budget, colon_to_dot) if \
        name_segment else ""
    if seg and norm_title(seg) == norm_title(cn):
        seg = ""                      # 与中文名相同的英文名不重复写
    sub = sanitize_segment(subtitle, budget, colon_to_dot) if subtitle else ""
    spec_part = f" [{specs.strip()}]" if (specs or "").strip() else ""

    fixed = len(ext.encode("utf-8")) + len(tag.encode("utf-8")) + \
        len(spec_part.encode("utf-8")) + 2      # 两个点号
    # 预算不够时依次让出副标题、来源名的空间，SxxExx 与规格始终保留
    def used(text: str) -> int:
        return len(text.encode("utf-8")) if text else 0

    while used(cn) + used(seg) + used(sub) + fixed > budget:
        if sub and used(sub) > 8:
            sub = sub[:-1].rstrip(" .-_")
            continue
        if sub:
            sub = ""
            continue
        if seg and used(seg) > 8:
            seg = seg[:-1].rstrip(" .-_")
            continue
        if seg:
            seg = ""
            continue
        if used(cn) > fixed + 8:
            cn = cn[:-1].rstrip(" .-_")
            continue
        break

    parts = [p for p in (cn, seg) if p]
    head = ".".join(parts)
    tail = ""
    for piece in (tag, sub):
        if piece:
            tail += "." + piece
    name = (head + tail + spec_part) if head else (tail.lstrip(".") + spec_part)
    return name + ext


def build_movie_filename(title: str, year: Optional[int], ext: str = "",
                         specs: str = "", id_suffix: str = "",
                         budget: int = 235) -> str:
    """电影：标题 (年份) [规格] [id]  —— 保持原有“电影不动原名”的规则由调用方决定。"""
    cn = sanitize_segment(title, budget, colon_to_dot=False)
    if year:
        cn = re.sub(r"\s*\(\s*\d{4}\s*\)\s*$", "", cn).strip(" .-_")
        cn = f"{cn} ({int(year)})"
    spec_part = f" [{specs.strip()}]" if (specs or "").strip() else ""
    return cn + spec_part + (id_suffix or "") + ext
