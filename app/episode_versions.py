# -*- coding: utf-8 -*-
"""同一季同一集多文件：区分合理多版本与疑似重复/错集。

判定原则：
- 两个文件都带规格，且规格/语言/版本标记不同 -> 合理多版本；
- 只有扩展名不同、或其中一个没有规格 -> 证据不足，按疑似重复处理；
- 显式 v2/REPACK/PROPER 视为版本标记；
- 疑似重复不阻止生成预览，但会把任务降级为“需确认”，不自动勾选。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .models import EpisodeVersionGroup
from .parser import quality_suffix

RE_EXPLICIT_VERSION = re.compile(
    r"(?i)(?:E\d{1,4}|(?<![A-Za-z0-9]))v(\d{1,2})"
    r"(?=$|[.\s_\[\]()-])")
RE_REPACK = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:repack|proper|rerip)(?![A-Za-z0-9])")
RE_LANG_TAG = re.compile(
    r"(?i)^(?:chs|cht|sc|tc|gb|big5|jpn?|jap|ja|eng?|简体|繁体|简繁|"
    r"简日|繁日|简繁日|双语|中字|内封|外挂|无字)$")
RE_TAG_SEP = re.compile(r"[\s._-]+")


@dataclass
class VersionAnalysis:
    groups: list[EpisodeVersionGroup] = field(default_factory=list)
    # fid -> 版本号；0 表示主版本（不加 v2）
    version_numbers: dict[str, int] = field(default_factory=dict)

    @property
    def duplicates(self) -> list[EpisodeVersionGroup]:
        return [g for g in self.groups if g.is_duplicate]

    @property
    def multi_versions(self) -> list[EpisodeVersionGroup]:
        return [g for g in self.groups if not g.is_duplicate]


def _norm_tag(tag: str) -> str:
    return RE_TAG_SEP.sub("", str(tag or "").casefold())


def _tag_set(entry: Any) -> frozenset[str]:
    parsed = getattr(entry, "parsed", None)
    tags = getattr(parsed, "tags", None) or []
    return frozenset(_norm_tag(t) for t in tags if _norm_tag(t))


def _explicit_version(entry: Any) -> int:
    item = getattr(entry, "item", None)
    stem = os.path.splitext(getattr(item, "name", "") or "")[0]
    m = RE_EXPLICIT_VERSION.search(stem)
    if m:
        try:
            return max(1, int(m.group(1)))
        except ValueError:
            return 1
    if RE_REPACK.search(stem):
        return 2
    return 0


def _joined_tags(entry: Any) -> str:
    parsed = getattr(entry, "parsed", None)
    tags = " ".join(str(t) for t in (getattr(parsed, "tags", None) or []))
    raw = str(getattr(parsed, "raw", "") or "")
    return f"{tags} {raw}".casefold()


def _resolution_rank(text: str) -> int:
    if re.search(r"(?<![0-9])(?:8k|4320p)(?![0-9])", text):
        return 8
    if re.search(r"(?<![0-9])(?:4k|2160p|uhd)(?![0-9])", text):
        return 7
    if re.search(r"(?<![0-9])(?:1080p|1080i|fhd)(?![0-9])", text):
        return 6
    if re.search(r"(?<![0-9])720p(?![0-9])", text):
        return 5
    if re.search(r"(?<![0-9])576p(?![0-9])", text):
        return 4
    if re.search(r"(?<![0-9])(?:480p|360p)(?![0-9])", text):
        return 3
    return 0


def _source_rank(text: str) -> int:
    if "remux" in text:
        return 6
    if "bluray" in text or "blu-ray" in text:
        return 5
    if "web-dl" in text or "webdl" in text:
        return 4
    if "webrip" in text or re.search(r"(?<![a-z])web(?![a-z])", text):
        return 3
    if "hdtv" in text:
        return 2
    if "dvdrip" in text or "hdrip" in text:
        return 1
    return 0


def _hdr_rank(text: str) -> int:
    if "dolby" in text and "vision" in text or "dovi" in text or \
            re.search(r"(?<![a-z])dv(?![a-z])", text):
        return 3
    if "hdr10+" in text or "hdr10plus" in text:
        return 2
    if "hdr" in text or "hlg" in text:
        return 1
    return 0


def _codec_rank(text: str) -> int:
    if re.search(r"(?<![a-z0-9])(?:av1|vp9)(?![a-z0-9])", text):
        return 4
    if re.search(r"(?<![a-z0-9])(?:x265|h\.?265|hevc)(?![a-z0-9])", text):
        return 3
    if re.search(r"(?<![a-z0-9])(?:x264|h\.?264|avc)(?![a-z0-9])", text):
        return 2
    return 0


def _bit_rank(text: str) -> int:
    if re.search(r"(?<![0-9])12bit(?![0-9])", text):
        return 3
    if re.search(r"(?<![0-9])(?:10bit|hi10p?|ma10p?)(?![0-9])", text):
        return 2
    if re.search(r"(?<![0-9])8bit(?![0-9])", text):
        return 1
    return 0


def _audio_rank(text: str) -> int:
    if re.search(
            r"(?<![a-z0-9])(?:truehd|dts[- ]?hd(?:[ .]?ma)?|flac|lpcm|pcm)"
            r"(?![a-z0-9])", text):
        return 4
    if re.search(r"(?<![a-z0-9])(?:dts|ddp|e-?ac-?3|atmos)(?![a-z0-9])",
                 text):
        return 3
    if re.search(r"(?<![a-z0-9])(?:ac-?3|aac|opus|mp3)(?![a-z0-9])", text):
        return 2
    return 0


def _quality_rank(entry: Any) -> tuple[int, ...]:
    text = _joined_tags(entry)
    return (
        _resolution_rank(text),
        _source_rank(text),
        _hdr_rank(text),
        _codec_rank(text),
        _bit_rank(text),
        _audio_rank(text),
    )


def _sort_key(entry: Any) -> tuple:
    item = getattr(entry, "item", None)
    size = int(getattr(item, "size", 0) or 0)
    name = str(getattr(item, "name", "") or "").casefold()
    return (_explicit_version(entry),) + \
        tuple(-x for x in _quality_rank(entry)) + (-size, name)


def _size(entry: Any) -> int:
    item = getattr(entry, "item", None)
    try:
        return max(0, int(getattr(item, "size", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _base_label(entry: Any) -> str:
    parsed = getattr(entry, "parsed", None)
    specs = quality_suffix(parsed) if parsed is not None else ""
    tags = [str(t).strip() for t in (getattr(parsed, "tags", None) or [])
            if str(t).strip()]
    langs = [t for t in tags if RE_LANG_TAG.fullmatch(t)]
    if langs:
        existing = specs.casefold()
        extra = [t for t in dict.fromkeys(langs)
                 if t.casefold() not in existing]
        if extra:
            specs = (specs + " " + " ".join(extra)).strip()
    if specs:
        return specs
    if tags:
        return " ".join(list(dict.fromkeys(tags))[:4])
    item = getattr(entry, "item", None)
    ext = str(getattr(item, "ext_raw", "") or "").lstrip(".")
    return ext.upper() if ext else "未标规格"


def _distinct_labels(entries: list[Any]) -> list[str]:
    labels = [_base_label(e) for e in entries]
    counts: dict[str, int] = {}
    for label in labels:
        counts[label.casefold()] = counts.get(label.casefold(), 0) + 1
    out: list[str] = []
    for entry, label in zip(entries, labels):
        if counts.get(label.casefold(), 0) > 1:
            item = getattr(entry, "item", None)
            ext = str(getattr(item, "ext_raw", "") or "").lstrip(".")
            if ext and ext.casefold() not in label.casefold():
                label = f"{label} {ext.lower()}"
        out.append(label)
    return out


def _short_name(name: str, limit: int = 72) -> str:
    if len(name) <= limit:
        return name
    return name[:limit - 20].rstrip() + "…" + name[-18:]


def _same_size(entries: list[Any]) -> bool:
    sizes = [_size(e) for e in entries]
    if any(s <= 0 for s in sizes):
        return False
    low, high = min(sizes), max(sizes)
    return high - low <= max(1024 * 1024, int(high * 0.01))


def _kind(entries: list[Any]) -> str:
    # 显式版本标记优先：v2 / REPACK / PROPER
    versions = [_explicit_version(e) for e in entries]
    if any(v > 0 for v in versions) and len(set(versions)) > 1:
        return "multi_version"
    tag_sets = [_tag_set(e) for e in entries]
    # 两边都带规格且确有差异，才算可解释的多版本；
    # 只有扩展名不同、或一边完全没规格时证据不足，按疑似重复处理。
    if all(tag_sets) and len(set(tag_sets)) > 1:
        return "multi_version"
    return "duplicate"


def analyze_episode_versions(rows) -> VersionAnalysis:
    """rows: [(FileEntry, season, episode), ...]，返回分组和版本号。"""
    by_key: dict[tuple[int, int], list[Any]] = {}
    for row in rows:
        if len(row) < 3:
            continue
        entry, season, episode = row[0], row[1], row[2]
        if season is None or episode is None:
            continue
        by_key.setdefault((int(season), int(episode)), []).append(entry)

    out = VersionAnalysis()
    for (season, episode), entries in by_key.items():
        if len(entries) <= 1:
            continue
        ordered = sorted(entries, key=_sort_key)
        labels = _distinct_labels(ordered)
        kind = _kind(ordered)
        fids = [str(getattr(getattr(e, "item", None), "fid", "") or "")
                for e in ordered]
        names = [str(getattr(getattr(e, "item", None), "name", "") or "")
                 for e in ordered]
        tag = f"S{season:02d}E{episode:02d}"
        if kind == "multi_version":
            label_text = " / ".join(dict.fromkeys(labels))
            note = (f"{tag} 在同一目录有 {len(ordered)} 个版本"
                    f"（{label_text}）；无法用文件夹区分，"
                    "临时用 v2 防止重名。")
        else:
            label_text = " / ".join(dict.fromkeys(labels)) or "未标规格"
            sizes = [_size(e) for e in ordered]
            if all(s > 0 for s in sizes):
                size_text = "规格和大小都相同" if _same_size(ordered) \
                    else "规格相同但大小不同"
            else:
                size_text = "规格相同"
            shown = " / ".join(_short_name(n) for n in names[:3])
            if len(names) > 3:
                shown += f" 等 {len(names)} 个"
            note = (f"{tag} 有 {len(ordered)} 个文件{size_text}"
                    f"（{label_text}），疑似重复或错集：{shown}。")
        out.groups.append(EpisodeVersionGroup(
            season=season, episode=episode, kind=kind,
            fids=fids, files=names, labels=labels, note=note))
        # 排序后的第一个作为主版本，其余依次 v2/v3…
        for pos, entry in enumerate(ordered):
            fid = str(getattr(getattr(entry, "item", None), "fid", "") or "")
            if fid:
                out.version_numbers[fid] = 0 if pos == 0 else pos + 1
    return out
