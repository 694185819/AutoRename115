# -*- coding: utf-8 -*-
"""候选预取：搜索阶段就把每个候选自己的「英文名 / 分集名」取好。

方案 1：搜索时预取，双击后立即出结果。
每个候选按**自己的来源**取自己的词句，互不混用：
  - 英文名：该来源条目的 original_title / title
  - 分集名：该来源的分集接口（TMDB season / Bangumi eps / 豆瓣分集页）
"""
from __future__ import annotations

from typing import Callable, Optional


def prefetch_for(meta, candidates: list, media_type: str = "series",
                 season: Optional[int] = None,
                 status: Optional[Callable[[str], None]] = None) -> int:
    """为候选列表预取英文名与分集名，返回成功预取的条数。

    只取「有明确 ID」的候选；失败静默跳过，不影响搜索结果展示。
    """
    say = status or (lambda _s: None)
    done = 0
    total = len(candidates or [])
    for idx, cand in enumerate(candidates or [], 1):
        src = getattr(cand, "source", "")
        sid = str(getattr(cand, "sid", "") or "")
        if not src or not sid:
            continue
        say(f"预取词句 {idx}/{total}：{src} {sid}")
        try:
            ok = _prefetch_one(meta, cand, media_type, season)
        except Exception:
            ok = False
        if ok:
            done += 1
    return done


def _prefetch_one(meta, cand, media_type: str, season) -> bool:
    extra = cand.extra if isinstance(cand.extra, dict) else {}
    cand.extra = extra
    got = False

    # ---- 英文名：优先取该来源的非中文名 ----
    # TMDB/豆瓣的 original_title 也可能是中文（青云志），
    # 这时要从别名里挑外文名。
    raw_names = [
        str(getattr(cand, "original_title", "") or ""),
        str(getattr(cand, "title", "") or ""),
    ]
    raw_names += [str(x) for x in (extra.get("aliases") or [])]

    def _is_cjk(s: str) -> bool:
        import re as _re
        return bool(_re.search(r"[\u4e00-\u9fff]", s or ""))

    foreign = [n for n in raw_names if n and not _is_cjk(n)]
    chinese = [n for n in raw_names if n and _is_cjk(n)]
    if foreign:
        extra.setdefault("english_title", foreign[0])
        got = True
    elif chinese:
        # 该来源只有中文名（例如 TMDB 的青云志）。不要把中文当英文名
        # 塞进 english_title——来源名那一段要的是外文名，
        # 让它走通用回退（拼音让位真英文名 / 文件名英文）。
        extra.setdefault("has_cjk_only", True)
        got = True

    # ---- 分集名：走该来源自己的接口 ----
    if not extra.get("episode_titles"):
        titles = _episode_titles(meta, cand, media_type, season)
        if titles:
            extra["episode_titles"] = titles
            got = True
    return got


def _episode_titles(meta, cand, media_type: str, season) -> dict:
    src = cand.source
    sid = str(cand.sid)
    se = season
    if se is None:
        se = 1
    try:
        data = meta.source_episode_titles(src, sid, int(se))
    except Exception:
        data = {}
    if not data and src == "tmdb":
        try:
            data = meta.season_episode_titles(sid, int(se)) or {}
        except Exception:
            data = {}
    return dict(data or {})
