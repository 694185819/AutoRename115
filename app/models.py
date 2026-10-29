# -*- coding: utf-8 -*-
"""数据模型：115 文件、解析结果、元数据候选、重命名计划。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".vob", ".iso", ".rmvb",
    ".rm", ".3gp", ".ogv", ".divx",
}
SUB_EXTS = {".ass", ".ssa", ".srt", ".sup", ".sub", ".idx", ".vtt"}
AUDIO_EXTS = {".flac", ".aac", ".m4a", ".mp3", ".wav", ".dts", ".ac3", ".eac3", ".opus"}


@dataclass
class P115Item:
    fid: str
    parent_id: str
    name: str
    is_dir: bool
    size: int = 0
    pickcode: str = ""
    updated: str = ""
    # 从网盘根目录到父目录的名称（不含自身），用于在文件名信息不足时
    # 回溯上级文件夹名（例如 “动画 / 某番剧 / Season 01 / 00001.m2ts”）。
    ancestors: list[str] = field(default_factory=list)

    @property
    def ext(self) -> str:
        if self.is_dir:
            return ""
        dot = self.name.rfind(".")
        return self.name[dot:].lower() if dot >= 0 else ""

    @property
    def ext_raw(self) -> str:
        """保留原扩展名大小写，115 对“扩展名”比较敏感。"""
        if self.is_dir:
            return ""
        dot = self.name.rfind(".")
        return self.name[dot:] if dot >= 0 else ""

    @property
    def is_video(self) -> bool:
        return not self.is_dir and self.ext in VIDEO_EXTS

    @property
    def stem(self) -> str:
        if self.is_dir:
            return self.name
        dot = self.name.rfind(".")
        return self.name[:dot] if dot > 0 else self.name


@dataclass
class ParsedName:
    raw: str
    title: str
    queries: list[str] = field(default_factory=list)
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_end: Optional[int] = None
    is_episode: bool = False
    tags: list[str] = field(default_factory=list)
    group: str = ""
    ext: str = ""
    warnings: list[str] = field(default_factory=list)
    # 季目录里的视频文件名与目录/上级剧名明显不一致时，记录这些文件名标题。
    # 自动搜索仍按目录锚点走，但匹配结果会先被要求同时支持这些标题，
    # 否则任务标记“需确认”，不再无脑改名。
    conflict_titles: list[str] = field(default_factory=list)
    # 上下文整理时从视频文件名里收集到的季号（例如目录里没写 Sxx，
    # 但文件名是 S2E01），供剧集任务在目录名缺季号时补用。
    file_season: Optional[int] = None

    @property
    def season_episode(self) -> str:
        if self.episode is None:
            return ""
        s = self.season if self.season is not None else 1
        if self.episode_end and self.episode_end != self.episode:
            return f"S{s:02d}E{self.episode:02d}-E{self.episode_end:02d}"
        return f"S{s:02d}E{self.episode:02d}"


@dataclass
class Candidate:
    source: str                 # douban / imdb / bangumi / tmdb
    title: str
    original_title: str = ""
    year: Optional[int] = None
    sid: str = ""               # douban id / tt / bgm id / tmdb id
    kind: str = ""              # tv / movie
    episodes: int = 0
    url: str = ""
    score: float = 0.0
    rank: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class MatchResult:
    douban: Optional[Candidate] = None
    imdb: Optional[Candidate] = None
    bangumi: Optional[Candidate] = None
    tmdb: Optional[Candidate] = None
    title_zh: str = ""
    title_original: str = ""
    year: Optional[int] = None
    imdb_id: str = ""
    tmdb_id: str = ""
    douban_id: str = ""
    bangumi_id: str = ""
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    alternatives: list[Candidate] = field(default_factory=list)

    # 电视剧：本季条目可能叫“某某 第二季”，但海报墙应归到主剧名下
    series_title: str = ""
    series_original_title: str = ""
    series_year: Optional[int] = None
    series_imdb_id: str = ""
    is_season_entry: bool = False
    country: str = ""           # jp / cn / ""（用于判断是否日番）
    animation: bool = False     # 国产内容是否动画（决定显示“国产动画”还是“电视剧”）
    # 自动搜索的诊断摘要：用了哪些搜索词、各来源第一名、置信度。
    # 显示在任务备注里，方便对照日志排查“为什么匹配成另一部片”。
    trace: str = ""
    # 各来源各自的条目号：{"douban": {"id": "...", "title": "...", "year": 2019}}
    # 用于“按来源命名/取副标题/取特别篇”时，按该来源自己的条目号去查。
    source_refs: dict = field(default_factory=dict)

    def ref(self, source: str) -> dict:
        """取某来源的条目号信息；没有时返回空 dict。"""
        refs = self.source_refs if isinstance(self.source_refs, dict) else {}
        item = refs.get(source)
        return item if isinstance(item, dict) else {}

    @property
    def display_title(self) -> str:
        """命名时优先使用主剧名。"""
        return self.series_title or self.title_zh or self.title_original

    @property
    def display_year(self) -> Optional[int]:
        return self.series_year or self.year

    @property
    def best(self) -> Optional[Candidate]:
        cands = [c for c in (self.douban, self.bangumi, self.imdb, self.tmdb) if c]
        return max(cands, key=lambda c: c.score) if cands else None


@dataclass(frozen=True)
class MediaIdentity:
    """一个任务最终采用的媒体身份（以 TMDB/IMDb 为锚点）。"""
    media_type: str = ""
    tmdb_id: str = ""
    imdb_id: str = ""
    title: str = ""
    original_title: str = ""
    year: Optional[int] = None
    series_title: str = ""
    series_original_title: str = ""
    series_year: Optional[int] = None


@dataclass
class RenameOp:
    fid: str
    old_name: str
    new_name: str
    is_dir: bool
    role: str = ""              # show / season / episode / movie
    parent_id: str = ""
    selected: bool = True       # 重命名预览里的勾选状态


@dataclass
class EpisodeVersionGroup:
    """同一季同一集出现多个文件时的分组结果。"""
    season: int
    episode: int
    kind: str                   # multi_version / duplicate
    fids: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def is_duplicate(self) -> bool:
        return self.kind == "duplicate"


@dataclass
class PlanItem:
    item: P115Item
    media_type: str             # series / movie / unknown
    parsed: ParsedName
    match: MatchResult = field(default_factory=MatchResult)
    title: str = ""
    year: Optional[int] = None
    season: Optional[int] = None
    episodes: list[int] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "auto"        # auto / review / skip / error
    note: str = ""
    ops: list[RenameOp] = field(default_factory=list)
    selected: bool = True
    # 结构化的“为什么需要确认/跳过”：QcResult 列表（见 app/qc.py）。
    # status/note 仍保留给既有界面使用，两者由 planner 同步维护。
    qc_codes: list[str] = field(default_factory=list)

    # 命名分类：jp_anime（简洁）/ cn_anime / tv（带规格）/ movie
    category: str = "auto"
    specs: str = ""
    rename_root: bool = True     # 选中的目录本身是否要改名（容器目录不改）
    season_confirmed: bool = True
    seasons: list[int] = field(default_factory=list)
    series_imdb_id: str = ""
    # 让 GUI 能对季数/标题做人工覆盖
    season_override: Optional[int] = None
    # 逐文件季集映射：{文件 fid: (季, 集)}
    episode_overrides: dict[str, tuple[int, int]] = field(default_factory=dict)
    # 同一集多文件的分组（多版本/疑似重复）
    version_groups: list[EpisodeVersionGroup] = field(default_factory=list)
    # 同一部剧/电影的额外版本目录：2 = V2，3 = V3…
    folder_version: int = 0
    # 当前“需确认”是否由疑似重复集触发，修正映射后可自动恢复
    duplicate_review: bool = False
    # 上一次重建写入的版本/重复集提示，重建前先移除，避免提示过期
    version_notes: list[str] = field(default_factory=list)
    title_override: str = ""
    year_override: Optional[int] = None
    # 命名来源："" = 自动；douban/bangumi/imdb/tmdb = 按该来源的条目命名。
    # 命名来源决定标题、单集副标题和特别篇顺序；命名规则仍按分类决定。
    name_source: str = ""
    context: dict = field(default_factory=dict, repr=False)

    @property
    def current_name(self) -> str:
        return self.item.name

    @property
    def display_title(self) -> str:
        return self.title_override or self.title

    @property
    def display_year(self) -> Optional[int]:
        return self.year_override or self.year

    @property
    def identity(self) -> MediaIdentity:
        """把 match / context / 人工覆盖统一成一份最终身份。

        以后命名、NFO、季集校验都从这里取 ID，避免同一个任务里
        match.tmdb_id、context["tmdb_id"]、series_imdb_id 各说各话。
        """
        ctx = self.context or {}
        m = self.match or MatchResult()
        tmdb = str(ctx.get("tmdb_id") or m.tmdb_id or "")
        if self.media_type == "series":
            imdb = str(self.series_imdb_id or ctx.get("imdb_id") or
                       m.series_imdb_id or m.imdb_id or "")
        else:
            imdb = str(ctx.get("imdb_id") or m.imdb_id or
                       self.series_imdb_id or "")
        title = (self.title_override or self.title or
                 m.display_title or self.parsed.title or "")
        original = (m.series_original_title or m.title_original or "")
        year = (self.year_override or self.year or m.display_year or
                self.parsed.year)
        return MediaIdentity(
            media_type=self.media_type,
            tmdb_id=tmdb,
            imdb_id=imdb,
            title=title,
            original_title=original,
            year=year,
            series_title=m.series_title,
            series_original_title=m.series_original_title,
            series_year=m.series_year,
        )

    @property
    def new_summary(self) -> str:
        if not self.ops:
            return ""
        if self.media_type == "series":
            show = next((o for o in self.ops if o.role == "show"), None)
            eps = [o for o in self.ops if o.role == "episode"]
            if show:
                return show.new_name + (f"  (+{len(eps)} 个视频)" if eps else "")
            if eps:
                eps = sorted(eps, key=lambda o: o.new_name)
                return eps[0].new_name + (
                    f"  (+{len(eps) - 1} 个视频)" if len(eps) > 1 else "")
            season = next((o for o in self.ops if o.role == "season"), None)
            return season.new_name if season else self.ops[0].new_name
        return self.ops[0].new_name
