# -*- coding: utf-8 -*-
"""手动搜索的共用逻辑：并发搜各来源 → 去重 → 合并 → 相关性排序。

Tk 界面与 Qt 界面都调用这里的函数，保证两端结果完全一致。
（此前 Qt 版各自直接调用 search_xxx，绕过了去重与排序，
结果里混进大量无关条目，且没有用上 IMDb 的正确命中。）
"""
from __future__ import annotations

from typing import Callable, Optional

from rapidfuzz import fuzz

from .textnorm import fuzzy_queries, norm_title

# 来源优先级：同等相关度时，中文来源优先
SOURCE_ORDER = {"bangumi": 0, "douban": 1, "imdb": 2, "tmdb": 3}


def candidate_season(c):
    """候选的季号（没有就返回 None）。"""
    from .scoring import candidate_season as _cs
    try:
        return _cs(c)
    except Exception:
        return None


def search_all(meta,
               query: str,
               keywords: Optional[list[str]] = None,
               media_type: str = "series",
               season: Optional[int] = None,
               year: Optional[int] = None,
               use_bangumi: bool = True,
               tmdb_key: str = "",
               status: Optional[Callable[[str], None]] = None) -> tuple[list, list]:
    """搜全部来源，返回 (已排序的候选列表, 说明列表)。

    - 关键词由 `fuzzy_queries` 生成（主标题优先，再季号变体）；
    - 每个来源按关键词顺序尝试，命中目标季即停止，减少请求；
    - 结果按（与关键词的相似度、来源优先级、年份）排序。
    """
    say = status or (lambda _s: None)
    keywords = list(keywords or [])
    queries = fuzzy_queries([query] + keywords, media_type, season, year,
                            limit=8) or [query]

    found: list = []
    notes: list[str] = []

    def run_many(label: str, fn, max_queries: int) -> None:
        say(f"{label} 搜索中…")
        got_all: list = []
        seen: set = set()
        error = ""
        for q in queries[:max_queries]:
            try:
                got = fn(q) or []
            except Exception as e:      # noqa: BLE001
                error = str(e)
                continue
            for c in got:
                key = ((c.source, c.sid) if c.sid
                       else (c.source, norm_title(c.title), c.year))
                if key in seen:
                    continue
                seen.add(key)
                got_all.append(c)
            if season is not None and any(
                    candidate_season(c) == season for c in got):
                break
        if got_all:
            found.extend(got_all)
            notes.append(f"{label} {len(got_all)}")
        elif error:
            notes.append(f"{label} 失败：{error}")
        else:
            notes.append(f"{label} 0")

    if use_bangumi:
        run_many("Bangumi", meta.search_bangumi, 3)
    else:
        notes.append("Bangumi 已关闭")
    run_many("IMDb", meta.search_imdb, 4)
    run_many("豆瓣", meta.search_douban, 4)
    if tmdb_key:
        run_many("TMDB", lambda q: meta.search_tmdb(q, media_type), 2)
    else:
        notes.append("未配置 TMDB Key")

    ranked = sort_by_relevance(found, query, keywords, season, year)

    # 方案 1：搜索阶段就为每个候选预取它自己的「英文名 / 分集名」，
    # 双击选中后可立即套用，不用再等联网。
    try:
        from .prefetch import prefetch_for
        top = [c for c in ranked if getattr(c, "sid", "")][:8]
        done = prefetch_for(meta, top, media_type, season, say)
        if done:
            notes.append(f"已预取词句 {done} 条")
    except Exception as e:      # noqa: BLE001
        notes.append(f"预取词句失败：{e}")

    return ranked, notes


def sort_by_relevance(found: list, query: str,
                      keywords: Optional[list[str]] = None,
                      season: Optional[int] = None,
                      year: Optional[int] = None) -> list:
    """按与搜索词的相关度排序（与 Tk 版规则一致）。

    完全同名的候选会被明显抬到前面；与目标季/年份不符的会被压后。
    """
    query_norms = [norm_title(q) for q in
                   ([query] + list(keywords or [])) if norm_title(q)]

    def relevance(c) -> float:
        vals = []
        for t in ((c.title or ""), (c.original_title or "")):
            tn = norm_title(t)
            if not tn:
                continue
            # 完全同名给 1.0，避免被长标题的模糊高分超过
            if tn in query_norms:
                vals.append(1.0)
                continue
            if query_norms:
                vals.append(max(fuzz.WRatio(qn, tn) / 100.0
                                for qn in query_norms))
        best = max(vals) if vals else 0.0
        cs = candidate_season(c)
        if season is not None and cs is not None:
            best += 0.10 if cs == season else -0.30
        if year and c.year:
            d = abs(year - c.year)
            if d == 0:
                best += 0.04
            elif d > 2:
                best -= 0.08
        return best

    return sorted(found, key=lambda c: (-relevance(c),
                                        SOURCE_ORDER.get(c.source, 9),
                                        -(c.year or 0), c.title or ""))
