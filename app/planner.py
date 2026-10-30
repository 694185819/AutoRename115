# -*- coding: utf-8 -*-
"""把 115 上的不规则文件整理成海报墙可识别的命名方案。

核心规则（按用户要求）：
- 日本番剧：`标题 S01E01.mkv`，不追加任何画质/编码规格。
- 电视剧、国产动画：`标题 S01E01 [1080p WEB-DL HEVC].mkv`。
- 电影：`标题 (年份).mkv`，简洁命名。
- 剧集目录统一为 `标题 (首播年份) [imdbid-tt...]`，方便 Emby/Jellyfin 刮削。
- 季目录统一为 `Season 01`；只重命名，不新建、不删除、不移动。
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from rapidfuzz import fuzz

from . import naming_rule, qc
from .episode_versions import analyze_episode_versions
from .metadata import (extract_latin_aliases, has_kana, norm_title,
                       strong_titles_agree, strip_season_and_subtitle,
                       strip_season_markers, titles_agree)
from .models import (AUDIO_EXTS, SUB_EXTS, VIDEO_EXTS, Candidate, MatchResult,
                     P115Item, ParsedName, PlanItem, RenameOp)
from .parser import (RE_PROVIDER_ID, parse_name, quality_suffix,
                     roman_to_int)

CATEGORY_LABELS = {
    "auto": "自动判断",
    "jp_anime": "日番（简洁）",
    "cn_anime": "国产动画（中英+副标题）",
    "us_anime": "美漫（中英+副标题）",
    "west_anime": "欧美动画（中英+副标题）",
    "tv": "电视剧（中英+副标题）",
    "movie": "电影（简洁）",
}

SPEC_CATEGORIES = {"tv", "cn_anime", "us_anime", "west_anime"}
DOTTED_CATEGORIES = {"tv", "cn_anime", "us_anime", "west_anime"}
# 可以作为“命名来源”的数据源；命名来源决定标题、单集副标题与特别篇顺序。
EPISODE_NAME_SOURCES = {"douban", "bangumi", "imdb", "tmdb"}
NAMING_SOURCE_LABELS = {"douban": "豆瓣", "bangumi": "Bangumi",
                        "imdb": "IMDb", "tmdb": "TMDB"}
# 额外版本目录：V2/V3 放在 ID 或目录末尾之前，例如
# “中文名 英文名 (2020) V2 [tmdbid-123]”
RE_FOLDER_VERSION = re.compile(
    r"(?i)(?<![A-Za-z0-9])V(\d{1,2})(?=\s*(?:[\[{(（]|$))")
GENERIC_DIR_NAMES = {
    "剧", "番", "片", "影",
    "日番", "番剧", "新番", "动画", "动漫", "动画片", "电视剧", "剧集",
    "电影", "影片", "美剧", "英剧", "韩剧", "日剧", "国产剧", "国产动画",
    "美漫", "美国动画", "美国动漫", "欧美动画",
    "下载", "未分类", "其他", "合集", "视频", "媒体", "媒体库", "115",
    "anime", "tv", "shows", "show", "movies", "movie", "downloads",
    "video", "videos", "media", "library", "others", "unsorted",
}
GENERIC_HINTS = ("新番", "合集", "系列", "其他", "其它", "番剧", "电视剧",
                 "国产动画", "动漫", "美漫", "美国动画", "美国动漫",
                 "欧美动画")
# 网盘常见的“1、国内 / 2、欧美 / 01.动画”这类分类目录：
# 它们只是路径分区，不是片名，不能拿去做搜索词或剧集名。
RE_NUMBERED_CATEGORY = re.compile(
    r"^\s*0?\d{1,2}\s*[、.．,，:：\-_ ]+\s*"
    r"(?:国内|国产|日韩|日本|韩国|欧美|美国|海外|港台|台湾|香港|"
    r"动画|动漫|番剧|电视剧|剧集|电影|影片|合集|其他)\s*$")

# 季目录后常跟“[全52集]”“（全54集）”“完结”等备注，月份目录也算季
_SEASON_TAIL = (
    r"(?:[\s._-]*(?:\[[^\]]*\]|\([^)]*\)|全\s*\d+\s*集|"
    r"共\s*\d+\s*集|全集|完结))*[\s._-]*")
SEASON_RE = re.compile(
    r"(?i)^(?:s|season|series)[\s._-]*0?(\d{1,2})" + _SEASON_TAIL + r"$|"
    r"^第\s*([0-9零一二两三四五六七八九十]+)\s*[季期部]" +
    _SEASON_TAIL + r"$|"
    r"^0?(\d{1,2})\s*(?:st|nd|rd|th)?\s*season" + _SEASON_TAIL + r"$")
# 罗马数字季目录：Season II / 第Ⅱ季 / Ⅱ部
SEASON_ROMAN_RE = re.compile(
    r"(?i)^(?:s|season|series)[\s._-]*([IVXLCDM]{1,6})" +
    _SEASON_TAIL + r"$|"
    r"^第\s*([IVXLCDM]{1,6})\s*[季期部]" + _SEASON_TAIL + r"$|"
    r"^([IVXLCDM]{1,6})\s*(?:季|部)" + _SEASON_TAIL + r"$")
# 季号前面直接跟说明的目录：“S2-美版暂无日语字幕”“第2季 无修”。
# 只认开头就是季号的写法，避免把“Show S02.1080p”当成纯季目录。
PREFIX_SEASON_RE = re.compile(
    r"(?i)^(?:s|season|series)[\s._-]*0?\d{1,2}"
    r"(?=$|[-_.\s㐀-鿿（(【\[、,，:：])|"
    r"^第\s*[0-9零一二两三四五六七八九十]+\s*[季期部]"
    r"(?=$|[-_.\s㐀-鿿（(【\[、,，:：])")
SPECIAL_RE = re.compile(r"(?i)^(?:specials?|sp|sps|特别篇|番外|ova|oad)$")
# 子目录名前面带剧名/年份/规格的季目录：
# “Overlord 2015 S01 JPN Blu-ray 1080p” / “Show Season 2 [1080p]”。
# 这里只用于发现子目录，不能拿“S01”去判断当前选中的根目录，
# 否则“Show S02.1080p”这种单独分析某一季的目录会被当成季子目录，
# 反而不会给剧集文件夹补上 S02。
EMBEDDED_SEASON_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:s(?:eason)?|series)"
    r"[\s._-]*0?(\d{1,2})(?![0-9A-Za-z])")
EMBEDDED_ORDINAL_SEASON_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])0?(\d{1,2})\s*(?:st|nd|rd|th)\s+season"
    r"(?![A-Za-z])")
EMBEDDED_CN_SEASON_RE = re.compile(
    r"第\s*[0-9零一二两三四五六七八九十]+\s*[季期部]")
EMBEDDED_ROMAN_SEASON_RE = re.compile(
    r"(?i)(?:season|series)\s*[IVXLCDM]{1,6}(?![A-Za-z0-9])")
PART_RE = re.compile(
    r"(?i)^(?:disc|disk|cd|dvd|bd|vol|volume|part|box)"
    r"[\s._-]*(?:\d+|[IVXLCDM]{1,6})?$|"
    r"^(?:上|下|前|后)(?:篇|卷|部|半)?$|^(?:前半|后半|前篇|后篇|上卷|下卷)$")
SUBS_DIR_RE = re.compile(
    r"(?i)^(?:subs?|subtitles?|字幕|字幕文件|sup|ssa|srt|ass|vtt|idx|sub)$")
FINAL_RE = re.compile(
    r"(?i)最终季|最终章|final\s+season|part[\s._-]*\d+|后半|下半|second\s+cour")
RE_RESOLUTION = re.compile(r"(?i)(?<!\d)(\d{3,4}p|4k|8k|uhd)(?!\w)")
RE_IMDB_TEXT = re.compile(r"(?i)imdb(?:id)?\s*[-=:]\s*(tt\d+)")
RE_TMDB_TEXT = re.compile(r"(?i)tmdb(?:id(?:id)?)?\s*[-=:]\s*(\d+)")
# BD 原盘常见的纯数字文件名：00001.m2ts / 0001.m2ts / 001.m2ts
RE_NUMBERING_STEM = re.compile(r"^0\d{2,5}$")
# 罗马音标题里常见的日语助词/词尾，用来在英文译名之间优先挑罗马音
RE_ROMAJI_HINT = re.compile(
    r"(?i)\b(?:no|wa|ga|wo|ni|de|to|mo|ka|yo|ne|da|desu|suru|"
    r"shite|shita|koto|mono|hito|monogatari|bouken|sekai|uta|yume|"
    r"sora|umi|hoshi|hikari|kaze|hana|mori|machi|mura|gakkou|"
    r"shoujo|shounen|mahou|sensou|shinobi|sensei)\b")


def provider_ids(text: str) -> tuple[str, str]:
    """从已有目录名里读取 {tmdbid-98123} / [imdbid-tt...] 等标识。"""
    text = text or ""
    im = RE_IMDB_TEXT.search(text)
    tm = RE_TMDB_TEXT.search(text)
    return (im.group(1) if im else "", tm.group(1) if tm else "")
LANG_SUFFIX_RE = re.compile(
    r"(?i)^(?:[.\-_](?:zh(?:[-_]?(?:cn|tw|hans|hant))?|chs|cht|sc|tc|"
    r"jpn?|jap|ja|eng?|gb|big5|简|繁|简繁|简日|繁日|简繁日|双语|中字))+$")

INVALID_MAP = {
    "<": "＜", ">": "＞", ":": "：", '"': "＂", "/": "／",
    "\\": "＼", "|": "｜", "?": "？", "*": "＊",
}


def _truncate_utf8(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max(1, max_bytes)].decode("utf-8", "ignore").rstrip(" ._-")


def sanitize_name(text: str, max_bytes: int = 240) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(INVALID_MAP.get(ch, ch) for ch in text)
    text = "".join(ch for ch in text if ord(ch) >= 32 and ch not in "\r\n\t")
    text = re.sub(r"\s+", " ", text).strip(" ._-–—·")
    return _truncate_utf8(text, max_bytes)


def _strip_trailing_year(title: str, year: Optional[int]) -> str:
    if not year:
        return title
    t = re.sub(rf"\s*[\(（]\s*{year}\s*[\)）]\s*$", "", title or "").strip()
    return t or title


def _natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", name or "")]


RE_SPECIAL_FILE = re.compile(
    r"(?i)(?:\[\s*(?:special(?:s)?|sp|sps|ova|oad|特别篇|特別篇|番外|特典|"
    r"スペシャル)\s*\]|(?:^|[.\s_\-])(?:special(?:s)?|ova|oad|特别篇|"
    r"特別篇|番外篇?|特典|スペシャル)(?=$|[.\s_\-\[\](){}]))")
RE_EXTRA_FILE = re.compile(
    r"(?i)(?:^|[.\s_\-\[\](){}])(?:menu|sample|preview|trailer|teaser|"
    r"ncop|nced|creditless|pv|cm)(?=$|[.\s_\-\[\](){}])")
RE_ZERO_EPISODE_TITLE = re.compile(
    r"(?i)第\s*0\s*[话話集]|(?:episode|ep)\.?\s*0(?![0-9])")
RE_EPISODE_MARKER = re.compile(
    r"(?i)(?:S\d{1,2}E\d{1,4}|(?:^|[.\s_\-])E(?:P|pisode)?"
    r"\s*[._ -]?\d{1,4}|第\s*\d{1,4}\s*[集话話]|"
    r"(?:^|[.\s_\-])\d{1,4}v\d+)")


def _is_meaningless_title(title: str) -> bool:
    """纯编号、空标题之类不能拿去搜元数据的“标题”。

    只把带前导零的编号（00001/0001/001）当成文件名序号；
    “86”“1917”这类本身可能就是片名的数字保留。
    """
    t = (title or "").strip()
    if not t:
        return True
    if RE_NUMBERING_STEM.match(t):
        return True
    # 01、02 这种两位序号；以及 01.m2ts / 02 mkv 这类文件名本身。
    if re.fullmatch(r"0\d{1,5}", t):
        return True
    if re.fullmatch(
            r"(?i)\d{1,4}\s*[.\s]\s*(?:mkv|mp4|avi|mov|wmv|flv|webm|m4v|"
            r"ts|m2ts|mts|mpg|mpeg|vob|iso|rmvb|rm|3gp|ogv|divx|"
            r"ass|ssa|srt|sup|sub|idx|vtt|flac|aac|m4a|mp3|wav|dts|"
            r"ac3|eac3|opus|nfo)(?!\w)", t):
        return True
    if re.fullmatch(r"(?i)(?:sample|menu|pv|preview|trailer|bonus|extra|"
                    r"teaser|op|ed|ncop|nced|sp|specials?|ova|oad)", t):
        return True
    # “剧版/真人版/动画版”只是版本说明；单独出现时绝不能拿去搜
    # “剧版”，否则会命中“剧版超能陆战队番外短片”这类完全无关条目。
    if re.fullmatch(r"(?i)(?:剧版|影版|电影版|电视剧版|真人版|动画版|"
                    r"网剧版?|网络剧版?|短剧版)", t):
        return True
    if re.fullmatch(r"(?i)(?:ep?|episode|part|disc|disk|cd|vol(?:ume)?|"
                    r"season|series|s)\s*0?\d{1,3}", t):
        return True
    return False


def _fit_name_parts(head: str, subtitle: str, fixed_bytes: int,
                    limit: int = 235, min_head: int = 20) -> tuple[str, str]:
    """在总字节预算内优先保留完整副标题，再截长标题。

    fixed_bytes 不包含 head、副标题，以及 head 与副标题之间的一个点。
    """
    head = str(head or "")
    subtitle = str(subtitle or "")

    def total(h: str, s: str) -> int:
        return (fixed_bytes + len(h.encode("utf-8")) +
                len(s.encode("utf-8")) + (1 if s else 0))

    if total(head, subtitle) <= limit:
        return head, subtitle
    if subtitle:
        room_head = limit - fixed_bytes - \
            len(subtitle.encode("utf-8")) - 1
        if room_head >= min_head:
            return _truncate_utf8(head, room_head), subtitle
        head = _truncate_utf8(head, min_head)
        room_sub = max(0, limit - fixed_bytes -
                       len(head.encode("utf-8")) - 1)
        return head, _truncate_utf8(subtitle, room_sub)
    return _truncate_utf8(
        head, max(min_head, limit - fixed_bytes)), ""


def _episode_name(title: str, season: int, ep: int, ep_end: Optional[int],
                  ext: str, specs: str, subtitle: str = "",
                  version: str = "") -> str:
    ep_part = f" S{season:02d}E{ep:02d}"
    if ep_end and ep_end != ep:
        ep_part += f"-E{ep_end:02d}"
    ep_part += version
    spec_part = f" [{specs}]" if specs else ""
    fixed = (len(ext.encode("utf-8")) +
             len(ep_part.encode("utf-8")) +
             len(spec_part.encode("utf-8")))
    title, sub = _fit_name_parts(
        sanitize_name(title, 235),
        sanitize_name(subtitle, 235) if subtitle else "",
        fixed)
    sub_part = f".{sub}" if sub else ""
    return title + ep_part + sub_part + spec_part + ext


RE_SPEC_TOKEN = re.compile(
    r"(?i)^\[?(?:480p|576p|720p|1080p|2160p|4k|8k|uhd|"
    r"blu-?ray|bdrip|bd-?remux|remux|web-?dl|webrip|hdtv|dvdrip|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|av1|"
    r"aac|ac3|eac3|ddp?|dts(?:-hd)?|truehd|flac|mp3|opus|atmos|"
    r"\d\.\d|10bit|8bit|hdr|dv|dolby|"
    r"chs|cht|jpn?|eng?|gb|big5|简体|繁体|简繁|双语|中字|内封|外挂|无字)\]?$")


def _dot_segment(text: str, max_bytes: int = 120,
                 colon_to_dot: bool = True) -> str:
    t = sanitize_name(text, max_bytes)
    if colon_to_dot:
        t = t.replace(":", ".").replace("：", ".")
    t = re.sub(r"[\s/\\]+", ".", t)
    t = re.sub(r"\.{2,}", ".", t)
    return t.strip(" .-_")


def _dotted_episode_name(cn: str, en: str, season: int, ep: int,
                         ep_end: Optional[int], subtitle: str,
                         specs: str, ext: str, version: str = "") -> str:
    """电视剧/国产动画/美漫/欧美动画：中文名.英文名.SxxExx.副标题 [规格].ext"""
    ep_part = f"S{season:02d}E{ep:02d}"
    if ep_end and ep_end != ep:
        ep_part += f"-E{ep_end:02d}"
    ep_part += version
    cn = _dot_segment(cn, 235, colon_to_dot=False)
    en = _dot_segment(en, 235) if en else ""
    sub = _dot_segment(subtitle, 235) if subtitle else ""
    if en and norm_title(en) == norm_title(cn):
        en = ""
    head = ".".join(p for p in (cn, en) if p)
    spec_part = f" [{specs}]" if specs else ""
    # “.SxxExx”和规格/扩展名固定保留，标题与副标题共享剩余空间。
    fixed = (len(ext.encode("utf-8")) + 1 +
             len(ep_part.encode("utf-8")) +
             len(spec_part.encode("utf-8")))
    head, sub = _fit_name_parts(head, sub, fixed)
    head = head.rstrip(" .-_")
    tail = "." + ep_part
    if sub:
        tail += "." + sub
    tail += spec_part
    return (head + tail + ext) if head else (tail.lstrip(".") + ext)


def _movie_name(title: str, year: Optional[int], ext: str,
                disambiguate: str = "", imdb_suffix: str = "") -> str:
    base = f"{title} ({year})" if year else title
    tail = imdb_suffix or ""
    if disambiguate:
        tail += f" [{disambiguate}]"
    max_base = 235 - len(ext.encode("utf-8")) - len(tail.encode("utf-8"))
    base = _truncate_utf8(base, max(40, max_base))
    return base + tail + ext


def _provider_suffix(imdb_id: str, tmdb_id: str, style: str,
                     provider: str = "auto") -> str:
    """Jellyfin/Emby/Plex 的元数据 ID 写法。

    Jellyfin 自带 TMDB/TVDB 提供器，TMDB ID 最稳；IMDb ID 需要 OMDb 插件。
    没有 TMDB ID 时退回 IMDb ID（Emby/Plex 原生支持）。
    """
    if style == "none":
        return ""
    use_tmdb = bool(tmdb_id) and provider in ("auto", "tmdb")
    use_imdb = bool(imdb_id and imdb_id.startswith("tt")) and \
        (provider in ("auto", "imdb") or not use_tmdb)
    if use_tmdb:
        if style == "emby":
            return f" [tmdbid={tmdb_id}]"
        if style == "plex":
            return f" {{tmdb-{tmdb_id}}}"
        return f" [tmdbid-{tmdb_id}]"
    if use_imdb:
        if style == "emby":
            return f" [imdbid={imdb_id}]"
        if style == "plex":
            return f" {{imdb-{imdb_id}}}"
        return f" [imdbid-{imdb_id}]"
    return ""


def is_season_dir(name: str) -> bool:
    """纯季目录名：Season 01 / S01 / 第二季 / Specials。"""
    name = unicodedata.normalize("NFKC", (name or "").strip())
    return bool(SEASON_RE.match(name)) or bool(SEASON_ROMAN_RE.match(name)) or \
        bool(SPECIAL_RE.match(name)) or bool(PREFIX_SEASON_RE.match(name))


def _embedded_season(name: str) -> Optional[int]:
    """从“Overlord 2015 S01 JPN Blu-ray”这种带前缀的名字里取季号。"""
    name = unicodedata.normalize("NFKC", (name or "").strip())
    if not name:
        return None
    m = EMBEDDED_SEASON_RE.search(name) or \
        EMBEDDED_ORDINAL_SEASON_RE.search(name)
    if m:
        return int(m.group(1))
    m = EMBEDDED_CN_SEASON_RE.search(name)
    if m:
        raw_m = re.search(
            r"第\s*([0-9零一二两三四五六七八九十]+)\s*[季期部]", name)
        if raw_m:
            raw = raw_m.group(1)
            if raw.isdigit():
                return int(raw)
            try:
                from .parser import cn_number
                return cn_number(raw)
            except Exception:
                return None
    m = EMBEDDED_ROMAN_SEASON_RE.search(name)
    if m:
        raw_m = re.search(
            r"(?i)(?:season|series)\s*([IVXLCDM]{1,6})(?![A-Za-z0-9])",
            name)
        if raw_m:
            return roman_to_int(raw_m.group(1))
    return None


def looks_like_season_dir(name: str) -> bool:
    """子目录判断用：允许“剧名 年份 S01 规格”这种完整季目录名。"""
    return is_season_dir(name) or _embedded_season(name) is not None


def season_from_dir(name: str) -> Optional[int]:
    name = unicodedata.normalize("NFKC", (name or "").strip())
    if SPECIAL_RE.match(name):
        return 0
    m = SEASON_RE.match(name)
    if not m:
        m = SEASON_ROMAN_RE.match(name)
    if not m:
        return _embedded_season(name)
    raw = next((g for g in m.groups() if g), "")
    if raw.isdigit():
        return int(raw)
    try:
        from .parser import cn_number
        return cn_number(raw) or roman_to_int(raw)
    except Exception:
        return roman_to_int(raw)


RE_SEASON_TEXT = re.compile(
    r"(?i)第\s*([0-9零一二两三四五六七八九十]+)\s*[季期部]|"
    r"\bSeason\s*(\d{1,2})\b|(?<![A-Za-z0-9])S(\d{1,2})(?![0-9E])|"
    r"第\s*([IVXLCDM]{1,6})\s*[季期部]|"
    r"\bSeason\s*([IVXLCDM]{1,6})\b")


def season_from_text(text: str) -> Optional[int]:
    normalized = unicodedata.normalize("NFKC", text or "")
    m = RE_SEASON_TEXT.search(normalized)
    if m:
        raw = next((g for g in m.groups() if g), "")
        if raw.isdigit():
            return int(raw)
        try:
            from .parser import cn_number
            cn = cn_number(raw)
            return cn if cn is not None else roman_to_int(raw)
        except Exception:
            return roman_to_int(raw)
    # 标题末尾的裸罗马数字：Show II / Show Ⅱ (2019)
    for rm in re.finditer(
            r"(?i)(?<![A-Za-z0-9])([IVXLCDM]{1,6})(?![A-Za-z0-9])",
            normalized):
        before = normalized[:rm.start()].strip(" ._-[]()（）")
        after = normalized[rm.end():].strip(" ._-[]()（）0123456789")
        if before and not after:
            return roman_to_int(rm.group(1))
    return None


def is_part_dir(name: str) -> bool:
    return bool(PART_RE.match(
        unicodedata.normalize("NFKC", (name or "").strip())))


def is_subs_dir(name: str) -> bool:
    return bool(SUBS_DIR_RE.match((name or "").strip()))


def _is_generic_dir(name: str) -> bool:
    low = (name or "").strip().lower()
    if low in GENERIC_DIR_NAMES:
        return True
    if RE_NUMBERED_CATEGORY.match(low):
        return True
    return any(h in low for h in GENERIC_HINTS)


def _usable_query(q: str) -> bool:
    """能拿去搜元数据的词。

    单个字（“剧”“番”“片”）和“电视剧/动画”这类容器名不是片名：
    拿“剧”去搜会把所有“剧场版/京剧猫”都当成 100% 匹配，
    这正是之前被匹配成宝可梦/城市猎人剧场版的原因。
    """
    q = (q or "").strip()
    if not q or len(norm_title(q)) < 2:
        return False
    if _is_generic_dir(q):
        return False
    return not _is_meaningless_title(q)


# “S1替换双语字幕”“S2-美版暂无日语字幕sup”里的后缀只是版本说明，
# 不是片名。不能拿“替换 字幕”去搜索，否则会盖住真正的上级剧名。
RE_SEASON_DESCRIPTION = re.compile(
    r"(?i)(?:替换|无修|无删|修正|修复|收藏|双语|中字|字幕|内封|外挂|"
    r"简繁|简日|繁日|美版|日版|台版|港版|国配|国语|原盘|重制|合成|剪辑|"
    r"加长|完结|全集|全\s*\d+\s*集|共\s*\d+\s*集|暂无|日语|英语|"
    r"音轨|特效|内嵌|"
    r"remaster(?:ed)?|uncensored|subs?|subtitles?|sup|ass|srt|vtt|"
    r"1080p|2160p|4k|hdr|web-?dl|blu-?ray|bd(?:rip|remux)?)")


def _is_season_description(parsed: ParsedName) -> bool:
    """季目录后缀是否全是“替换/字幕/美版”这类说明文字。

    只看后缀里有没有剩下真正的标题：
    “ S1替换双语字幕 ”没有剩余，是说明；
    “ S1东离剑游记 ”剩下“东离剑游记”，是剧名，不能丢。
    """
    title = (parsed.title or "").strip()
    if not title or _is_meaningless_title(title):
        return True
    rest = RE_SEASON_DESCRIPTION.sub("", title)
    rest = re.sub(r"(?i)[\s._\-–—:：·,，;；/\\|()（）\[\]【】{}0-9a-z]+",
                  "", rest)
    return not rest.strip()


@dataclass
class NamingOptions:
    include_imdb_id: bool = True
    imdb_id_style: str = "jellyfin"      # jellyfin / emby / plex / none
    id_provider: str = "auto"            # auto / imdb / tmdb
    jp_folder_style: str = "standard"    # standard / bdremux / bdremux_suffix / bdremux_no_year
    rename_subtitles: bool = True
    rename_season_folders: bool = True
    min_auto_confidence: float = 0.70
    # 命名方式（对应“命名规则”面板）：
    # 中文主名称 . <来源名> . SxxExx . <副标题> [规格]
    name_segment_source: str = "imdb"    # none/imdb/tmdb/douban/bangumi/local
    subtitle_source: str = "auto"        # auto/keyword/name_source/imdb/...
    include_specs: bool = True           # 是否写规格（原来的分类决定，现在可开关）


@dataclass
class FileEntry:
    item: P115Item
    parsed: ParsedName
    container: Optional[P115Item] = None
    folder_season: Optional[int] = None
    # 原文件名是 SxxE00，已映射到第 0 季特别篇
    special_zero: bool = False

    @property
    def is_video(self) -> bool:
        return self.item.ext in VIDEO_EXTS


@dataclass
class MediaRoot:
    item: P115Item
    entries: list[FileEntry] = field(default_factory=list)
    season_dirs: list[P115Item] = field(default_factory=list)
    part_dirs: list[P115Item] = field(default_factory=list)
    subs_dirs: list[P115Item] = field(default_factory=list)
    nfo_files: list[P115Item] = field(default_factory=list)
    root_season: Optional[int] = None
    # 从合集目录里发现的独立季目录（文件夹名可能没写 Sxx）
    is_season_root: bool = False
    unsupported: str = ""

    @property
    def videos(self) -> list[FileEntry]:
        return [e for e in self.entries if e.is_video]

    @property
    def sidecars(self) -> list[FileEntry]:
        return [e for e in self.entries if not e.is_video]


class Planner:
    def __init__(self, metadata, options: Optional[NamingOptions] = None,
                 log: Optional[Callable[[str], None]] = None):
        self.metadata = metadata
        self.options = options or NamingOptions()
        self.log = log or (lambda s: None)
        self._nfo_cache: dict[str, dict] = {}

    # ------------------------------------------------------------ 目录发现
    def _list(self, client, cid: str) -> list[P115Item]:
        return client.list_dir(cid)

    def _looks_like_nested_series(self, client, item: P115Item,
                                  root_title: str = "") -> bool:
        """合集根目录里的子目录是否像一个独立剧集/季目录。

        只看直属视频里是否有至少两个集号文件，避免把字体、字幕、
        花絮目录误当成剧集；也不进入 BDMV/VIDEO_TS 内部。
        """
        name = (item.name or "").strip()
        if not name or item.name.upper() in (
                "BDMV", "VIDEO_TS", "CERTIFICATE", "STREAM", "PLAYLIST",
                "CLIPINF") or is_subs_dir(name) or is_part_dir(name) or \
                is_season_dir(name):
            return False
        # 先按目录名做一层过滤：带 BDMV/Vol/Season 等介质提示，或与
        # 合集根目录同属一部片。避免对“电影合集”里的每个子目录都发请求。
        hint = bool(re.search(
            r"(?i)BDMV|Blu-?ray|Vol(?:ume)?|Season|S\d{1,2}|"
            r"第\s*\d+\s*季|Cour|Part|OVA|OAD", name))
        child_title = parse_name(name, is_dir=True).title
        same_show = bool(
            root_title and child_title and
            fuzz.WRatio(norm_title(root_title), norm_title(child_title))
            >= 60)
        if not hint and not same_show:
            return False
        try:
            children = self._list(client, item.fid)
        except Exception:
            return False
        videos = [c for c in children if c.is_video]
        if len(videos) < 2:
            return False
        episodic = sum(1 for c in videos
                       if parse_name(c.name).episode is not None)
        return episodic >= 2 and episodic >= len(videos) * 0.5

    def _discover(self, client, dir_item: P115Item,
                  depth: int = 0) -> list[MediaRoot]:
        if depth > 5:
            return []
        try:
            children = self._list(client, dir_item.fid)
        except Exception as e:
            self.log(f"读取目录失败：{dir_item.name}：{e}")
            return []
        # 把完整上级路径带到每个子项上：文件名只有 00001.m2ts 时，
        # 还能靠“动画 / 某番剧 / Season 01”这些上级目录名识别剧集。
        child_ancestors = list(dir_item.ancestors or []) + [dir_item.name]
        for c in children:
            c.ancestors = list(child_ancestors)
        videos = [c for c in children if c.is_video]
        dirs = [c for c in children if c.is_dir]
        nfo_files = [c for c in children if c.ext == ".nfo"]
        season_dirs = [d for d in dirs if is_season_dir(d.name)]
        # 有些发布把季目录写成“Overlord 2015 S01 JPN Blu-ray 1080p”，
        # 不是纯 “S01”。只在当前目录不是“动画/电视剧”这类库目录、
        # 且这些子目录的剧名一致时，才当成同一部剧的季目录；否则继续
        # 向下递归，避免把一个库目录里的多部剧硬拼成一部。
        if not season_dirs and not _is_generic_dir(dir_item.name):
            loose = [d for d in dirs if not is_season_dir(d.name) and
                     looks_like_season_dir(d.name)]
            loose_titles = {
                norm_title(parse_name(d.name, is_dir=True).title)
                for d in loose}
            loose_titles.discard("")
            if loose and len(loose_titles) == 1:
                season_dirs = loose
        part_dirs = [d for d in dirs if is_part_dir(d.name)]
        subs_dirs = [d for d in dirs if is_subs_dir(d.name)]
        structure = [d for d in dirs if d.name.upper() in
                     ("BDMV", "VIDEO_TS", "CERTIFICATE")]
        root_title = parse_name(dir_item.name, is_dir=True).title

        if structure and not videos:
            root = MediaRoot(item=dir_item, unsupported="蓝光目录结构（BDMV），暂不支持")
            return [root]

        if videos or season_dirs or part_dirs:
            root_season = season_from_dir(dir_item.name)
            root = MediaRoot(item=dir_item, season_dirs=season_dirs,
                             part_dirs=part_dirs, subs_dirs=subs_dirs,
                             nfo_files=nfo_files, root_season=root_season)
            # 根目录直属文件
            for c in children:
                if c.is_video or c.ext in (SUB_EXTS | AUDIO_EXTS):
                    root.entries.append(FileEntry(
                        item=c,
                        parsed=parse_name(c.name, parent_season=root_season),
                        container=None,
                        folder_season=root_season))
            # 季目录
            for sd in season_dirs:
                season = season_from_dir(sd.name)
                try:
                    sub_children = self._list(client, sd.fid)
                except Exception as e:
                    self.log(f"读取季目录失败：{sd.name}：{e}")
                    continue
                for c in sub_children:
                    if c.is_video or c.ext in (SUB_EXTS | AUDIO_EXTS):
                        root.entries.append(FileEntry(
                            item=c,
                            parsed=parse_name(c.name, parent_season=season),
                            container=sd, folder_season=season))
                    elif c.is_dir and is_subs_dir(c.name):
                        try:
                            for sc in self._list(client, c.fid):
                                if sc.ext in (SUB_EXTS | AUDIO_EXTS):
                                    root.entries.append(FileEntry(
                                        item=sc,
                                        parsed=parse_name(sc.name,
                                                          parent_season=season),
                                        container=c, folder_season=season))
                        except Exception:
                            pass
            # 分卷目录（Disc1/CD1…）：不重命名目录，只收集文件
            for pd in part_dirs:
                try:
                    sub_children = self._list(client, pd.fid)
                except Exception as e:
                    self.log(f"读取分卷目录失败：{pd.name}：{e}")
                    continue
                for c in sub_children:
                    if c.is_video or c.ext in (SUB_EXTS | AUDIO_EXTS):
                        root.entries.append(FileEntry(
                            item=c,
                            parsed=parse_name(c.name, parent_season=root_season),
                            container=pd, folder_season=root_season))
                    elif c.is_dir and is_subs_dir(c.name):
                        try:
                            for sc in self._list(client, c.fid):
                                if sc.ext in (SUB_EXTS | AUDIO_EXTS):
                                    root.entries.append(FileEntry(
                                        item=sc,
                                        parsed=parse_name(sc.name,
                                                          parent_season=root_season),
                                        container=c, folder_season=root_season))
                        except Exception:
                            pass
            # 字幕目录
            for sd in subs_dirs:
                try:
                    sub_children = self._list(client, sd.fid)
                except Exception:
                    continue
                for c in sub_children:
                    if c.ext in (SUB_EXTS | AUDIO_EXTS):
                        root.entries.append(FileEntry(
                            item=c, parsed=parse_name(c.name),
                            container=sd, folder_season=root_season))
            # 合集根目录同时有散装电影和季目录时（例如一个系列文件夹里
            # 放了两部剧场版 ISO，另有 S1/S2 两个剧集目录），不能只
            # 分析根目录电影而漏掉子目录里的整季。只把“直属视频里至少
            # 有两个集号文件”的子目录当成独立季目录。
            nested: list[MediaRoot] = []
            handled = {d.fid for d in season_dirs + part_dirs +
                       subs_dirs + structure}
            for d in dirs:
                if d.fid in handled:
                    continue
                if not self._looks_like_nested_series(client, d, root_title):
                    continue
                for nr in self._discover(client, d, depth + 1):
                    nr.is_season_root = True
                    nested.append(nr)
            return [root] + nested

        # 没有任何视频/季目录：继续向下找
        out: list[MediaRoot] = []
        for d in dirs:
            out += self._discover(client, d, depth + 1)
        return out

    # ------------------------------------------------------------ 上级目录
    def _ancestor_names(self, mr: MediaRoot) -> list[str]:
        """从最近到最远返回有意义的上级目录名（跳过“动画/番剧”等容器名）。"""
        names: list[str] = []
        for name in reversed(list(mr.item.ancestors or [])):
            name = (name or "").strip()
            if not name or name in ("根目录", "/", "\\"):
                continue
            if name.upper() in ("BDMV", "VIDEO_TS", "CERTIFICATE", "STREAM",
                                "PLAYLIST", "CLIPINF"):
                continue
            if _is_generic_dir(name) or is_part_dir(name) or \
                    is_subs_dir(name):
                continue
            if is_season_dir(name):
                # “S1替换双语字幕”是纯季目录+说明，跳过；
                # “S1东离剑游记”后缀是真剧名，保留下来兜底。
                ap = parse_name(name, is_dir=True)
                if _is_season_description(ap):
                    continue
            names.append(name)
        return names

    def _context_parsed(self, mr: MediaRoot) -> ParsedName:
        """当前文件夹名 + 上级文件夹名合并后的解析结果。

        当前目录如果是 “Season 01”“Disc1”“动画” 这类没有片名的目录，
        就把片名/年份/季号从上级目录补回来。

        搜索词必须带来源：只保留当前目录自己的词，以及“提供片名/与片名
        一致”的上级目录的词。不能把 “其他布袋戏（全系列）”“布袋戏系列”
        这类合集名，或无关季目录里的说明文字，一起丢给元数据搜索。
        """
        current_name = mr.item.name
        base = parse_name(current_name, is_dir=mr.item.is_dir,
                          parent_season=mr.root_season)
        current_generic = _is_generic_dir(current_name)
        # “S1替换双语字幕”是季目录+说明；“S1东离剑游记”虽然也带 S1，
        # 但后缀是真正的片名，要保留。只有后缀全是说明时才清空。
        season_desc = is_season_dir(current_name) and \
            _is_season_description(base)
        own_title_ok = bool(
            base.title and _usable_query(base.title) and
            not current_generic and
            not is_part_dir(current_name) and
            not is_subs_dir(current_name) and
            not season_desc)
        if not own_title_ok:
            base.title = ""
            queries: list[str] = []
        else:
            queries = [
                q.strip() for q in base.queries if _usable_query(q)]
        title = base.title
        year = base.year
        season = base.season if base.season is not None else mr.root_season

        for name in self._ancestor_names(mr):
            ap = parse_name(name, is_dir=True)
            ap_title = ap.title if _usable_query(ap.title) else ""
            # 没有片名的合集/分区目录直接跳过，不能只拿它的年份/季号，
            # 更不能把它的名字混进搜索词。
            if not ap_title:
                continue
            if not title:
                title = ap_title
            elif not titles_agree(ap_title, title):
                # 与已选片名不一致的上级目录（例如 “其他布袋戏（全系列）”）
                # 只可能是容器，不是这部作品的别名。
                continue
            for q in ap.queries:
                q = q.strip()
                if _usable_query(q) and q not in queries:
                    queries.append(q)
            if year is None:
                year = ap.year
            if season is None:
                season = ap.season
        base.title = title
        base.queries = queries
        base.year = year
        base.season = season
        return base

    @staticmethod
    def _looks_like_release_tag(text: str) -> bool:
        """目录名里的纯规格标记，不能当成英文片名。"""
        t = (text or "").strip()
        if not t:
            return True
        return bool(re.fullmatch(
            r"(?i)(?:bd(?:rip|remux|mv|iso)?|bd-?remux|web-?dl|webrip|"
            r"blu-?ray|uhd|4k|8k|\d{3,4}p|hdr(?:10)?|dolby|dv|"
            r"hevc|avc|x26[45]|h\.?26[45]|10bit|8bit|aac|ac3|eac3|flac|"
            r"dts(?:-hd)?|truehd|atmos|opus|mp3|chs|cht|jpn?|eng?|gb|"
            r"big5|简体|繁体|简繁|双语|中字|内封|外挂|无字)", t))

    def _local_names(self, mr: MediaRoot, folder_parsed: Optional[ParsedName],
                     parsed: Optional[ParsedName],
                     entries: list[FileEntry]) -> dict:
        """从原始目录/文件名里提取中文、日文、英文名。

        这部分完全离线：只要原目录已经写了中文名 + 日/英文名，命名时
        就直接使用，不再去 Bangumi/IMDb/TMDB 取第二段名称。
        """
        zh = ""
        for t in ((parsed.title if parsed else ""),
                  (folder_parsed.title if folder_parsed else "")):
            t = (t or "").strip()
            if (t and not _is_meaningless_title(t) and not has_kana(t)
                    and re.search(r"[㐀-鿿]", t)):
                zh = t
                break

        texts: list[str] = []

        def add(values):
            for v in values or []:
                v = (v or "").strip()
                if v and v not in texts:
                    texts.append(v)
                # “不死者之王 Overlord”是一个完整搜索词，但命名时仍需
                # 拆出英文名；否则会丢掉本地已有的 Overlord，改用联网日文名。
                if v and re.search(r"[㐀-鿿]", v) and \
                        re.search(r"[A-Za-z]", v):
                    for alias in extract_latin_aliases(v):
                        alias = alias.strip(" .-_")
                        if alias and alias not in texts:
                            texts.append(alias)

        if folder_parsed:
            add(folder_parsed.queries)
        if parsed:
            add(parsed.queries)
        # 上级目录只加入与本地主标题一致的那一级；否则
        # “其他布袋戏（全系列）/布袋戏系列”会被当成日文/英文
        # 别名写进文件夹名。当前目录自己的词已由 folder_parsed 带入。
        anchor = (zh or (parsed.title if parsed else "") or
                  (folder_parsed.title if folder_parsed else "")).strip()
        for name in self._ancestor_names(mr):
            ap = parse_name(name, is_dir=True)
            if not _usable_query(ap.title):
                continue
            if anchor and not titles_agree(ap.title, anchor):
                continue
            add(ap.queries)
            if not anchor:
                anchor = ap.title
        # 有些发布把双语名放在文件名里；但只接受和本地主标题对得上
        # 的文件名，不能让季目录里混进的另一部剧成为文件夹英文名。
        for e in [x for x in entries if x.is_video][:3]:
            if anchor and e.parsed.title and \
                    not titles_agree(e.parsed.title, anchor):
                continue
            add(e.parsed.queries)

        jp = jp_kanji = en = ""
        nz = norm_title(zh)
        for t in texts:
            t = sanitize_name(t, 120)
            if not t or _is_meaningless_title(t) or \
                    self._looks_like_release_tag(t):
                continue
            nt = norm_title(t)
            if nz and nt == nz:
                continue
            if has_kana(t) and len(t) >= 2:
                if not jp:
                    jp = t
            elif re.search(r"[㐀-鿿]", t) and \
                    not re.search(r"[A-Za-z]", t):
                # 纯汉字别名：可能是日文原名（如 進撃の巨人 之外的汉字标题）
                if not jp_kanji:
                    jp_kanji = t
            elif (re.search(r"[A-Za-z]{2,}", t) and not has_kana(t) and
                  not re.search(r"[㐀-鿿]", t)):
                if not en:
                    en = t

        year = None
        for src in (parsed, folder_parsed):
            if src and src.year:
                year = src.year
                break
        if year is None:
            for e in entries:
                if anchor and e.parsed.title and \
                        not titles_agree(e.parsed.title, anchor):
                    continue
                if e.parsed.year:
                    year = e.parsed.year
                    break
        imdb, tmdb = self._existing_ids(mr, entries, anchor)
        return {"zh": zh, "jp": jp, "jp_kanji": jp_kanji, "en": en,
                "year": year, "imdb": imdb, "tmdb": tmdb}

    def _assign_numbering(self, videos: list[FileEntry],
                          context_title: str) -> bool:
        """把 00001.m2ts 这类原盘编号识别成 S01E01…，而不是当成电影。

        绝大多数文件是带前导零的编号、且已知片名时启用；混在里面的
        menu/SP/NCOP 等花絮仍按原逻辑跳过，不会被硬塞成某一集。
        """
        if not context_title or len(videos) < 2:
            return False
        rows: list[tuple[int, FileEntry]] = []
        extras: list[FileEntry] = []
        for e in videos:
            stem = e.item.stem.strip()
            if RE_NUMBERING_STEM.match(stem):
                rows.append((int(stem), e))
            else:
                extras.append(e)
        # 其余文件必须是 menu/SP 这类没有片名的花絮，否则不启用编号模式
        if extras and any(not _is_meaningless_title(o.parsed.title)
                          for o in extras):
            return False
        if len(rows) < 2 or len(extras) > max(2, int(len(videos) * 0.2)):
            return False

        # 00000 常常是菜单/预告：明显小于正片时跳过
        if len(rows) > 2:
            sizes = sorted(e.item.size for _, e in rows if e.item.size > 0)
            median = sizes[len(sizes) // 2] if sizes else 0
            kept = []
            for n, e in rows:
                if n == 0 and e.item.size and median and \
                        e.item.size < median * 0.5:
                    e.parsed.episode = None
                    continue
                kept.append((n, e))
            rows = kept
        if len(rows) < 2:
            return False

        nums = [n for n, _ in rows]
        if len(set(nums)) == len(nums):
            # 00000 开头说明是 0 基编号，整体后移一位
            shift = 1 if min(nums) == 0 else 0
            for n, e in rows:
                ep = n + shift
                if ep <= 0:
                    continue
                e.parsed.episode = ep
                e.parsed.title = ""
        else:
            # 多张 Disc 都从 00001 开始：按目录/文件名顺序连续编号
            ordered = sorted(rows, key=lambda r: (
                _natural_key(r[1].container.name if r[1].container else ""),
                _natural_key(r[1].item.name)))
            for idx, (_, e) in enumerate(ordered, 1):
                e.parsed.episode = idx
                e.parsed.title = ""
        return True

    # ------------------------------------------------------------ 主入口
    def analyze(self, client, roots: list[P115Item],
                progress: Optional[Callable[[int, int, str], None]] = None,
                trace: Optional[Callable[[PlanItem], None]] = None
                ) -> list[PlanItem]:
        if progress:
            progress(0, 0, "正在扫描目录…")
        media_roots: list[MediaRoot] = []
        for r in roots:
            if not r.is_dir:
                # 用户直接选了文件：当成一个只含该文件的目录处理
                e = FileEntry(item=r, parsed=parse_name(r.name))
                media_roots.append(MediaRoot(item=r, entries=[e]))
                continue
            media_roots += self._discover(client, r)

        plans: list[PlanItem] = []
        total = max(1, len(media_roots))
        if progress:
            progress(0, total, "正在准备分析…")
        for idx, mr in enumerate(media_roots, 1):
            if progress:
                progress(idx - 1, total,
                         f"正在分析：{mr.item.name}（读取目录/联网查询）")
            built: list[PlanItem] = []
            try:
                built = self._build_plans(client, mr)
                plans += built
            except Exception as e:
                self.log(f"分析失败：{mr.item.name}：{e}")
                p = PlanItem(item=mr.item, media_type="unknown",
                             parsed=parse_name(mr.item.name, is_dir=mr.item.is_dir))
                p.status = "error"
                p.note = f"分析失败：{e}"
                p.selected = False
                plans.append(p)
                built = [p]
            if trace:
                for p in built:
                    try:
                        trace(p)
                    except Exception as e:
                        self.log(f"搜索诊断记录失败：{e}")
            if progress:
                progress(idx, total, f"已分析：{mr.item.name}")
        self._apply_folder_versions(plans)
        try:
            self.metadata.save_cache()
        except Exception:
            pass
        return plans

    # ------------------------------------------------------------ 版本目录
    @staticmethod
    def _version_identity(plan: PlanItem) -> tuple[str, str]:
        ident = plan.identity
        if ident.tmdb_id:
            return "tmdb", ident.tmdb_id
        if ident.imdb_id:
            return "imdb", ident.imdb_id
        return "", ""

    @staticmethod
    def _plan_videos(plan: PlanItem) -> list[FileEntry]:
        return [e for e in ((plan.context or {}).get("entries") or [])
                if e.is_video]

    def _version_group_key(self, plan: PlanItem) -> Optional[tuple]:
        if not plan.rename_root or plan.status in ("error", "skip"):
            return None
        if (plan.context or {}).get("is_container"):
            return None
        kind, sid = self._version_identity(plan)
        if not sid:
            return None
        if plan.media_type == "series":
            if not plan.seasons or not plan.episodes:
                return None
            # 只有季集集合完全一致，才认定为同一部剧的不同版本；
            # S01 与 S02 这种不同季的目录不能标成 V2。
            return ("series", kind, sid, tuple(plan.seasons),
                    tuple(plan.episodes))
        if plan.media_type == "movie":
            count = len(self._plan_videos(plan))
            if count <= 0:
                return None
            return ("movie", kind, sid, count)
        return None

    @staticmethod
    def _append_note(plan: PlanItem, note: str) -> None:
        parts = [x for x in (plan.note.split("；") if plan.note else []) if x]
        if note not in parts:
            parts.append(note)
        plan.note = "；".join(dict.fromkeys(parts))

    @staticmethod
    def _mark(plan: PlanItem, result: "qc.QcResult") -> None:
        """记录一条结构化检查结果，并按严重度更新 status。

        - 原来“自动”的任务遇到警告/阻断 → 需确认；
        - 已经“跳过”的保持跳过（没有可改名项），但原因仍会记录。
        """
        if result.code not in plan.qc_codes:
            plan.qc_codes.append(result.code)
        if plan.status == "auto" and result.severity in (qc.WARN, qc.BLOCK):
            plan.status = "review"
        if result.message and result.message not in (plan.note or ""):
            Planner._append_note(plan, result.message)

    def _apply_folder_versions(self, plans: list[PlanItem]) -> None:
        """同一部剧/电影的多个版本目录：主目录原名，额外目录标 V2/V3。

        视频文件仍按正常规则命名；版本号只加在文件夹名里、ID 之前。
        """
        groups: dict[tuple, list[PlanItem]] = {}
        for p in plans:
            key = self._version_group_key(p)
            if key:
                groups.setdefault(key, []).append(p)
        for group in groups.values():
            if len(group) < 2:
                continue
            if len({p.item.fid for p in group}) != len(group):
                continue
            # 已经有 V2/V3 的目录不抢主版本；只从没有版本号的分组里选主版本。
            plain = [p for p in group
                     if self._existing_folder_version(p.item.name) <= 1]
            if not plain:
                continue

            def size_of(p: PlanItem) -> int:
                return sum(int(getattr(e.item, "size", 0) or 0)
                           for e in self._plan_videos(p))

            primary = sorted(
                plain, key=lambda p: (-p.confidence, -size_of(p),
                                      p.item.name.casefold()))[0]
            extras = [p for p in group if p is not primary]
            extras.sort(key=lambda p: (
                self._existing_folder_version(p.item.name) <= 1,
                -p.confidence, -size_of(p), p.item.name.casefold()))
            used = {1}
            assigned: dict[str, int] = {}
            for p in extras:
                number = self._existing_folder_version(p.item.name)
                if number <= 1 or number in used:
                    number = 2
                    while number in used:
                        number += 1
                used.add(number)
                assigned[p.item.fid] = number

            self._append_note(
                primary,
                f"检测到 {len(group)} 个同片版本目录；本目录作为主版本，"
                "其余标记 V2/V3，视频文件保持正常命名。")
            for p in [primary] + extras:
                number = assigned.get(p.item.fid, 0)
                if number:
                    p.folder_version = number
                    self._append_note(
                        p,
                        f"同片额外版本目录，文件夹在 ID 前标记 V{number}"
                        f"（主版本：{primary.item.name}）；视频文件保持正常命名。")
                try:
                    self.rebuild(p)
                except Exception as e:
                    self.log(f"版本目录重建失败：{p.item.name}：{e}")

    # ------------------------------------------------------------ 分组
    def _build_plans(self, client, mr: MediaRoot) -> list[PlanItem]:
        if mr.unsupported:
            return [self._bdmv_plan(mr)]
        videos = mr.videos
        if not videos:
            return []

        # 当前文件夹名 + 上级文件夹名一起参与识别
        folder_parsed = self._context_parsed(mr)
        folder_title = folder_parsed.title
        # 00001.m2ts / 00002.m2ts 这类原盘文件：按编号补出集数
        self._assign_numbering(videos, folder_title)
        titles = [e.parsed.title for e in videos
                  if e.parsed.title and not _is_meaningless_title(e.parsed.title)]
        distinct = {norm_title(t) for t in titles if norm_title(t)}
        episodic = [e for e in videos if e.parsed.episode is not None]

        generic = _is_generic_dir(mr.item.name) if mr.item.is_dir else False
        # 剧集根目录里同时放了季目录和电影（例如 Overlord 的 S01-S04
        # 加一个剧场版 ISO）时，先把季目录合成一部剧，再把根目录里
        # 独立电影文件单独列出来；不能因为有 ISO 就把整个根目录当电影。
        season_entries = [e for e in videos if e.folder_season is not None]
        if mr.season_dirs and season_entries and \
                not is_season_dir(mr.item.name) and \
                not is_part_dir(mr.item.name):
            return self._seasoned_root_plans(
                client, mr, videos, season_entries, folder_parsed, generic)

        container = False
        if len(videos) > 1:
            if generic:
                container = True
            elif len(distinct) >= 2 and len(episodic) < max(2, int(len(videos) * 0.6)):
                container = True
            elif len(distinct) >= 2 and folder_title and \
                    not any(titles_agree(folder_title, t) for t in distinct):
                # 目录名是“某某”而文件是“某某 第X季”“某某 OVA”这类
                # 同一部剧的变体时，它仍是一部剧的目录，不能当成多剧合集；
                # 否则文件夹会因为“文件级标题不一致”而被判成认不得。
                container = not episodic or any(
                    titles_agree(folder_title, t) for t in distinct)
        # 选中的目录本身是季目录/分卷目录时，不能把它当成剧集根目录改名
        if mr.item.is_dir and (is_season_dir(mr.item.name) or is_part_dir(mr.item.name)):
            container = True

        if container and len(distinct) >= 2:
            plans: list[PlanItem] = []
            groups: dict[str, list[FileEntry]] = {}
            for e in videos:
                key = norm_title(e.parsed.title) or \
                    norm_title(strip_season_markers(folder_title)) or "unknown"
                groups.setdefault(key, []).append(e)
            # 同一部剧的季号变体（“X”与“X 第二季”/“X 第四季”）只是
            # 文件名写法不同，按标题分组会把文件夹拆散；这里合并成一组。
            merged: dict[str, list[FileEntry]] = {}
            for key, group in groups.items():
                base = norm_title(strip_season_markers(key))
                target = next((k for k in merged
                               if norm_title(strip_season_markers(k)) == base),
                              None)
                if target is None:
                    merged[key] = list(group)
                else:
                    merged[target].extend(group)
            groups = merged
            # 目录名是中文、文件里写日文别名时（例如
            # “女子落语 [じょしらく]”里的“じょしらく S01E01”），
            # 不能因为中文字面不同就把整个目录当成合集。只要有一组
            # 集数文件能和目录的中文名/别名对上，这一组仍然代表
            # 当前剧集目录，文件夹要参与改名；OVA/其他组继续单独列出。
            folder_anchors = [folder_title] + [
                q for q in folder_parsed.queries
                if _usable_query(q)]
            folder_anchors = list(dict.fromkeys(
                a for a in folder_anchors if a))

            def same_as_folder(text: str) -> bool:
                nt = norm_title(text)
                if not nt:
                    return False
                for anchor in folder_anchors:
                    na = norm_title(anchor)
                    if na and (nt == na or titles_agree(text, anchor)):
                        return True
                return False

            root_group = ""
            for key, group in groups.items():
                if same_as_folder(key) and any(
                        e.parsed.episode is not None for e in group):
                    root_group = key
                    break
            if not root_group and not generic and \
                    not is_season_dir(mr.item.name) and \
                    not is_part_dir(mr.item.name):
                # 目录没有写日文别名时，中文目录名和日文文件名也可能
                # 只是翻译关系。这里只有一个成组的集数标题（其余是
                # OVA/花絮），就把这一组当作当前剧集，文件夹正常改名。
                episodic_groups = [
                    (key, group) for key, group in groups.items()
                    if any(e.parsed.episode is not None for e in group)]
                if len(episodic_groups) == 1:
                    key, group = episodic_groups[0]
                    if sum(1 for e in group
                           if e.parsed.episode is not None) >= 2:
                        root_group = key
            for key, group in groups.items():
                if any(e.parsed.episode is not None for e in group):
                    rename_root = key == root_group
                    p = self._series_plan(
                        client, mr, group, folder_parsed,
                        rename_root=rename_root,
                        is_container=not rename_root)
                else:
                    if len(group) == 1:
                        p = self._movie_plan(client, mr, [group[0]],
                                             folder_parsed, rename_root=False)
                    else:
                        # 同一标题的多个版本
                        p = self._movie_plan(client, mr, group, folder_parsed,
                                             rename_root=False)
                if p:
                    plans.append(p)
            return plans

        if episodic:
            # 一个剧集目录。选中的是季目录/分卷目录时，文件里偶尔会混进
            # 别的片名（放错目录、字幕文件、合集残留）；不能因此把单个
            # 文件名当成整季的剧名去搜索。先按上级剧名搜，再由冲突校验
            # 决定是否标记“需确认”。真正的多片名容器仍然按文件分组。
            prefer_file_title = container and (
                len(distinct) >= 2 or
                not (is_season_dir(mr.item.name) or
                     is_part_dir(mr.item.name)))
            rename_root = not container and not generic
            p = self._series_plan(
                client, mr, videos, folder_parsed,
                rename_root=rename_root, is_container=prefer_file_title)
            return [p] if p else []

        # 没有集数：电影
        if len(distinct) >= 2 and not generic:
            plans = []
            groups: dict[str, list[FileEntry]] = {}
            for e in videos:
                groups.setdefault(norm_title(e.parsed.title) or "unknown", []).append(e)
            for group in groups.values():
                p = self._movie_plan(client, mr, group, folder_parsed,
                                     rename_root=False)
                if p:
                    plans.append(p)
            return plans
        rename_root = not container and not generic and len(videos) >= 1
        p = self._movie_plan(client, mr, videos, folder_parsed,
                             rename_root=rename_root)
        return [p] if p else []

    @staticmethod
    def _is_root_movie_extra(entry: FileEntry) -> bool:
        """剧集根目录里独立存在的电影文件（ISO/剧场版），不是花絮。"""
        if entry.parsed.episode is not None or \
                entry.parsed.season is not None:
            return False
        title = entry.parsed.title or ""
        if re.search(r"(?i)\b(?:NCOP|NCED|PV|CM|MENU|TRAILER)\b", title):
            return False
        if entry.item.ext.lower() == ".iso":
            return True
        return bool(re.search(r"(?i)\bMOVIE\b|剧场版|映画|电影", title))

    def _seasoned_root_plans(self, client, mr: MediaRoot,
                             videos: list[FileEntry],
                             season_entries: list[FileEntry],
                             folder_parsed: ParsedName,
                             generic: bool) -> list[PlanItem]:
        """根目录同时有季目录和独立电影时，拆成剧集 + 电影任务。"""
        plans: list[PlanItem] = []
        rename_root = not generic and not is_season_dir(mr.item.name)
        series = self._series_plan(client, mr, season_entries, folder_parsed,
                                   rename_root=rename_root,
                                   is_container=False)
        if series:
            plans.append(series)

        extras = [e for e in videos
                  if e.folder_season is None and self._is_root_movie_extra(e)]
        groups: dict[str, list[FileEntry]] = {}
        for e in extras:
            key = norm_title(e.parsed.title) or e.item.stem
            groups.setdefault(key, []).append(e)
        movie_plans: list[PlanItem] = []
        for group in groups.values():
            p = self._movie_plan(client, mr, group, folder_parsed,
                                 rename_root=False)
            if p:
                movie_plans.append(p)
        if series and movie_plans:
            series.note = "；".join(dict.fromkeys(
                [n for n in (series.note.split("；") if series.note else []) if n] +
                [f"根目录另有 {len(movie_plans)} 个电影文件，已单独列出。"]))
        plans += movie_plans
        return plans

    # ------------------------------------------------------------ 搜索词
    def _search_parsed(self, mr: MediaRoot, entries: list[FileEntry],
                       folder_parsed: ParsedName,
                       prefer_file_title: bool = False) -> ParsedName:
        folder_title = folder_parsed.title
        # 只有视频文件能提供片名/搜索词。字幕、音轨、NFO 的文件名
        # （例如 “Friends.S01E01.chs.ass”）绝不能把整部剧带偏。
        video_entries = [e for e in entries if e.is_video]
        title_entries = video_entries or entries
        # 00001、00002 这种文件只是序号，不能当片名参与搜索
        file_titles = [e.parsed.title for e in title_entries
                       if e.parsed.title and
                       not _is_meaningless_title(e.parsed.title)]
        counts = Counter(file_titles)
        common_file_title = counts.most_common(1)[0][0] if counts else ""

        # 目录名被识别为“动画/Season 01”时，folder_title 来自上级目录；
        # 这时只要文件名没有有效片名，就用上级目录名。
        # 一个“电影库/电视剧库”目录（如 1、国内）里有多个片名时，
        # 必须用文件自己的片名，不能把库目录当电影名。
        use_folder = (not prefer_file_title and bool(folder_title) and
                      (not _is_generic_dir(mr.item.name) or
                       not common_file_title))
        if not use_folder and common_file_title:
            title = common_file_title
        elif folder_title:
            title = folder_title
        else:
            # 季目录/分区目录本身不是片名（例如 “S1替换双语字幕”）。
            # 片名只能来自上级/上上级目录或文件；都没有就留空，
            # 让任务进“需确认”，不能拿说明文字去联网搜索。
            title = common_file_title

        queries: list[str] = []
        # 独立剧集/电影目录的上级搜索词（含中/日/英别名）参与匹配；
        # 库目录里的文件夹名只是分区，不能拿它当搜索词。
        # 这里的词由 _context_parsed 按来源筛过：只保留当前目录，
        # 以及提供片名/与片名一致的那一级上级目录。
        if not prefer_file_title:
            for q in folder_parsed.queries:
                if _usable_query(q) and q not in queries:
                    queries.append(q)
        # 文件自己的搜索词也必须服从本地锚点。一个季目录里混进的
        # “Friends.S01E01”不能因为文件名独立，就获得一次整剧搜索机会。
        anchor_ok = _usable_query(title)
        for e in title_entries:
            for q in e.parsed.queries:
                if not _usable_query(q):
                    continue
                if anchor_ok and not titles_agree(q, title):
                    continue
                if q not in queries:
                    queries.append(q)
        if _usable_query(title) and title not in queries:
            queries.insert(0, title)

        # 季目录里如果所有有意义的视频文件名都和上级剧名对不上，
        # 说明本地层级本身可能有问题（放错目录/多部剧混放）。此时仍
        # 按目录锚点搜索，但把冲突标题带给 _series_plan 做二次校验。
        conflict_titles: list[str] = []
        if not prefer_file_title and anchor_ok:
            current_is_season = (looks_like_season_dir(mr.item.name) or
                                 is_part_dir(mr.item.name))
            conflict_entries = [
                e for e in title_entries
                if current_is_season or (
                    e.container is not None and
                    (looks_like_season_dir(e.container.name) or
                     is_part_dir(e.container.name)))]
            if conflict_entries:
                # 目录自己的中英混合别名也算锚点：
                # “不死者之王 Overlord”能支持文件名里的 Overlord，
                # 但不能支持 Friends。
                anchor_names = [title] + [
                    q for q in folder_parsed.queries
                    if _usable_query(q) and q not in (title,)]
                meaningful = Counter(
                    e.parsed.title for e in conflict_entries
                    if e.parsed.title and _usable_query(e.parsed.title))
                for t, _count in meaningful.most_common():
                    if not any(titles_agree(t, a) for a in anchor_names):
                        conflict_titles.append(t)
                conflict_titles = conflict_titles[:4]

        year = None if prefer_file_title else folder_parsed.year
        if year is None:
            for e in title_entries:
                # 和片名对不上的文件（例如季目录里混进的 Friends）不能
                # 把它的年份带进搜索，否则 1994 会把结果拉向另一部剧。
                if anchor_ok and e.parsed.title and \
                        not titles_agree(e.parsed.title, title):
                    continue
                if e.parsed.year:
                    year = e.parsed.year
                    break
        season = folder_parsed.season
        season_from_file = None
        if season is None:
            # 目录名没写 Sxx/第N季，但视频文件名是 S2E01 时，季号仍属于
            # 这部剧；交回 _series_plan，让 TMDB 季结构按实际季校验。
            # 只有季号一致的多数文件才采用，混季目录不硬套。
            file_seasons = Counter(
                e.parsed.season for e in title_entries
                if (not anchor_ok or not e.parsed.title or
                    titles_agree(e.parsed.title, title))
                and e.parsed.season and e.parsed.season > 0)
            if file_seasons:
                season_from_file = file_seasons.most_common(1)[0][0]
        return ParsedName(raw=mr.item.name, title=title, queries=queries[:6],
                          year=year, season=season, is_episode=False,
                          ext="", warnings=[], conflict_titles=conflict_titles,
                          file_season=season_from_file)

    def _match(self, parsed: ParsedName, media_type: str,
               category_hint: str = "") -> MatchResult:
        try:
            res = self.metadata.match(parsed, media_type, category_hint)
        except Exception as e:
            self.log(f"元数据搜索失败：{parsed.title}：{e}")
            return MatchResult()
        self._trace_match(parsed, res)
        return res

    @staticmethod
    def _cand_brief(cand: Optional[Candidate]) -> str:
        if not cand:
            return "无"
        sid = cand.sid or "?"
        year = cand.year or "?"
        return f"{cand.title}｜{year}｜{sid}｜{cand.score:.2f}"

    def _trace_match(self, parsed: ParsedName, res: MatchResult) -> None:
        """把这次自动搜索的关键信息记进备注，方便对照排查错配。

        只记“用了哪些词、各来源选了什么、综合置信度多少”，候选过多时
        只取各来源第一名，避免备注变成长日志。
        """
        if getattr(res, "trace", ""):
            return    # ID/NFO 锚点等不走标题搜索，不需要重复记录
        parts = [f"搜索词 {' / '.join(parsed.queries[:3]) or '无'}"]
        for source, cand in (("豆瓣", res.douban), ("Bangumi", res.bangumi),
                             ("IMDb", res.imdb), ("TMDB", res.tmdb)):
            parts.append(f"{source} {self._cand_brief(cand)}")
        parts.append(f"置信度 {res.confidence * 100:.0f}%")
        res.trace = "；".join(parts)

    @staticmethod
    def _match_titles(match: MatchResult) -> list[str]:
        """收集匹配结果里所有可用来核对本地标题的名称/别名。"""
        titles: list[str] = []

        def add(value):
            value = str(value or "").strip()
            if value and value not in titles:
                titles.append(value)

        add(match.title_zh)
        add(match.title_original)
        add(match.series_title)
        add(match.series_original_title)
        for cand in (match.douban, match.bangumi, match.imdb, match.tmdb):
            if not cand:
                continue
            add(cand.title)
            add(cand.original_title)
            extra = cand.extra if isinstance(cand.extra, dict) else {}
            for alias in (extra.get("aliases") or []):
                add(alias)
        return titles

    def _season_conflict_note(self, parsed: ParsedName, match: MatchResult,
                              id_anchored: bool = False) -> str:
        """季目录的本地标题与视频文件名冲突时，阻止无根据的自动改名。"""
        if id_anchored or not parsed.conflict_titles:
            return ""
        cand_titles = self._match_titles(match)
        bad = [t for t in parsed.conflict_titles
               if not any(titles_agree(t, c) for c in cand_titles)]
        # 匹配结果还必须支持目录锚点；否则即使它支持了文件里的另一部剧，
        # 也只是把“无关关键词”换了个方向。
        title_ok = any(titles_agree(parsed.title, c) for c in cand_titles)
        if not bad and title_ok:
            return ""
        shown = "、".join(parsed.conflict_titles[:3])
        return (f"季目录里的视频文件名（{shown}）与上级剧名不一致，"
                "已暂停自动改名；请核对目录，或右键任务手动搜索。")

    def _match_by_ids(self, parsed: ParsedName, media_type: str,
                      imdb_id: str, tmdb_id: str,
                      fallback_title: str = "") -> Optional[MatchResult]:
        """原目录/文件名已有 ID 时，按 ID 解析，避免标题搜索匹配错。"""
        if not (imdb_id or tmdb_id):
            return None
        fn = getattr(self.metadata, "match_by_ids", None)
        if not fn:
            return None
        try:
            return fn(imdb_id, tmdb_id, media_type,
                      fallback_title or parsed.title)
        except Exception as e:
            self.log(f"按 ID 匹配失败：{imdb_id or tmdb_id}：{e}")
            return None

    @staticmethod
    def _path_category_hints(context: str) -> tuple[bool, bool, bool]:
        """从当前/上级目录名判断“动画区 / 电视剧区”。

        返回 (是否动画区, 是否电视剧区, 是否明确写着电视剧类词)。
        根目录“剧”只是泛剧集容器，里面也可能有动画；而“电视剧/日剧”
        是明确指向真人剧的强提示。
        """
        anime_words = ("动画", "动漫", "番剧", "新番", "日番",
                       "美漫", "美国动画", "美国动漫",
                       "anime", "animation")
        tv_words = ("电视剧", "剧集", "连续剧", "美剧", "英剧", "韩剧",
                    "日剧", "国产剧", "真人", "tv", "shows", "series")
        path_anime = False
        path_tv = False
        path_tv_strong = False
        for tok in (context or "").split():
            t = tok.strip().lower()
            if not t:
                continue
            if t in ("番", "动画", "动漫") or any(w in t for w in anime_words):
                path_anime = True
            if any(w in t for w in tv_words):
                path_tv = True
                path_tv_strong = True
            elif t == "剧":
                path_tv = True
        return path_anime, path_tv, path_tv_strong

    def _detect_category(self, media_type: str, match: MatchResult,
                         parsed: ParsedName, context: str = "") -> str:
        if media_type == "movie":
            return "movie"
        path_anime, path_tv, path_tv_strong = \
            self._path_category_hints(context)
        ctx = (context or "").lower()
        us_anime_path = any(
            k in ctx for k in ("美漫", "美国动画", "美国动漫")) or bool(
            re.search(r"(?<![A-Za-z])US(?:A)?[ ._\-]*(?:ANIMATION|ANIME)",
                      ctx, re.I))
        animation = bool(match.animation)
        for c in (match.tmdb, match.imdb, match.bangumi, match.douban):
            if c and isinstance(c.extra, dict) and c.extra.get("animation"):
                animation = True

        # 文件夹明确在“电视剧/剧集/日剧/美剧”下：不要再因为
        # 地区是日本或标题里有假名就归成日番。这是之前真人剧被
        # 分类成动画的主要原因。
        # 根目录只写“剧”时是弱提示：如果元数据明确是动画（TMDB
        # genre 16 / Bangumi 动画标签），仍按动画处理。
        if path_tv and not path_anime and (path_tv_strong or not animation):
            if path_tv_strong and animation:
                note = "所在文件夹是电视剧目录，但元数据标记为动画，请核对。"
                if note not in match.notes:
                    match.notes.append(note)
            return "tv"
        # 文件夹明确在“动画/动漫/番剧/日番”下，但元数据明确不是动画：
        # 动画目录里也可能放真人剧（日剧/国产剧），不能被目录名强行
        # 改成动画命名。日语/中文原名里带假名时仍按日番/动画处理，
        # 只有西文原名才放宽成电视剧；明确写着“美漫/美国动画”的目录除外。
        if path_anime and not path_tv and match.country and not animation \
                and not us_anime_path:
            loose_latin = us_anime_path or match.country in (
                "us", "uk", "ca", "west") or (
                match.country in ("jp", "cn") and
                re.search(r"[A-Za-z]{3,}", match.title_original or ""))
            if loose_latin:
                return "tv"
        if path_anime and not path_tv and us_anime_path:
            return "us_anime"
        # 文件夹明确在“动画/动漫/番剧/日番”下：按动画命名规则处理。
        if path_anime and not path_tv:
            if match.country == "jp":
                return "jp_anime"
            if match.country == "cn":
                return "cn_anime"
            # 美漫单独归类；目录明确写“美漫/美国动画”时也按美漫处理。
            if match.country == "us" and animation:
                return "us_anime"
            if match.country in ("uk", "ca", "west") and animation:
                return "west_anime"
            if has_kana(match.title_original or "") or \
                    has_kana(parsed.title or "") or has_kana(context):
                return "jp_anime"
            if re.search(r"[㐀-鿿]", match.title_zh or parsed.title or ""):
                return "cn_anime"
            if re.search(r"[A-Za-z]", match.title_original or parsed.title or ""):
                return "west_anime"
            return "jp_anime"

        # 地区优先于“目录里有日文假名”的兜底判断：
        # 欧美动画/电视剧的目录名里也常带日文别名，不能因此当成日番。
        if match.country == "jp":
            return "jp_anime" if animation else "tv"
        if match.country == "cn":
            return "cn_anime" if animation else "tv"
        orig = match.title_original or ""
        if match.country == "us":
            animation_hint = animation or path_anime or us_anime_path or any(
                k in context for k in ("动画", "动漫", "anime"))
            return "us_anime" if animation_hint else "tv"
        if match.country in ("uk", "ca", "west"):
            animation_hint = animation or path_anime or any(
                k in context for k in ("动画", "动漫", "anime"))
            return "west_anime" if animation_hint else "tv"
        if has_kana(orig) or has_kana(parsed.title or ""):
            return "jp_anime"
        if has_kana(context):
            # 主标题是英文/拉丁时，目录里的日文别名不足以判定日番
            main_is_latin = bool(re.search(
                r"[A-Za-z]", orig or match.title_zh or parsed.title or ""))
            if not main_is_latin:
                return "jp_anime"
        if "国产" in ctx:
            return "cn_anime"
        if any(k in ctx for k in ("日番", "新番", "番剧")):
            return "jp_anime"
        if us_anime_path:
            return "us_anime"
        # 没有地区信息时，英文原名 + 动画目录 → 欧美动画
        if (not match.country and
                re.search(r"[A-Za-z]", orig) and
                not has_kana(orig) and
                not re.search(r"[㐀-鿿]", orig) and
                any(k in context for k in ("动画", "动漫"))):
            return "west_anime"
        return "tv"

    @staticmethod
    def _nfo_priority(name: str) -> int:
        low = (name or "").lower()
        if low == "tvshow.nfo":
            return 0
        if low == "movie.nfo":
            return 1
        if low == "season.nfo":
            return 2
        if low.endswith(".nfo"):
            return 3
        return 9

    def _nfo_anchor(self, client, mr: MediaRoot,
                    media_type: str = "",
                    entries: Optional[list[FileEntry]] = None,
                    allow_generic: bool = True) -> dict:
        """读取当前目录里的 tvshow.nfo/movie.nfo，提取 ID/标题/年份。

        只读下载小文件；没有 pickcode、没有下载能力或解析失败时返回空。
        同一 Planner 生命周期内按目录缓存，避免重建预览时重复下载。
        """
        entries = list(entries or [])
        entry_key = ",".join(str(e.item.fid) for e in entries)
        key = f"{mr.item.fid}:{media_type}:{entry_key}"
        if key in self._nfo_cache:
            return self._nfo_cache[key]
        files = list(getattr(mr, "nfo_files", []) or [])
        if media_type == "series":
            # season.nfo 里的 <title> 通常是“Season 1”，不能当剧名；
            # 只把 tvshow.nfo 当作剧集锚点，避免污染搜索词。
            files = [f for f in files
                     if (f.name or "").lower() == "tvshow.nfo"]
        elif media_type == "movie":
            files = [f for f in files
                     if (f.name or "").lower() not in ("tvshow.nfo",
                                                       "season.nfo")]
            stems = {os.path.splitext(e.item.name)[0].lower()
                     for e in entries if e.item.name}
            exact = [f for f in files
                     if os.path.splitext(f.name)[0].lower() in stems]
            if exact:
                files = exact
            elif not allow_generic:
                files = []
            else:
                movie_nfo = [f for f in files
                             if (f.name or "").lower() == "movie.nfo"]
                files = movie_nfo or files
        if not files:
            self._nfo_cache[key] = {}
            return {}
        fn = getattr(client, "download_bytes", None)
        if not callable(fn):
            self._nfo_cache[key] = {}
            return {}
        from .nfo import parse_nfo_bytes
        files.sort(key=lambda f: (self._nfo_priority(f.name),
                                  (f.name or "").lower()))
        for item in files[:3]:
            if not item.pickcode:
                continue
            try:
                try:
                    blob = fn(item.pickcode, 2 * 1024 * 1024)
                except TypeError:
                    blob = fn(item.pickcode)
            except Exception as e:
                self.log(f"读取 NFO 失败：{item.name}：{e}")
                continue
            if isinstance(blob, str):
                blob = blob.encode("utf-8", "ignore")
            data = parse_nfo_bytes(blob or b"")
            if not data:
                continue
            # 单集 NFO 的 <showtitle> 才是剧名；tvshow.nfo 没有该字段。
            title = str(data.get("show_title") or data.get("title") or "").strip()
            out = dict(data)
            if title:
                out["title"] = title
            out["nfo_name"] = item.name
            self._nfo_cache[key] = out
            return out
        self._nfo_cache[key] = {}
        return {}

    @staticmethod
    def _apply_nfo_hints(parsed: ParsedName, info: dict) -> None:
        """把 NFO 的标题/年份补进搜索信息，但不覆盖已有的有效片名。"""
        if not info:
            return
        title = str(info.get("title") or "").strip()
        original = str(info.get("original_title") or "").strip()
        if title and (not parsed.title or
                      _is_meaningless_title(parsed.title)):
            parsed.title = title
        queries = list(parsed.queries or [])
        for q in (title, original):
            if q and q not in queries:
                queries.insert(0, q)
        parsed.queries = queries[:8]
        if parsed.year is None and isinstance(info.get("year"), int):
            parsed.year = info["year"]

    def _existing_ids(self, mr: MediaRoot,
                      entries: list[FileEntry] = (),
                      anchor: str = "") -> tuple[str, str]:
        """目录名/上级目录名/文件名里已有的 IMDb/TMDB 标识。

        只认当前目录自己的 ID，以及和片名对得上的上级/文件 ID。
        季目录里混进的另一部剧，即使文件名带 ID，也不能把整季带偏。
        """
        names = [mr.item.name] + list(reversed(list(mr.item.ancestors or [])))
        for idx, n in enumerate(names):
            # 当前选中的目录名是用户明确指定的，始终读取；上级目录要过滤。
            if idx and anchor:
                ap = parse_name(n, is_dir=True)
                if _usable_query(ap.title) and \
                        not titles_agree(ap.title, anchor):
                    continue
            imdb_id, tmdb_id = provider_ids(n)
            if imdb_id or tmdb_id:
                return imdb_id, tmdb_id
        for e in entries:
            if anchor and e.parsed.title and \
                    not titles_agree(e.parsed.title, anchor):
                continue
            imdb_id, tmdb_id = provider_ids(e.item.name)
            if imdb_id or tmdb_id:
                return imdb_id, tmdb_id
        return "", ""

    # ------------------------------------------------------------ 蓝光目录
    def _bdmv_plan(self, mr: MediaRoot) -> PlanItem:
        """BDMV/VIDEO_TS 目录：只改最外层文件夹，不碰内部结构文件。"""
        name = mr.item.name
        parsed = self._context_parsed(mr)
        if name.upper() in ("BDMV", "VIDEO_TS", "CERTIFICATE"):
            p = PlanItem(item=mr.item, media_type="unknown", parsed=parsed)
            p.status = "skip"
            p.note = "这是蓝光结构内部目录，请选择上一级的剧集/电影文件夹。"
            p.selected = False
            return p
        if not parsed.title:
            parsed.title = name
            parsed.queries = [name]

        context_text = " ".join([name] + list(mr.item.ancestors or []))
        movie_hint = bool(re.search(
            r"(?i)\bMOVIE\b|剧场版|映画|(?<![一-鿿])电影(?![一-鿿])",
            context_text))
        series_hint = bool(re.search(
            r"(?i)\b(?:Vol|Disc|BOX|S\d{1,2})\b|"
            r"第\s*[0-9一二三四五六七八九十]+\s*[季期]|全集|完结|OVA|OAD",
            context_text))
        media_type = "movie" if movie_hint and not series_hint else "series"
        path_anime, path_tv, _ = self._path_category_hints(context_text)
        category_hint = ""
        if media_type == "series":
            category_hint = ("tv" if path_tv and not path_anime else
                             "anime" if path_anime and not path_tv else "")
        ex_imdb, ex_tmdb = self._existing_ids(mr)
        match = (self._match_by_ids(parsed, media_type, ex_imdb, ex_tmdb)
                 or self._match(parsed, media_type, category_hint))
        if media_type == "series" and match.confidence < 0.55:
            m2 = (self._match_by_ids(parsed, "movie", ex_imdb, ex_tmdb)
                  or self._match(parsed, "movie"))
            if m2.confidence > match.confidence:
                media_type, match = "movie", m2

        if media_type == "series":
            title = (match.series_title or match.title_zh or
                     match.title_original or
                     strip_season_markers(parsed.title) or parsed.title)
            year = match.series_year or match.year or parsed.year
        else:
            title = (match.title_zh or match.title_original or
                     strip_season_markers(parsed.title) or parsed.title)
            year = match.year or parsed.year
        title = strip_season_markers(_strip_trailing_year(title, year))

        if media_type == "series":
            imdb_id = ex_imdb or match.series_imdb_id
        else:
            imdb_id = ex_imdb or match.imdb_id
        tmdb_id = ex_tmdb or match.tmdb_id
        category = ("movie" if media_type == "movie" else
                    self._detect_category("series", match, parsed,
                                          context_text))

        p = PlanItem(item=mr.item, media_type=media_type, parsed=parsed,
                     match=match, title=title, year=year,
                     confidence=match.confidence, category=category,
                     rename_root=True, series_imdb_id=imdb_id)
        p.context = {"mr": mr, "entries": [], "folder_parsed": parsed,
                     "imdb_id": imdb_id, "tmdb_id": tmdb_id}
        notes = list(match.notes)
        if match.trace:
            notes.append(match.trace)
        notes.append("蓝光 BDMV/VIDEO_TS 目录：只重命名最外层文件夹，"
                     "内部 BDMV/STREAM 等文件保持原样。")
        folder_name = ""
        if media_type == "movie":
            suffix = self._movie_id_suffix(imdb_id, tmdb_id)
            if suffix:
                folder_name = self._insert_id_after_title(name, suffix, True)
                if folder_name:
                    notes.append("电影：IMDb/TMDB 号已放到中文名后，"
                                 "其他规格保持不变。")
        if not folder_name:
            if media_type == "movie" and self._find_title_end(name) >= 0:
                folder_name = name
                notes.append("没有找到 IMDb/TMDB 标识，电影名称保持不变。")
            else:
                folder_name = self._folder_name(p, title, year,
                                                imdb_id, tmdb_id)
        if folder_name and folder_name != name:
            p.ops = [RenameOp(
                fid=mr.item.fid, old_name=name, new_name=folder_name,
                is_dir=True,
                role="show" if media_type == "series" else "movie",
                parent_id=mr.item.parent_id)]
        else:
            notes.append("名称已符合规则，无需修改。")
        # 蓝光目录内部无法可靠判断季/集，统一标为需确认
        p.status = "review" if p.ops else "skip"
        p.selected = False
        p.note = "；".join(dict.fromkeys(notes))
        return p

    def _repair_tmdb(self, match: MatchResult, title: str) -> None:
        """TMDB 标题和 IMDb/豆瓣/Bangumi 明显冲突时，丢弃错误 TMDB。"""
        tmdb = match.tmdb
        if not tmdb:
            return
        # 不要拿 match.title_zh / series_title 当依据：它们本身可能
        # 就是错误 TMDB 条目带进来的（例如“假如是爱”）。
        refs = [title, match.title_original]
        for c in (match.douban, match.bangumi, match.imdb):
            if c:
                refs += [c.title, c.original_title]
        for a in (tmdb.title, tmdb.original_title):
            for b in refs:
                if a and b and strong_titles_agree(a, b):
                    return
        old = match.tmdb_id or tmdb.sid
        match.tmdb = None
        match.tmdb_id = ""
        match.notes.append(f"忽略标题不一致的 TMDB 条目：{old}")
        # 用正确的 IMDb 号反查主剧 TMDB ID（What If -> 91363）
        imdb = match.series_imdb_id or match.imdb_id or (
            match.imdb.sid if match.imdb else "")
        finder = getattr(self.metadata, "tmdb_find_by_imdb", None)
        if imdb and callable(finder):
            try:
                found = finder(imdb, "series")
            except Exception:
                found = None
            if found and found.get("id"):
                match.tmdb_id = str(found["id"])

    def _online_series_title(self, match: MatchResult,
                             year: Optional[int] = None,
                             parsed: Optional[ParsedName] = None) -> str:
        """强制使用联网结果里的主剧名，不拿本地文件名兜底。"""
        # 豆瓣/Bangumi 的中文季条目最可靠；TMDB 可能命中同名的另一部剧。
        values = []
        for c in (match.douban, match.bangumi):
            if c and c.title:
                values.append(c.title)
        values += [match.series_title, match.title_zh]
        if match.imdb and match.imdb.title:
            values.append(match.imdb.title)
        if match.tmdb and match.tmdb.title:
            values.append(match.tmdb.title)
        values.append(match.title_original)
        cleaned: list[str] = []
        for raw in values:
            t = strip_season_and_subtitle(str(raw or "")).strip(
                " ._-–—:：·")
            t = strip_season_markers(t).strip(" ._-–—:：·")
            if not t:
                continue
            # “假如 ? What If” -> “假如 ?”，英文名由 _english_title 单独给
            if re.search(r"[㐀-鿿]", t) and re.search(r"[A-Za-z]", t):
                m = re.match(
                    r"^(.+?[㐀-鿿][^A-Za-z]*?)(?:\s+[A-Za-z].*)?$", t)
                if m:
                    t = m.group(1).strip(" ._-–—:：·")
            if year:
                t = _strip_trailing_year(t, year)
            t = strip_season_markers(t).strip(" ._-–—:：·")
            if t and t not in cleaned:
                cleaned.append(t)
        # 本地目录名就是“葬送的芙莉莲”时，不能被 Bangumi 搜索返回的
        # 同名番外“葬送的芙莉莲 ~●●的魔法~”抢走主剧名。优先选和本地
        # 主标题（去掉季号后）完全一致的候选。
        anchor = norm_title(strip_season_markers(
            (parsed.title if parsed else "") or ""))
        if anchor:
            exact = [t for t in cleaned if norm_title(t) == anchor]
            # 目录是英文名、联网主剧名是中文时，仍优先用中文主剧名
            # （英文名由 _english_title 单独补），不要让英文原名把
            # “降世神通：最后的气宗”挤成 Avatar: The Last Airbender。
            cjk_exact = [t for t in exact if re.search(r"[㐀-鿿]", t)]
            if cjk_exact:
                return cjk_exact[0]
            if exact and not any(re.search(r"[㐀-鿿]", t) for t in cleaned):
                return exact[0]
        return cleaned[0] if cleaned else ""

    # ------------------------------------------------------------ 剧集
    def _tmdb_season_counts(self, plan: PlanItem) -> dict[int, int]:
        """取 TMDB 每季集数；没有 Key/没有结果时返回空字典。"""
        tmdb_id = plan.identity.tmdb_id
        if not tmdb_id:
            return {}
        fn = getattr(self.metadata, "tmdb_tv_structure", None)
        if not callable(fn):
            return {}
        try:
            data = fn(tmdb_id) or {}
        except Exception:
            return {}
        out: dict[int, int] = {}
        for item in data.get("seasons") or []:
            if not isinstance(item, dict):
                continue
            try:
                number = int(item.get("season_number"))
                count = int(item.get("episode_count") or 0)
            except Exception:
                continue
            if count > 0:
                out[number] = count
        return out

    @staticmethod
    def _first_tmdb_season(counts: dict[int, int]) -> tuple[Optional[int], int]:
        positive = sorted((s, c) for s, c in counts.items()
                          if s > 0 and c > 0)
        return positive[0] if positive else (None, 0)

    def _tmdb_absolute_hint(self, ep: Optional[int],
                            counts: dict[int, int]) -> bool:
        """没有季标记、但集号超过 TMDB 第一季集数：疑似总集编号。

        只有 TMDB 明确有两季以上时才启用，避免单季番剧被误判。
        """
        if ep is None or not counts:
            return False
        positive = [(s, c) for s, c in counts.items() if s > 0 and c > 0]
        if len(positive) < 2:
            return False
        _, first_count = self._first_tmdb_season(counts)
        return bool(first_count and ep > first_count)

    def season_counts_for_plan(self, plan: PlanItem) -> dict[int, int]:
        """供季集映射界面读取 TMDB 每季集数。"""
        return self._tmdb_season_counts(plan)

    def infer_episode_rows(self, plan: PlanItem,
                           use_overrides: bool = True) -> list[dict]:
        """给出每个视频当前推断的季/集，供人工映射界面显示。"""
        entries = [e for e in (plan.context.get("entries") or [])
                   if e.is_video]
        counts = self._tmdb_season_counts(plan)
        mr: Optional[MediaRoot] = plan.context.get("mr")
        root_name = mr.item.name if mr is not None else ""
        rows: list[dict] = []
        for e in entries:
            forced = (plan.episode_overrides.get(e.item.fid)
                      if use_overrides else None)
            manual = forced is not None
            if forced is not None:
                season, ep = forced
                source = "手动"
            else:
                ep = e.parsed.episode
                if use_overrides and plan.season_override is not None:
                    season = plan.season_override
                    source = "季号覆盖"
                elif e.folder_season is not None:
                    season = e.folder_season
                    source = "目录"
                elif e.parsed.season is not None:
                    season = e.parsed.season
                    source = "文件"
                else:
                    hinted = (season_from_text(plan.match.title_zh) or
                              season_from_text(plan.match.title_original) or
                              season_from_text(root_name))
                    if hinted is not None:
                        season = hinted
                        source = "标题"
                    elif FINAL_RE.search(plan.parsed.title or "") or \
                            FINAL_RE.search(root_name or ""):
                        season = None
                        source = "最终季"
                    elif self._tmdb_absolute_hint(ep, counts):
                        season = None
                        source = "待分季"
                    else:
                        season = 1
                        source = "默认"
            if ep is not None and ep <= 0:
                ep = None
                source = "无效集号"
            elif ep is None and not manual:
                source = "未识别"
            rows.append({
                "fid": e.item.fid,
                "entry": e,
                "name": e.item.name,
                "season": season,
                "episode": ep,
                "episode_end": e.parsed.episode_end,
                "source": source,
                "manual": manual,
            })
        return rows

    def _series_plan(self, client, mr: MediaRoot, entries: list[FileEntry],
                     folder_parsed: ParsedName, rename_root: bool,
                     is_container: bool) -> Optional[PlanItem]:
        parsed = self._search_parsed(mr, entries, folder_parsed,
                                     prefer_file_title=is_container)
        # 目录名没写季号、季号来自文件名时，用它补进搜索季号：
        # 否则同一部剧会退化成“主剧条目”，集数无法按季校验/自动分季。
        if parsed.season is None and parsed.file_season is not None:
            parsed.season = parsed.file_season
        nfo_info = self._nfo_anchor(client, mr, "series", entries)
        self._apply_nfo_hints(parsed, nfo_info)
        if not parsed.title:
            p = PlanItem(item=mr.item, media_type="series", parsed=parsed)
            p.status = "review"
            p.note = "没有识别出剧名，请手动填写。"
            p.selected = False
            self._mark(p, qc.NO_TITLE)
            return p
        # 原目录/文件名里已有的 IMDb/TMDB 号：先用它解析标题和年份
        ex_imdb, ex_tmdb = self._existing_ids(mr, entries, parsed.title)
        nfo_imdb = str(nfo_info.get("imdb_id") or "")
        nfo_tmdb = str(nfo_info.get("tmdb_id") or "")
        nfo_title = str(nfo_info.get("title") or "")
        # NFO 的 ID 比目录名/文件名更可靠，优先用它，并用 NFO 标题校验。
        nfo_match = (self._match_by_ids(
            parsed, "series", nfo_imdb, nfo_tmdb,
            fallback_title=nfo_title)
            if (nfo_imdb or nfo_tmdb) else None)
        if nfo_match and nfo_info.get("nfo_name"):
            nfo_match.notes.append(
                f"使用 NFO（{nfo_info['nfo_name']}）中的标题/ID。")
        ex_imdb = ex_imdb or nfo_imdb
        ex_tmdb = ex_tmdb or nfo_tmdb
        context_text = " ".join([mr.item.name] +
                                list(mr.item.ancestors or []))
        path_anime, path_tv, _ = self._path_category_hints(context_text)
        category_hint = ("tv" if path_tv and not path_anime else
                         "anime" if path_anime and not path_tv else "")
        # 原目录已经写了中文名 + 日文名 + 年份 + ID 时，直接本地组结果，
        # 不再访问 Bangumi/IMDb/TMDB。容器目录（一个目录里多部剧）不走此路径。
        local = self._local_names(mr, folder_parsed, parsed, entries)
        has_id = bool(local["imdb"] or local["tmdb"])
        id_match = None
        if nfo_match is not None:
            match = nfo_match
            id_match = nfo_match
        elif (not is_container and local["zh"] and local["jp"] and
                local["year"] and
                (has_id or not self.options.include_imdb_id)):
            match = MatchResult(
                title_zh=local["zh"], title_original=local["jp"],
                year=local["year"], imdb_id=local["imdb"],
                tmdb_id=local["tmdb"], series_title=local["zh"],
                series_original_title=local["jp"],
                series_year=local["year"],
                series_imdb_id=local["imdb"], country="jp",
                confidence=1.0)
            match.notes.append(
                "原目录已包含中文名/日文名"
                + ("、年份和 ID" if has_id else "和年份")
                + "，未联网获取。")
            if local["imdb"]:
                match.imdb = Candidate(
                    source="imdb", title=local["en"] or local["jp"],
                    original_title=local["en"] or local["jp"],
                    year=local["year"], sid=local["imdb"], kind="tv",
                    extra={"aliases": [a for a in (local["en"], local["jp"])
                                       if a]})
            if local["tmdb"]:
                match.tmdb = Candidate(
                    source="tmdb", title=local["zh"],
                    original_title=local["en"] or local["jp"],
                    year=local["year"], sid=local["tmdb"], kind="tv",
                    extra={"aliases": [a for a in (local["en"], local["jp"])
                                       if a]})
            # 本地组结果也要登记来源条目号，供“按来源命名”使用。
            refs: dict[str, dict] = {}
            if local["imdb"]:
                refs["imdb"] = {"id": local["imdb"],
                                "title": local["en"] or local["jp"],
                                "original_title": local["en"] or local["jp"],
                                "year": local["year"]}
            if local["tmdb"]:
                refs["tmdb"] = {"id": local["tmdb"], "title": local["zh"],
                                "original_title": local["en"] or local["jp"],
                                "year": local["year"]}
            match.source_refs = refs
            id_match = match
        else:
            id_match = self._match_by_ids(parsed, "series", ex_imdb, ex_tmdb)
            match = id_match or self._match(parsed, "series", category_hint)
            if (nfo_imdb or nfo_tmdb) and nfo_match is None:
                match.notes.append(
                    "NFO 中的 IMDb/TMDB 编号未能确认，已继续按标题搜索。")
        category = self._detect_category("series", match, parsed, context_text)

        year = (match.series_year or match.year or parsed.year)
        title = self._online_series_title(match, year, parsed=parsed)
        if not title:
            p = PlanItem(item=mr.item, media_type="series", parsed=parsed,
                         match=match)
            p.status = "review"
            p.selected = False
            p.note = ("没有联网获取到剧集标题，已跳过改名；"
                      "请检查网络或使用手动搜索。")
            self._mark(p, qc.NO_ONLINE_TITLE)
            return p
        title = strip_season_markers(_strip_trailing_year(title, year))
        self._repair_tmdb(match, title)
        # 季条目的 imdb_id 可能是“某一季”的条目，海报墙需要的是主剧 ID；
        # 强制优先使用联网匹配到的主剧 ID。只有联网结果没有 ID 时，
        # 才使用通过标题校验的旧 ID，避免残留 ID 把整部剧改错。
        imdb_id = match.series_imdb_id or (
            ex_imdb if id_match else "")
        tmdb_id = match.tmdb_id or (ex_tmdb if id_match else "")
        confidence = match.confidence

        final_rename = rename_root and not is_container
        display_item = mr.item if final_rename else entries[0].item
        p = PlanItem(item=display_item, media_type="series", parsed=parsed,
                     match=match, title=title, year=year,
                     confidence=confidence, category=category,
                     rename_root=final_rename,
                     series_imdb_id=imdb_id)
        p.context = {"mr": mr, "entries": entries,
                     "folder_parsed": folder_parsed,
                     "imdb_id": imdb_id, "tmdb_id": tmdb_id}

        notes: list[str] = list(match.notes)
        if year is None:
            notes.append("缺少首播年份，目录名会省略年份。")
        conflict_note = self._season_conflict_note(
            parsed, match, id_anchored=bool(id_match or nfo_match))
        if conflict_note:
            notes.append(conflict_note)
        if match.trace:
            notes.append(match.trace)
        if conflict_note or \
                match.confidence < self.options.min_auto_confidence:
            p.status = "review"
        else:
            p.status = "auto"
        p.note = "；".join(dict.fromkeys(notes))
        if conflict_note:
            self._mark(p, qc.SEASON_TITLE_CONFLICT)
        if match.confidence < self.options.min_auto_confidence:
            self._mark(p, qc.LOW_CONFIDENCE)

        self.rebuild(p)
        return p

    # ------------------------------------------------------------ 电影
    def _movie_plan(self, client, mr: MediaRoot, entries: list[FileEntry],
                    folder_parsed: ParsedName,
                    rename_root: bool) -> Optional[PlanItem]:
        videos = [e for e in entries if e.is_video]
        if not videos:
            return None
        parsed = self._search_parsed(mr, videos, folder_parsed,
                                     prefer_file_title=not rename_root)
        nfo_info = self._nfo_anchor(client, mr, "movie", videos,
                                    allow_generic=rename_root)
        self._apply_nfo_hints(parsed, nfo_info)
        if not parsed.title:
            p = PlanItem(item=mr.item, media_type="movie", parsed=parsed)
            p.status = "review"
            p.note = "没有识别出电影名，请手动填写。"
            p.selected = False
            self._mark(p, qc.NO_TITLE)
            return p
        # ID 只用于查元数据；后面的 _movie_ops 仍按电影规则生成改名操作
        ex_imdb, ex_tmdb = self._existing_ids(mr, videos, parsed.title)
        nfo_imdb = str(nfo_info.get("imdb_id") or "")
        nfo_tmdb = str(nfo_info.get("tmdb_id") or "")
        nfo_title = str(nfo_info.get("title") or "")
        nfo_match = (self._match_by_ids(
            parsed, "movie", nfo_imdb, nfo_tmdb,
            fallback_title=nfo_title)
            if (nfo_imdb or nfo_tmdb) else None)
        if nfo_match:
            match = nfo_match
            if nfo_info.get("nfo_name"):
                match.notes.append(
                    f"使用 NFO（{nfo_info['nfo_name']}）中的标题/ID。")
            ex_imdb = nfo_imdb or ex_imdb
            ex_tmdb = nfo_tmdb or ex_tmdb
        else:
            match = (self._match_by_ids(parsed, "movie", ex_imdb, ex_tmdb)
                     or self._match(parsed, "movie"))
            if nfo_imdb or nfo_tmdb:
                match.notes.append(
                    "NFO 中的 IMDb/TMDB 编号未能确认，已继续按标题搜索。")
        title = (match.title_zh or match.title_original or
                 strip_season_markers(parsed.title) or parsed.title)
        title = _strip_trailing_year(title, match.year or parsed.year)
        year = match.year or parsed.year
        imdb_id = ex_imdb or match.imdb_id
        tmdb_id = ex_tmdb or match.tmdb_id
        p = PlanItem(item=mr.item if rename_root else videos[0].item,
                     media_type="movie", parsed=parsed,
                     match=match, title=title, year=year,
                     confidence=match.confidence, category="movie",
                     rename_root=rename_root,
                     series_imdb_id=imdb_id)
        p.context = {"mr": mr, "entries": videos,
                     "folder_parsed": folder_parsed,
                     "imdb_id": imdb_id, "tmdb_id": tmdb_id}
        notes = list(match.notes)
        if year is None:
            notes.append("缺少年份，文件名会省略年份。")
        if match.trace:
            notes.append(match.trace)
        p.status = "auto" if match.confidence >= self.options.min_auto_confidence else "review"
        p.note = "；".join(dict.fromkeys(notes))
        if match.confidence < self.options.min_auto_confidence:
            self._mark(p, qc.LOW_CONFIDENCE)
        self.rebuild(p)
        return p

    # ------------------------------------------------------------ 生成重命名操作
    def rebuild(self, plan: PlanItem) -> PlanItem:
        mr: MediaRoot = plan.context.get("mr")
        if not mr:
            return plan
        # 选了“命名来源”时，标题/年份以该来源条目为准（多次重建也幂等）。
        self._apply_naming_source(plan)
        videos = [e for e in plan.context.get("entries", []) if e.is_video]
        sidecars = [e for e in mr.sidecars]
        title = sanitize_name(plan.identity.title or plan.parsed.title, 220)
        year = plan.identity.year
        if plan.media_type == "series":
            plan.ops, extra_notes = \
                self._series_ops(plan, mr, videos, sidecars, title, year)
        else:
            plan.ops, extra_notes = self._movie_ops(plan, mr, videos,
                                                    sidecars, title, year)
        if extra_notes:
            plan.note = "；".join(dict.fromkeys(
                [n for n in (plan.note.split("；") if plan.note else []) if n] +
                extra_notes))
        plan.selected = bool(plan.ops) and plan.status == "auto"
        if not plan.ops and plan.status not in ("error", "skip"):
            plan.status = "skip"
            if "无需修改" not in plan.note:
                plan.note = (plan.note + "；" if plan.note else "") + "文件名已符合规则，无需修改。"
            plan.selected = False
        return plan

    def _bd_tag(self, plan: PlanItem) -> str:
        """“你的风格”统一使用 [BD-REMUX]。

        原目录里的 [BDMV]/[BDISO]/[BDRip] 只是来源说明，不搬到新文件夹
        开头；否则同一个剧集会一会儿 [BD-REMUX]、一会儿 [BDMV]。
        """
        return "[BD-REMUX]"

    def _find_title_end(self, stem: str) -> int:
        """找到电影名里中文/日文标题的结束位置（用于插入 ID）。"""
        for m in re.finditer(r"[\[【（(]([^\]】）)]*)[\]】）)]", stem):
            content = m.group(1).strip()
            if not re.search(r"[㐀-鿿぀-ヿ]", content):
                continue
            if self._looks_like_release_tag(content):
                continue
            if re.fullmatch(r"(?:19|20)\d{2}", content):
                continue
            return m.end()
        for m in re.finditer(r"[㐀-鿿぀-ヿ]+", stem):
            content = m.group(0)
            if self._looks_like_release_tag(content):
                continue
            return m.end()
        return -1

    def _insert_id_after_title(self, name: str, suffix: str,
                               is_dir: bool) -> str:
        """把 IMDb/TMDB 标识插到中文名后面，其他规格保持不变。

        原名称里已有的标识会先删掉（不管在哪个位置），再按你的规则
        放到中文名/带括号的中文名后面。
        """
        suffix = (suffix or "").strip()
        if not suffix:
            return ""
        stem, ext = (name, "") if is_dir else os.path.splitext(name)
        cleaned = RE_PROVIDER_ID.sub(" ", stem)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\.\s*\.", ".", cleaned)
        cleaned = re.sub(r"\.{2,}", ".", cleaned)
        cleaned = cleaned.strip(" ._-")
        pos = self._find_title_end(cleaned)
        if pos < 0:
            return ""
        if cleaned[pos:pos + len(suffix)].casefold() == suffix.casefold():
            new_stem = cleaned
        else:
            new_stem = cleaned[:pos] + suffix + cleaned[pos:]
        return new_stem + ext

    def _movie_id_suffix(self, imdb_id: str, tmdb_id: str) -> str:
        """电影的 ID 后缀：默认优先 IMDb；设置明确选 tmdb 时才用 TMDB。"""
        if not self.options.include_imdb_id:
            return ""
        style = self.options.imdb_id_style
        if self.options.id_provider == "tmdb" and tmdb_id:
            return _provider_suffix("", tmdb_id, style, "tmdb")
        suffix = _provider_suffix(imdb_id, "", style, "imdb")
        if not suffix and tmdb_id:
            suffix = _provider_suffix("", tmdb_id, style, "auto")
        return suffix

    def _local_second_title(self, plan: PlanItem,
                            local: dict) -> str:
        """原目录/文件名里的第二语言名：日文 → 日文汉字 → 英文/罗马音。"""
        if not local:
            return ""
        for key in ("jp", "jp_kanji", "en"):
            c = sanitize_name(local.get(key, ""), 120)
            if c and norm_title(c) != norm_title(plan.title):
                return c
        return ""

    def _online_japanese_title(self, plan: PlanItem) -> str:
        """联网结果里的日文原名（假名或汉字）。"""
        candidates: list[str] = []
        if plan.title_override and has_kana(plan.title_override):
            candidates.append(plan.title_override)
        if plan.match.bangumi and plan.match.bangumi.original_title:
            candidates.append(plan.match.bangumi.original_title)
        if plan.match.title_original:
            candidates.append(plan.match.title_original)
        for c in candidates:
            c = sanitize_name(c, 120)
            if not c or norm_title(c) == norm_title(plan.title):
                continue
            # 日文假名，或汉字/汉字+拉丁的日文原名
            if has_kana(c) or re.search(r"[㐀-鿿]", c):
                return c
        return ""

    def _online_romaji_title(self, plan: PlanItem) -> str:
        """联网结果里的拉丁标题，优先像罗马音的那一条。"""
        names: list[str] = []

        def add(v):
            v = sanitize_name(v, 120)
            if v and v not in names:
                names.append(v)

        if plan.match.bangumi and isinstance(plan.match.bangumi.extra, dict):
            for a in plan.match.bangumi.extra.get("aliases") or []:
                add(a)
        for cand in (plan.match.imdb, plan.match.tmdb):
            if not cand:
                continue
            for t in (cand.original_title, cand.title):
                if t:
                    add(t)
        if plan.match.title_original:
            add(plan.match.title_original)

        cleaned: list[str] = []
        for c in names:
            if not c or norm_title(c) == norm_title(plan.title):
                continue
            if self._looks_like_release_tag(c):
                continue
            if re.search(r"[A-Za-z]{2,}", c) and not has_kana(c) and \
                    not re.search(r"[㐀-鿿]", c):
                cleaned.append(c)
        for c in cleaned:
            if RE_ROMAJI_HINT.search(c):
                return c
        return cleaned[0] if cleaned else ""

    def _jp_title(self, plan: PlanItem) -> str:
        """取目录第二段名称：本地日/英文 → Bangumi 日文 → IMDb/TMDB 英文。"""
        local = {}
        mr = plan.context.get("mr")
        if mr and not plan.context.get("manual_match"):
            local = self._local_names(
                mr, plan.context.get("folder_parsed"), plan.parsed,
                plan.context.get("entries") or [])
        return (self._local_second_title(plan, local) or
                self._online_japanese_title(plan) or
                self._online_romaji_title(plan))

    def _episode_subtitle(self, e: FileEntry) -> str:
        """从原始文件名里取 SxxExx 后面的单集副标题。"""
        raw = e.item.stem
        m = re.search(
            r"(?i)(?:S\d{1,2}E\d{1,4}|E(?:P)?\d{1,4})"
            r"(?:-E?\d{1,4})?(?:v\d+)?[.\s_-]+(.+)$", raw)
        if not m:
            return ""
        tokens = re.split(r"[.\s_]+", m.group(1))
        out: list[str] = []
        for tok in tokens:
            tok = tok.strip("[](){}")
            if not tok:
                continue
            # SxxExx 后面紧跟的 2024 是发行年份，不是单集副标题。
            # 例如 Parasyte.The.Grey.S01E06.2024.2160p... 不能变成
            # “S01E06.2024 [2160p …]”。
            if re.fullmatch(r"(?:19|20)\d{2}", tok):
                break
            if RE_SPEC_TOKEN.match(tok):
                break
            if re.fullmatch(r"(?i)(?:repack|proper|rerip|dual|multi|v\d+)",
                            tok):
                break
            if "-" in tok:
                base, _, suffix = tok.rpartition("-")
                if base and suffix and suffix.isupper() and len(suffix) >= 2:
                    tok = base
            out.append(tok)
            if len(out) >= 24:
                break
        if out and out[-1].isupper() and len(out[-1]) <= 12 and \
                not re.search(r"[㐀-鿿぀-ヿ()[\]{}（）【】]", out[-1]):
            out.pop()
        if out and len(out) <= 2 and all(t.isupper() for t in out):
            return ""
        return " ".join(out).strip(" -._")[:120]

    def _name_segment(self, plan: PlanItem) -> str:
        """“来源名”那一段：按设置里选的来源取。

        - 所选来源**有**名字时一定用它（不会偷偷换成别的来源）；
        - 所选来源**没有**名字（例如只拿到裸 ID、或该源条目缺失）时，
          回退到原有的英文名推断（IMDb/TMDB/本地），保持旧行为；
        - 选“不显示”则整段省略。
        """
        source = str(getattr(self.options, "name_segment_source", "imdb")
                     or "imdb").lower()
        if source == "none":
            return ""
        if source == "local":
            return self._english_title(plan)
        cand = {
            "imdb": plan.match.imdb,
            "tmdb": plan.match.tmdb,
            "douban": plan.match.douban,
            "bangumi": plan.match.bangumi,
        }.get(source)
        ref = plan.match.ref(source)
        names: list[str] = []
        if cand is not None:
            names += [cand.original_title, cand.title]
            if isinstance(cand.extra, dict):
                names += list(cand.extra.get("aliases") or [])
        if not names and ref:
            names += [ref.get("original_title"), ref.get("title")]
        for raw in names:
            c = sanitize_name(str(raw or ""), 120)
            if not c or norm_title(c) == norm_title(plan.title):
                continue
            if self._looks_like_release_tag(c):
                continue
            return c
        # 该来源没有可用名字：回退到原有推断，避免“整段凭空消失”
        return self._english_title(plan)

    def _english_title(self, plan: PlanItem) -> str:
        """取英文名（用于 中文名.英文名.SxxExx 这种文件命名）。"""
        names: list[str] = []
        for cand in (plan.match.imdb, plan.match.tmdb):
            if not cand:
                continue
            for t in (cand.original_title, cand.title):
                if t:
                    names.append(t)
        if plan.match.title_original:
            names.append(plan.match.title_original)
        mr = plan.context.get("mr")
        # 非日番剧集强制使用联网英文名，避免把发布组/文件名残片
        # （如 If KKYY@CHDBits）当成英文名。日番仍允许本地日/英文名。
        if mr and not plan.context.get("manual_match") and \
                plan.category == "jp_anime":
            local = self._local_names(
                mr, plan.context.get("folder_parsed"), plan.parsed,
                plan.context.get("entries") or [])
            if local.get("en"):
                names.append(local["en"])
        for c in names:
            c = sanitize_name(c, 120)
            if not c or norm_title(c) == norm_title(plan.title):
                continue
            if self._looks_like_release_tag(c):
                continue
            if re.search(r"[A-Za-z]{2,}", c) and not has_kana(c) and \
                    not re.search(r"[㐀-鿿]", c):
                return c
        online = self._online_english_title(plan)
        if online:
            c = sanitize_name(online, 120)
            if c and re.search(r"[A-Za-z]{2,}", c) and not has_kana(c) and \
                    not re.search(r"[㐀-鿿]", c):
                return c
        return ""

    def _online_english_title(self, plan: PlanItem) -> str:
        """中国电视剧/国产动画补充英文名。

        TMDB 中文条目的 name/original_name 常常还是中文（如“庆余年”），
        需要再用英文接口或 IMDb 号取 “Joy of Life”。
        """
        meta = self.metadata
        if not meta:
            return ""
        kind = "tv" if plan.media_type == "series" else "movie"
        get_en = getattr(meta, "tmdb_english_title", None)
        ident = plan.identity
        if callable(get_en) and ident.tmdb_id:
            en = get_en(ident.tmdb_id, kind)
            if en:
                return en
        get_by_imdb = getattr(meta, "tmdb_english_by_imdb", None)
        if callable(get_by_imdb) and ident.imdb_id:
            en = get_by_imdb(ident.imdb_id, plan.media_type)
            if en:
                return en
        return ""

    def _video_title(self, plan: PlanItem) -> str:
        """日番视频文件名的标题：日文原名优先；没有日文时用罗马音/英文名。

        注意这里和文件夹第二段不同：视频名要尽量用日文，所以先看本地
        日文假名，再看联网日文，最后才用本地/联网的罗马音。
        """
        local = {}
        mr = plan.context.get("mr")
        if mr and not plan.context.get("manual_match"):
            local = self._local_names(
                mr, plan.context.get("folder_parsed"), plan.parsed,
                plan.context.get("entries") or [])
        override = (plan.title_override or "").strip()
        if override and has_kana(override):
            return override
        main = plan.display_title or ""
        if has_kana(main):
            return main

        # 1) 原目录里的日文假名
        c = sanitize_name(local.get("jp", ""), 120)
        if c and norm_title(c) != norm_title(plan.title):
            return c
        # 2) 联网结果里的日文原名
        jp = self._online_japanese_title(plan)
        if jp:
            return jp
        # 3) 原目录里的日文汉字别名
        c = sanitize_name(local.get("jp_kanji", ""), 120)
        if c and norm_title(c) != norm_title(plan.title):
            return c
        # 4) 原目录里的英文/罗马音
        c = sanitize_name(local.get("en", ""), 120)
        if c and norm_title(c) != norm_title(plan.title):
            return c
        # 5) 联网结果里的罗马音/英文
        romaji = self._online_romaji_title(plan)
        if romaji:
            return romaji
        return main or plan.title

    def _folder_season_marker(self, plan: PlanItem) -> str:
        """季目录根任务在剧名后加 S01/S02，中文名也能一眼分清。"""
        if plan.media_type != "series" or len(plan.seasons) != 1:
            return ""
        season = plan.seasons[0]
        if season is None:
            return ""
        mr: MediaRoot = plan.context.get("mr")
        if mr is None:
            return ""
        # 原目录带季标记，或它是从合集目录里发现的独立季目录时加 Sxx：
        # 整部剧根目录（含多个季子目录）保持“剧名 (年份) [ID]”。
        if season_from_text(mr.item.name) is None and \
                not mr.is_season_root:
            return ""
        if re.search(rf"(?i)(?:^|[\s._-])S0?{season}(?!\d)",
                     plan.display_title or ""):
            return ""
        return f" S{season:02d}"

    @staticmethod
    def _existing_folder_version(name: str) -> int:
        m = RE_FOLDER_VERSION.search(name or "")
        if not m:
            return 0
        try:
            return max(0, int(m.group(1)))
        except ValueError:
            return 0

    def _folder_version_tag(self, plan: PlanItem) -> str:
        number = plan.folder_version
        if number <= 1:
            number = self._existing_folder_version(plan.item.name)
        return f"V{number}" if number > 1 else ""

    def _versioned_folder_name(self, name: str, plan: PlanItem) -> str:
        """把 V2/V3 放到 ID 之前；没有 ID 时放在末尾。"""
        tag = self._folder_version_tag(plan)
        if not tag:
            return name
        existing = RE_FOLDER_VERSION.search(name or "")
        if existing:
            name = (name[:existing.start()] + name[existing.end():]).strip()
            name = re.sub(r"\s{2,}", " ", name)
        m = RE_PROVIDER_ID.search(name or "")
        if m:
            before = name[:m.start()].rstrip()
            after = name[m.start():].lstrip()
            return f"{before} {tag} {after}".strip()
        return f"{name} {tag}".strip()

    def _folder_name(self, plan: PlanItem, title: str,
                     year: Optional[int], imdb_id: str,
                     tmdb_id: str = "") -> str:
        style = self.options.jp_folder_style
        is_jp_series = (plan.media_type == "series" and
                        plan.category == "jp_anime")
        season_part = self._folder_season_marker(plan)
        version_tag = self._folder_version_tag(plan)
        if is_jp_series and style in ("bdremux", "bdremux_suffix",
                                      "bdremux_no_year"):
            jp = self._jp_title(plan)
            body = f"{title} {jp}".strip() if jp else title
            body = (body + season_part).strip()
            id_part = ""
            if self.options.include_imdb_id:
                id_part = _provider_suffix(
                    imdb_id, tmdb_id, self.options.imdb_id_style,
                    self.options.id_provider)
            year_part = ""
            if year and style != "bdremux_no_year":
                year_part = f" ({year})"
            tag = self._bd_tag(plan)
            prefix = tag if style in ("bdremux", "bdremux_no_year") else ""
            suffix = year_part
            if version_tag:
                suffix += f" {version_tag}"
            suffix += id_part
            if style == "bdremux_suffix":
                suffix += f" {tag}"
            room = 240 - len(prefix.encode("utf-8")) - \
                len(suffix.encode("utf-8"))
            body = sanitize_name(body, max(20, room))
            return sanitize_name(prefix + body + suffix, 255)

        # 原目录是“中文名 + 英文名”的，保留英文名，三季统一：
        # 假如...? What If...? S01 (2021) [tmdbid-...]
        # 文件夹固定顺序：中文名 英文名 Sxx (年份) [ID]
        # 日番选了“不使用”（style == "none"）时，也按普通剧集规则处理，
        # 包括保留英文名。
        jp_rule_off = style == "none"
        english_part = ""
        if plan.media_type == "series" and (not is_jp_series or jp_rule_off):
            en = self._english_title(plan)
            # “What If...?”这类风格标题，文件夹里保留 What If 即可；
            # 英文名里的冒号统一换成空格，避免出现“Avatar： The...”
            en = re.sub(r"(?:\.{2,}|…)\s*[?？]\s*$", "", en or "").strip()
            en = re.sub(r"[:：]", " ", en)
            en = re.sub(r"\s+", " ", en).strip()
            if en and norm_title(en) != norm_title(title):
                english_part = f" {en}"
        base = title + english_part + season_part
        if year:
            base += f" ({year})"
        version_part = f" {version_tag}" if version_tag else ""
        suffix = ""
        if self.options.include_imdb_id:
            suffix = _provider_suffix(imdb_id, tmdb_id,
                                      self.options.imdb_id_style,
                                      self.options.id_provider)
        # 先给版本号 + ID 后缀留出空间，避免长标题把它们截断
        reserved = len(version_part.encode("utf-8")) + \
            len(suffix.encode("utf-8"))
        base = sanitize_name(base, 240 - reserved)
        return sanitize_name(base + version_part + suffix, 255)

    def naming_ref(self, plan: PlanItem) -> tuple[str, str]:
        """命名来源及其条目号：("douban"/"bangumi"/"imdb"/"tmdb", sid)。

        返回 ("", "") 表示按自动匹配结果命名（维持原有行为）。
        """
        source = str(getattr(plan, "name_source", "") or "")
        if source in EPISODE_NAME_SOURCES:
            ref = plan.match.ref(source)
            sid = str(ref.get("id") or "") if ref else ""
            if not sid:
                sid = self._fallback_source_id(plan, source)
            if sid:
                return source, sid
        return "", ""

    @staticmethod
    def _fallback_source_id(plan: PlanItem, source: str) -> str:
        m = plan.match
        ident = plan.identity
        if source == "douban":
            return str((m.douban.sid if m.douban else "") or m.douban_id or "")
        if source == "bangumi":
            return str((m.bangumi.sid if m.bangumi else "") or m.bangumi_id or "")
        if source == "imdb":
            return str((m.imdb.sid if m.imdb else "") or ident.imdb_id or "")
        if source == "tmdb":
            return str((m.tmdb.sid if m.tmdb else "") or ident.tmdb_id or "")
        return ""

    def _source_episode_titles(self, plan: PlanItem, season: int,
                               source: str, sid: str) -> dict[int, str]:
        """按命名来源取单集标题；来源没有分集数据时返回空（不混用别的来源）。"""
        if not source or not sid:
            return {}
        fn = getattr(self.metadata, "source_episode_titles", None)
        if not callable(fn):
            # 兼容旧测试桩：只有 TMDB 接口时，仅 TMDB 来源可用
            if source == "tmdb":
                fn = getattr(self.metadata, "season_episode_titles", None)
            if not callable(fn):
                return {}
        try:
            data = fn(source, sid, int(season)) or {}
        except Exception as exc:
            self.log(f"{source} 单集标题获取失败（{sid} S{season}）：{exc}")
            return {}
        return {int(k): str(v) for k, v in data.items()
                if str(v or "").strip()}

    def _apply_naming_source(self, plan: PlanItem) -> None:
        """把命名来源的标题/年份换成该来源自己的，并记录备注。

        只换“命名依据”；分类（日番/电视剧/美漫…）仍由自动判断或人工选择
        决定，避免换个来源就改变命名格式。
        """
        source, sid = self.naming_ref(plan)
        if not source:
            return
        ref = plan.match.ref(source)
        title = str(ref.get("title") or "").strip()
        if title:
            plan.title = sanitize_name(strip_season_markers(title), 220)
        year = ref.get("year")
        if isinstance(year, int) and year > 0:
            plan.year = year
        label = {"douban": "豆瓣", "bangumi": "Bangumi",
                 "imdb": "IMDb", "tmdb": "TMDB"}.get(source, source)
        self._append_note(
            plan, f"命名来源：{label}（条目 {sid}）；"
                  "标题、单集副标题与特别篇顺序按该来源。")

    @staticmethod
    def _special_texts(plan: PlanItem, entry: FileEntry) -> list[str]:
        """用于匹配 TMDB 特别篇标题的本地标题/别名。"""
        show_keys = {
            norm_title(x) for x in (
                plan.identity.title, plan.title, plan.match.title_zh,
                plan.match.title_original, plan.parsed.title)
            if norm_title(x)
        }
        out: list[str] = []
        for value in [entry.parsed.title] + list(entry.parsed.queries or []):
            text = str(value or "").strip()
            if not text or _is_meaningless_title(text):
                continue
            key = norm_title(text)
            if not key or key in show_keys or key in ("oad", "ova", "sp"):
                continue
            if text not in out:
                out.append(text)
        return out

    def _clean_special_subtitle(self, plan: PlanItem, subtitle: str) -> str:
        """去掉特别篇标题里重复的剧名：南家三姐妹 甜品别腹 → 甜品别腹。"""
        text = str(subtitle or "").strip()
        if not text:
            return ""
        for name in (plan.identity.title, plan.title,
                     plan.match.title_zh, plan.match.title_original):
            name = str(name or "").strip()
            if not name:
                continue
            m = re.match(rf"^\s*{re.escape(name)}\s*[:：.\-_ ]*", text,
                         re.I)
            if m and len(m.group(0)) < len(text):
                cleaned = text[m.end():].strip()
                if cleaned:
                    return cleaned
        return text

    def _assign_specials_episodes(self, plan: PlanItem,
                                  videos: list[FileEntry],
                                  notes: list[str]) -> None:
        """把第 0 集和特别篇文件补成 S00E01…

        覆盖三种来源：
        - OAD/SP/特别篇目录里没有集数的文件；
        - 任意目录里明确写了 SxxE00 的文件；
        - 任意目录里带 [Special]/OVA/OAD/特别篇 等标记、但没有集数的文件。

        优先用 TMDB 第 0 季单集标题做模糊匹配；匹配不到的文件才按
        文件名顺序补号，并把任务降为“需确认”。
        """
        if not videos:
            return
        zero: list[FileEntry] = []
        pending: list[FileEntry] = []
        for e in videos:
            name = e.item.stem or ""
            if RE_EXTRA_FILE.search(name):
                continue
            marked = bool(RE_SPECIAL_FILE.search(name))
            if e.parsed.episode == 0:
                zero.append(e)
            elif marked and not RE_EPISODE_MARKER.search(name):
                # [Special]/[OVA] 里的 [1080] 会被解析器误当成第 1080 集，
                # 只要没有真正的 SxxExx/EP/第N集标记，就按特别篇处理。
                pending.append(e)
            elif e.parsed.episode is None and (e.folder_season == 0 or marked):
                pending.append(e)
        if not zero and not pending:
            return

        explicit = {
            int(e.parsed.episode) for e in videos
            if e.folder_season == 0 and e.parsed.episode
            and int(e.parsed.episode) > 0
        }
        for season, ep in (plan.episode_overrides or {}).values():
            if int(season) == 0 and int(ep) > 0:
                explicit.add(int(ep))
        titles: dict[int, str] = {}
        name_source, name_sid = self.naming_ref(plan)
        if name_source:
            # 按所选来源取特别篇列表；该来源没有特别篇数据时留空，
            # 不借用 TMDB 的第 0 季顺序（两边对特别篇的认定常不一致）。
            titles = self._source_episode_titles(
                plan, 0, name_source, name_sid)
        else:
            tmdb_id = plan.identity.tmdb_id
            fetch = getattr(self.metadata, "season_episode_titles", None)
            if tmdb_id and callable(fetch):
                try:
                    raw = fetch(tmdb_id, 0) or {}
                    titles = {int(ep): str(name).strip()
                              for ep, name in raw.items()
                              if str(name).strip() and int(ep) > 0}
                except Exception as exc:
                    self.log(f"TMDB 特别篇标题获取失败：{exc}")

        def apply(e: FileEntry, ep: int) -> None:
            e.folder_season = 0
            e.parsed.season = 0
            e.parsed.episode = ep
            e.parsed.is_episode = True

        used_eps = set(explicit)
        zero_ep = 0
        if zero:
            # “第0话/第0集/Episode 0”是最强的对应关系；没有时用第一个
            # 特别篇。E00 可能是同一集的不同版本，因此统一用同一个集号，
            # 交给后面的多版本检测加 v2。
            zero_ep = next(
                (ep for ep, title in sorted(titles.items())
                 if RE_ZERO_EPISODE_TITLE.search(title)), 0)
            if not zero_ep and titles:
                zero_ep = min(titles)
                notes.append(
                    "SxxE00 没有找到“第0话”标题，暂按第一个特别篇映射，"
                    "请核对。")
                if plan.status == "auto":
                    plan.status = "review"
                self._mark(plan, qc.SPECIAL_ZERO_GUESSED)
            if not zero_ep:
                zero_ep = 1
                notes.append(
                    "SxxE00 没有 TMDB 特别篇信息，暂映射为 S00E01，"
                    "请用“季集映射…”核对。")
                if plan.status == "auto":
                    plan.status = "review"
                self._mark(plan, qc.SPECIAL_ZERO_GUESSED)
            for e in zero:
                e.special_zero = True
                apply(e, zero_ep)
            used_eps.add(zero_ep)
            notes.append(
                f"检测到第 0 集文件 {len(zero)} 个，已映射为 "
                f"S00E{zero_ep:02d}。")

        texts = {e.item.fid: self._special_texts(plan, e) for e in pending}
        pairs: list[tuple[float, FileEntry, int]] = []
        for e in pending:
            for ep, title in titles.items():
                nt = norm_title(title)
                if not nt:
                    continue
                score = max((fuzz.WRatio(norm_title(q), nt) / 100.0
                             for q in texts.get(e.item.fid, [])),
                            default=0.0)
                if score >= 0.74:
                    pairs.append((score, e, ep))
        pairs.sort(key=lambda x: (-x[0], _natural_key(x[1].item.name), x[2]))
        matched_fids: set[str] = set()
        for _score, e, ep in pairs:
            if e.item.fid in matched_fids or ep in used_eps:
                continue
            apply(e, ep)
            used_eps.add(ep)
            matched_fids.add(e.item.fid)
        rest = [e for e in pending if e.item.fid not in matched_fids]
        rest.sort(key=lambda e: _natural_key(e.item.name))
        forced_ep = 0
        unused_online = sorted(set(titles) - used_eps)
        if len(rest) == 1 and len(unused_online) == 1:
            # 只剩一个文件、TMDB 也只剩一个未用集号：编号是唯一的，
            # 不需要因为“标题没匹配上”把整个任务降为需确认。
            forced_ep = unused_online[0]
            e = rest.pop(0)
            apply(e, forced_ep)
            used_eps.add(forced_ep)
        next_ep = 1
        for e in rest:
            while next_ep in used_eps:
                next_ep += 1
            apply(e, next_ep)
            used_eps.add(next_ep)
            next_ep += 1
        if matched_fids:
            notes.append(
                f"特别篇文件：已按 TMDB 特别篇标题匹配 "
                f"{len(matched_fids)} 个文件为 S00Exx。")
        if forced_ep:
            notes.append(
                f"特别篇有 1 个文件未匹配到标题，已补入唯一剩余的 "
                f"S00E{forced_ep:02d}。")
        if rest:
            notes.append(
                f"特别篇有 {len(rest)} 个文件没有匹配到标题，"
                "已按文件名顺序补为 S00Exx，请用“季集映射…”核对。")
            if plan.status == "auto":
                plan.status = "review"
            self._mark(plan, qc.SPECIAL_UNMATCHED)

    def _series_ops(self, plan: PlanItem, mr: MediaRoot,
                    videos: list[FileEntry], sidecars: list[FileEntry],
                    title: str, year: Optional[int]):
        ops: list[RenameOp] = []
        notes: list[str] = []
        category = plan.category if plan.category != "auto" else \
            self._detect_category(
                "series", plan.match, plan.parsed,
                " ".join([mr.item.name] + list(mr.item.ancestors or [])))
        plan.category = category
        # 以前规格是否写入由分类决定；现在改成显式开关（默认开），
        # 日番本来就从简，保持不写。
        want_specs = category in SPEC_CATEGORIES and bool(
            getattr(self.options, "include_specs", True))
        # 日番视频名用日文；没有日文时用罗马音/英文名，最后才中文。
        # 日番选了“不使用”时，文件名也按普通规则（用中文标题）。
        jp_rule_off = str(getattr(self.options, "jp_folder_style", "")) == "none"
        video_title = title
        if category == "jp_anime" and not jp_rule_off:
            video_title = sanitize_name(
                self._video_title(plan) or title, 220)

        # TMDB 季集结构：用于发现“总集编号”和季集数不一致。
        season_counts = self._tmdb_season_counts(plan)
        first_season_num, first_season_count = \
            self._first_tmdb_season(season_counts)
        absolute_hint = False
        unknown_season = False

        # OAD/SP/特别篇目录通常没有 SxxExx；先补成 S00E01…
        self._assign_specials_episodes(plan, videos, notes)

        # 解析每一集的季/集
        resolved: list[tuple[FileEntry, Optional[int], Optional[int], Optional[int], bool]] = []
        for e in videos:
            forced = plan.episode_overrides.get(e.item.fid)
            if forced is not None:
                season, ep = forced
                confirmed = True
            else:
                folder_season = e.folder_season
                file_season = e.parsed.season
                if plan.season_override is not None:
                    season = plan.season_override
                    confirmed = True
                elif folder_season is not None:
                    season = folder_season
                    confirmed = True
                    if file_season is not None and \
                            file_season != folder_season:
                        notes.append(f"{e.item.name} 的季号和目录不一致（目录 S{folder_season:02d}，文件 S{file_season:02d}），按目录处理。")
                elif file_season is not None:
                    season = file_season
                    confirmed = True
                else:
                    hinted = (season_from_text(plan.match.title_zh) or
                              season_from_text(plan.match.title_original) or
                              season_from_text(mr.item.name))
                    if hinted is not None:
                        season = hinted
                        confirmed = True
                    elif FINAL_RE.search(plan.parsed.title or "") or \
                            FINAL_RE.search(mr.item.name or ""):
                        season = None
                        confirmed = False
                        unknown_season = True
                    elif self._tmdb_absolute_hint(e.parsed.episode,
                                                  season_counts):
                        # 文件只有 E13、E14…，TMDB S01 只有 12 集：
                        # 不能直接写成 S01E13，先暂停集数改名。
                        season = None
                        confirmed = False
                        absolute_hint = True
                    else:
                        season = 1
                        confirmed = True
                ep = e.parsed.episode
            if ep is not None and ep <= 0:
                notes.append(f"{e.item.name} 的集号是 0，可能是菜单/花絮，已跳过。")
                ep = None
            elif ep is None:
                notes.append(f"{e.item.name} 没有识别到集数，已跳过。")
            if season is None:
                plan.season_confirmed = False
            resolved.append((e, season, ep, e.parsed.episode_end, confirmed))
        plan.episodes = sorted({ep for _, _, ep, _, _ in resolved if ep is not None})
        plan.seasons = sorted({s for _, s, _, _, _ in resolved if s is not None})
        plan.specs = ""

        if unknown_season:
            notes.append("标题含“最终季/Part”等信息，无法自动确定季号，请手动选择季。")
        if absolute_hint:
            notes.append(
                f"文件没有季标记，但集号超过 TMDB 第 {first_season_num} 季的 "
                f"{first_season_count} 集；可能是总集编号，已暂停集数改名，"
                "请手动选择季。")

        # 明确写了 Sxx 时也做一次校验；这里只提示，不阻止用户手动应用。
        if season_counts:
            by_season: dict[int, list[int]] = {}
            for _, season, ep, _, _ in resolved:
                if season is not None and ep is not None:
                    by_season.setdefault(season, []).append(ep)
            for season, eps in sorted(by_season.items()):
                count = season_counts.get(season)
                if count and max(eps) > count:
                    notes.append(
                        f"TMDB 第 {season} 季共 {count} 集，本任务出现 "
                        f"E{max(eps):02d}；请核对是否混入其他季或使用总集编号。")

        # 电视剧/国产动画/美漫/欧美动画：中文名.来源名.SxxExx.副标题 [规格]
        english_title = ""
        online_subs: dict[tuple[int, int], str] = {}
        name_source, name_sid = self.naming_ref(plan)
        if category in DOTTED_CATEGORIES or category == "jp_anime":
            # “来源名”那一段：按设置里选的来源取（none 表示不显示）
            english_title = self._name_segment(plan)
            seasons = sorted({s for _, s, ep, _, _ in resolved
                              if s is not None and ep is not None})
            source_empty = False
            for s in seasons:
                missing = any(
                    not self._episode_subtitle(e)
                    for e, ss, ep, _, _ in resolved
                    if ss == s and ep is not None)
                if not missing:
                    continue
                if name_source:
                    # 按所选来源取单集标题；该来源没有分集数据时留空，
                    # 绝不悄悄混入其他来源（尤其是 TMDB）的标题。
                    data = self._source_episode_titles(
                        plan, s, name_source, name_sid)
                    if not data:
                        source_empty = True
                else:
                    tmdb_id = plan.identity.tmdb_id
                    fetch_titles = getattr(self.metadata,
                                           "season_episode_titles", None)
                    data = {}
                    if tmdb_id and fetch_titles:
                        try:
                            data = fetch_titles(tmdb_id, s) or {}
                        except Exception as exc:
                            self.log(f"单集副标题获取失败：{exc}")
                            data = {}
                for ep_num, ep_title in (data or {}).items():
                    online_subs[(s, ep_num)] = ep_title
            if source_empty:
                label = NAMING_SOURCE_LABELS.get(name_source, name_source)
                self._mark(plan, qc.name_source_no_episodes(label))

        # 季目录重命名
        if self.options.rename_season_folders and mr.season_dirs:
            seen: dict[int, int] = {}
            for sd in mr.season_dirs:
                s = season_from_dir(sd.name)
                if s is None:
                    continue
                seen[s] = seen.get(s, 0) + 1
            for sd in mr.season_dirs:
                s = season_from_dir(sd.name)
                if s is None:
                    continue
                if seen.get(s, 0) > 1:
                    notes.append(f"多个目录都对应第 {s} 季，已跳过季目录改名。")
                    continue
                target = "Specials" if s == 0 else f"Season {s:02d}"
                if sd.name == target:
                    continue
                ops.append(RenameOp(fid=sd.fid, old_name=sd.name,
                                    new_name=target, is_dir=True,
                                    role="season", parent_id=sd.parent_id))

        # 同一季同一集多文件：区分合理多版本与疑似重复/错集
        analysis = analyze_episode_versions(
            [(e, s, ep) for e, s, ep, _, _ in resolved])
        plan.version_groups = analysis.groups
        multi_groups = analysis.multi_versions
        duplicate_groups = analysis.duplicates
        # 先清掉上一轮生成的版本/重复提示，避免用户修正映射后仍显示旧提示。
        if plan.version_notes:
            stale = set(plan.version_notes)
            plan.note = "；".join(
                x for x in (plan.note.split("；") if plan.note else [])
                if x and x not in stale)
            plan.version_notes = []
        version_notes: list[str] = []
        if multi_groups:
            version_notes.extend(g.note for g in multi_groups[:2])
            if len(multi_groups) > 2:
                version_notes.append(
                    f"另有 {len(multi_groups) - 2} 组同集多版本，"
                    "已在文件名中用 v2/v3 区分。")
        if duplicate_groups:
            version_notes.extend(g.note for g in duplicate_groups[:2])
            if len(duplicate_groups) > 2:
                version_notes.append(
                    f"另有 {len(duplicate_groups) - 2} 组疑似重复，"
                    "请在预览中核对。")
            version_notes.append("疑似重复/错集不会自动勾选，请核对后再改名。")
            if plan.status == "auto":
                plan.status = "review"
            self._mark(plan, qc.DUPLICATE_EPISODES)
            plan.duplicate_review = True
        elif plan.duplicate_review:
            # 用户通过季集映射修正后，恢复原来自动状态。
            if plan.status == "review" and \
                    plan.confidence >= self.options.min_auto_confidence:
                plan.status = "auto"
            plan.duplicate_review = False
        plan.version_notes = version_notes
        notes.extend(version_notes)

        video_map: list[tuple[FileEntry, str, str]] = []  # (entry, old_stem, new_stem)
        for e, season, ep, ep_end, confirmed in resolved:
            if season is None or ep is None:
                continue
            specs = quality_suffix(e.parsed) if want_specs else ""
            if specs and not plan.specs:
                plan.specs = specs
            ext = e.item.ext_raw
            subtitle = ""
            if category in DOTTED_CATEGORIES or category == "jp_anime":
                subtitle = (self._episode_subtitle(e) or
                            online_subs.get((season, ep), ""))
                if season == 0 and subtitle:
                    subtitle = self._clean_special_subtitle(plan, subtitle)
            version_no = analysis.version_numbers.get(e.item.fid, 0)
            version = f"v{version_no}" if version_no > 1 else ""
            if category in DOTTED_CATEGORIES:
                new_name = naming_rule.build_episode_filename(
                    title, season, ep, ext=ext,
                    name_segment=english_title, subtitle=subtitle,
                    specs=specs, ep_end=ep_end, version=version)
            else:
                # 日番保留简洁命名；同集多文件时仍加 v2，避免同名冲突。
                new_name = _episode_name(video_title, season, ep, ep_end,
                                         ext, specs, subtitle, version)
            old_stem = e.item.stem
            new_stem = new_name[:-len(ext)] if ext else new_name
            video_map.append((e, old_stem, new_stem))
            if e.item.name != new_name:
                ops.append(RenameOp(fid=e.item.fid, old_name=e.item.name,
                                    new_name=new_name, is_dir=False,
                                    role="episode", parent_id=e.item.parent_id))

        # 字幕/音轨
        if self.options.rename_subtitles and sidecars:
            sub_ops, sub_notes = self._sidecar_ops(sidecars, video_map)
            ops += sub_ops
            notes += sub_notes

        # 剧集文件夹
        if plan.rename_root and not plan.context.get("is_container"):
            ident = plan.identity
            folder_name = self._folder_name(
                plan, title, year, ident.imdb_id, ident.tmdb_id)
            if mr.item.name != folder_name:
                ops.insert(0, RenameOp(fid=mr.item.fid, old_name=mr.item.name,
                                       new_name=folder_name, is_dir=True,
                                       role="show", parent_id=mr.item.parent_id))

        if not plan.season_confirmed:
            # 季号没确认前，不生成集数改名，避免改错
            ops = [o for o in ops if o.role in ("show", "season")]
            plan.selected = False
            plan.status = "review"
            self._mark(plan, qc.SEASON_UNCONFIRMED)
        return ops, notes

    def _movie_ops(self, plan: PlanItem, mr: MediaRoot,
                   videos: list[FileEntry], sidecars: list[FileEntry],
                   title: str, year: Optional[int]):
        ops: list[RenameOp] = []
        notes: list[str] = []
        counts = Counter()
        for e in videos:
            counts[e.item.stem.lower()] += 1
        # 电影：优先把 IMDb 号插到中文名后面；只有 TMDB 号时才用 TMDB。
        # 写法仍按设置里的“标识写法”，但不会因为 auto 把 IMDb 换成 TMDB。
        ident = plan.identity
        id_suffix = self._movie_id_suffix(ident.imdb_id, ident.tmdb_id)
        # 没有电影文件夹时（散落在“电影”目录里），把 ID 写进文件名
        loose_id = "" if plan.rename_root else id_suffix
        used_insert = False
        kept_original = False
        targets: dict[str, int] = {}
        video_map: list[tuple[FileEntry, str, str]] = []
        for e in videos:
            disamb = ""
            spec = self._quality_tag(e.parsed)
            if len(videos) > 1:
                disamb = spec or ""
            ext = e.item.ext_raw
            moved = self._insert_id_after_title(
                e.item.name, id_suffix, False) if id_suffix else ""
            if moved:
                new_name = moved
                used_insert = True
            elif self._find_title_end(os.path.splitext(e.item.name)[0]) >= 0:
                # 有中文标题但没有 ID：保留原名和规格
                new_name = e.item.name
                kept_original = True
            else:
                new_name = _movie_name(title, year, ext, disamb, loose_id)
            # 目标重名：再用分辨率/序号区分
            if new_name.lower() in targets:
                targets[new_name.lower()] += 1
                base, tail_ext = os.path.splitext(new_name)
                new_name = f"{base}.v{targets[new_name.lower()] + 1}{tail_ext}"
                notes.append(f"多个版本重名，已用版本号区分：{e.item.name}")
            else:
                targets[new_name.lower()] = 1
            new_stem = new_name[:-len(ext)] if ext else new_name
            video_map.append((e, e.item.stem, new_stem))
            if e.item.name != new_name:
                ops.append(RenameOp(fid=e.item.fid, old_name=e.item.name,
                                    new_name=new_name, is_dir=False,
                                    role="movie", parent_id=e.item.parent_id))

        if self.options.rename_subtitles and sidecars:
            sub_ops, sub_notes = self._sidecar_ops(sidecars, video_map)
            ops += sub_ops
            notes += sub_notes

        if plan.rename_root and mr.item.is_dir:
            folder_name = ""
            if id_suffix:
                folder_name = self._insert_id_after_title(
                    mr.item.name, id_suffix, True)
            if folder_name:
                folder_name = self._versioned_folder_name(folder_name, plan)
                used_insert = True
            elif self._find_title_end(mr.item.name) >= 0:
                # 中文电影文件夹但找不到 ID：文件夹保持原名
                folder_name = self._versioned_folder_name(
                    mr.item.name, plan)
                kept_original = True
            else:
                folder_name = self._folder_name(
                    plan, title, year, ident.imdb_id, ident.tmdb_id)
            if mr.item.name != folder_name:
                ops.insert(0, RenameOp(fid=mr.item.fid, old_name=mr.item.name,
                                       new_name=folder_name, is_dir=True,
                                       role="movie", parent_id=mr.item.parent_id))
        if used_insert:
            notes.append("电影：IMDb/TMDB 号已放到中文名后，其他规格保持不变。")
        elif kept_original:
            notes.append("没有找到 IMDb/TMDB 标识，电影名称保持不变。")
        return ops, notes

    def _quality_tag(self, parsed: ParsedName) -> str:
        q = quality_suffix(parsed)
        if q:
            return q.split()[0]
        m = RE_RESOLUTION.search(parsed.raw or "")
        return m.group(1) if m else ""

    # ------------------------------------------------------------ 字幕匹配
    @staticmethod
    def _lang_suffix(stem: str) -> str:
        tags = re.findall(
            r"(?i)([.\-_](?:zh(?:[-_]?(?:cn|tw|hans|hant))?|chs|cht|sc|tc|"
            r"jpn?|jap|ja|eng?|gb|big5|简体|繁体|简|繁|简繁|简日|繁日|简繁日|双语|中字))"
            r"(?=[.\-_]|$)", stem)
        return tags[-1] if tags else ""

    def _sidecar_ops(self, sidecars: list[FileEntry],
                     video_map: list[tuple[FileEntry, str, str]]
                     ) -> tuple[list[RenameOp], list[str]]:
        ops: list[RenameOp] = []
        notes: list[str] = []
        by_parent: dict[str, list[tuple[FileEntry, str, str]]] = {}
        by_number: dict[int, list[tuple[FileEntry, str, str]]] = {}
        for e, old_stem, new_stem in video_map:
            by_parent.setdefault(e.item.parent_id, []).append((e, old_stem, new_stem))
            if re.fullmatch(r"\d{1,6}", e.item.stem.strip()):
                by_number.setdefault(int(e.item.stem), []).append(
                    (e, old_stem, new_stem))
        unmatched = 0
        for sub in sidecars:
            old_stem = sub.item.stem
            match = None
            suffix = ""
            sub_season = sub.parsed.season if sub.parsed.season is not None \
                else sub.folder_season
            sub_ep = sub.parsed.episode
            if sub_ep is None:
                # 01.chs.ass / Show 01.chs.ass 这类字幕名
                mep = re.search(
                    r"(?:^|[.\-_])(\d{1,4})(?:v\d+)?(?=[.\-_]|$)", old_stem)
                if not mep:
                    # ReinForce 等字幕组：... Grace Note~ 00 (BDRip...).sc.sup
                    mep = re.search(
                        r"(?:^|[\s._\-])(\d{1,3})(?=\s*[\[(（])",
                        old_stem)
                if not mep:
                    # VCB 等字幕组：[05(New Angle Ver.)] / [11][Ma10p_1080p]
                    mep = re.search(
                        r"(?:^|\[\s*)(\d{1,3})(?:v\d+)?(?=\s*[\]\[(（])",
                        old_stem)
                if mep:
                    sub_ep = int(mep.group(1))

            def video_season(e: FileEntry) -> Optional[int]:
                return e.parsed.season if e.parsed.season is not None \
                    else e.folder_season

            def season_ok(e: FileEntry) -> bool:
                if sub_season is None:
                    # 没有季标记的字幕优先匹配正片，避免把 01 配到
                    # S00E01 特别篇；只有找不到正片时才在下面兜底匹配特别篇。
                    v = video_season(e)
                    return v is None or v != 0
                v = video_season(e)
                return v is None or v == sub_season

            # 同目录：前缀匹配
            for e, vstem, nstem in by_parent.get(sub.item.parent_id, []):
                if old_stem == vstem:
                    match, suffix = (e, nstem), ""
                    break
                if old_stem.startswith(vstem + "."):
                    match, suffix = (e, nstem), old_stem[len(vstem):]
                    break
            # 原盘编号：ass/00001.ass ↔ 00001.m2ts，按原始数字名匹配
            mnum = re.match(r"^(\d{1,6})(?=[.\-_]|$)", old_stem)
            if match is None and mnum:
                num = int(mnum.group(1))
                cands = by_number.get(num, [])
                if cands:
                    same = [c for c in cands
                            if c[0].item.parent_id == sub.item.parent_id]
                    pool = same or cands
                    if len(pool) == 1:
                        match = (pool[0][0], pool[0][2])
                        suffix = self._lang_suffix(old_stem)
            # 字幕名是 00：对应原 SxxE00，已映射到第 0 季特别篇
            if match is None and sub_ep == 0:
                pool = [(e, vstem, nstem) for e, vstem, nstem in video_map
                        if getattr(e, "special_zero", False)]
                if len(pool) == 1:
                    match = (pool[0][0], pool[0][2])
                    suffix = self._lang_suffix(old_stem)
            # 字幕目录：按集数匹配（字幕名可能只有 01.chs）
            if match is None and sub.container is not None and \
                    is_subs_dir(sub.container.name) and sub_ep is not None:
                for e, vstem, nstem in video_map:
                    if e.parsed.episode == sub_ep and season_ok(e):
                        match, suffix = (e, nstem), self._lang_suffix(old_stem)
                        break
            # 同目录/字幕目录：按“集数”兜底（字幕名可能比视频短很多）
            if match is None and sub_ep is not None:
                for e, vstem, nstem in video_map:
                    if e.parsed.episode != sub_ep or not season_ok(e):
                        continue
                    same_parent = e.item.parent_id == sub.item.parent_id
                    in_subs = (sub.container is not None and
                               is_subs_dir(sub.container.name))
                    if same_parent or in_subs:
                        match, suffix = (e, nstem), self._lang_suffix(old_stem)
                        break
            # 只有特别篇的剧集：字幕没有季标记时，最后再允许匹配第 0 季
            if match is None and sub_ep is not None and sub_season is None \
                    and sub.container is not None and \
                    is_subs_dir(sub.container.name):
                for e, vstem, nstem in video_map:
                    if e.parsed.episode == sub_ep and video_season(e) == 0:
                        match = (e, nstem)
                        suffix = self._lang_suffix(old_stem)
                        break
            if match is None:
                unmatched += 1
                continue
            new_name = match[1] + suffix + sub.item.ext_raw
            if sub.item.name != new_name:
                ops.append(RenameOp(fid=sub.item.fid, old_name=sub.item.name,
                                    new_name=new_name, is_dir=False,
                                    role="subtitle",
                                    parent_id=sub.item.parent_id))
        if unmatched:
            notes.append(f"{unmatched} 个字幕/音轨文件无法对应到视频，已保持原名。")
        return ops, notes
