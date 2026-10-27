# -*- coding: utf-8 -*-
"""元数据来源扩展点。

这里定义“一个来源需要提供什么”，不定义“来源内部怎么写”：

- `SourceAdapter.search()`：按搜索词查候选，统一返回 `Candidate`；
- `SourceAdapter.detail()`：按来源内部 ID 取详情（评分/封面/简介/演员等）；
- `SourceAdapter.identify()`：把候选解析成可写的 IMDb/TMDB 标识（可选）。

调用方（`MetadataClient.match` / 手动搜索 / 详情面板）只依赖这些方法，
新增来源时实现一个适配器并 `register()` 即可，不用改匹配主流程。

注意：现有四个来源（Bangumi / 豆瓣 / IMDb / TMDB）的请求代码仍在
`metadata.MetadataClient` 内，这里提供的是它们实现该协议的转发适配器，
以及给新来源预留的注册表。渐进式迁移不会改变现有调用行为。
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

from ..models import Candidate


@runtime_checkable
class SourceAdapter(Protocol):
    """元数据来源的最小契约。"""

    name: str

    def search(self, query: str, media_type: str = "series",
               season: Optional[int] = None) -> list[Candidate]:
        """按搜索词返回候选；失败/无结果返回空列表，不抛异常。"""

    def detail(self, sid: str) -> Optional[dict]:
        """按来源内部 ID 取详情；不支持时返回 None。"""

    def identify(self, cand: Candidate, media_type: str,
                 aliases: tuple[str, ...] = ()) -> dict:
        """把候选解析成 IMDb/TMDB 标识等；不支持时返回空 dict。"""


# 新增来源注册表：name -> 适配器工厂（按需构造，避免导入时报错）
_FACTORIES: dict[str, Callable[["object"], SourceAdapter]] = {}


def register(name: str, factory: Callable[["object"], SourceAdapter]) -> None:
    """注册一个来源适配器；`factory(metadata_client)` 返回实例。"""
    _FACTORIES[str(name or "").strip().lower()] = factory


def registered() -> list[str]:
    return sorted(_FACTORIES)


def build(name: str, metadata_client) -> Optional[SourceAdapter]:
    """按名字构造来源适配器；未注册返回 None。"""
    factory = _FACTORIES.get(str(name or "").strip().lower())
    return factory(metadata_client) if factory else None


class ClientAdapter:
    """把 `MetadataClient` 上的同名方法包装成 `SourceAdapter`。

    现有四个来源用它接入协议；迁移到独立模块后，改为直接实现协议即可，
    调用方（匹配、手动搜索、详情）无需感知差别。
    """

    def __init__(self, client, name: str):
        self.client = client
        self.name = name

    def search(self, query: str, media_type: str = "series",
               season: Optional[int] = None) -> list[Candidate]:
        try:
            if self.name == "tmdb":
                return self.client.search_tmdb(query, media_type)
            fn = getattr(self.client, "search_" + self.name, None)
            return list(fn(query)) if fn else []
        except Exception:
            return []

    def detail(self, sid: str) -> Optional[dict]:
        fn = getattr(self.client, "detail_" + self.name, None)
        if fn:
            try:
                return fn(sid)
            except Exception:
                return None
        return None

    def identify(self, cand: Candidate, media_type: str,
                 aliases: tuple[str, ...] = ()) -> dict:
        try:
            return self.client.resolve_ids(cand, media_type, aliases) or {}
        except Exception:
            return {}


def builtin(metadata_client, name: str) -> Optional[SourceAdapter]:
    """取内置四个来源的适配器（都通过 `ClientAdapter` 转发）。"""
    if name not in ("bangumi", "douban", "imdb", "tmdb"):
        return None
    return ClientAdapter(metadata_client, name)
