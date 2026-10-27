# -*- coding: utf-8 -*-
"""Kodi/Jellyfin NFO 与图片文件名处理。"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Optional
from xml.sax.saxutils import escape

from .models import P115Item, PlanItem

NFO_EXTS = {".nfo"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tbn", ".bmp", ".gif"}
INFO_EXTS = NFO_EXTS | IMAGE_EXTS
STANDARD_ART = {
    "poster.jpg", "folder.jpg", "fanart.jpg", "backdrop.jpg",
    "banner.jpg", "thumb.jpg", "logo.png", "clearlogo.png",
    "landscape.jpg", "disc.jpg", "discart.png", "keyart.jpg",
}
STANDARD_NFO = {"tvshow.nfo", "movie.nfo", "season.nfo", "episode.nfo"}


def parse_nfo_bytes(data: bytes) -> dict:
    """解析已有 NFO 的标题、年份、TMDB/IMDb 标识和季集。

    只做只读提取，不依赖 Kodi 的完整 schema；字段缺失就返回空。
    """
    if not data:
        return {}
    try:
        root = ET.fromstring(data)
    except Exception:
        return {}
    if root is None:
        return {}

    def text(tag: str) -> str:
        value = root.findtext(tag)
        return str(value or "").strip()

    out: dict = {}
    title = text("title")
    original = text("originaltitle")
    show_title = text("showtitle")
    if title:
        out["title"] = title
    elif show_title:
        out["title"] = show_title
    if original:
        out["original_title"] = original
    if show_title:
        out["show_title"] = show_title
    year_text = text("year")
    if year_text.isdigit():
        out["year"] = int(year_text)

    tmdb = ""
    imdb = ""
    for node in root.findall("uniqueid"):
        kind = str(node.get("type") or "").strip().lower()
        val = str(node.text or "").strip()
        if not val:
            continue
        if kind in ("tmdb", "tmdbid") and val.isdigit():
            tmdb = tmdb or val
        elif kind in ("imdb", "imdbid") and re.fullmatch(r"tt\d+", val):
            imdb = imdb or val
    if not tmdb:
        val = text("tmdbid") or text("tmdb_id")
        if val.isdigit():
            tmdb = val
    if not imdb:
        val = text("imdbid") or text("imdb_id")
        if re.fullmatch(r"tt\d+", val):
            imdb = val
    if not imdb:
        val = text("id")
        if re.fullmatch(r"tt\d+", val):
            imdb = val
    if tmdb:
        out["tmdb_id"] = tmdb
    if imdb:
        out["imdb_id"] = imdb

    for key in ("season", "episode"):
        val = text(key)
        if val.isdigit():
            out[key] = int(val)
    return out


def is_info_file(name: str) -> bool:
    ext = os.path.splitext(name or "")[1].lower()
    return ext in INFO_EXTS


def is_standard_art(name: str) -> bool:
    low = (name or "").lower()
    return low in STANDARD_ART or low in STANDARD_NFO


def _xml(v) -> str:
    return escape("" if v is None else str(v))


def _actors(details: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in details.get("cast") or []:
        s = str(item or "").strip()
        if not s:
            continue
        role = ""
        m = re.match(r"^(.*?)[（(](.*?)[)）]$", s)
        if m:
            s, role = m.group(1).strip(), m.group(2).strip()
        out.append((s, role))
    return out


def _unique_ids(plan: PlanItem) -> list[tuple[str, str]]:
    m = plan.match
    ident = plan.identity
    ids: list[tuple[str, str]] = []
    douban = m.douban_id
    bangumi = m.bangumi_id
    for kind, val in (("imdb", ident.imdb_id), ("tmdb", ident.tmdb_id),
                      ("douban", douban), ("bangumi", bangumi)):
        if val:
            ids.append((kind, str(val)))
    return ids


def _base_fields(plan: PlanItem, details: dict) -> list[str]:
    ident = plan.identity
    title = str(details.get("title") or ident.title or "")
    original = str(ident.original_title or "")
    year = details.get("year") or ident.year or ""
    rating = details.get("rating")
    lines = [
        f"  <title>{_xml(title)}</title>",
        f"  <originaltitle>{_xml(original or title)}</originaltitle>",
    ]
    if year:
        lines.append(f"  <year>{_xml(year)}</year>")
    if details.get("overview"):
        lines.append(f"  <plot>{_xml(details.get('overview'))}</plot>")
    if isinstance(rating, (int, float)):
        lines.append(f"  <rating>{rating:.1f}</rating>")
    for kind, val in _unique_ids(plan):
        default = ' default="true"' if kind == "imdb" else ""
        lines.append(
            f'  <uniqueid type="{kind}"{default}>{_xml(val)}</uniqueid>')
    for genre in details.get("genres") or []:
        if genre:
            lines.append(f"  <genre>{_xml(genre)}</genre>")
    lines.append("  <poster>poster.jpg</poster>")
    lines.append("  <fanart><thumb>fanart.jpg</thumb></fanart>")
    for i, (name, role) in enumerate(_actors(details), 1):
        lines += [
            "  <actor>",
            f"    <name>{_xml(name)}</name>",
            f"    <role>{_xml(role)}</role>",
            f"    <order>{i}</order>",
            "  </actor>",
        ]
    return lines


def build_tvshow_nfo(plan: PlanItem, details: dict) -> bytes:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
             "<tvshow>", *_base_fields(plan, details), "</tvshow>"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_movie_nfo(plan: PlanItem, details: dict) -> bytes:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
             "<movie>", *_base_fields(plan, details), "</movie>"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _episode_title(new_name: str, ep: int) -> str:
    stem = os.path.splitext(new_name)[0]
    m = re.search(r"S\d{1,2}E\d{1,4}(?:-E?\d{1,4})?(?:v\d+)?\.(.+)$",
                  stem, re.I)
    if not m:
        return f"第 {ep} 集"
    title = m.group(1)
    title = re.sub(r"\s*\[[^\]]*\]$", "", title).strip(" ._-")
    title = title.replace(".", " ").strip()
    return title or f"第 {ep} 集"


def episode_nfos(plan: PlanItem, details: dict) -> list[dict]:
    """返回每集要生成的 NFO：目录、文件名、内容。"""
    if plan.media_type != "series":
        return []
    out: list[dict] = []
    seen = set()
    for op in plan.ops:
        if op.role != "episode" or op.is_dir:
            continue
        m = re.search(r"S(\d{1,2})E(\d{1,4})", op.new_name, re.I)
        if not m:
            continue
        season, ep = int(m.group(1)), int(m.group(2))
        stem = os.path.splitext(op.new_name)[0]
        filename = stem + ".nfo"
        key = (op.parent_id, filename)
        if key in seen:
            continue
        seen.add(key)
        title = _episode_title(op.new_name, ep)
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
            "<episodedetails>",
            f"  <title>{_xml(title)}</title>",
            f"  <showtitle>{_xml(details.get('title') or plan.identity.title)}</showtitle>",
            f"  <season>{season}</season>",
            f"  <episode>{ep}</episode>",
        ]
        if details.get("overview"):
            lines.append(f"  <plot>{_xml(details.get('overview'))}</plot>")
        rating = details.get("rating")
        if isinstance(rating, (int, float)):
            lines.append(f"  <rating>{rating:.1f}</rating>")
        for kind, val in _unique_ids(plan):
            default = ' default="true"' if kind == "imdb" else ""
            lines.append(
                f'  <uniqueid type="{kind}"{default}>{_xml(val)}</uniqueid>')
        lines.append("</episodedetails>")
        mr = (plan.context or {}).get("mr")
        cid = op.parent_id or (mr.item.fid if mr is not None else "")
        out.append({"cid": cid, "filename": filename,
                    "data": ("\n".join(lines) + "\n").encode("utf-8")})
    return out


def desired_files(plan: PlanItem, details: dict,
                  poster: bytes = b"", fanart: bytes = b"") -> list[dict]:
    """需要补齐/上传的 NFO 和图片（目录、文件名、内容）。"""
    mr = (plan.context or {}).get("mr")
    root_cid = mr.item.fid if mr is not None else plan.item.parent_id
    out: list[dict] = []
    if plan.media_type == "series":
        if plan.rename_root:
            out.append({"cid": root_cid, "filename": "tvshow.nfo",
                        "data": build_tvshow_nfo(plan, details)})
        out.extend(episode_nfos(plan, details))
    else:
        movie = next((o for o in plan.ops
                      if o.role == "movie" and not o.is_dir), None)
        if movie:
            stem = os.path.splitext(movie.new_name)[0]
            out.append({"cid": movie.parent_id or root_cid,
                        "filename": stem + ".nfo",
                        "data": build_movie_nfo(plan, details)})
    # 标准 poster/fanart 只能放在该任务独占的根目录；电影库根目录有
    # 很多电影时不能写共享 poster.jpg，避免覆盖/误删其他电影的资料。
    if plan.rename_root and poster:
        out.append({"cid": root_cid, "filename": "poster.jpg",
                    "data": poster, "mime": "image/jpeg"})
    if plan.rename_root and fanart:
        out.append({"cid": root_cid, "filename": "fanart.jpg",
                    "data": fanart, "mime": "image/jpeg"})
    return out


def matching_info_files(plan: PlanItem,
                        files: list[P115Item]) -> list[P115Item]:
    """只挑出属于当前任务的 NFO/图片，避免误删同目录其他电影。

    匹配依据：视频旧名/新名的前缀；标准 poster/fanart/tvshow/movie.nfo
    只在该任务独占的根目录（rename_root）里才算匹配。
    """
    mr = (plan.context or {}).get("mr")
    root_cid = mr.item.fid if mr is not None else plan.item.parent_id
    maps: dict[str, list[tuple[str, str]]] = {}
    for op in plan.ops:
        if op.is_dir or op.role not in ("episode", "movie"):
            continue
        old = os.path.splitext(op.old_name)[0]
        new = os.path.splitext(op.new_name)[0]
        if old and new:
            maps.setdefault(op.parent_id, []).append((old, new))
    # 有些文件只存在于分析上下文、未必产出改名操作
    for e in ((plan.context or {}).get("entries") or []):
        try:
            if not e.is_video:
                continue
            stem = os.path.splitext(e.item.name)[0]
            maps.setdefault(e.item.parent_id, []).append((stem, stem))
        except Exception:
            continue
    for arr in maps.values():
        arr.sort(key=lambda x: len(x[0]), reverse=True)
    out: list[P115Item] = []
    for item in files:
        if item.is_dir or not is_info_file(item.name):
            continue
        if is_standard_art(item.name):
            if item.parent_id == root_cid and plan.rename_root:
                out.append(item)
            continue
        for old, new in maps.get(item.parent_id, []):
            stem = item.stem
            if stem == old or stem == new or \
                    stem.startswith(old + ".") or \
                    stem.startswith(old + "-") or \
                    stem.startswith(old + "_") or \
                    stem.startswith(old + " ") or \
                    stem.startswith(new + ".") or \
                    stem.startswith(new + "-") or \
                    stem.startswith(new + "_") or \
                    stem.startswith(new + " "):
                out.append(item)
                break
    return out


def matching_info_files_for_root(files: list[P115Item]) -> list[P115Item]:
    """当前文件夹范围：按文件夹里的视频名匹配 NFO/图片。

    电影库根目录有多部电影时，标准 poster.jpg/tvshow.nfo 不会被当成
    某一部电影的附件；每个电影子文件夹（或单视频文件夹）才会。
    """
    vids: dict[str, list[str]] = {}
    for f in files:
        if not f.is_dir and f.is_video:
            vids.setdefault(f.parent_id, []).append(f.stem)

    def dedicated(parent: str) -> bool:
        stems = vids.get(parent, [])
        if len(stems) <= 1:
            return True
        return any(re.search(
            r"(?i)(?:S\d{1,2}E\d{1,4}|E(?:P)?\s*\d{1,4}|第\s*\d+\s*[集话話])",
            s) for s in stems)

    out: list[P115Item] = []
    for item in files:
        if item.is_dir or not is_info_file(item.name):
            continue
        if is_standard_art(item.name):
            if dedicated(item.parent_id):
                out.append(item)
            continue
        for stem in vids.get(item.parent_id, []):
            if item.stem == stem or \
                    item.stem.startswith(stem + ".") or \
                    item.stem.startswith(stem + "-") or \
                    item.stem.startswith(stem + "_") or \
                    item.stem.startswith(stem + " "):
                out.append(item)
                break
    return out


def sidecar_renames(plan: PlanItem,
                    files: list[P115Item]) -> list[tuple[P115Item, str]]:
    """已有 NFO/图片跟随视频旧名 → 新名。"""
    maps: dict[str, list[tuple[str, str]]] = {}
    for op in plan.ops:
        if op.is_dir or op.role not in ("episode", "movie"):
            continue
        old = os.path.splitext(op.old_name)[0]
        new = os.path.splitext(op.new_name)[0]
        if old and new and old != new:
            maps.setdefault(op.parent_id, []).append((old, new))
    for arr in maps.values():
        arr.sort(key=lambda x: len(x[0]), reverse=True)
    out: list[tuple[P115Item, str]] = []
    for item in files:
        if item.is_dir or not is_info_file(item.name) or \
                is_standard_art(item.name):
            continue
        for old, new in maps.get(item.parent_id, []):
            if item.stem == old:
                suffix = item.name[len(old):]
            elif item.stem.startswith(old + ".") or \
                    item.stem.startswith(old + "-") or \
                    item.stem.startswith(old + "_") or \
                    item.stem.startswith(old + " "):
                suffix = item.name[len(old):]
            else:
                continue
            new_name = new + suffix
            if new_name != item.name:
                out.append((item, new_name))
            break
    return out
