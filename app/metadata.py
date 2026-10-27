# -*- coding: utf-8 -*-
"""豆瓣 / IMDb / Bangumi（可选 TMDB）元数据搜索与匹配。

设计要点：
- 豆瓣 subject_suggest 经常限流返回空数组，必须限速 + 缓存，并允许降级。
- Bangumi 对日番/国产动画/美漫的中文名、日文原名、别名最可靠，用作“锚点”；
  再用别名去 IMDb 找 tt 号，解决中文名在 IMDb 搜不到的问题。
- 季条目（例如“庆余年 第二季”）会额外解析出主剧名和首播年份，
  因为海报墙需要的是“庆余年 (2019) / Season 02”，而不是“庆余年 第二季 (2024)”。
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import unicodedata
from typing import Callable, Optional
from urllib.parse import quote

import requests
from rapidfuzz import fuzz
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import decider, scoring
from .models import Candidate, MatchResult, ParsedName

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BANGUMI_UA = "AutoRename115/0.1 (local desktop tool)"

# ------------------------------------------------------------ 文本工具
# 实现已迁到 app/textnorm.py（纯文本，无网络/无缓存）；这里保留同名对象，
# 既有 `from app.metadata import norm_title / fuzzy_queries ...` 不受影响。
from .textnorm import (  # noqa: E402  （放在常量之后，保持原文件布局）
    RE_CJK, RE_KANA, RE_SEASON_NUM, RE_SEASON_SUFFIX, SEASON_SUFFIXES,
    _BOOK_WORDS, _CN_DIGITS, candidate_season, cn_season_number,
    dedupe_str as _dedupe_str, douban_title_parts, extract_latin_aliases,
    fuzzy_queries, has_kana, is_generic_episode_title, norm_title,
    strong_titles_agree, strip_season_and_subtitle, strip_season_markers,
    titles_agree,
)


class MetadataClient:
    def __init__(self, cache_path: str,
                 log: Optional[Callable[[str], None]] = None,
                 tmdb_key: str = "", use_bangumi: bool = True,
                 douban_delay: float = 2.2):
        self.cache_path = cache_path
        self.log = log or (lambda s: None)
        self.tmdb_key = (tmdb_key or "").strip()
        self.use_bangumi = use_bangumi
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA,
                                     "Accept": "application/json, text/plain, */*"})
        # 网络偶尔被重置/SSL EOF，GET 自动重试两次
        retry = Retry(total=2, connect=2, read=2, backoff_factor=0.6,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET"]))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.cache: dict = {}
        self.delays = {"douban": douban_delay, "imdb": 0.7,
                       "bangumi": 0.7, "tmdb": 0.3,
                       "bangumi_detail": 0.5}
        self.last_request = {k: 0.0 for k in self.delays}
        self.douban_blocked_until = 0.0
        self._douban_landing_done = False
        self._load_cache()

    # ------------------------------------------------------------ 缓存/限速
    def _load_cache(self) -> None:
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except Exception as e:
            self.log(f"元数据缓存写入失败：{e}")

    def _cache_get(self, key: str, ttl: float):
        item = self.cache.get(key)
        if not item:
            return None
        if time.time() - float(item.get("t", 0)) > ttl:
            return None
        return item

    def _cache_put(self, key: str, data) -> None:
        self.cache[key] = {"t": time.time(), "data": data}

    def _wait(self, source: str) -> None:
        delay = self.delays[source]
        wait = self.last_request[source] + delay - time.time()
        if wait > 0:
            time.sleep(min(wait, 15.0))
        self.last_request[source] = time.time()

    def _get_json(self, url: str, source: str, params=None,
                  referer: str = "", headers=None) -> Optional[dict]:
        self._wait(source)
        h = dict(self.session.headers)
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        try:
            r = self.session.get(url, params=params, headers=h, timeout=18)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            return r.json()
        except Exception as e:
            raise RuntimeError(str(e))

    # ------------------------------------------------------------ 豆瓣
    def _douban_html_search(self, query: str) -> list[Candidate]:
        """subject_suggest 只给 1-2 季时，从豆瓣搜索页补全四季。"""
        self._wait("douban")
        r = self.session.get(
            "https://search.douban.com/movie/subject_search",
            params={"search_text": query, "cat": 1002},
            headers={"Referer": "https://movie.douban.com/",
                     "Accept": "text/html,application/xhtml+xml"},
            timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        m = re.search(r"window\.__DATA__\s*=\s*(\{.*?\});",
                      r.text, re.S)
        if not m:
            raise RuntimeError("搜索页没有结果数据")
        data = json.loads(m.group(1))
        out: list[Candidate] = []
        for it in (data.get("items") or [])[:20]:
            sid = str(it.get("id") or "")
            if not sid:
                um = re.search(r"/subject/(\d+)/", str(it.get("url") or ""))
                sid = um.group(1) if um else ""
            if not sid:
                continue
            title, original, year = douban_title_parts(it.get("title", ""))
            if not title:
                continue
            labels = [str(x.get("text", "")) for x in (it.get("labels") or [])]
            more = str(it.get("more_url") or "")
            abstract = str(it.get("abstract") or "")
            is_tv = ("剧集" in labels or "电视剧" in labels or
                     "is_tv:'1'" in more)
            out.append(Candidate(
                source="douban", title=title, original_title=original,
                year=year, sid=sid, kind="tv" if is_tv else "movie",
                url=str(it.get("url") or ""),
                extra={"img": it.get("cover_url", ""), "labels": labels,
                       "abstract": abstract,
                       "animation": "动画" in abstract,
                       "rating": (it.get("rating") or {}).get("value")}))
        return out

    def search_douban(self, query: str) -> list[Candidate]:
        query = query.strip()
        if not query:
            return []
        # v3：旧缓存里可能只有残缺的 1-2 季且没有动画/真人标记
        key = "douban3:" + query.lower()
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            if cached.get("empty") and time.time() - cached.get("t", 0) > 15 * 60:
                cached = None
            else:
                return [Candidate(**c) for c in cached["data"]]
        if time.time() < self.douban_blocked_until:
            return []
        if not self._douban_landing_done:
            self._douban_landing_done = True
            try:
                self.session.get("https://movie.douban.com/", timeout=12,
                                 headers={"Referer": "https://www.douban.com/"})
            except Exception:
                pass

        out: list[Candidate] = []
        error = ""
        try:
            url = "https://movie.douban.com/j/subject_suggest"
            data = self._get_json(url, "douban", params={"q": query},
                                  referer="https://movie.douban.com/")
            items = data if isinstance(data, list) else []
            for it in items[:12]:
                ep = str(it.get("episode", "") or "")
                kind = "tv" if ep.isdigit() and int(ep) > 0 else "movie"
                year = None
                if str(it.get("year", "")).isdigit():
                    year = int(it["year"])
                out.append(Candidate(
                    source="douban", title=str(it.get("title", "")).strip(),
                    original_title=str(it.get("sub_title", "") or "").strip(),
                    year=year, sid=str(it.get("id", "")), kind=kind,
                    episodes=int(ep) if ep.isdigit() else 0,
                    url=str(it.get("url", "")),
                    extra={"img": it.get("img", "")}))
        except Exception as e:
            error = str(e)

        # subject_suggest 常常只给第一季/第三季；搜索页能一次给全四季。
        if len(out) < 4:
            try:
                extra = self._douban_html_search(query)
                by_sid = {c.sid: c for c in out}
                for c in extra:
                    old = by_sid.get(c.sid)
                    if old is None:
                        out.append(c)
                        by_sid[c.sid] = c
                        continue
                    # subject_suggest 没有“动画/真人”信息，用搜索页补上
                    if isinstance(old.extra, dict) and \
                            isinstance(c.extra, dict):
                        for k, v in c.extra.items():
                            if v not in (None, "", []):
                                old.extra[k] = v
                    if not old.original_title and c.original_title:
                        old.original_title = c.original_title
                    if old.year is None and c.year:
                        old.year = c.year
            except Exception as e:
                error = error or str(e)

        if out:
            self.delays["douban"] = max(2.0, self.delays["douban"] * 0.85)
            self._cache_put(key, [c.__dict__ for c in out])
            return out

        # 两个入口都没结果：短缓存 15 分钟，并放慢
        self.cache[key] = {"t": time.time(), "data": [], "empty": True}
        self.delays["douban"] = min(8.0, self.delays["douban"] * 1.5)
        if error:
            self.douban_blocked_until = time.time() + 60
            self.log(f"豆瓣搜索失败（{query}）：{error}")
        return []

    # ------------------------------------------------------------ IMDb
    def search_imdb(self, query: str) -> list[Candidate]:
        query = query.strip()
        if not query:
            return []
        key = "imdb:" + query.lower()
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return [Candidate(**c) for c in cached["data"]]
        first = query[0].lower()
        if not re.match(r"[a-z0-9]", first):
            first = "x"
        try:
            url = (f"https://v2.sg.media-imdb.com/suggestion/{first}/"
                   f"{quote(query)}.json")
            data = self._get_json(url, "imdb", referer="https://www.imdb.com/") or {}
        except Exception as e:
            self.log(f"IMDb 搜索失败（{query}）：{e}")
            return []
        out: list[Candidate] = []
        for it in (data.get("d") or [])[:12]:
            sid = str(it.get("id", ""))
            if not sid.startswith("tt"):
                continue
            qid = str(it.get("qid", "") or "").lower()
            q = str(it.get("q", "") or "")
            if qid in ("video game", "podcast", "music video"):
                continue
            qlow = q.lower()
            if "movie" in qid or "movie" in qlow:
                kind = "movie"
            elif "series" in qid or qlow.startswith("tv"):
                kind = "tv"
            else:
                kind = "movie"
            year = it.get("y")
            out.append(Candidate(
                source="imdb", title=str(it.get("l", "")).strip(),
                original_title=str(it.get("l", "")).strip(),
                year=int(year) if isinstance(year, int) else None,
                sid=sid, kind=kind, rank=int(it.get("rank", 10 ** 9) or 10 ** 9),
                url=f"https://www.imdb.com/title/{sid}/",
                extra={"qid": qid, "q": q, "via": query}))
        if out:
            self._cache_put(key, [c.__dict__ for c in out])
        return out

    # ------------------------------------------------------------ Bangumi
    def search_bangumi(self, query: str) -> list[Candidate]:
        if not self.use_bangumi:
            return []
        query = query.strip()
        if not query:
            return []
        key = "bangumi:" + query.lower()
        cached = self._cache_get(key, 14 * 86400)
        if cached is not None:
            return [Candidate(**c) for c in cached["data"]]
        try:
            url = ("https://api.bgm.tv/search/subject/" + quote(query)
                   + "?type=2&responseGroup=large&max_results=8")
            data = self._get_json(url, "bangumi", headers={
                "User-Agent": BANGUMI_UA}) or {}
        except Exception as e:
            self.log(f"Bangumi 搜索失败（{query}）：{e}")
            return []
        out: list[Candidate] = []
        for it in (data.get("list") or []):
            name = str(it.get("name", "")).strip()
            name_cn = str(it.get("name_cn", "") or "").strip()
            date = str(it.get("air_date", "") or "")
            year = int(date[:4]) if date[:4].isdigit() and date[:4] != "0000" else None
            out.append(Candidate(
                source="bangumi", title=name_cn or name,
                original_title=name, year=year,
                sid=str(it.get("id", "")), kind="tv",
                episodes=int(it.get("eps", 0) or 0),
                url=f"https://bgm.tv/subject/{it.get('id')}",
                extra={"name_cn": name_cn, "name": name, "aliases": []}))
        if out:
            self._cache_put(key, [c.__dict__ for c in out])
        return out

    @staticmethod
    def normalize_country(value: str) -> str:
        """把 Bangumi/TMDB/目录里的地区写法统一成 jp/cn/us/uk/ca/west。"""
        text = str(value or "").strip()
        if not text:
            return ""
        low = text.lower()
        exact = {
            "jp": "jp", "japan": "jp", "日本": "jp",
            "cn": "cn", "china": "cn", "中国": "cn",
            "中国大陆": "cn", "大陆": "cn", "国产": "cn",
            "us": "us", "usa": "us", "美国": "us", "美漫": "us",
            "uk": "uk", "英国": "uk",
            "ca": "ca", "加拿大": "ca",
            "west": "west", "欧美": "west", "欧洲": "west",
            "fr": "west", "france": "west", "法国": "west",
            "de": "west", "germany": "west", "deutschland": "west",
            "德国": "west",
            "it": "west", "italy": "west", "意大利": "west",
            "es": "west", "spain": "west", "西班牙": "west",
            "nl": "west", "netherlands": "west", "荷兰": "west",
            "se": "west", "sweden": "west", "瑞典": "west",
            "ru": "west", "russia": "west", "俄罗斯": "west",
        }
        if low in exact:
            return exact[low]
        aliases = (
            ("united states of america", "us"), ("united states", "us"),
            ("美国", "us"), ("美漫", "us"),
            ("united kingdom", "uk"), ("great britain", "uk"),
            ("英国", "uk"),
            ("加拿大", "ca"), ("canada", "ca"),
            ("日本", "jp"), ("japan", "jp"),
            ("中国大陆", "cn"), ("中国", "cn"), ("china", "cn"),
            ("国产", "cn"),
            ("欧美", "west"), ("欧洲", "west"), ("europe", "west"),
            ("法国", "west"), ("france", "west"),
            ("德国", "west"), ("germany", "west"),
            ("意大利", "west"), ("italy", "west"),
            ("西班牙", "west"), ("spain", "west"),
            ("荷兰", "west"), ("netherlands", "west"),
            ("瑞典", "west"), ("sweden", "west"),
            ("俄罗斯", "west"), ("russia", "west"),
        )
        # 先按分隔符逐段判断，保留“日本 / 美国”里的先后顺序。
        for part in re.split(r"[\s/、,，;；|]+", low):
            if not part:
                continue
            for key, code in aliases:
                if key in part:
                    return code
        for key, code in aliases:
            if key in low:
                return code
        return ""

    @classmethod
    def _country_from_tags(cls, tags: list[str]) -> str:
        joined = " ".join(str(t) for t in (tags or []))
        if not joined:
            return ""
        if "日本" in joined:
            return "jp"
        if any(t in joined for t in ("中国", "国产", "中国动画", "国产动画")):
            return "cn"
        if any(t in joined for t in ("美国", "美国动画", "美国动漫", "美漫")):
            return "us"
        if any(t in joined for t in ("英国", "英剧", "英国动画")):
            return "uk"
        if "加拿大" in joined:
            return "ca"
        if any(t in joined for t in (
                "欧美", "欧美动画", "欧洲", "法国", "德国", "意大利",
                "西班牙", "荷兰", "瑞典", "俄罗斯")):
            return "west"
        return ""

    def bangumi_detail(self, sid: str) -> dict:
        """取别名/地区/标签。别名是打通 IMDb 的关键（如 庆余年 → Joy of Life）。"""
        if not sid:
            return {}
        key = "bgm_detail:" + str(sid)
        cached = self._cache_get(key, 30 * 86400)
        if cached is not None:
            detail = cached["data"]
            # 旧缓存可能没有 country，或存的是“美国/日本”这种原文：
            # 统一成代码，再用标签兜底（美漫标签也能识别）。
            detail["country"] = self.normalize_country(
                detail.get("country") or "")
            if not detail["country"]:
                detail["country"] = self._country_from_tags(
                    detail.get("tags") or [])
            return detail
        try:
            url = f"https://api.bgm.tv/v0/subjects/{quote(str(sid))}"
            data = self._get_json(url, "bangumi_detail",
                                  headers={"User-Agent": BANGUMI_UA}) or {}
        except Exception as e:
            self.log(f"Bangumi 详情失败（{sid}）：{e}")
            return {}
        aliases: list[str] = []
        country = ""
        for box in (data.get("infobox") or []):
            k = str(box.get("key", ""))
            val = box.get("value")
            vals: list[str] = []
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, dict):
                        vals.append(str(v.get("v", "")))
                    else:
                        vals.append(str(v))
            elif val is not None:
                vals.append(str(val))
            if k in ("别名", "中文名", "日文名"):
                aliases += vals
            elif k == "地区":
                country = self.normalize_country(vals[0] if vals else "")
        tags = [str(t.get("name", "")) for t in (data.get("tags") or [])]
        if not country:
            country = self._country_from_tags(tags)
        aliases += extract_latin_aliases(" ".join(aliases))
        detail = {"aliases": _dedupe_str(aliases), "country": country,
                  "tags": tags, "platform": str(data.get("platform", ""))}
        self._cache_put(key, detail)
        return detail

    # ------------------------------------------------------------ 影片资料
    @staticmethod
    def _clean_html_text(text: str) -> str:
        t = re.sub(r"(?is)<br\s*/?>", "\n", text or "")
        t = re.sub(r"(?is)<[^>]+>", " ", t)
        t = html.unescape(t)
        return re.sub(r"\s+", " ", t).strip()

    def _details_tmdb(self, sid: str, kind: str) -> dict:
        if not self.tmdb_key:
            return {"error": "未配置 TMDB API Key"}
        k = "movie" if kind == "movie" else "tv"
        key = f"details:tmdb:{k}:{sid}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached["data"]
        url = f"https://api.themoviedb.org/3/{k}/{quote(str(sid))}"
        data = self._get_json(url, "tmdb", params={
            "api_key": self.tmdb_key, "language": "zh-CN",
            "append_to_response": "credits"}) or {}
        if not data.get("id"):
            return {"error": "TMDB 没有返回详情"}
        date = str(data.get("first_air_date") or data.get("release_date") or "")
        year = int(date[:4]) if date[:4].isdigit() else None
        rating = data.get("vote_average")
        try:
            rating = round(float(rating), 1) if float(rating or 0) > 0 else None
        except Exception:
            rating = None
        poster_path = str(data.get("poster_path") or "")
        poster = (f"https://image.tmdb.org/t/p/w342{poster_path}"
                  if poster_path else "")
        backdrop_path = str(data.get("backdrop_path") or "")
        fanart = (f"https://image.tmdb.org/t/p/w780{backdrop_path}"
                  if backdrop_path else poster)
        genres = [str(g.get("name") or "") for g in
                  (data.get("genres") or []) if isinstance(g, dict)]
        cast = []
        for c in ((data.get("credits") or {}).get("cast") or [])[:12]:
            name = str(c.get("name") or "").strip()
            char = str(c.get("character") or "").strip()
            if name:
                cast.append(f"{name}（{char}）" if char else name)
        info = {
            "source": "tmdb",
            "title": str(data.get("name") or data.get("title") or "").strip(),
            "year": year,
            "rating": rating,
            "overview": str(data.get("overview") or "").strip(),
            "poster": poster,
            "fanart": fanart,
            "genres": [g for g in genres if g],
            "cast": cast,
        }
        self._cache_put(key, info)
        return info

    def _details_bangumi(self, sid: str) -> dict:
        key = f"details:bangumi:{sid}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached["data"]
        url = f"https://api.bgm.tv/v0/subjects/{quote(str(sid))}"
        data = self._get_json(url, "bangumi_detail",
                              headers={"User-Agent": BANGUMI_UA}) or {}
        if not data.get("id"):
            return {"error": "Bangumi 没有返回详情"}
        rating = (data.get("rating") or {}).get("score")
        try:
            rating = round(float(rating), 1) if float(rating or 0) > 0 else None
        except Exception:
            rating = None
        images = data.get("images") or {}
        poster = str(images.get("large") or images.get("common") or
                     images.get("medium") or "")
        cast: list[str] = []
        for box in (data.get("infobox") or []):
            k = str(box.get("key", ""))
            if k not in ("主演", "声优", "配音", "演员"):
                continue
            val = box.get("value")
            vals = val if isinstance(val, list) else [val]
            for v in vals:
                if isinstance(v, dict):
                    v = v.get("v") or v.get("name") or ""
                v = str(v or "").strip()
                if v and v not in cast:
                    cast.append(v)
        if not cast:
            try:
                chars = self._get_json(
                    f"https://api.bgm.tv/v0/subjects/{quote(str(sid))}/characters",
                    "bangumi_detail",
                    headers={"User-Agent": BANGUMI_UA}) or []
                for ch in (chars if isinstance(chars, list) else [])[:10]:
                    actors = [str(a.get("name") or "").strip()
                              for a in (ch.get("actors") or [])
                              if isinstance(a, dict) and a.get("name")]
                    name = str(ch.get("name") or "").strip()
                    if name and actors:
                        cast.append(f"{name}（{actors[0]}）")
            except Exception:
                pass
        date = str(data.get("date") or "")
        year = int(date[:4]) if date[:4].isdigit() else None
        info = {
            "source": "bangumi",
            "title": str(data.get("name_cn") or data.get("name") or "").strip(),
            "year": year,
            "rating": rating,
            "overview": str(data.get("summary") or "").strip(),
            "poster": poster,
            "fanart": poster,
            "genres": [str(t.get("name")) for t in (data.get("tags") or [])
                       if isinstance(t, dict) and t.get("name")][:8],
            "cast": cast,
        }
        self._cache_put(key, info)
        return info

    def _details_douban(self, sid: str, fallback_poster: str = "",
                        kind: str = "tv") -> dict:
        key = f"details2:douban:{sid}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached["data"]
        # 豆瓣手机接口一次给齐评分/封面/简介/演员；网页版容易跳登录/验证码
        order = ["tv", "movie"] if kind != "movie" else ["movie", "tv"]
        for k in order:
            try:
                data = self._get_json(
                    f"https://m.douban.com/rexxar/api/v2/{k}/"
                    f"{quote(str(sid))}", "douban",
                    referer="https://m.douban.com/") or {}
            except Exception:
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            rating = (data.get("rating") or {}).get("value")
            try:
                rating = round(float(rating), 1) if float(rating or 0) > 0 else None
            except Exception:
                rating = None
            pic = data.get("pic") or {}
            poster = str(data.get("cover_url") or pic.get("large") or
                         pic.get("normal") or fallback_poster or "")
            cast = []
            for a in (data.get("actors") or [])[:12]:
                name = str(a.get("name") if isinstance(a, dict) else a or "").strip()
                if name and name not in cast:
                    cast.append(name)
            year_raw = str(data.get("year") or "")
            year = int(year_raw[:4]) if year_raw[:4].isdigit() else None
            if not year:
                date = str(data.get("release_date") or data.get("pubdate") or "")
                year = int(date[:4]) if date[:4].isdigit() else None
            info = {
                "source": "douban",
                "title": str(data.get("title") or "").strip(),
                "year": year,
                "rating": rating,
                "overview": str(data.get("intro") or "").strip(),
                "poster": poster,
                "fanart": poster,
                "genres": [str(g) for g in (data.get("genres") or []) if g],
                "cast": cast,
            }
            self._cache_put(key, info)
            return info
        url = f"https://movie.douban.com/subject/{quote(str(sid))}/"
        self._wait("douban")
        headers = dict(self.session.headers)
        headers.update({
            "Referer": "https://movie.douban.com/",
            "Accept": "text/html,application/xhtml+xml",
        })
        try:
            r = self.session.get(url, headers=headers, timeout=18)
        except Exception as e:
            return {"error": f"豆瓣详情获取失败：{e}", "poster": fallback_poster}
        if r.status_code != 200:
            return {"error": f"豆瓣详情 HTTP {r.status_code}",
                    "poster": fallback_poster}
        text = r.text
        rating = None
        m = re.search(r'property="v:average"[^>]*>\s*([\d.]+)', text)
        if not m:
            m = re.search(r'class="rating_num"[^>]*>\s*([\d.]+)', text)
        if m:
            try:
                rating = round(float(m.group(1)), 1)
            except Exception:
                rating = None
        overview = ""
        m = re.search(r'<span[^>]+property="v:summary"[^>]*>(.*?)</span>',
                      text, re.S)
        if not m:
            m = re.search(r'<div[^>]+id="link-report-intra"[^>]*>(.*?)</div>',
                          text, re.S)
        if m:
            overview = self._clean_html_text(m.group(1))
        poster = ""
        for tag in re.finditer(r"<img\b[^>]*>", text):
            t = tag.group(0)
            if "v:image" not in t:
                continue
            sm = re.search(r'src="([^"]+)"', t)
            if sm:
                poster = sm.group(1)
                break
        if not poster:
            poster = fallback_poster
        cast = []
        for m in re.finditer(
                r'<a[^>]+(?:rel|property)="v:starring"[^>]*>([^<]+)</a>',
                text):
            name = self._clean_html_text(m.group(1))
            if name and name not in cast:
                cast.append(name)
        tm = re.search(r"<title>(.*?)</title>", text, re.S)
        title = self._clean_html_text(tm.group(1)) if tm else ""
        title = re.sub(r"\s*\(豆瓣\)\s*$", "", title)
        year = None
        m = re.search(
            r'property="v:initialReleaseDate"[^>]+content="(\d{4})',
            text)
        if m:
            year = int(m.group(1))
        if not (rating or overview or cast or
                (title and title not in ("豆瓣", "登录豆瓣"))):
            return {"error": "豆瓣详情被限制（可能需要登录/验证）",
                    "poster": fallback_poster}
        info = {
            "source": "douban",
            "title": title,
            "year": year,
            "rating": rating,
            "overview": overview,
            "poster": poster,
            "cast": cast[:12],
        }
        self._cache_put(key, info)
        return info

    def _details_imdb(self, sid: str) -> dict:
        key = f"details:imdb:{sid}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached["data"]
        self._wait("imdb")
        # IMDb 网页版现在经常返回 202/验证页，改用其 GraphQL 公共端点
        query = (
            'query { title(id: "' + str(sid).replace('"', "") + '") { '
            'titleText { text } releaseYear { year } '
            'ratingsSummary { aggregateRating } '
            'plot { plotText { plainText } } '
            'primaryImage { url } '
            'credits(first: 12) { edges { node { name { nameText { text } } } } } '
            '} }')
        try:
            r = self.session.post(
                "https://api.graphql.imdb.com/", json={"query": query},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "x-imdb-client-name": "imdb-web-next",
                    "x-imdb-user-country": "US",
                    "x-imdb-user-language": "en-US",
                }, timeout=20)
            if r.status_code == 200:
                title = ((r.json().get("data") or {}).get("title") or {})
                title_text = str(((title.get("titleText") or {})
                                  .get("text") or "")).strip()
                if title_text:
                    rating = ((title.get("ratingsSummary") or {})
                              .get("aggregateRating"))
                    try:
                        rating = (round(float(rating), 1)
                                  if float(rating or 0) > 0 else None)
                    except Exception:
                        rating = None
                    plot = ((title.get("plot") or {}).get("plotText") or {})
                    cast = []
                    for edge in ((title.get("credits") or {}).get("edges") or []):
                        name = (((edge.get("node") or {}).get("name") or {})
                                .get("nameText") or {}).get("text")
                        name = str(name or "").strip()
                        if name and name not in cast:
                            cast.append(name)
                    year = ((title.get("releaseYear") or {}).get("year"))
                    info = {
                        "source": "imdb",
                        "title": title_text,
                        "year": int(year) if str(year).isdigit() else None,
                        "rating": rating,
                        "overview": str(plot.get("plainText") or "").strip(),
                        "poster": str((title.get("primaryImage") or {})
                                      .get("url") or ""),
                        "fanart": str((title.get("primaryImage") or {})
                                      .get("url") or ""),
                        "genres": [],
                        "cast": cast,
                    }
                    self._cache_put(key, info)
                    return info
        except Exception:
            pass
        # 最后退回网页 JSON-LD（有的网络环境下 GraphQL 不可用）
        url = f"https://www.imdb.com/title/{quote(str(sid))}/"
        headers = dict(self.session.headers)
        headers.update({
            "Referer": "https://www.imdb.com/",
            "Accept": "text/html,application/xhtml+xml",
        })
        try:
            r = self.session.get(url, headers=headers, timeout=18)
        except Exception as e:
            return {"error": f"IMDb 详情获取失败：{e}"}
        if r.status_code != 200:
            return {"error": f"IMDb 详情 HTTP {r.status_code}"}
        info: dict = {"source": "imdb"}
        for raw in re.findall(
                r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                r.text, re.S):
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, list):
                data = next((x for x in data if isinstance(x, dict)), {})
            if not isinstance(data, dict):
                continue
            rating = (data.get("aggregateRating") or {}).get("ratingValue")
            try:
                rating = round(float(rating), 1) if float(rating or 0) > 0 else None
            except Exception:
                rating = None
            poster = data.get("image")
            if isinstance(poster, dict):
                poster = poster.get("url")
            if isinstance(poster, list):
                poster = poster[0] if poster else ""
            actors = data.get("actor") or []
            if isinstance(actors, dict):
                actors = [actors]
            cast = [str(a.get("name") or "").strip()
                    for a in actors if isinstance(a, dict) and a.get("name")]
            date = str(data.get("datePublished") or "")
            info.update({
                "title": str(data.get("name") or "").strip(),
                "year": int(date[:4]) if date[:4].isdigit() else None,
                "rating": rating,
                "overview": str(data.get("description") or "").strip(),
                "poster": str(poster or ""),
                "cast": cast[:12],
            })
            break
        if not info.get("title"):
            return {"error": "IMDb 页面没有可解析的资料"}
        self._cache_put(key, info)
        return info

    def media_details(self, source: str, sid: str, kind: str = "tv",
                      fallback_poster: str = "",
                      fallback_title: str = "") -> dict:
        """评分/封面/简介/演员；渠道由界面单选决定。"""
        source = (source or "").lower()
        if not sid:
            return {"source": source, "error": "这个渠道没有可用 ID"}
        try:
            if source == "tmdb":
                info = self._details_tmdb(sid, kind)
            elif source == "bangumi":
                info = self._details_bangumi(sid)
            elif source == "douban":
                info = self._details_douban(sid, fallback_poster, kind)
            elif source == "imdb":
                info = self._details_imdb(sid)
            else:
                info = {"error": f"不支持的渠道：{source}"}
        except Exception as e:
            info = {"source": source, "error": str(e)}
        info.setdefault("source", source)
        info.setdefault("title", fallback_title)
        info.setdefault("year", None)
        info.setdefault("rating", None)
        info.setdefault("overview", "")
        info.setdefault("poster", fallback_poster)
        info.setdefault("fanart", info.get("poster") or fallback_poster)
        info.setdefault("genres", [])
        info.setdefault("cast", [])
        return info

    def fetch_image(self, url: str) -> bytes:
        if not url:
            return b""
        headers = dict(self.session.headers)
        headers["Accept"] = "image/avif,image/webp,image/*,*/*;q=0.8"
        if "douban" in url:
            headers["Referer"] = "https://movie.douban.com/"
        elif "bgm.tv" in url or "bangumi" in url:
            headers["Referer"] = "https://bgm.tv/"
        try:
            r = self.session.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
        return b""

    def _enrich_bangumi(self, cands: list[Candidate], limit: int = 2) -> None:
        if not cands:
            return
        ranked = sorted(cands, key=lambda c: c.score, reverse=True)[:limit]
        for c in ranked:
            if c.source != "bangumi" or not c.sid:
                continue
            d = self.bangumi_detail(c.sid)
            if not d:
                continue
            if not isinstance(c.extra, dict):
                c.extra = {}
            aliases = _dedupe_str(list(c.extra.get("aliases") or []) +
                                  list(d.get("aliases") or []))
            c.extra["aliases"] = aliases
            if d.get("country"):
                c.extra["country"] = d["country"]
            c.extra["tags"] = d.get("tags", [])
            platform = str(d.get("platform", "") or "")
            tags = [str(t) for t in (d.get("tags") or [])]
            if platform in ("剧场版", "电影") or \
                    any(t in ("剧场版", "电影", "映画", "动画电影") for t in tags):
                c.kind = "movie"

    def enrich_bangumi(self, cands: list[Candidate],
                       limit: int = 2) -> None:
        """手动搜索用：补齐 Bangumi 地区/标签，并识别剧场版。"""
        self._enrich_bangumi(cands, limit)

    # ------------------------------------------------------------ TMDB（可选）
    @staticmethod
    def _tmdb_country(countries: list[str], lang: str) -> str:
        """TMDB 国家/语言 → 内部地区码；用于动画/真人、美漫/欧美区分。"""
        codes = [str(c).upper() for c in (countries or [])]
        lang = str(lang or "").lower()
        if lang == "ja" or "JP" in codes:
            return "jp"
        if lang in ("zh", "cn") or any(
                c in ("CN", "TW", "HK") for c in codes):
            return "cn"
        if "GB" in codes:
            return "uk"
        if "CA" in codes and "US" not in codes:
            return "ca"
        if "US" in codes:
            return "us"
        # 法/德/意/西等欧洲国家统一归到“欧美”，否则这些 TMDB
        # 结果在手动搜索里会被当成“地区未知”，无法按欧美筛选。
        if any(c in codes for c in (
                "FR", "DE", "IT", "ES", "NL", "BE", "SE", "NO", "DK",
                "FI", "PL", "RU", "IE", "AT", "CH", "PT")):
            return "west"
        if lang == "en":
            return "us"
        if lang in ("fr", "de", "it", "es", "nl", "sv", "no", "da",
                    "fi", "pl", "ru"):
            return "west"
        return ""

    def search_tmdb(self, query: str, media_type: str) -> list[Candidate]:
        if not self.tmdb_key or not query.strip():
            return []
        kind = "tv" if media_type == "series" else "movie"
        # v2：缓存里带上 genre_ids / animation，旧缓存没有分类信息
        key = f"tmdb2:{kind}:{query.lower()}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return [Candidate(**c) for c in cached["data"]]
        try:
            url = f"https://api.themoviedb.org/3/search/{kind}"
            data = self._get_json(url, "tmdb", params={
                "api_key": self.tmdb_key, "query": query,
                "language": "zh-CN", "include_adult": "false"}) or {}
        except Exception as e:
            self.log(f"TMDB 搜索失败（{query}）：{e}")
            return []
        out: list[Candidate] = []
        for it in (data.get("results") or [])[:10]:
            title = it.get("name") if kind == "tv" else it.get("title")
            original = it.get("original_name") if kind == "tv" else it.get("original_title")
            date = it.get("first_air_date") if kind == "tv" else it.get("release_date")
            year = int(str(date)[:4]) if str(date)[:4].isdigit() else None
            genre_ids = []
            for g in (it.get("genre_ids") or []):
                try:
                    genre_ids.append(int(g))
                except Exception:
                    pass
            lang = str(it.get("original_language") or "")
            origin = [str(c) for c in (it.get("origin_country") or [])
                      if c]
            out.append(Candidate(
                source="tmdb", title=str(title or "").strip(),
                original_title=str(original or "").strip(), year=year,
                sid=str(it.get("id", "")), kind=kind,
                url=f"https://www.themoviedb.org/{kind}/{it.get('id')}",
                extra={"lang": lang,
                       "genre_ids": genre_ids,
                       "country": self._tmdb_country(origin, lang),
                       "first_air_date": str(date or ""),
                       "overview": str(it.get("overview") or "").strip(),
                       "vote_average": it.get("vote_average"),
                       "poster_path": str(it.get("poster_path") or ""),
                       # TMDB genre 16 = Animation
                       "animation": 16 in genre_ids}))
        if out:
            self._cache_put(key, [c.__dict__ for c in out])
        return out

    def season_episode_titles(self, tmdb_id: str, season: int) -> dict[int, str]:
        """TMDB 整季单集标题：{episode_number: original_name/name}。"""
        if not self.tmdb_key or not tmdb_id:
            return {}
        try:
            season = int(season)
        except Exception:
            return {}
        key = f"tmdb:season_eps:{tmdb_id}:{season}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return {int(k): str(v) for k, v in cached["data"].items()
                    if not is_generic_episode_title(str(v))}
        try:
            url = (f"https://api.themoviedb.org/3/tv/{quote(str(tmdb_id))}"
                   f"/season/{season}")
            data = self._get_json(url, "tmdb", params={
                "api_key": self.tmdb_key, "language": "zh-CN"}) or {}
        except Exception as e:
            self.log(f"TMDB 单集标题获取失败（{tmdb_id} S{season}）：{e}")
            return {}
        out: dict[int, str] = {}
        for ep in (data.get("episodes") or []):
            num = ep.get("episode_number")
            if not isinstance(num, int):
                continue
            title = str(ep.get("original_name") or ep.get("name") or "").strip()
            if title and not is_generic_episode_title(title):
                out[num] = title
        if out:
            self._cache_put(key, {str(k): v for k, v in out.items()})
        return out

    def tmdb_detail(self, tmdb_id: str, kind: str = "tv") -> Optional[dict]:
        """按 TMDB ID 取标题/年份/地区/类型；先试指定类型，再试另一种。"""
        if not self.tmdb_key or not tmdb_id:
            return None
        kinds = [kind] if kind in ("tv", "movie") else []
        other = "movie" if kind == "tv" else "tv"
        if other not in kinds:
            kinds.append(other)
        for k in kinds:
            # v2：缓存里加入季列表/每季集数，旧缓存没有这些字段。
            key = f"tmdb_detail2:{k}:{tmdb_id}"
            cached = self._cache_get(key, 7 * 86400)
            if cached is not None:
                return cached["data"]
            try:
                url = (f"https://api.themoviedb.org/3/{k}/"
                       f"{quote(str(tmdb_id))}")
                data = self._get_json(url, "tmdb", params={
                    "api_key": self.tmdb_key, "language": "zh-CN",
                    "append_to_response": "external_ids"}) or {}
            except Exception:
                continue
            if not data.get("id"):
                continue
            raw_title = data.get("name") if k == "tv" else data.get("title")
            raw_original = (data.get("original_name") if k == "tv"
                            else data.get("original_title"))
            raw_date = (data.get("first_air_date") if k == "tv"
                        else data.get("release_date"))
            title = str(raw_title or "").strip()
            original = str(raw_original or "").strip()
            date = str(raw_date or "")
            year = int(date[:4]) if date[:4].isdigit() else None
            if k == "tv":
                countries = [str(c) for c in (data.get("origin_country") or [])]
            else:
                countries = [str(c.get("iso_3166_1", ""))
                             for c in (data.get("production_countries") or [])
                             if isinstance(c, dict)]
            lang = str(data.get("original_language") or "")
            country = self._tmdb_country(countries, lang)
            genres = [str(g.get("name", "")) for g in
                      (data.get("genres") or []) if isinstance(g, dict)]
            animation = any("animation" in g.lower() or "动画" in g
                            for g in genres)
            ext = data.get("external_ids") or {}
            seasons: list[dict] = []
            if k == "tv":
                for s in (data.get("seasons") or []):
                    if not isinstance(s, dict):
                        continue
                    num = s.get("season_number")
                    if not isinstance(num, int):
                        continue
                    try:
                        count = int(s.get("episode_count") or 0)
                    except Exception:
                        count = 0
                    seasons.append({
                        "season_number": num,
                        "name": str(s.get("name") or ""),
                        "episode_count": count,
                        "air_date": str(s.get("air_date") or ""),
                    })
                seasons.sort(key=lambda x: x["season_number"])
            info = {"id": str(data.get("id")), "kind": k,
                    "title": title or original, "original_title": original,
                    "year": year, "country": country,
                    "animation": animation, "genres": genres,
                    "imdb_id": str(ext.get("imdb_id") or ""),
                    "seasons": seasons,
                    "number_of_seasons": int(
                        data.get("number_of_seasons") or 0),
                    "number_of_episodes": int(
                        data.get("number_of_episodes") or 0)}
            self._cache_put(key, info)
            return info
        return None

    def tmdb_tv_structure(self, tmdb_id: str) -> dict:
        """TMDB 剧集结构：总季/总集和每季集数。

        只对电视剧有意义；没有 TMDB Key 或请求失败时返回空字典，
        调用方应退回原来的“默认第一季”逻辑。
        """
        if not tmdb_id:
            return {}
        info = self.tmdb_detail(str(tmdb_id), "tv")
        if not info or info.get("kind") != "tv":
            return {}
        return {
            "seasons": list(info.get("seasons") or []),
            "number_of_seasons": int(info.get("number_of_seasons") or 0),
            "number_of_episodes": int(info.get("number_of_episodes") or 0),
        }

    @staticmethod
    def _usable_english_title(title: str) -> bool:
        t = str(title or "").strip()
        return bool(t and re.search(r"[A-Za-z]{2,}", t) and
                    not re.search(r"[㐀-鿿぀-ヿ]", t))

    def tmdb_english_title(self, tmdb_id: str, kind: str = "tv") -> str:
        """取 TMDB 的英文标题（中国电视剧的 zh-CN 标题往往还是中文）。

        依次看 en-US 主标题、alternative_titles、translations(en)。
        例如《庆余年》的主条目在 en-US 下是 "Joy of Life"。
        """
        if not self.tmdb_key or not tmdb_id:
            return ""
        key = f"tmdb_en2:{kind}:{tmdb_id}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return str(cached.get("data") or "")
        k = kind if kind in ("tv", "movie") else "tv"
        found = ""
        try:
            url = f"https://api.themoviedb.org/3/{k}/{quote(str(tmdb_id))}"
            data = self._get_json(url, "tmdb", params={
                "api_key": self.tmdb_key, "language": "en-US",
                "append_to_response": "alternative_titles,translations",
            }) or {}
        except Exception:
            data = {}
        if data.get("id"):
            candidates = [data.get("name") if k == "tv" else data.get("title")]
            for a in ((data.get("alternative_titles") or {}).get("results") or []):
                candidates.append(a.get("title"))
            for tr in ((data.get("translations") or {}).get("translations") or []):
                if str(tr.get("iso_639_1") or "").lower() != "en":
                    continue
                td = tr.get("data") or {}
                candidates.extend([td.get("name"), td.get("title")])
            for c in candidates:
                if self._usable_english_title(c):
                    found = str(c).strip()
                    break
        self._cache_put(key, found)
        return found

    def tmdb_english_by_imdb(self, imdb_id: str, media_type: str = "") -> str:
        """用 IMDb 号从 TMDB 的英文结果里取英文名。"""
        if not self.tmdb_key or not imdb_id:
            return ""
        key = f"tmdb_find_en2:{imdb_id}"
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return str(cached.get("data") or "")
        try:
            url = f"https://api.themoviedb.org/3/find/{quote(str(imdb_id))}"
            data = self._get_json(url, "tmdb", params={
                "api_key": self.tmdb_key, "external_source": "imdb_id",
                "language": "en-US"}) or {}
        except Exception as e:
            self.log(f"TMDB 英文名查询失败（{imdb_id}）：{e}")
            return ""
        order = (["tv", "movie"] if media_type == "series" else
                 ["movie", "tv"] if media_type == "movie" else
                 ["tv", "movie"])
        found = ""
        for k in order:
            arr = data.get(f"{k}_results") or []
            if not arr:
                continue
            item = arr[0]
            name = item.get("name") if k == "tv" else item.get("title")
            if self._usable_english_title(name):
                found = str(name).strip()
                break
            # find 结果没英文名时，再按 id 查一次英文详情
            found = self.tmdb_english_title(str(item.get("id", "")), k)
            if found:
                break
        self._cache_put(key, found)
        return found

    def tmdb_find_by_imdb(self, imdb_id: str,
                          media_type: str = "") -> Optional[dict]:
        """用 IMDb 号在 TMDB 反查 {kind, id}。"""
        if not self.tmdb_key or not imdb_id:
            return None
        key = "tmdb_find:" + str(imdb_id)
        cached = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached.get("data") or None
        try:
            url = f"https://api.themoviedb.org/3/find/{quote(str(imdb_id))}"
            data = self._get_json(url, "tmdb", params={
                "api_key": self.tmdb_key, "external_source": "imdb_id",
                "language": "zh-CN"}) or {}
        except Exception as e:
            self.log(f"TMDB 按 IMDb 号查询失败（{imdb_id}）：{e}")
            return None
        order = (["tv", "movie"] if media_type == "series" else
                 ["movie", "tv"] if media_type == "movie" else
                 ["tv", "movie"])
        result = None
        for k in order:
            arr = data.get(f"{k}_results") or []
            if arr:
                result = {"kind": k, "id": str(arr[0].get("id", ""))}
                break
        self._cache_put(key, result)
        return result

    def match_by_ids(self, imdb_id: str, tmdb_id: str,
                     media_type: str, fallback_title: str = ""
                     ) -> Optional[MatchResult]:
        """原文件名已有 IMDb/TMDB 号时，直接按号解析，减少搜错。"""
        if not (imdb_id or tmdb_id):
            return None
        kind = "tv" if media_type == "series" else "movie"
        info = self.tmdb_detail(tmdb_id, kind) if tmdb_id else None
        if not info and imdb_id:
            found = self.tmdb_find_by_imdb(imdb_id, media_type)
            if found:
                info = self.tmdb_detail(found["id"], found["kind"])
                if info and not info.get("imdb_id"):
                    info["imdb_id"] = imdb_id
        if not info:
            return None
        title = info.get("title") or fallback_title
        original = info.get("original_title") or ""
        year = info.get("year")
        imdb = info.get("imdb_id") or imdb_id or ""
        tmdb = info.get("id") or tmdb_id or ""
        res = MatchResult(
            title_zh=title, title_original=original, year=year,
            imdb_id=imdb, tmdb_id=tmdb,
            series_title=title, series_original_title=original,
            series_year=year, series_imdb_id=imdb,
            country=info.get("country", ""),
            animation=bool(info.get("animation")), confidence=1.0)
        res.notes.append("使用已有的 IMDb/TMDB 编号匹配。")
        if info.get("kind") and info["kind"] != kind:
            res.notes.append("ID 对应的类型与当前任务不同，请核对分类。")
        if fallback_title and title and not strong_titles_agree(
                title, fallback_title):
            if not (original and strong_titles_agree(original, fallback_title)):
                # 旧目录里可能残留了别的剧/某季的 ID（例如 208452）。
                # 这种 ID 不能当锚点，否则会把整部剧改成另一部片。
                self.log(f"忽略与标题不一致的 ID：{tmdb or imdb} "
                         f"({title}) ↔ {fallback_title}")
                return None
        if tmdb:
            res.tmdb = Candidate(
                source="tmdb", title=title, original_title=original,
                year=year, sid=str(tmdb), kind=info.get("kind", ""),
                url=f"https://www.themoviedb.org/{info.get('kind')}/{tmdb}")
        if imdb:
            res.imdb = Candidate(
                source="imdb", title=original or title,
                original_title=original or title, year=year,
                sid=imdb, kind=info.get("kind", ""))
        return res

    # ------------------------------------------------------------ 评分/筛选
    # ------------------------------------------------------------ 评分/筛选
    # 规则本体已迁到 app/scoring.py（纯函数，可单独测试）；
    # 这里保留同名方法，既有调用方与行为不变。

    @staticmethod
    def _candidate_is_animation(cand: Candidate) -> bool:
        return scoring.candidate_is_animation(cand)

    @classmethod
    def _anchor_titles(cls, parsed: ParsedName) -> list[str]:
        return scoring.anchor_titles(parsed)

    @staticmethod
    def _anchor_parts(text: str) -> list[str]:
        return scoring.anchor_parts(text)

    @staticmethod
    def _season_alias(text: str) -> bool:
        return scoring.season_alias(text)

    @staticmethod
    def _candidate_names(cand: Candidate) -> list[str]:
        return scoring.candidate_names(cand)

    @classmethod
    def _combo_anchors(cls, parsed: ParsedName) -> list[str]:
        return scoring.combo_anchors(parsed)

    @staticmethod
    def _names_really_agree(a: str, b: str) -> bool:
        return scoring.names_really_agree(a, b)

    @classmethod
    def _candidate_matches_anchor(cls, cand: Candidate,
                                  anchors: list[str]) -> bool:
        return scoring.candidate_matches_anchor(cand, anchors)

    def _score(self, parsed: ParsedName, cand: Candidate,
               media_type: str) -> float:
        return scoring.score(parsed, cand, media_type)

    @staticmethod
    def _kind_ok(c: Candidate, media_type: str) -> bool:
        return scoring.kind_ok(c, media_type)

    def _pick_primary(self, cands: list[Candidate],
                      media_type: str) -> Optional[Candidate]:
        return scoring.pick_primary(cands, media_type)

    def _pick_imdb(self, cands: list[Candidate], media_type: str,
                   anchor_year: Optional[int],
                   aliases: tuple[str, ...] = ()) -> Optional[Candidate]:
        return scoring.pick_imdb(cands, media_type, anchor_year, aliases)

    # ------------------------------------------------------------ 主剧名
    def _series_identity(self, base: str) -> dict:
        """给“某某 第二季”找回主剧名、首播年份和 IMDb ID。"""
        empty = {"title": base, "year": None, "imdb_id": "",
                 "country": "", "bangumi": None, "douban": None}
        if not base:
            return empty
        syn = ParsedName(raw=base, title=base, queries=[base])
        bg = self.search_bangumi(base)
        for c in bg:
            c.score = self._score(syn, c, "series")
        self._enrich_bangumi(bg, 2)
        for c in bg:
            c.score = self._score(syn, c, "series")
        best_bg = self._pick_primary(bg, "series")

        db: list[Candidate] = []
        best_db = None
        # Bangumi 有明确首播年就够用；否则再问豆瓣要主剧年份
        if not (best_bg and best_bg.year):
            db = self.search_douban(base)
            for c in db:
                c.score = self._score(syn, c, "series")
            best_db = self._pick_primary(db, "series")

        pool = [c for c in (best_bg, best_db) if c]
        # 主剧名要的是“庆余年”而不是“庆余年 第二季”；同分时取首播更早的
        exact = [c for c in pool if norm_title(c.title) == norm_title(base)]
        plain = [c for c in pool if strip_season_markers(c.title) == c.title]
        candidates = exact or plain or pool
        best = max(candidates, key=lambda c: (c.score,
                                              -(c.year or 9999)),
                   default=None)
        if not best:
            return empty

        aliases: list[str] = []
        if best_bg:
            aliases += list(best_bg.extra.get("aliases") or [])
        if best_db and best_db.original_title:
            aliases.append(best_db.original_title)
        aliases += extract_latin_aliases(base)
        aliases = _dedupe_str(aliases)

        imdb_best = None
        if aliases or re.search(r"[A-Za-z]", base):
            imdb_all: list[Candidate] = []
            for q in _dedupe_str(aliases + [base])[:4]:
                imdb_all += self.search_imdb(q)
            for c in imdb_all:
                c.score = self._score(syn, c, "series")
            anchor = best.year or None
            imdb_best = self._pick_imdb(imdb_all, "series", anchor,
                                        tuple(aliases))
            if imdb_best and not anchor:
                # 没有年份时，只接受标题高度一致的 IMDb 结果
                if max(imdb_best.extra.get("title_score", 0),
                       imdb_best.extra.get("alias_title_score", 0)) < 0.9:
                    imdb_best = None

        country = best.extra.get("country", "") if isinstance(best.extra, dict) else ""
        if not country:
            orig = best.original_title or best.title
            if has_kana(orig):
                country = "jp"
        tags: list[str] = []
        if best_bg and isinstance(best_bg.extra, dict):
            tags = list(best_bg.extra.get("tags") or [])
        animation = any("动画" in t for t in tags)
        # 主剧名不能是“第一季/第四季”；若只找到季条目，就用去掉季号的 base。
        best_title = best.title or base
        if candidate_season(best) is not None:
            best_title = base
        # 首播年份取各季里最早的一年，避免 S04 的 2014 盖掉 2012。
        years = [c.year for c in pool if c.year]
        series_year = min(years) if years else (
            imdb_best.year if imdb_best else best.year)
        return {
            "title": best_title,
            "year": series_year,
            "imdb_id": imdb_best.sid if imdb_best else "",
            "country": country,
            "animation": animation,
            "bangumi": best_bg,
            "douban": best_db,
        }

    # ------------------------------------------------------------ 手动选择
    def resolve_ids(self, cand: Candidate, media_type: str) -> dict:
        """手动选中一个搜索结果后，尽量补齐 IMDb/TMDB 标识。

        例如手动选了 Bangumi 的“冰菓”，这里会用它的日文名/别名再找
        IMDb 的 tt 号；已经有对应来源 ID 时直接沿用。
        """
        out = {"imdb_id": "", "tmdb_id": "", "country": "",
               "animation": False,
               "imdb_title": "", "tmdb_title": "", "tmdb_original": ""}
        if not cand:
            return out
        aliases: list[str] = []
        if isinstance(cand.extra, dict):
            aliases += [str(x) for x in (cand.extra.get("aliases") or [])]
            out["country"] = str(cand.extra.get("country") or "")
            out["animation"] = bool(cand.extra.get("animation"))
        if cand.source == "bangumi" and cand.sid:
            detail = self.bangumi_detail(cand.sid)
            aliases += [str(x) for x in (detail.get("aliases") or [])]
            if not out["country"]:
                out["country"] = str(detail.get("country") or "")
            tags = [str(t) for t in (detail.get("tags") or [])]
            if any(k in t for t in tags for k in ("动画", "动漫", "美漫")):
                out["animation"] = True

        queries = _dedupe_str([cand.title, cand.original_title] + aliases)
        parsed = ParsedName(raw=cand.title, title=cand.title,
                            queries=queries or [cand.title], year=cand.year)
        if cand.source == "imdb" and cand.sid.startswith("tt"):
            out["imdb_id"] = cand.sid
            out["imdb_title"] = cand.title or cand.original_title
        else:
            pool: list[Candidate] = []
            for q in queries[:3]:
                pool += self.search_imdb(q)
            for c in pool:
                c.score = self._score(parsed, c, media_type)
            best = self._pick_imdb(pool, media_type, cand.year,
                                   tuple(aliases))
            if best:
                out["imdb_id"] = best.sid
                out["imdb_title"] = best.title or best.original_title

        if cand.source == "tmdb" and cand.sid:
            out["tmdb_id"] = cand.sid
            out["tmdb_title"] = cand.title or cand.original_title
            out["tmdb_original"] = cand.original_title or cand.title
        elif self.tmdb_key:
            pool = self.search_tmdb(cand.title, media_type)
            for c in pool:
                c.score = self._score(parsed, c, media_type)
            best = self._pick_primary(pool, media_type)
            if best:
                out["tmdb_id"] = best.sid
                out["tmdb_title"] = best.title or best.original_title
                out["tmdb_original"] = (best.original_title or best.title)
        return out

    # ------------------------------------------------------------ 匹配
    def search_pool(self, parsed: ParsedName, media_type: str
                    ) -> tuple[list[str], dict[str, list[Candidate]]]:
        """按搜索词把四个来源的候选抓回来（带扩展查询与提前停止）。

        只负责"搜"，不负责"选"；选择交给 app.decider.decide()。
        """
        base_queries = _dedupe_str(parsed.queries or [parsed.title])
        # 一个字（“剧”“番”）搜不出片名：整轮自动搜索直接放弃，
        # 不要退回去用这些词，否则又会搜到“剧场版/京剧猫”之类的错误条目。
        base_queries = [q for q in base_queries if len(norm_title(q)) >= 2]
        # 模糊搜索：主标题 + 英文名 + 第N季/Season N，一次搜全四季。
        queries = fuzzy_queries(base_queries, media_type, parsed.season,
                                parsed.year, limit=6)
        queries = [q for q in queries if len(norm_title(q)) >= 2]
        pools: dict[str, list[Candidate]] = {
            "bangumi": [], "douban": [], "imdb": [], "tmdb": []}
        if not queries:
            return queries, pools

        bangumi_all = pools["bangumi"]
        if self.use_bangumi:
            for q in queries[:2]:
                bangumi_all += self.search_bangumi(q)
        for c in bangumi_all:
            c.score = self._score(parsed, c, media_type)
        self._enrich_bangumi(bangumi_all, 2)

        imdb_queries = list(queries)
        douban_queries = list(queries)
        for b in bangumi_all[:4]:
            # 只让靠谱的 Bangumi 条目扩展搜索词，避免把无关条目的
            # 原名/别名带进 IMDb/豆瓣查询（交叉污染）。
            if b.extra.get("title_score", 0) < 0.8:
                continue
            for t in (b.original_title, b.title):
                if t:
                    imdb_queries.append(t)
            for a in (b.extra.get("aliases") or [])[:4]:
                if a:
                    imdb_queries.append(a)
            if b.title and RE_CJK.search(b.title):
                # 豆瓣用中文名最好找；把可靠的 Bangumi 中文名提到前面，
                # 并补上“第N季”，否则英文名/无季号查询只能搜到残缺季。
                b_base = strip_season_markers(b.title)
                douban_queries[0:0] = fuzzy_queries(
                    [b_base], "series", parsed.season, parsed.year, limit=3)
            elif b.title:
                douban_queries.append(b.title)

        douban_all = pools["douban"]
        for q in _dedupe_str(douban_queries)[:4]:
            got = self.search_douban(q)
            douban_all += got
            if parsed.season is not None and any(
                    candidate_season(c) == parsed.season for c in got):
                break
        for d in douban_all[:4]:
            if d.original_title and d.extra.get("title_score", 0) >= 0.75:
                imdb_queries.append(d.original_title)

        imdb_all = pools["imdb"]
        for q in _dedupe_str(imdb_queries)[:8]:
            imdb_all += self.search_imdb(q)

        if self.tmdb_key:
            for q in queries[:2]:
                pools["tmdb"] += self.search_tmdb(q, media_type)

        for c in bangumi_all + douban_all + imdb_all + pools["tmdb"]:
            c.score = self._score(parsed, c, media_type)
        return queries, pools

    def match(self, parsed: ParsedName, media_type: str,
              category: str = "") -> MatchResult:
        queries, pools = self.search_pool(parsed, media_type)
        if not queries:
            res = MatchResult()
            res.notes.append("搜索词太短（单字或容器名），已跳过自动搜索；"
                             "请右键任务使用“手动搜索”。")
            return res
        res = decider.decide(parsed, media_type, category, pools, self.log)
        decider.identify_series(parsed, media_type, res,
                                self._series_identity)
        return res
