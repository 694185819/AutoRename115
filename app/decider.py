# -*- coding: utf-8 -*-
"""候选决策：从各来源候选集合到最终 `MatchResult`。

从 `MetadataClient.match()` 拆出的后两段：

1. `decide()`：去重、锚点过滤、年份过滤、主结果挑选、跨来源核对、
   标题/ID/地区/动画/置信度——只依赖候选与 `scoring`，不碰网络；
2. `identify_series()`：季条目的主剧还原（主剧名/首播年/主剧 IMDb）。

网络与编排仍在 `MetadataClient.search_pool()` / `match()`。
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from . import scoring
from .models import Candidate, MatchResult, ParsedName
from .textnorm import (
    RE_CJK, candidate_season, has_kana, norm_title,
    strip_season_and_subtitle, strip_season_markers, titles_agree,
)


def dedupe(cands: list[Candidate]) -> list[Candidate]:
    """同一来源同一 ID 只留分数最高的一条。"""
    by_id: dict[tuple[str, str], Candidate] = {}
    for c in cands:
        if not c:
            continue
        k = (c.source, c.sid)
        if k not in by_id or c.score > by_id[k].score:
            by_id[k] = c
    return list(by_id.values())


def apply_category_bias(category: str, pools: dict[str, list[Candidate]]) -> None:
    """文件夹归属（动画区/电视剧区）参与排序。

    同一个中文名下既有动画又有真人剧时，优先选和目录一致的那个。
    """
    if category not in ("anime", "jp_anime", "cn_anime", "us_anime",
                        "west_anime", "tv", "movie"):
        return
    want_anime = category in ("anime", "jp_anime", "cn_anime",
                              "us_anime", "west_anime")
    for cands in pools.values():
        for c in cands:
            is_anim = scoring.candidate_is_animation(c)
            if is_anim:
                if want_anime:
                    c.score = min(1.0, c.score + 0.06)
                else:
                    c.score = max(0.0, c.score - 0.10)
            elif isinstance(c.extra, dict) and \
                    c.extra.get("animation") is False and want_anime:
                # 动画目录里明确不是动画的条目（如真人版）要明显降权，
                # 否则“降世神通 第二季”会输给同名的 2026 真人版。
                c.score = max(0.0, c.score - 0.18)


def filter_by_anchor(parsed: ParsedName, pools: dict[str, list[Candidate]],
                     log: Callable[[str], None],
                     res: MatchResult) -> None:
    """主结果必须和本地标题/别名有真正的文字重合。

    仅靠“剧版”“第一季”这类前缀或高年份拿高分的条目直接淘汰，
    否则 Big Hero 6 会因为标题以“剧版”开头而抢走一部布袋戏。
    """
    anchors = scoring.anchor_titles(parsed)
    if not anchors:
        return
    dropped: list[str] = []
    for name in ("bangumi", "douban", "tmdb"):
        kept = []
        for c in pools.get(name, []):
            if scoring.candidate_matches_anchor(c, anchors):
                kept.append(c)
            elif c.title:
                dropped.append(c.title)
        pools[name] = kept
    if dropped:
        shown = "、".join(list(dict.fromkeys(dropped))[:6])
        # 这些是搜索接口顺带返回的模糊结果，已被锚点校验淘汰；
        # 详情只写运行日志，避免预览里看起来像是采用了它们。
        log(f"自动匹配已过滤无关候选（未采用）：{shown}")
        res.notes.append(
            "已忽略标题与本地不一致的候选"
            f"（{len(set(dropped))} 个，未采用）。")


def filter_by_movie_year(parsed: ParsedName, media_type: str,
                         pools: dict[str, list[Candidate]]) -> None:
    """电影年份是最强的消歧信息：先排除年份差超过 1 年的同名条目。

    剧集首播年与季年份可能不同，不能这样硬过滤。
    """
    if media_type != "movie" or not parsed.year:
        return
    for name in ("bangumi", "douban", "tmdb"):
        kept = [c for c in pools.get(name, [])
                if c.year is None or abs(c.year - parsed.year) <= 1]
        if kept:
            pools[name] = kept


def _pick_one(pools: dict[str, list[Candidate]], media_type: str,
              picker) -> tuple[Optional[Candidate], Optional[Candidate],
                               Optional[Candidate]]:
    return (picker(pools.get("bangumi", []), media_type),
            picker(pools.get("douban", []), media_type),
            picker(pools.get("tmdb", []), media_type))


def decide(parsed: ParsedName, media_type: str, category: str,
           pools: dict[str, list[Candidate]],
           log: Callable[[str], None]) -> MatchResult:
    """由候选集合决定最终匹配结果（不访问网络）。"""
    res = MatchResult()
    scoring_pools = {
        "bangumi": list(pools.get("bangumi", [])),
        "douban": list(pools.get("douban", [])),
        "imdb": list(pools.get("imdb", [])),
        "tmdb": list(pools.get("tmdb", [])),
    }
    # 先确保每条候选都有分数：title_score 等细节写在 extra 里，
    # 后面的锚点过滤与挑选都依赖它（老版本在搜索阶段就打过分，
    # 这里再打一次是幂等的，调用方能直接传裸候选进来）。
    for cands in scoring_pools.values():
        for c in cands:
            if not isinstance(c.extra, dict) or "title_score" not in c.extra:
                c.score = scoring.score(parsed, c, media_type)
    apply_category_bias(category, scoring_pools)
    for name in scoring_pools:
        scoring_pools[name] = dedupe(scoring_pools[name])

    filter_by_anchor(parsed, scoring_pools, log, res)
    filter_by_movie_year(parsed, media_type, scoring_pools)
    anchors = scoring.anchor_titles(parsed)

    best_bg, best_db, best_tmdb = _pick_one(
        scoring_pools, media_type, scoring.pick_primary)
    if not any((best_bg, best_db, best_tmdb)):
        # 严格锚点把全部候选都淘汰时，再给一次“整串组合名”机会：
        # 本地是“异国日记 Ikoku Nikki”而官方只有英文名时，严格
        # 第一轮会一个都不剩；第二轮要求候选名和本地整串/分隔段
        # 真正相似（不是 partial 包含），仍不满足就让任务进需确认。
        combo = scoring.combo_anchors(parsed)
        if combo:
            def combo_ok(c: Candidate) -> bool:
                if not scoring.candidate_matches_anchor(c, combo):
                    return False
                names = [norm_title(n) for n in
                         scoring.candidate_names(c) if norm_title(n)]
                return any(scoring.names_really_agree(n, cp)
                           for n in names for cp in combo)

            def combo_picker(cands, mt):
                return scoring.pick_primary(
                    [c for c in cands if combo_ok(c)], mt)
            best_bg, best_db, best_tmdb = _pick_one(
                scoring_pools, media_type, combo_picker)
    primary_pool = [c for c in (best_bg, best_db, best_tmdb) if c]
    # 主结果必须与本地标题指向同一部作品：同系列外传（“祝福”vs“爆焰”）
    # 相似度很高，但不是同一部剧，不能当主结果。
    local_title = parsed.title or ""
    if local_title:
        filtered = [c for c in primary_pool
                    if not _is_different_work(local_title, c.title)]
        if filtered:
            primary_pool = filtered
    primary = max(primary_pool, key=lambda c: c.score, default=None)

    anchor_year = (primary.year if primary and primary.year else parsed.year)
    known_aliases: list[str] = []
    for c in (best_bg, best_db, best_tmdb):
        if not c:
            continue
        if isinstance(c.extra, dict):
            known_aliases += list(c.extra.get("aliases") or [])
        if c.original_title and re.search(r"[A-Za-z]", c.original_title):
            known_aliases.append(c.original_title)
    alias_tuple = tuple(dict.fromkeys(
        a for a in known_aliases if a))
    best_imdb = scoring.pick_imdb(scoring_pools["imdb"], media_type,
                                  anchor_year, alias_tuple)

    # 没有豆瓣/Bangumi 时，可靠的 IMDb 结果也可以作为主结果（常见于英美剧）。
    # 但只有当它的标题/别名也能对得上本地锚点时才允许，
    # 否则 IMDb 的模糊前缀同样会把整部剧带偏。
    if primary is None and best_imdb and anchors and \
            not scoring.candidate_matches_anchor(best_imdb, anchors):
        best_imdb = None
    if primary is None and best_imdb and \
            max(best_imdb.extra.get("title_score", 0),
                best_imdb.extra.get("alias_title_score", 0)) >= 0.8:
        primary = best_imdb

    bg_ok = _agrees_with_primary(best_bg, primary)
    if best_bg and not bg_ok:
        res.notes.append(f"忽略来源不一致的 Bangumi 条目：{best_bg.title}")
    # 豆瓣同理：高相似度的同系列外传（“为美好的世界献上祝福！”vs
    # “为美好的世界献上爆焰！”）不能当成同一部作品，否则主标题、
    # 单集副标题、影片资料全会被带成另一部剧。
    db_ok = _agrees_with_primary(best_db, primary)
    if best_db and not db_ok:
        res.notes.append(f"忽略来源不一致的豆瓣条目：{best_db.title}")
    res.douban = best_db if db_ok else None
    res.bangumi = best_bg if bg_ok else None
    res.tmdb = best_tmdb
    res.imdb = best_imdb

    # 主标题
    if primary:
        if primary.source == "imdb":
            res.title_zh = primary.title
            res.title_original = primary.title
        else:
            res.title_zh = primary.title
            res.title_original = (
                (best_bg.original_title if bg_ok else "") or
                (best_imdb.title if best_imdb else "") or
                primary.original_title)
        # 采用的主条目只是“本地标题 + 季/分段后缀”时（例如本地“灵笼”，
        # 数据源只有“灵笼 上半季”），标题会带上分段名，需要在预览里说清楚，
        # 否则用户会以为匹配错了。主剧名仍会还原成不带分段的标题。
        if isinstance(primary.extra, dict) and \
                not primary.extra.get("title_exact") and \
                scoring._anchor_suffix_match(parsed, primary):
            res.notes.append(
                f"数据源没有与「{parsed.title}」完全同名的条目，"
                f"暂用「{primary.title}」（分段/季条目）；"
                "主剧名会还原为不带分段的名字，请核对。")
    elif best_imdb:
        res.title_zh = best_imdb.title
        res.title_original = best_imdb.title
    else:
        res.title_zh = parsed.title
        res.title_original = ""

    res.year = (primary.year if primary and primary.year else
                (best_imdb.year if best_imdb else parsed.year))
    res.imdb_id = best_imdb.sid if best_imdb else ""
    res.tmdb_id = best_tmdb.sid if best_tmdb else ""
    res.douban_id = best_db.sid if best_db else ""
    res.bangumi_id = best_bg.sid if bg_ok else ""

    res.country = _country_from(best_bg, bg_ok, primary)
    if bg_ok and isinstance(best_bg.extra, dict):
        tags = [str(t) for t in (best_bg.extra.get("tags") or [])]
        res.animation = any(
            k in t for t in tags for k in ("动画", "动漫", "美漫"))
    # TMDB genre 16（Animation）比目录名可靠；IMDb/TMDB 分类归属
    # 也要参与判断，避免真人剧被归成动画。
    if best_tmdb and isinstance(best_tmdb.extra, dict) and \
            best_tmdb.extra.get("animation"):
        res.animation = True

    res.confidence = _confidence(primary, best_imdb, best_bg, best_db,
                                best_tmdb)

    res.alternatives = sorted(
        [c for c in dedupe(scoring_pools["bangumi"] + scoring_pools["douban"]
                           + scoring_pools["imdb"] + scoring_pools["tmdb"])
         if c.extra.get("title_score", 0) >= 0.45],
        key=lambda c: c.score, reverse=True)[:8]

    # 记录各来源自己的条目号，供“按来源命名/取单集标题/取特别篇”使用。
    refs: dict[str, dict] = {}
    for source, cand in (("douban", best_db), ("bangumi", res.bangumi),
                         ("imdb", best_imdb), ("tmdb", best_tmdb)):
        if not cand or not cand.sid:
            continue
        refs[source] = {
            "id": str(cand.sid),
            "title": str(cand.title or ""),
            "original_title": str(cand.original_title or ""),
            "year": cand.year,
            "season_title": str(cand.title or ""),
        }
    res.source_refs = refs

    if not primary and not best_imdb:
        res.notes.append("没有找到匹配，请手动输入标题或改用原名搜索。")
    elif res.confidence < 0.55:
        res.notes.append("匹配置信度较低，请检查标题/年份或手动修正。")
    return res


def _agrees_with_primary(c: Optional[Candidate],
                         primary: Optional[Candidate]) -> bool:
    """跨来源核对：只有和主结果标题（以及年份）对得上的 Bangumi 条目，
    才有资格贡献原名/地区/动画标记。否则就是拿 A 片的标题配 B 片的
    原名和地区（之前“寄生兽”被当成国产动画就是这个原因）。
    """
    if not c or not primary:
        return False
    if primary.year and c.year and abs(primary.year - c.year) > 1:
        return False
    if c is primary or titles_agree(primary.title, c.title):
        return True
    # 同一部作品被不同来源拆成不同分段时（豆瓣“灵笼 第一季” vs
    # Bangumi“灵笼 上半季”），标题不会直接相似，但它们共有一个基础标题；
    # 这种情况下两边都是高分命中同一批搜索词，应当都保留。
    base_primary = _base_title(primary.title)
    base_c = _base_title(c.title)
    if base_primary and base_c and base_primary == base_c:
        if _both_confident(primary, c):
            return True
    # 中英文标题不同（IMDb 英文名 vs Bangumi 中文名）时，
    # 只要这条 Bangumi 自己也是高分命中同一个搜索词，仍可采用。
    ok = bool(isinstance(c.extra, dict) and
              c.extra.get("title_score", 0) >= 0.85)
    if not ok:
        return False
    # 高相似度的“同系列外传”不是同一部作品：
    # “为美好的世界献上祝福！”与“为美好的世界献上爆焰！”只差一个词，
    # 模糊相似度极高，但它们是两部独立的剧，不能互相顶替。
    return not _is_different_work(primary.title, c.title)


def _is_different_work(a: str, b: str) -> bool:
    """两条标题高度相似但指向不同作品时返回 True。

    判据：
    - 一边标题尾部多出的只是季/分段说明（第二季、最终季、剧场版）→ 同一作品；
    - 多出的是实词（爆焰、红传说、外传…）→ 不同作品；
    - 两边长度接近、只有个别字不同（如“祝福”→“爆焰”）→ 不同作品。
    """
    from .scoring import _is_suffix_only

    an, bn = norm_title(a), norm_title(b)
    if not an or not bn or an == bn:
        return False

    shorter, longer = (an, bn) if len(an) <= len(bn) else (bn, an)
    if len(shorter) >= 4 and longer.startswith(shorter):
        rest = longer[len(shorter):]
        if rest:
            return not _is_suffix_only(rest)

    # 长度接近但内容不同：同系列外传常把主标题里的两三个字换掉
    if abs(len(an) - len(bn)) <= 2 and len(an) >= 6:
        same = sum(1 for x, y in zip(an, bn) if x == y)
        ratio = same / max(len(an), len(bn))
        if ratio >= 0.75:
            return True
    return False


def _base_title(title: str) -> str:
    """去掉季/分段后缀后的基础标题：“灵笼 第一季”→“灵笼”。"""
    text = norm_title(title)
    if not text:
        return ""
    # 反复剥离末尾的分段词（与 scoring 用的是同一套词）。
    # 注意先剥长的（“最终季”先于“季”），否则会留下半截“最终”。
    from .scoring import _SEASON_SUFFIX_WORDS
    words = sorted(set(_SEASON_SUFFIX_WORDS) | {"最终季", "完结季", "finalseason"},
                   key=len, reverse=True)
    changed = True
    while changed and len(text) > 2:
        changed = False
        for word in words:
            if text.endswith(word) and len(text) > len(word):
                rest = text[: -len(word)]
                # “最终”这种半截词不剥：剥完只剩片段时跳过
                if len(rest) >= 2:
                    text = rest
                    changed = True
                    break
        trimmed = re.sub(r"[0-9一二三四五六七八九十零〇两百]+$", "", text)
        trimmed = re.sub(r"(?:第|part|season|s|final)$", "", trimmed)
        if trimmed != text and len(trimmed) >= 2:
            text = trimmed
            changed = True
    return text


def _both_confident(a: Candidate, b: Candidate) -> bool:
    """两边都至少是 0.6 的标题命中，才允许按基础标题合并。"""
    ta = float((a.extra or {}).get("title_score", 0)) \
        if isinstance(a.extra, dict) else 0.0
    tb = float((b.extra or {}).get("title_score", 0)) \
        if isinstance(b.extra, dict) else 0.0
    return min(ta, tb) >= 0.6


def _country_from(best_bg: Optional[Candidate], bg_ok: bool,
                  primary: Optional[Candidate]) -> str:
    """地区：用于区分日番（简洁命名）与国产动画/电视剧（带规格）。"""
    country = ""
    if bg_ok and isinstance(best_bg.extra, dict):
        country = best_bg.extra.get("country", "")
    if not country and primary and isinstance(primary.extra, dict):
        country = primary.extra.get("country", "")
    if not country and primary and isinstance(primary.extra, dict):
        # TMDB 搜索结果的原始语言也是可靠分类依据
        lang = str(primary.extra.get("lang") or "")
        if lang == "ja":
            country = "jp"
        elif lang in ("zh", "cn"):
            country = "cn"
        elif lang == "en":
            country = "us"
    if not country:
        orig = (best_bg.original_title if bg_ok else "") or \
               (primary.original_title if primary else "")
        if has_kana(orig):
            country = "jp"
    return country


def _confidence(primary: Optional[Candidate],
                best_imdb: Optional[Candidate],
                best_bg: Optional[Candidate],
                best_db: Optional[Candidate],
                best_tmdb: Optional[Candidate]) -> float:
    """置信度：标题分是核心，年份/类型只是修正；跨来源必须标题相似才算印证。"""
    if primary:
        conf = primary.score
        if best_imdb and best_imdb is not primary:
            y1, y2 = primary.year, best_imdb.year
            if y1 and y2 and abs(y1 - y2) <= 1:
                conf += 0.05
            else:
                conf += 0.02
        for other in (best_bg, best_db, best_tmdb):
            if other and other is not primary and \
                    titles_agree(primary.title, other.title):
                if (not primary.year or not other.year or
                        abs(primary.year - other.year) <= 1):
                    conf += 0.04
        return min(1.0, conf)
    if best_imdb:
        return max(best_imdb.score,
                   0.9 * best_imdb.extra.get("alias_title_score", 0))
    return 0.0


def identify_series(parsed: ParsedName, media_type: str, res: MatchResult,
                    identity_lookup: Callable[[str], dict]) -> None:
    """季条目的主剧还原：主剧名、首播年、主剧 IMDb。

    `identity_lookup(base)` 由调用方注入（通常是
    `MetadataClient._series_identity`），本函数不直接访问网络。
    """
    base = strip_season_markers(parsed.title) if media_type == "series" else ""
    needs_ident = (
        media_type == "series" and base and
        (base != parsed.title or
         (parsed.season is not None and parsed.season != 1))
    )
    if needs_ident:
        ident = identity_lookup(base)
        ident_title = strip_season_markers(
            ident.get("title") or base) or base
        # 英文文件名命中了中文季条目时，主剧名优先用中文，
        # 例如 “科拉传奇 第四季：平衡” -> “科拉传奇”。
        cn_main = strip_season_and_subtitle(res.title_zh or "")
        tmdb_main = ""
        if res.tmdb and RE_CJK.search(res.tmdb.title or "") and \
                candidate_season(res.tmdb) is None:
            tmdb_main = strip_season_markers(res.tmdb.title)
        if tmdb_main and (
                not cn_main or titles_agree(tmdb_main, cn_main) or
                titles_agree(tmdb_main, ident_title)) and (
                not RE_CJK.search(ident_title) or
                len(norm_title(tmdb_main)) >= len(norm_title(ident_title))):
            ident_title = tmdb_main
        elif cn_main and RE_CJK.search(cn_main) and \
                not RE_CJK.search(ident_title):
            ident_title = cn_main
        res.series_title = ident_title
        years = [ident.get("year")]
        if res.tmdb:
            years.append(res.tmdb.year)
        if res.imdb:
            years.append(res.imdb.year)
        years = [y for y in years if y]
        res.series_year = min(years) if years else res.year
        res.series_imdb_id = (ident.get("imdb_id") or res.imdb_id or "")
        if not res.country:
            res.country = ident.get("country", "") or ""
        res.animation = res.animation or bool(ident.get("animation"))
        res.is_season_entry = True
    elif media_type == "series":
        raw_title = res.title_zh or res.title_original or parsed.title
        res.series_title = strip_season_markers(raw_title) or raw_title
        res.series_year = res.year
        res.series_imdb_id = res.imdb_id
    else:
        res.series_title = res.title_zh or res.title_original or parsed.title
        res.series_year = res.year

    # 同一部剧的不同季必须使用同一个主剧名。TMDB 的 TV 条目是整部剧，
    # 标题最稳定；S01/S02/S03 不再出现“中文名 / 中文名+英文 / 带发布组”
    # 三种写法。
    if media_type == "series" and res.tmdb and \
            candidate_season(res.tmdb) is None:
        tmdb_title = strip_season_markers(res.tmdb.title or "")
        if tmdb_title and RE_CJK.search(tmdb_title) and (
                not res.series_title or
                not RE_CJK.search(res.series_title) or
                titles_agree(tmdb_title, res.series_title)):
            res.series_title = tmdb_title

    if media_type == "series" and res.is_season_entry and not res.series_year:
        res.notes.append("已还原主剧名，但没找到首播年份。")
