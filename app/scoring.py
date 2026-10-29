# -*- coding: utf-8 -*-
"""候选打分与锚点校验（纯函数，无网络、无缓存）。

从 `MetadataClient` 迁出的规则，行为保持一致：

- `anchor_titles`：本地标题/别名的可信锚点（中英文分段、去掉弱词，
  季号来自文件名时剔除“第一季”类别名）；
- `score`：标题相似度 + 年份 + 类型 + 季号加减权，partial 按长度打折；
- `pick_primary` / `pick_imdb`：精确同名优先，再按分数/年份挑选。

调用方可以单独对这个模块写测试，不必启动整个元数据客户端。
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz

from .textnorm import (
    RE_CJK, candidate_season, fuzzy_queries, norm_title, titles_agree,
)
from .models import Candidate, ParsedName

# 只是分区/版本说明的短词，不能单独拿来确认一部作品。
WEAK_ANCHOR_NAMES = {
    "剧", "番", "片", "影", "电视剧", "剧集", "电影", "影片",
    "动画", "动漫", "动画片", "番剧", "新番", "美剧", "英剧",
    "韩剧", "日剧", "国产剧", "国产动画", "美漫", "美国动画",
    "欧美动画", "合集", "系列", "全系列", "全集", "其他", "其它",
    "剧版", "影版", "电影版", "电视剧版", "真人版", "动画版",
    "网剧版", "网络剧版", "短剧版", "字幕", "双语", "中字",
}

# 番外/短片类条目：标题带这些词时，不能只靠 partial 相似度当主条目。
# 注意不能给中文加 \b（中文不是 \w），“女子落语OAD番外”里的 OAD 会漏掉。
_WEAK_SOURCE_RE = re.compile(
    r"(?i)(?<![a-z])(?:OAD|OVA|SP|SPECIAL|SHORT)(?![a-z])|"
    r"短片|番外|小剧场|特别篇")


def season_alias(text: str) -> bool:
    """“第一季 / Season 1 / 第2季”这种只是季号说明的别名。"""
    t = str(text or "").strip()
    return bool(t) and (
        re.fullmatch(r"(?i)(?:Season|S|第)\s*\d+\s*季?", t) is not None or
        re.fullmatch(r"第[一二三四五六七八九十]+季", t) is not None)


def anchor_parts(text: str) -> list[str]:
    """整串 + 其中文段 + 其英文/罗马字段。"""
    text = str(text or "").strip()
    if not text:
        return []
    out = [text]
    for run in re.findall(r"[㐀-鿿぀-ヿ]{2,}", text):
        out.append(run)
    for run in re.findall(
            r"[A-Za-z][A-Za-z0-9'&!+\-]*(?:[ .][A-Za-z0-9'&!+\-]+)*", text):
        run = run.strip(" .-")
        if len(run) >= 3 and re.search(r"[A-Za-z]{2,}", run):
            out.append(run)
    return out


def combo_anchors(parsed: ParsedName) -> list[str]:
    """本地整串名，以及按分隔符/中英文边界拆出的 3 字以上片段。"""
    out: list[str] = []
    texts = [parsed.title] + list(parsed.queries or [])
    for text in texts:
        text = str(text or "").strip()
        if not text:
            continue
        for part in re.split(r"[\s/|,;:\[\]【】()（）·•]+", text):
            part = part.strip(" -–—_.")
            key = norm_title(part)
            if len(key) < 3 or key in WEAK_ANCHOR_NAMES:
                continue
            if part not in out:
                out.append(part)
        # 中英文混写没有分隔符时按字母/汉字边界再拆一次
        for run in re.findall(
                r"[A-Za-z][A-Za-z0-9'&!+\-]*(?: [A-Za-z0-9'&!+\-]+)*", text):
            run = run.strip(" .-")
            if len(norm_title(run)) >= 3 and run not in out:
                out.append(run)
    return out


def anchor_titles(parsed: ParsedName) -> list[str]:
    """自动匹配必须对得上的本地标题/别名。

    目录名常把中英文写在一起（“异国日记 Ikoku Nikki”），整串和
    官方条目很少逐字相同；必须把中文段、英文段也各算一个锚点，
    否则正确候选会被锚点校验当成“无关候选”淘汰，任务只能进需确认。
    """
    parts: list[str] = []
    for text in [parsed.title] + list(parsed.queries or []):
        for part in anchor_parts(str(text or "")):
            if part not in parts:
                parts.append(part)
    if parsed.file_season is not None:
        # 本地没写季号、季号来自文件名时，“第一季/第二季”这类别名
        # 不是可靠锚点：任何一季的官方标题都可能对得上。
        parts = [p for p in parts if not season_alias(p)]
    out: list[str] = []
    seen: set[str] = set()
    for text in parts:
        key = norm_title(text)
        if len(key) < 2 or key in WEAK_ANCHOR_NAMES or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def candidate_names(cand: Candidate) -> list[str]:
    names = [cand.title, cand.original_title]
    if isinstance(cand.extra, dict):
        names += list(cand.extra.get("aliases") or [])
    return [str(n).strip() for n in names if str(n or "").strip()]


def names_really_agree(a: str, b: str) -> bool:
    """锚点用的保守比较：短名只认包含或极相似，长名才允许轻微错字。"""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if shorter in longer:
        return True
    return len(shorter) >= 4 and fuzz.WRatio(na, nb) >= 92


def candidate_matches_anchor(cand: Candidate, anchors: list[str]) -> bool:
    """候选标题/别名是否和本地锚点有真正的文字重合。

    短锚点（2 个字）只接受完全同名，避免“剧版”命中
    “剧版超能陆战队番外短片”这种前缀伪匹配。
    官方中文名较长、本地是简称（“女子落语”对“女子落语 じょしらく”）
    时，本地名包含在官方名里也算对得上。
    """
    if not anchors:
        return True
    names = candidate_names(cand)
    for anchor in anchors:
        an = norm_title(anchor)
        if not an:
            continue
        for name in names:
            cn = norm_title(name)
            if not cn:
                continue
            if cn == an:
                return True
            # 短标题（2 字）不能靠任意包含关系命中，但允许“标题 + 季/分段后缀”，
            # 否则“灵笼”会漏掉“灵笼 上半季 / 灵笼 第二季”这种同系列条目。
            if len(an) >= 2 and cn.startswith(an) and \
                    _is_suffix_only(cn[len(an):]):
                return True
            if len(an) < 3:
                continue
            if titles_agree(name, anchor):
                return True
            if an in cn:
                return True
    return False


_SEASON_SUFFIX_WORDS = (
    "季", "期", "部", "章", "中章", "上章", "下章", "终章", "序章",
    "上半", "下半", "上卷", "下卷", "篇", "前篇", "后篇",
    "part", "season", "s", "final", "cour",
    "上半季", "下半季", "新章", "续章", "精编版", "总集篇", "剧场版",
    "incarnation", "ova", "oad", "sp",
)


def _is_suffix_only(rest: str) -> bool:
    """候选名去掉本地名后，剩余部分是否只是季/分段说明。

    rest 已经过 norm_title（去标点、小写）。允许阿拉伯/中文数字与上述词组合，
    例如“上半季”“第二季”“2”“finalseason”“中章”。
    """
    if not rest:
        return True
    if len(rest) > 12:
        return False
    # 去掉数字与量词“第”后，必须只剩说明词：“第二季”→“季”，“灵笼2”→“”
    letters = re.sub(r"[0-9一二三四五六七八九十零〇两百]+", "", rest)
    letters = letters.replace("第", "")
    if not letters:
        return True          # 只剩数字，例如“灵笼 2”
    for word in _SEASON_SUFFIX_WORDS:
        if letters == word:
            return True
        if letters.startswith(word) and \
                _is_suffix_only(letters[len(word):]):
            return True
    return False


def _anchor_suffix_match(parsed: ParsedName, cand: Candidate) -> bool:
    """该候选是否只是“本地标题 + 季/分段后缀”（没有完全同名条目时）。"""
    anchor_norms = {norm_title(t) for t in
                    ([parsed.title] + list(parsed.queries or [])) if norm_title(t)}
    for name in candidate_names(cand):
        cn = norm_title(name)
        if not cn or cn in anchor_norms:
            continue
        for an in anchor_norms:
            if len(an) >= 2 and cn.startswith(an) and \
                    _is_suffix_only(cn[len(an):]):
                return True
    return False


def _title_similarity(q: str, cn: str) -> tuple[float, bool]:
    """单个搜索词对单个候选名的相似度，以及是否完全同名。"""
    qn = norm_title(q)
    if len(qn) < 2 or not cn:
        return 0.0, False
    if qn == cn:
        return 1.0, True
    w = fuzz.WRatio(qn, cn) / 100.0
    if len(qn) == 2:
        return w, False
    # partial_ratio 对“候选标题里含一段相同文字”给满分，是
    # “女子落语 OAD”抢走“女子落语”这类近似条目的来源。
    # 只在两段文字长度接近时采用，分数也要打折。
    shorter = min(len(qn), len(cn))
    longer = max(len(qn), len(cn))
    partial = fuzz.partial_ratio(qn, cn) / 100.0
    if shorter >= max(4, int(longer * 0.6)):
        partial *= 0.85
    else:
        partial *= 0.6
    return max(w, partial), False


def score(parsed: ParsedName, cand: Candidate, media_type: str) -> float:
    """候选综合得分（0~1）；同时把细节写进 `cand.extra` 供后续挑选使用。"""
    queries = fuzzy_queries(parsed.queries or [parsed.title], media_type,
                            parsed.season, parsed.year, limit=7)
    cand_titles = [cand.title, cand.original_title]
    if isinstance(cand.extra, dict) and cand.extra.get("aliases"):
        cand_titles += list(cand.extra["aliases"])
    cand_norms = [norm_title(t) for t in cand_titles if t]
    best_title = 0.0
    exact_title = False
    for q in queries:
        for cn in cand_norms:
            value, exact = _title_similarity(q, cn)
            if exact:
                exact_title = True
            if value > best_title:
                best_title = value

    year_score = 0.6
    if parsed.year and cand.year:
        d = abs(parsed.year - cand.year)
        year_score = 1.0 if d == 0 else (0.8 if d == 1 else
                                        (0.5 if d == 2 else 0.0))
    elif cand.year:
        year_score = 0.65

    want = "tv" if media_type == "series" else "movie"
    type_score = 1.0 if cand.kind == want else 0.3
    if not cand.kind:
        type_score = 0.6

    value = 0.64 * best_title + 0.22 * year_score + 0.14 * type_score
    if cand.source in ("douban", "bangumi") and RE_CJK.search(
            parsed.title or ""):
        value += 0.02
    if cand.source == "imdb" and re.search(r"[A-Za-z]", parsed.title or ""):
        value += 0.02
    if exact_title:
        # 主剧条目优先于同名番外/小剧场（如“葬送的芙莉莲 ～●●的魔法～”）
        value += 0.04
    if not isinstance(cand.extra, dict):
        cand.extra = {}
    local_parts = {norm_title(p) for p in
                   ([parsed.title] + list(parsed.queries or []))
                   if norm_title(p)}
    anchor_parts_set = {norm_title(p) for p in anchor_titles(parsed)
                        if norm_title(p)}
    cand_norm_set = {cn for cn in cand_norms if cn}
    # 只认“候选名 == 本地整串/某一段”，以及“候选名是本地名的合理扩展”
    # （官方名更长，但多出来的部分不超过本地名的长度）。反过来
    # “本地含候选名”会让短候选（“女子落语OAD”对“女子落语[じょしらく]”）
    # 也算精确；“女子落语OAD番外”这种长尾巴番外同样不能算精确。
    contains_local = any(
        lp in cn and len(cn) <= 2 * len(lp)
        for cn in cand_norm_set for lp in anchor_parts_set
        if len(lp) >= 3)
    cand.extra["anchor_exact"] = int(
        bool(cand_norm_set & local_parts) or contains_local)
    # “本地标题 + 季/分段后缀”（灵笼 上半季）也算对得上，但它不是同名条目：
    # 同类候选里要优先选与本地标题完全同名的那条，否则主标题会被带成
    # “灵笼 上半季”。
    cand.extra["title_exact"] = int(bool(cand_norm_set & local_parts))
    # 番外/短片：“女子落语 OAD”不能只看 partial 就当成主条目
    if _WEAK_SOURCE_RE.search(cand.title or "") and not exact_title:
        value = max(0.0, value - 0.15)
    # 季号明确时，第三季不能抢第四季的任务。
    if media_type == "series":
        cs = candidate_season(cand)
        if parsed.season is not None and cs is not None:
            match_season = cs == parsed.season
            value += 0.05 if match_season else -0.18
            cand.extra["season_score"] = 1.0 if match_season else 0.0
            cand.extra["candidate_season"] = cs
        elif parsed.season is None and cs is not None:
            # 本地没写季号时优先主剧条目，别让“第二季”抢走第一季
            value -= 0.08
            cand.extra["season_score"] = 0.5
            cand.extra["candidate_season"] = cs
    cand.extra["title_score"] = round(best_title, 4)
    cand.extra["year_score"] = year_score
    cand.extra["type_score"] = type_score
    return max(0.0, min(1.0, value))


def kind_ok(c: Candidate, media_type: str) -> bool:
    if not c.kind:
        return True
    want = "tv" if media_type == "series" else "movie"
    return c.kind == want


def pick_primary(cands: list[Candidate],
                 media_type: str) -> Optional[Candidate]:
    pool = [c for c in cands if c and kind_ok(c, media_type)]
    if not pool:
        return None
    # 与本地标题完全一致的条目优先，避免高季号/高年份的近似条目
    # 靠模糊分抢走主条目（Jellyfin TMDB provider 也采用这一策略）。
    # “标题 + 季/分段后缀”虽然也通过锚点，但不能压过完全同名条目。
    exact = [c for c in pool if isinstance(c.extra, dict) and
             c.extra.get("title_exact")]
    if not exact:
        exact = [c for c in pool if isinstance(c.extra, dict) and
                 c.extra.get("anchor_exact")]
    if exact:
        pool = exact

    def good(c: Candidate) -> bool:
        ts = float(c.extra.get("title_score", 0))
        # 季条目有时少了系列前缀（“降世神通 第二季”），
        # 标题分不到 0.8，但季号完全匹配，仍应参与选择。
        return ts >= 0.8 or (
            ts >= 0.70 and c.extra.get("season_score") == 1.0)

    picked = [c for c in pool if good(c)]
    return max(picked, key=lambda c: c.score, default=None)


def pick_imdb(cands: list[Candidate], media_type: str,
              anchor_year: Optional[int],
              aliases: tuple[str, ...] = ()) -> Optional[Candidate]:
    alias_norms = [norm_title(a) for a in aliases if a]
    good: list[Candidate] = []
    for c in cands:
        if not kind_ok(c, media_type):
            continue
        if not isinstance(c.extra, dict):
            c.extra = {}
        ts = float(c.extra.get("title_score", 0))
        # IMDb 条目名常是英文，而本地文件名是中文/日文；用 Bangumi 别名比对
        alias_ts = 0.0
        cn = norm_title(c.title)
        if cn and alias_norms:
            alias_ts = max(fuzz.WRatio(cn, a) / 100.0 for a in alias_norms)
        c.extra["alias_title_score"] = round(alias_ts, 4)
        best_ts = max(ts, alias_ts)
        year_ok = (anchor_year is None or c.year is None or
                   abs(c.year - anchor_year) <= 1)
        exact = any(
            cn and cn in alias_norms
            for cn in (norm_title(c.title), norm_title(c.original_title)))
        c.extra["imdb_exact"] = 1 if exact else 0
        if best_ts >= 0.82 and (year_ok or exact):
            c.score = max(c.score, best_ts * 0.95)
            if exact:
                c.score = min(1.0, c.score + 0.02)
            good.append(c)
            continue
        if best_ts >= 0.62 and anchor_year and c.year and c.year == anchor_year:
            c.score = max(c.score, best_ts * 0.9)
            if exact:
                c.score = min(1.0, c.score + 0.02)
            good.append(c)
    # 和主来源一样：有精确同名/别名条目时，不让模糊近似条目
    # 仅凭年份或轻微更高的相似分抢走 IMDb ID。
    exact_good = [c for c in good
                  if isinstance(c.extra, dict) and c.extra.get("imdb_exact")]
    pool = exact_good or good
    return max(pool, key=lambda c: (
        c.score, c.extra.get("imdb_exact", 0), -c.rank), default=None)


def candidate_is_animation(cand: Candidate) -> bool:
    """TMDB genre 16 / Bangumi“动画”标签 → 明确是动画条目。"""
    if not isinstance(cand.extra, dict):
        return False
    if cand.extra.get("animation"):
        return True
    if cand.source == "bangumi":
        tags = cand.extra.get("tags") or []
        return any(k in str(t) for t in tags
                   for k in ("动画", "动漫", "美漫"))
    return False
