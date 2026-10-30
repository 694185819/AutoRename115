# -*- coding: utf-8 -*-
"""统一命名模板：所有媒体类型都通过同一套字段 + 模板拼名字。

设计目标
--------
以前各媒体类型各有一套硬编码拼装（_folder_name / _video_title /
build_episode_filename / build_movie_filename），
格式改一处要改好几个地方，而且「命名规则」面板只能影响其中一部分。

现在把「拼名字」收敛成一个模板引擎：

    {中文名}.{来源名}.{季集}.{副标题} [{规格}]

由「命名规则」面板决定：
  - 用哪些字段（来源名选哪个来源、副标题选哪个来源、要不要规格）
  - 各媒体类型用同一个模板，只是字段值不同

媒体信息（IMDb/TMDB/豆瓣/Bangumi）只负责**填字段**，不决定结构。

字段说明
--------
  title        中文主名称（必填，固定）
  name_segment 来源名（英文/日文原名，可为空）
  season_ep    季集标记 S01E02 / S01E02-E03 / v2
  subtitle     单集副标题
  specs        规格 [1080p WEB-DL]
  year         年份 (2018)
  id           [imdbid-tt...]
"""
import re
from typing import Optional

# 默认模板：与现有剧集命名保持一致，保证不改变既有行为
DEFAULT_EPISODE_TEMPLATE = "{title}.{name_segment}.{season_ep}.{subtitle} [{specs}]"
DEFAULT_FOLDER_TEMPLATE = "{title} {name_segment} {season} ({year}) [{id}]"
DEFAULT_MOVIE_TEMPLATE = "{title} ({year}) [{specs}] [{id}]"

# 模板里可用的占位符
TEMPLATE_FIELDS = (
    "title", "name_segment", "name_segment_ja", "season_ep", "subtitle",
    "specs", "year", "id", "season", "episode",
)

# 分隔符清理用
_SEP_RE = re.compile(r"[.\s]+")


def _clean(text: str, limit: int = 235) -> str:
    t = str(text or "").strip()
    if len(t.encode("utf-8")) > limit:
        while len(t.encode("utf-8")) > limit and t:
            t = t[:-1]
    return t.rstrip(" .-_")


def render(template: str, fields: dict) -> str:
    """按模板拼接。缺失字段自动省略对应的分隔符。

    `{a}.{b}` 在 b 为空时输出 `a`（不会留下多余的点）。
    这样同一套模板能覆盖“有来源名/没来源名”“有副标题/没副标题”等情况。
    """
    out = template
    for key in TEMPLATE_FIELDS:
        value = fields.get(key)
        if value is None:
            value = ""
        if key == "year" and value:
            # 模板里可能已经写了括号「({year})」，这里只填数字
            value = str(int(value))
        # 规格/ID 是否加方括号由模板决定（模板里已经写了 []），
        # 这里只负责填值，避免出现 [[2160p]]。
        out = out.replace("{" + key + "}", str(value))

    # 清掉空字段留下的多余分隔：重复点、空括号、结尾点、首尾空格
    out = re.sub(r"\.\s*\.", ".", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\[\s*\]", "", out)
    # 空字段会留下「. 」这种“点 + 空格”，要整体收掉：
    # 「S01E01. [2160p]」→「S01E01 [2160p]」
    out = re.sub(r"\.\s+(?=[\[(])", " ", out)
    out = re.sub(r"\.\s*$", "", out)
    out = re.sub(r"\s+\.", ".", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"^\s*\.\s*", "", out)
    return out.strip()


def build_episode_filename(
        title: str, season: int, ep: int, *,
        ext: str = "", name_segment: str = "", subtitle: str = "",
        specs: str = "", ep_end: Optional[int] = None, version: str = "",
        budget: int = 235, colon_to_dot: bool = True) -> str:
    """剧集文件名（保持原行为，内部改为走模板引擎）。"""
    tag = episode_tag(season, ep, ep_end, version)
    cn = sanitize_segment(title, budget, colon_to_dot=False)
    seg = sanitize_segment(name_segment, budget, colon_to_dot) \
        if name_segment else ""
    if seg and _norm(seg) == _norm(cn):
        seg = ""
    sub = sanitize_segment(subtitle, budget, colon_to_dot) if subtitle else ""

    fields = {"title": cn, "name_segment": seg, "season_ep": tag,
              "subtitle": sub, "specs": (specs or "").strip()}
    name = render(DEFAULT_EPISODE_TEMPLATE, fields)

    # 超长时依次让出副标题、来源名、主名（与原逻辑一致）
    while len(name.encode("utf-8")) + len(ext.encode("utf-8")) > budget:
        if fields["subtitle"] and len(fields["subtitle"]) > 4:
            fields["subtitle"] = fields["subtitle"][:-1]
        elif fields["subtitle"]:
            fields["subtitle"] = ""
        elif fields["name_segment"] and len(fields["name_segment"]) > 4:
            fields["name_segment"] = fields["name_segment"][:-1]
        elif fields["name_segment"]:
            fields["name_segment"] = ""
        elif len(fields["title"]) > 8:
            fields["title"] = fields["title"][:-1]
        else:
            break
        name = render(DEFAULT_EPISODE_TEMPLATE, fields)
    return name + ext


def build_movie_filename(title: str, year: Optional[int], ext: str = "",
                         specs: str = "", id_suffix: str = "",
                         budget: int = 235) -> str:
    """电影文件名（保持原行为）。"""
    cn = sanitize_segment(title, budget, colon_to_dot=False)
    if year:
        # 标题里已带年份时先去掉，避免出现 ((2018))
        cn = re.sub(r"\s*\(\s*\d{4}\s*\)\s*$", "", cn).strip(" .-_")
    fields = {"title": cn, "year": year or "", "specs": (specs or "").strip()}
    out = render(DEFAULT_MOVIE_TEMPLATE, fields)
    return out + (id_suffix or "") + ext


def _norm(text: str) -> str:
    return _SEP_RE.sub("", (text or "")).lower()


def episode_tag(season: int, ep: int, ep_end: Optional[int] = None,
                version: str = "") -> str:
    """S01E02 / S01E02-E03 / 带 v2。"""
    tag = f"S{int(season):02d}E{int(ep):02d}"
    if ep_end and int(ep_end) != int(ep):
        tag += f"-E{int(ep_end):02d}"
    return tag + (version or "")


def sanitize_segment(text: str, max_bytes: int = 120,
                     colon_to_dot: bool = True) -> str:
    """清洗一个名字段（与 naming_rule.sanitize_segment 行为一致）。

    这里保留一份独立实现，避免 naming_rule ← naming_template 循环导入；
    两者必须保持等价（有测试守护）。
    """
    t = str(text or "")
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
