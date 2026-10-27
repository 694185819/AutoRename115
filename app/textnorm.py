# -*- coding: utf-8 -*-
"""标题规范化与季号解析（纯文本工具，无网络/无缓存）。

这些函数原先定义在 `metadata.py`，但评分（`scoring.py`）也要用；
抽出来后两边都从这里导入，避免 scoring ↔ metadata 循环依赖。

`metadata.py` 仍保留同名对象（转发到这里），既有
`from app.metadata import norm_title` 之类调用不受影响。
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Optional

from rapidfuzz import fuzz

from .models import Candidate

RE_KANA = re.compile(r"[぀-ヿ]")
RE_CJK = re.compile(r"[㐀-鿿]")

# 附加在剧名后面的“季/部/Part”标记，用于还原主剧名
SEASON_SUFFIXES = [
    r"第\s*[0-9一二三四五六七八九十百]+\s*[季期部]",
    r"\bSeason\s*\d+\b",
    r"\bS\d{1,2}\b",
    r"最终季", r"最终章",
    r"\bFinal\s+Season\b",
    r"\bPart\.?\s*\d+\b",
    r"\bCour\s*\d+\b",
]
RE_SEASON_SUFFIX = re.compile(
    r"(?i)(?:\s*[-–—:：·]?\s*(?:" + "|".join(SEASON_SUFFIXES) + r"))+\s*$")

_CN_DIGITS = "零一二三四五六七八九"
RE_SEASON_NUM = re.compile(
    r"(?i)第\s*([0-9零〇一二两三四五六七八九十百]+)\s*[季期部]|"
    r"\bSeason\s*(\d{1,2})\b|(?<![A-Za-z0-9])S(\d{1,2})(?!\d)|"
    r"\bBook\s*(\d{1,2})\b")
_BOOK_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def has_kana(text: str) -> bool:
    return bool(RE_KANA.search(text or ""))


def norm_title(text: str) -> str:
    """用于相似度比较：全半角、大小写、标点、空格。"""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w぀-ヿ㐀-鿿]+", "", text)
    return text


def is_generic_episode_title(title: str) -> bool:
    """TMDB 没有单集标题时会返回“第 1 集 / Episode 1 / 1화”这类占位符。

    它们不能当成副标题写进文件名，否则每集都会变成
    “S01E01.第.1.集”。
    """
    t = (title or "").strip()
    if not t:
        return True
    return bool(re.fullmatch(
        r"(?i)(?:第\s*\d+\s*[集话話回]|[ée]pisode\s*\d+|ep\.?\s*\d+|"
        r"\d+\s*화|\d+)", t))


def titles_agree(a: str, b: str) -> bool:
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return False
    if fuzz.WRatio(na, nb) >= 80:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(shorter) >= 3 and shorter in longer


def strong_titles_agree(a: str, b: str) -> bool:
    """ID 校验用的严格标题比较，避免“假如”命中“假如是爱”。"""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) < 4:
        return False
    return titles_agree(a, b)


def strip_season_markers(title: str) -> str:
    """把“庆余年 第二季”“进击的巨人 最终季 Part.2”还原成主剧名。"""
    t = unicodedata.normalize("NFKC", title or "").strip()
    t = re.sub(r"[\(（\[【]\s*(?:第\s*[0-9一二三四五六七八九十]+\s*[季期]|"
               r"Season\s*\d+)\s*[\)）\]】]\s*$", "", t, flags=re.I)
    prev = None
    while t and t != prev:
        prev = t
        t = RE_SEASON_SUFFIX.sub("", t).strip(" -–—:：·")
    return t or title


def cn_season_number(n: int) -> str:
    if n <= 0:
        return _CN_DIGITS[0]
    if n < 10:
        return _CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + _CN_DIGITS[n - 10]
    if n < 100:
        return _CN_DIGITS[n // 10] + "十" + (
            _CN_DIGITS[n % 10] if n % 10 else "")
    return str(n)


def candidate_season(cand: Candidate) -> Optional[int]:
    """从候选标题里读出“第三季 / Season 3 / S03 / Book 3”。"""
    texts = [cand.title, cand.original_title]
    if isinstance(cand.extra, dict):
        texts += [str(a) for a in (cand.extra.get("aliases") or [])]
    for text in texts:
        text = str(text or "")
        m = RE_SEASON_NUM.search(text)
        if m:
            raw = next((g for g in m.groups() if g), "")
            if raw.isdigit():
                return int(raw)
            try:
                from .parser import cn_number
                val = cn_number(raw)
                if val is not None:
                    return val
            except Exception:
                pass
        m = re.search(r"(?i)\bBook\s+([a-z]+)\b", text)
        if m and m.group(1).lower() in _BOOK_WORDS:
            return _BOOK_WORDS[m.group(1).lower()]
    return None


def fuzzy_queries(queries, media_type: str = "series",
                  season: Optional[int] = None,
                  year: Optional[int] = None,
                  limit: int = 7) -> list[str]:
    """把主标题、英文名、季号拆成多组搜索词。

    先放所有主标题，再放季号变体。这样豆瓣/IMDb 都能先命中基础条目，
    再补“第四季 / 第4季 / Season 4 / S04”等残缺结果。
    """
    bases: list[str] = []
    seen: set[str] = set()

    def add_base(text: str) -> None:
        text = str(text or "").strip(" ._-–—:：·")
        key = norm_title(text)
        if len(key) < 2 or key in seen:
            return
        seen.add(key)
        bases.append(text)

    for q in queries:
        add_base(q)

    out: list[str] = []
    out_seen: set[str] = set()

    def add_out(text: str) -> None:
        text = str(text or "").strip(" ._-–—:：·")
        key = norm_title(text)
        if len(key) < 2 or key in out_seen:
            return
        out_seen.add(key)
        out.append(text)

    season_mode = media_type == "series" and season is not None
    for base in bases:
        add_out(base)
        if not season_mode:
            continue
        # 主标题的季号变体紧跟主标题，豆瓣前几条就能搜到第四季；
        # 英文名仍排在后面，留给 IMDb/TMDB。
        if RE_SEASON_NUM.search(base) or re.search(
                r"(?i)最终季|final\s+season|part\s+\d+", base):
            continue
        cn = cn_season_number(season)
        if RE_CJK.search(base):
            add_out(f"{base} 第{cn}季")
            if cn != str(season):
                add_out(f"{base} 第{season}季")
        if re.search(r"[A-Za-z]", base):
            add_out(f"{base} Season {season}")
            add_out(f"{base} S{season:02d}")

    if year:
        for base in bases[:2]:
            add_out(f"{base} {year}")

    return out[:limit]


def strip_season_and_subtitle(title: str) -> str:
    """“科拉传奇 第四季：平衡” -> “科拉传奇”。"""
    t = strip_season_markers(title)
    m = re.search(
        r"(?i)\s*(?:第\s*[0-9零〇一二两三四五六七八九十百]+\s*[季期部]|"
        r"Season\s*\d+|S\d{1,2}|Book\s*(?:\d+|[a-z]+))",
        t)
    if m:
        t = t[:m.start()]
    return t.strip(" -–—:：·") or title


def douban_title_parts(title: str) -> tuple[str, str, Optional[int]]:
    """拆豆瓣搜索结果标题：“中文名 第X季 English (年份)”。"""
    text = html.unescape(str(title or "")).replace("‎", "").strip()
    year = None
    m = re.search(r"\((\d{4})\)\s*$", text)
    if m:
        year = int(m.group(1))
        text = text[:m.start()].strip()
    m = re.match(
        r"^(.+?[㐀-鿿].*?)\s+([A-Za-z][A-Za-z0-9:.,'&!+\- ]*)$", text)
    if m:
        return m.group(1).strip(" -–—:：·"), m.group(2).strip(), year
    m = re.search(r"([A-Za-z][A-Za-z0-9:.,'&!+\- ]{2,})$", text)
    if m and m.start() > 0:
        return (text[:m.start()].strip(" -–—:：·"),
                m.group(1).strip(), year)
    return text, "", year


def extract_latin_aliases(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9:.'&!+\- ]{2,}", text or ""):
        s = m.group(0).strip(" .-")
        if len(s) >= 3:
            out.append(s)
    return out


def dedupe_str(items) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        x = str(x or "").strip()
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out
