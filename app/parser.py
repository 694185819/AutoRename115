# -*- coding: utf-8 -*-
"""从 115 的不规则文件名/文件夹名中提取标题、年份、季、集。

目标不是 100% 还原发布名，而是给出足够好的搜索词，并把季集号规范化成
SxxExx，供海报墙软件识别。
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Optional

from .models import AUDIO_EXTS, SUB_EXTS, VIDEO_EXTS, ParsedName

KNOWN_EXTS = VIDEO_EXTS | SUB_EXTS | AUDIO_EXTS | {
    ".zip", ".rar", ".7z", ".nfo", ".jpg", ".jpeg", ".png", ".webp",
}

# ---------------------------------------------------------------- 正则
RE_SXXEXX = re.compile(
    r"(?i)(?<![A-Za-z0-9])S(\d{1,2})\s*[._ -]?\s*E(?:P)?(\d{1,4})"
    r"(?:\s*[-~]\s*E?(\d{1,4}))?(?![0-9])")
RE_SEASON_CN = re.compile(r"第\s*([0-9零一二两三四五六七八九十]+)\s*季")
RE_SEASON_EN = re.compile(r"(?i)(?<![A-Za-z])Season\s*(\d{1,2})(?![0-9])")
RE_SEASON_S = re.compile(r"(?i)(?<![A-Za-z0-9])S(\d{1,2})(?![0-9E])")
# 罗马数字季/部：第Ⅱ季、Season II、Show II.2019.EP01
RE_SEASON_ROMAN_CN = re.compile(r"第\s*([IVXLCDM]{1,6})\s*[季期部]")
RE_SEASON_ROMAN_EN = re.compile(
    r"(?i)(?<![A-Za-z])(?:Season|Series)\s*([IVXLCDM]{1,6})(?![A-Za-z0-9])")
RE_SEASON_ROMAN_PART = re.compile(
    r"(?i)(?<![A-Za-z])(?:Part|Vol(?:ume)?|Cour)"
    r"[\s._-]*([IVXLCDM]{1,6})(?![A-Za-z0-9])")
RE_ROMAN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?=[IVXLCDM])"
    r"((?:X{0,3})(?:IX|IV|V?I{0,3}))(?![A-Za-z0-9])")
RE_EP_CN = re.compile(r"第\s*(\d{1,4})\s*[集话話]")
RE_EP_EN = re.compile(
    r"(?i)(?<![A-Za-z0-9])E(?:P|pisode)?\s*[._ -]?\s*(\d{1,4})"
    r"(?:\s*[-~]\s*(\d{1,4}))?(?:v\d+)?(?![0-9])")
RE_EP_BRACKET = re.compile(
    r"[\[【(（]\s*(\d{1,4})(?:\s*[-~]\s*(\d{1,4}))?(?:v\d+)?\s*[\]】)）]")
RE_EP_DASH = re.compile(
    r"(?:^|[\s._])(?:-|–|—)\s*(\d{1,4})(?:\s*[-~]\s*(\d{1,4}))?(?:v\d+)?"
    r"(?=$|[\s._\[\]()]|\.[A-Za-z0-9]{2,4}$)")
RE_EP_TRAIL = re.compile(
    r"(?:^|[\s._])(\d{1,4})(?:v\d+)?(?:\s*[-~]\s*(\d{1,4}))?\s*$")
# 中文片名紧跟集号、中间没有分隔符：「将夜01」「犬夜叉03」
# 只认紧贴在汉字/假名后面的数字，且必须是整个名字的结尾，
# 避免把「1984」「琅琊榜2」这类含数字的片名误判成集号。
RE_EP_CJK_TAIL = re.compile(
    r"(?<=[\u4e00-\u9fff\u3040-\u30ff])(\d{1,4})(?:v\d+)?\s*$")
RE_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
RE_RESOLUTION = re.compile(r"(?i)(?<!\d)\d{3,4}\s*[x×]\s*\d{3,4}(?!\d)")
RE_RELEASE_NOISE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:REPACK|PROPER|RERIP|DUAL|MULTI|v\d)(?![A-Za-z0-9])")
RE_BRACKET = re.compile(r"[\[【（(]([^\]】）)]*)[\]】）)]")
RE_LEAD_BRACKET = re.compile(r"^\s*[\[【（(]([^\]】）)]*)[\]】）)]\s*")
RE_SEASON_LABEL = re.compile(
    r"(?:[★☆]\s*(?:\d{1,2}\s*月)?新番\s*[★☆]?)|(?:\d{1,2}\s*月新番)")
# 已有海报墙标识：{tmdbid-98123}、{tmdb-256783}、[tmdbid=298026]、
# {tmdbidid-273190}（原目录里常见的笔误）、[imdbid-tt...]
RE_PROVIDER_ID = re.compile(
    r"(?i)[\[{（(]?\s*(?:tmdb(?:id(?:id)?)?|imdb(?:id)?)"
    r"\s*[-=:]\s*(?:tt)?\d+\s*[\]}）)]?")
# 裸豆瓣号：寄生兽：灰色部队_35954429[全6集]…
# 片子后面直接跟的 5-10 位数字基本是豆瓣 subject id，不是片名的一部分；
# 留在标题里会污染搜索词（也搜不到任何东西）。
RE_BARE_ID = re.compile(r"(?<=[_\s-])\d{5,10}(?=[^0-9]|$)")
# “五季完结”“12集完结”“全集”是合集标记，不是第 5 季
RE_COLLECTION = re.compile(
    r"(?:第?\s*[0-9一二三四五六七八九十百]+\s*季\s*(?:完结|全集|全))|"
    r"(?:\d+\s*集\s*完结)|(?:全\s*\d+\s*集)|(?:完结|全集)")
RE_SEASON_RANGE = re.compile(
    r"(?i)(?<![A-Za-z0-9])S\d{1,2}\s*[-~]\s*S?\d{1,2}(?![0-9E])")
RE_SPACES = re.compile(r"\s+")
RE_SEP_EDGE = re.compile(
    r"^[\s._\-–—·:：,，;；!！?？/\\|★☆●○◆■□▲△]+"
    r"|[\s._\-–—·:：,，;；!！?？/\\|★☆●○◆■□▲△]+$")

GROUP_HINTS = re.compile(
    r"(?i)字幕|汉化|压制|字幕社|Sub(?:s|title)?\b|Raws?\b|Studio|Team|Group|"
    r"LoliHouse|VCB|ReinForce|ANK|DMG|喵萌|幻樱|桜都|悠哈|Nekomoe|"
    r"Sakurato|SweetSub|Lilith|Airota|Ohys|Horrible|Baha|B-Global|"
    r"JYFanSub|HYSUB|XKsub|LoliHouse")
# 结尾的发布组：...1080p.BluRay.x264-Huan@HDsky / ...DTS-HD.MA.5.1-HDSky
# 只认带 @ 的组名或已知组名，避免把 WEB-DL、DTS-HD、Blu-Ray、
# Spider-Man 里的连字符当成发布组。
RELEASE_GROUPS = {
    "hdsky", "hdchina", "hds", "hdtime", "cmct", "wiki", "frds", "evo",
    "ntb", "ddr", "handjob", "tayto", "playready", "beast", "qxr", "yts",
    "yify", "rarbg", "fgt", "ift", "phd", "chd", "mysilu", "ttg", "adc",
    "d3filter", "hdsweb", "hdarea", "hdhome", "hdroad", "hdtv",
    "zerotv", "zero", "dsnp", "chdweb",
}
RE_GROUP_SUFFIX = re.compile(
    r"(?i)(?<=[0-9A-Za-z\]\)])\-([A-Za-z][A-Za-z0-9@_]{1,30})$")

RE_AUDIO_COMBINED_PATTERN = (
    r"(?i)(?<![A-Za-z0-9])"
    r"(?P<codec>DTS(?:[- ]?HD(?:[ .]?MA)?|[- :]?X)?|TrueHD|DDP|DD\+|DD|AAC|"
    r"E-?AC-?3|AC-?3|FLAC|LPCM|PCM|MP3|Opus)"
    r"(?P<channel>[257]\.1(?:\.\d)?|[1-6]\.0|6\.1)"
    r"(?![0-9])")

TAG_PATTERNS = [
    r"(?i)(?<![A-Za-z0-9])(?:2160p|1080p|1080i|720p|576p|480p|360p|4K|8K|UHD|FHD)(?![A-Za-z0-9])",
    r"(?i)(?<![A-Za-z])(?:BluRay|Blu-ray|BDRip|BDRemux|WEB-?DL|WEB-?Rip|HDTV|DVDRip|"
    r"Remux|HDRip|TVRip|WEB|Baha|B-Global|CR|Netflix|Amazon|Disney\+?|Hulu|"
    r"DSNP|DSNY|HMAX|ATVP|PCOK|PMTP)(?![A-Za-z])",
    r"(?i)(?<![A-Za-z0-9])(?:x264|x265|H\.?264|H\.?265|HEVC|AVC|AV1|VP9|"
    r"Hi10P?|Ma10p|Ma10|10bit|8bit|12bit|Hi444pp)(?![A-Za-z0-9])",
    # HDR / 杜比视界 / 色域 / 帧率
    r"(?i)(?<![A-Za-z0-9])(?:HDR10\+?|HDR10|HDR|DoVi|DOVI|DV|"
    r"Dolby[ ._-]?Vision|HLG|BT\.?2020|BT\.?709|DCI[ -]?P3|HFR)"
    r"(?![A-Za-z0-9])",
    r"(?i)(?<![A-Za-z0-9])\d{1,3}(?:\.\d+)?\s*fps(?![A-Za-z0-9])",
    # 音频编码 + 声道是一个整体：DDP5.1 / TrueHD7.1.2 / AAC2.0。
    # 必须先于下面的单独编码/声道规则匹配，否则会被拆成
    # “DDP Atmos 5.1”这种错误排列。
    RE_AUDIO_COMBINED_PATTERN,
    # 音频编码（没有紧跟声道数字时）
    r"(?i)(?<![A-Za-z0-9])(?:DTS(?:[- ]?HD(?:[ .]?MA)?|[- :]?X)?|TrueHD|"
    r"Dolby[ ._-]?Atmos|Atmos|FLAC|AAC|E-?AC-?3|AC-?3|DD\+|DDP|DD|"
    r"LPCM|PCM|MP3|Opus)(?![A-Za-z])",
    # 单独出现的声道（例如 TrueHD.Atmos.7.1 里的 7.1）
    r"(?i)(?<![0-9])(?:[257]\.1(?:\.\d)?|6\.1|[1-6]\.0)(?![0-9])",
    r"(?i)(?<![A-Za-z0-9])(?:CHS|CHT|GB|BIG5|JPN|JPSC|简体|繁体|简繁|简日|繁日|简繁日|"
    r"双语|中字|内封|外挂|无字)(?![A-Za-z0-9])",
    # 发布地区码（Big.Fish...2016.GBR.1080p）：不是片名的一部分
    r"(?i)(?<![A-Za-z0-9])(?:GBR|USA|JPN|CHN|HKG|TWN|KOR|FRA|GER|DEU|"
    r"ITA|ESP|AUS|CAN|IND|RUS|NZL|SWE|NOR|DEN|FIN|NLD|BEL|SUI|AUT|"
    r"POL|CZE|BRA|MEX|ARG)(?![A-Za-z0-9])",
]
RE_TAGS = [re.compile(p) for p in TAG_PATTERNS]
RE_AUDIO_COMBINED = re.compile(RE_AUDIO_COMBINED_PATTERN)

CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100,
                "D": 500, "M": 1000}


def roman_to_int(text: str) -> Optional[int]:
    """把 I/II/III/IV…（含 Unicode Ⅰ/Ⅱ）转成季号。"""
    s = unicodedata.normalize("NFKC", text or "").upper()
    if not s or any(ch not in ROMAN_VALUES for ch in s):
        return None
    total = 0
    prev = 0
    for ch in reversed(s):
        v = ROMAN_VALUES[ch]
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total if 0 < total <= 99 else None


def cn_number(text: str) -> Optional[int]:
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = CN_DIGITS.get(left, 1) if left else 1
        ones = CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(text) == 1:
        return CN_DIGITS.get(text)
    digits = [CN_DIGITS[c] for c in text if c in CN_DIGITS]
    return int("".join(map(str, digits))) if digits else None


def _is_likely_tag(text: str) -> bool:
    low = text.lower().strip()
    if not low:
        return True
    if re.fullmatch(r"(?:中?文字幕|字幕|字幕文件|内封字幕|外挂字幕)", low):
        return True
    for rx in RE_TAGS:
        if rx.search(low):
            return True
    if re.fullmatch(r"[\dA-Za-z+./&_-]{1,12}", text) and not re.search(r"[A-Za-z]{3,}", text):
        return True
    return False


def _collect_brackets(text: str) -> tuple[list[str], list[str]]:
    """返回 (保留为标题候选的括号内容, 标签)。"""
    alts, tags = [], []
    for m in RE_BRACKET.finditer(text):
        content = m.group(1).strip()
        if not content:
            continue
        if _is_likely_tag(content):
            tags.append(content)
        elif len(content) >= 2 and re.search(r"[0-9A-Za-z぀-ヿ㐀-鿿]", content):
            alts.append(content)
    return alts, tags


def _strip_brackets(text: str) -> str:
    return RE_BRACKET.sub(" ", text)


def _strip_tags(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    out = text
    for rx in RE_TAGS:
        for m in rx.finditer(out):
            found.append(m.group(0))
        out = rx.sub(" ", out)
    return out, found


def _remove_span(text: str, start: int, end: int) -> str:
    return text[:start] + " " + text[end:]


def _clean_title_prefix(text: str, original_name: str) -> str:
    """清洗 SxxExx 之前的片名部分，去掉年份/规格/括号。"""
    t = RE_PROVIDER_ID.sub(" ", text)
    t = RE_COLLECTION.sub(" ", t)
    t = RE_SEASON_LABEL.sub(" ", t)
    t = RE_SEASON_RANGE.sub(" ", t)
    t, _ = _strip_tags(t)
    t = _strip_brackets(t)
    t = RE_RELEASE_NOISE.sub(" ", t)
    t = RE_YEAR.sub(" ", t)
    t = t.replace("_", " ")
    if " " not in original_name and "." in t:
        t = t.replace(".", " ")
    t = RE_SPACES.sub(" ", t)
    return RE_SEP_EDGE.sub("", t).strip()


# “剧版（剑尘道魔录之玄劫天锋 2019）”这类目录：前缀只是版本说明，
# 真正的片名在括号/书名号里。不能把“剧版”当成片名去搜索。
TITLE_DESCRIPTOR_PREFIX = re.compile(
    r"(?i)^(?:剧版|影版|电影版|电视剧版|真人版|动画版|网剧版?|"
    r"网络剧版?|短剧版)")
_BRACKET_PAIRS = {"（": "）", "(": ")", "【": "】", "《": "》", "[": "]"}


def _strip_title_descriptor(name: str) -> str:
    """取出“剧版/真人版/动画版 + 括号标题”里的真正片名。"""
    text = (name or "").strip()
    m = TITLE_DESCRIPTOR_PREFIX.match(text)
    if not m:
        return name
    rest = text[m.end():].lstrip(" ._-–—:：·")
    if len(rest) < 2:
        return name
    opener = rest[0]
    closer = _BRACKET_PAIRS.get(opener)
    if closer:
        end = rest.rfind(closer)
        inner = rest[1:end].strip() if end > 0 else ""
        trailing = rest[end + 1:].strip(" ._-–—:：·") if end > 0 else ""
        # 括号里必须还有真正的文字，不能只是“全12集/2019”这类标签。
        if inner and re.search(r"[0-9A-Za-z぀-ヿ㐀-鿿]", inner) and \
                not re.fullmatch(r"(?i)(?:全\s*\d+\s*集|共\s*\d+\s*集|"
                                r"全集|完结|\d{4})", inner):
            return (inner + (" " + trailing if trailing else "")).strip()
        return name
    return rest


def _norm_text(text: str) -> str:
    return re.sub(r"[\s._\-–—·:：,，;；!！?？/\\|\[\]()（）]+",
                  "", text or "").lower()


def _is_part_number(text: str, match) -> bool:
    """`Part.2` / `Vol.2` / `Disc 2` / `Season 2` 里的数字不是集数。"""
    prefix = text[max(0, match.start() - 16):match.start()]
    # 末尾单独一个 S 才是 Season 简写；不能把 Highness 的 s 当成 S。
    return bool(re.search(
        r"(?i)(?:part|vol(?:ume)?|disc|disk|cd|bd|box|season)"
        r"\s*[._ -]?\s*$|(?<![A-Za-z])s\s*[._ -]?\s*$", prefix))


def _is_audio_channel(text: str, match) -> bool:
    """`DTS-HD.MA.5.1` / `TrueHD7.1` 末尾的 1 不是集数。"""
    end = match.end()
    return bool(re.search(
        r"(?<!\d)(?:[257]\.1(?:\.\d)?|[1-6]\.0|6\.1)$", text[:end]))


def _roman_is_season_marker(text: str, match) -> bool:
    """判断标题后面的裸罗马数字是不是季号。

    只认后面跟着集数标记的写法（Show II.2019.EP01 / Show II S02E01），
    避免把电影名里的 Rocky II、Final Fantasy VII 当成第二季/第七季。
    """
    before = text[:match.start()]
    after = text[match.end():]
    if not before.strip(" ._-[]()（）"):
        return False
    return bool(re.search(
        r"(?i)(?:S\d{1,2}\s*E\d|E(?:P)?\s*\d{1,4}|"
        r"第\s*\d+\s*[集话話])", after))


def _strip_release_group(text: str) -> str:
    """去掉结尾的 -Huan@HDsky / -HDSky / -FLTTH 等发布组。"""
    m = RE_GROUP_SUFFIX.search(text)
    if not m:
        return text
    group = m.group(1)
    if "@" in group or group.casefold() in RELEASE_GROUPS:
        return text[:m.start()]
    # 「2160p.WEB-DL.H264.AAC-FLTTH」这类：-XXXX 紧跟在规格词后面时，
    # 基本可以确定是发布组，不管它是否在白名单里。
    before = text[:m.start()]
    if re.search(r"(?i)(?:[\.\s_-])(?:aac|ac3|eac3|dts|flac|ddp?|truehd|"
                 r"atmos|opus|mp3|h26[45]|hevc|avc|x26[45]|2160p|1080p|"
                 r"720p|480p|web-?dl|webrip|bluray|remux|hdtv|multi|"
                 r"chs|cht|gb|big5)[\s._-]*$", before):
        return before
    return text


def parse_name(raw: str, is_dir: bool = False,
               parent_season: Optional[int] = None) -> ParsedName:
    original = raw
    ext = ""
    name = raw
    if not is_dir:
        base, candidate_ext = os.path.splitext(raw)
        if candidate_ext.lower() in KNOWN_EXTS and base:
            ext = candidate_ext
            name = base
        else:
            # 文件名里可能有点号（Part.2），只去掉真正的媒体后缀
            ext = ""

    name = RE_BARE_ID.sub("", name)
    text = unicodedata.normalize("NFKC", name)
    text = text.replace("【", "[").replace("】", "]")
    text = text.replace("（", "(").replace("）", ")")

    # 开头的 [字幕组] / 【字幕组】 去掉；如果开头括号里其实像标题，则展开
    group = ""

    def looks_like_group(content: str) -> bool:
        content = (content or "").strip()
        if GROUP_HINTS.search(content):
            return True
        if RE_YEAR.search(content):
            return False
        # 中文/日文括号更可能是片名别名，例如 [黑街][GANGSTA.]
        if re.search(r"[㐀-鿿぀-ヿ]", content):
            return False
        # 带空格的拉丁括号更像片名（[Movie Title]），组名通常是一串
        if " " in content or len(content) > 24:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9&+._'\-]{1,24}", content))

    m = RE_LEAD_BRACKET.match(text)
    if m:
        content = m.group(1).strip()
        if looks_like_group(content):
            group = content
            text = text[m.end():]
            while True:
                m = RE_LEAD_BRACKET.match(text)
                if not m or not looks_like_group(m.group(1)):
                    break
                text = text[m.end():]
        else:
            # [Movie Title (2019)] [1080p] → 把括号里的标题展开
            text = text[:m.start()] + " " + content + " " + text[m.end():]

    text = _strip_release_group(text)
    text = _strip_title_descriptor(text)
    text = RE_SEASON_LABEL.sub(" ", text)
    text = RE_PROVIDER_ID.sub(" ", text)
    text = RE_COLLECTION.sub(" ", text)
    text = RE_SEASON_RANGE.sub(" ", text)
    alts, bracket_tags = _collect_brackets(text)
    work = text
    # 分辨率里的 1920x1080 不是年份
    work = RE_RESOLUTION.sub(" ", work)

    season: Optional[int] = None
    roman_season = False
    episode: Optional[int] = None
    ep_end: Optional[int] = None
    spans: list[tuple[int, int]] = []
    season_span: Optional[tuple[int, int]] = None
    ep_marker_start: Optional[int] = None

    m = RE_SXXEXX.search(work)
    if m:
        season = int(m.group(1))
        episode = int(m.group(2))
        if m.group(3):
            ep_end = int(m.group(3))
        spans.append(m.span())
        season_span = m.span()
        ep_marker_start = m.start()
    else:
        m = RE_SEASON_CN.search(work)
        if not m:
            m = RE_SEASON_ROMAN_CN.search(work)
        if not m:
            m = RE_SEASON_EN.search(work)
        if not m:
            m = RE_SEASON_ROMAN_EN.search(work)
        if not m:
            m = RE_SEASON_S.search(work)
        if not m:
            for pm in RE_SEASON_ROMAN_PART.finditer(work):
                if _roman_is_season_marker(work, pm):
                    m = pm
                    break
        if m:
            raw = m.group(1)
            if raw.isdigit():
                season = int(raw)
            else:
                season = cn_number(raw)
                if season is None:
                    season = roman_to_int(raw)
            spans.append(m.span())
            season_span = m.span()
            roman_season = bool(season and not raw.isdigit() and
                                cn_number(raw) is None)
        # 目录名「将夜II」「将夜 II Ever Night」：中文片名紧跟罗马数字，
        # 该数字就是季号（中文名后面几乎不会是 Rocky II 那种序号）。
        # 即使已经从 S02 得到季号，也要把「II」从标题里去掉，
        # 否则会留下「将夜II Ever Night」这种片名。
        m2 = re.search(
            r"(?<=[\u4e00-\u9fff])\s*([IVX]{1,4})(?=$|[\s._\-])", work)
        if m2:
            val = roman_to_int(m2.group(1))
            if val and val <= 20:
                if season is None:
                    season = val
                    roman_season = True
                    season_span = m2.span(1)
                spans.append(m2.span(1))
        if season is None:
            # 标题后的裸罗马数字：Your Highness Ⅱ.2019.EP01-22
            # 必须同时有集数标记，避免误伤 Rocky II 这类电影名。
            for rm in RE_ROMAN.finditer(work):
                val = roman_to_int(rm.group(1))
                if not val or not _roman_is_season_marker(work, rm):
                    continue
                season = val
                roman_season = True
                spans.append(rm.span())
                season_span = rm.span()
                break

        def overlaps_season(match) -> bool:
            if not season_span:
                return False
            a, b = match.span()
            c, d = season_span
            return a < d and c < b

        ep_match = None
        for rx in (RE_EP_CN, RE_EP_EN, RE_EP_BRACKET, RE_EP_DASH):
            for m in rx.finditer(work):
                num = int(m.group(1))
                if 1900 <= num <= 2099 or overlaps_season(m):
                    continue
                if _is_part_number(work, m) or _is_audio_channel(work, m):
                    continue
                ep_match = m
                break
            if ep_match:
                break
        if ep_match is None and not is_dir:
            # 「将夜01」这类中文片名紧贴集号的写法（无分隔符）
            for m in RE_EP_CJK_TAIL.finditer(work):
                num = int(m.group(1))
                if 1900 <= num <= 2099 or overlaps_season(m):
                    continue
                if _is_part_number(work, m) or _is_audio_channel(work, m):
                    continue
                head = work[:m.start()].strip()
                if len(head) < 2:
                    continue
                # 一位数字（琅琊榜2）和 00（高达00）多半是片名的一部分，
                # 只有两位以上且非全零的数字才当作集号。
                raw = m.group(1)
                if len(raw) < 2 or num == 0:
                    continue
                ep_match = m
                break
        if ep_match is None and not is_dir:
            for m in RE_EP_TRAIL.finditer(work):
                num = int(m.group(1))
                if not (1900 <= num <= 2099) and not overlaps_season(m) \
                        and not _is_part_number(work, m) \
                        and not _is_audio_channel(work, m):
                    ep_match = m
                    break
        if ep_match is None and is_dir:
            # 文件夹名里的 “Show 01” 也允许，但三位数容易是标题数字，保守一点
            for m in RE_EP_TRAIL.finditer(work):
                num = int(m.group(1))
                if 1 <= num <= 99 and not overlaps_season(m) \
                        and not _is_part_number(work, m) \
                        and not _is_audio_channel(work, m):
                    ep_match = m
                    break
        if ep_match is not None:
            episode = int(ep_match.group(1))
            if len(ep_match.groups()) >= 2 and ep_match.group(2):
                ep_end = int(ep_match.group(2))
            spans.append(ep_match.span())
            ep_marker_start = ep_match.start()

    if season is None:
        season = parent_season

    # 年份：区分“片名里的数字”和“发行年份”
    year = None
    current_year = __import__("datetime").date.today().year
    chosen_year = None
    for m in RE_YEAR.finditer(work):
        val = int(m.group(1))
        before = work[:m.start()]
        after = work[m.end():]
        in_bracket = before.rstrip().endswith(("(", "（", "[", "【"))
        at_end = not after.strip(" ._-[]()（）")
        tag_after = any(rx.search(after) for rx in RE_TAGS)
        noise_after = RE_RELEASE_NOISE.search(after) is not None
        plausible = val <= current_year + 1
        title_before = before.strip(" ._-[]()（）")
        if (in_bracket or tag_after or noise_after or
                (plausible and at_end and title_before)):
            chosen_year = m
            year = val
            break
    if chosen_year is not None:
        spans.append(chosen_year.span())

    work_full = work
    for a, b in sorted(spans, reverse=True):
        work = _remove_span(work, a, b)

    # 拜见宫主大人2 + Your Highness Ⅱ：Ⅱ 已判定为第 2 季，
    # 中文标题末尾同值的阿拉伯数字也一并去掉。
    if roman_season and season:
        work = re.sub(
            rf"(?<=[㐀-鿿])0?{season}(?=[.\s_-]|$)", "", work)

    work = RE_RELEASE_NOISE.sub(" ", work)
    work, tag_words = _strip_tags(work)
    tags = []
    for t in bracket_tags + tag_words:
        t = t.strip()
        if t and t not in tags:
            tags.append(t)
    work = _strip_brackets(work)

    # 分隔符清理
    work = work.replace("_", " ")
    if " " not in name and "." in work:
        work = work.replace(".", " ")
    work = re.sub(r"\s*[-–—]\s*$", " ", work)
    work = RE_SPACES.sub(" ", work)
    work = RE_SEP_EDGE.sub("", work).strip()

    # 中文标题 + 英文别名：取中文主标题（“剑来 .Sword.of.Coming”“A / B”）
    for sep in ("丨", "｜", " / "):
        if sep in work:
            first = work.split(sep, 1)[0].strip()
            if len(first) >= 2:
                work = first
                break
    bilingual_full = ""
    m = re.match(
        r"^(.+?[一-鿿][^A-Za-z]*?)[.\s]+"
        r"([A-Za-z][A-Za-z0-9 .,'&:!+\-]*)$", work)
    if m:
        first = m.group(1).strip()
        suffix = m.group(2).strip()
        # “进击的巨人 最终季 Part.2”不要切掉 Part.2
        if len(first) >= 2 and not re.search(
                r"(?i)(?:季|season|part|cour)\s*$", first):
            # 后缀带数字时通常是标题的一部分（攻壳机动队 SAC 2045、
            # 机动战士高达 00），只留中文会搜到别的季/别的作品。
            if re.search(r"\d", suffix) or re.search(
                    r"(?i)(?:season|part|cour|s\d)", suffix):
                pass
            else:
                bilingual_full = work
                work = first

    # 取 " - " 之前的主标题，但保留完整串作为搜索候选。
    # 例外：`86 - Eighty Six`、`1917 - ...` 里的数字本身就是片名。
    full_clean = work
    if " - " in work:
        first = work.split(" - ", 1)[0].strip()
        if len(first) >= 2 and not re.fullmatch(r"\d{1,4}", first):
            work = first

    # 如果清洗后为空：优先用括号里的标题候选（[字幕组] 已去掉的情况）；
    # 纯集数文件（S01E01）保持空标题，让上层用文件夹名。
    if not work:
        if alts:
            work = alts[0]
        elif episode is None and season is None:
            work = (group or full_clean or name or original).strip()
            if not work:
                work = original
                ext = ""

    title = work.strip(" ._-–—·:：,，;；")

    # SxxExx 后面通常是单集副标题（Avatar...S01E01.The.Boy...），
    # 片名只取标记之前的部分，避免把副标题当成剧名。
    if ep_marker_start is not None and episode is not None:
        pre = _clean_title_prefix(work_full[:ep_marker_start], name)
        if pre and len(_norm_text(pre)) >= 2 and \
                _norm_text(title).startswith(_norm_text(pre)):
            title = pre
            full_clean = pre

    queries: list[str] = []

    def add_query(q: str):
        q = RE_SPACES.sub(" ", q).strip(" ._-–—·:：,，;；")
        if len(q) >= 1 and q not in queries:
            queries.append(q)

    add_query(title)
    if bilingual_full and bilingual_full != title:
        add_query(bilingual_full)
    if full_clean and full_clean != title:
        add_query(full_clean)
    for a in alts:
        if len(a) >= 2 and not _is_likely_tag(a):
            add_query(a)
    # 标题里带 & / 的情况拆开
    for q in list(queries):
        if "&" in q or "/" in q:
            for part in re.split(r"[&/]", q):
                add_query(part)

    warnings = []
    if not title:
        warnings.append("标题为空")
    if episode is None and not is_dir:
        warnings.append("未识别到集数")
    if not queries:
        queries = [title or original]

    return ParsedName(
        raw=original, title=title, queries=queries, year=year,
        season=season, episode=episode, episode_end=ep_end,
        is_episode=episode is not None, tags=tags, group=group,
        ext=ext.lower(), warnings=warnings,
    )


def quality_suffix(parsed: ParsedName) -> str:
    """尽量保留所有画质/音质规格（分辨率、HDR/DV、编码、音轨、声道等）。"""
    keep: list[str] = []
    for t in parsed.tags:
        tl = t.strip().lower()
        if not tl:
            continue
        if re.fullmatch(
                r"(?:2160p|1080p|1080i|720p|576p|480p|360p|4k|8k|uhd|fhd)",
                tl):
            keep.append(t)
        elif re.fullmatch(
                r"(?:hdr10\+?|hdr10|hdr|dovi|dv|dolby[ ._-]?vision|hlg|"
                r"bt\.?2020|bt\.?709|dci[ -]?p3|hfr)", tl):
            keep.append(t)
        elif re.fullmatch(r"\d{1,3}(?:\.\d+)?\s*fps", tl):
            keep.append(t)
        elif tl in ("bluray", "blu-ray", "bdrip", "bdremux", "web-dl",
                    "webrip", "web", "remux", "hdtv", "dvdrip", "hdrip"):
            keep.append(t)
        elif re.fullmatch(
                r"(?:x264|x265|h\.?264|h\.?265|hevc|avc|av1|vp9|"
                r"hi10p?|ma10p?|ma10|10bit|8bit|12bit|hi444pp)", tl):
            keep.append(t)
        elif RE_AUDIO_COMBINED.fullmatch(t):
            keep.append(t)
        elif re.fullmatch(
                r"(?:dts(?:[- ]?hd(?:[ .]?ma)?|[- :]?x)?|truehd|"
                r"dolby[ ._-]?atmos|atmos|flac|aac|e-?ac-?3|ac-?3|dd\+|ddp|dd|"
                r"lpcm|pcm|mp3|opus)", tl):
            keep.append(t)
        elif re.fullmatch(r"(?:[257]\.1(?:\.\d)?|[1-6]\.0|6\.1)", tl):
            keep.append(t)
    # 去重（不区分大小写）
    out: list[str] = []
    seen = set()
    for t in keep:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return " ".join(out)
