# -*- coding: utf-8 -*-
"""手动搜索元数据：搜索豆瓣/Bangumi/IMDb/TMDB，选中一条应用标题/年份/ID。"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from typing import Callable, Optional

from rapidfuzz import fuzz

from .metadata import (MetadataClient, candidate_season, fuzzy_queries,
                       norm_title)
from .models import Candidate

SOURCE_LABELS = {
    "douban": "豆瓣",
    "bangumi": "Bangumi",
    "imdb": "IMDb",
    "tmdb": "TMDB",
}
SOURCE_TABS = [
    ("all", "全部"),
    ("douban", "豆瓣"),
    ("bangumi", "Bangumi"),
    ("imdb", "IMDb"),
    ("tmdb", "TMDB"),
]
SOURCE_ORDER = {"bangumi": 0, "douban": 1, "imdb": 2, "tmdb": 3}
COUNTRY_LABELS = {
    "jp": "日本", "cn": "中国", "us": "美国",
    "uk": "英国", "ca": "加拿大", "west": "欧美",
}
MEDIA_FILTERS = [("all", "全部"), ("tv", "剧集"), ("movie", "电影"),
                 ("unknown", "未知")]
CONTENT_FILTERS = [("all", "全部"), ("animation", "动画"),
                   ("live", "真人"), ("unknown", "未知")]
REGION_FILTERS = [("all", "全部")] + list(COUNTRY_LABELS.items()) + \
    [("unknown", "未知")]


def candidate_kind(c: Candidate) -> str:
    """剧集/电影；来源标签能纠正时优先用标签。"""
    extra = c.extra if isinstance(c.extra, dict) else {}
    labels = " ".join(
        [str(x or "") for x in (extra.get("labels") or [])] +
        [str(x or "") for x in (extra.get("tags") or [])])
    if any(k in labels for k in ("剧集", "电视剧", "TV动画", "WEB剧")):
        return "tv"
    if any(k in labels for k in ("电影", "剧场版", "映画", "动画电影")):
        return "movie"
    kind = str(c.kind or "").strip().lower()
    return kind if kind in ("tv", "movie") else ""


def candidate_country(c: Candidate) -> str:
    """从候选结果里提取可确认的地区；没有可靠信息时返回空。"""
    extra = c.extra if isinstance(c.extra, dict) else {}
    code = MetadataClient.normalize_country(str(extra.get("country") or ""))
    if code:
        return code
    for value in list(extra.get("labels") or []) + \
            list(extra.get("tags") or []):
        code = MetadataClient.normalize_country(str(value or ""))
        if code:
            return code
    return ""


def candidate_animation(c: Candidate) -> Optional[bool]:
    """动画 / 真人 / 未知。只信来源明确给出的标记，避免误判。"""
    extra = c.extra if isinstance(c.extra, dict) else {}
    if extra.get("animation") is True:
        return True
    # Bangumi 搜索接口 type=2 本身就是动画条目。
    if c.source == "bangumi":
        return True
    if c.source == "tmdb" and extra.get("animation") is False:
        return False
    text = " ".join(
        [str(x or "") for x in (extra.get("labels") or [])] +
        [str(x or "") for x in (extra.get("tags") or [])] +
        [str(extra.get("abstract") or "")])
    low = text.casefold()
    if any(k in low for k in ("动画", "动漫", "anime", "アニメ")):
        return True
    if "真人" in low:
        return False
    return None


class ManualSearchDialog(tk.Toplevel):
    """非阻塞搜索窗口：网络请求在后台线程，结果通过队列回到界面线程。"""

    def __init__(self, parent, metadata, query: str, media_type: str,
                 on_pick: Callable[[Candidate, dict], None],
                 keywords: Optional[list[str]] = None,
                 season: Optional[int] = None,
                 year: Optional[int] = None):
        super().__init__(parent)
        self.parent = parent
        self.meta = metadata
        self.media_type = media_type
        self.on_pick = on_pick
        self.keywords = [str(k).strip() for k in (keywords or [])
                         if str(k).strip()]
        self.season = season
        self.year = year
        self.q: queue.Queue = queue.Queue()
        self.results: list[Candidate] = []
        self.all_results: list[Candidate] = []
        self.by_iid: dict[str, Candidate] = {}
        self._result_notes: list[str] = []
        self.source_filter_var = tk.StringVar(value="all")
        self.source_tabs: dict[str, ttk.Radiobutton] = {}
        self.media_filter_var = tk.StringVar(value="全部")
        self.content_filter_var = tk.StringVar(value="全部")
        self.region_filter_var = tk.StringVar(value="全部")
        self.filter_hint_var = tk.StringVar(
            value="筛选只使用来源明确给出的信息；未知项可在对应筛选中选“未知”。")
        self._searching = False
        self._applying = False
        self._closed = False
        self._last_query = query
        self._last_queries: list[str] = []

        self.title("手动搜索")
        self.transient(parent)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_ui(query)
        self._update_source_counts()
        self._center(parent)
        try:
            self.grab_set()
        except Exception:
            pass
        self.after(100, self._poll)
        if query.strip():
            self.after(120, self._start_search)

    # ------------------------------------------------------------ 界面
    def _build_ui(self, query: str) -> None:
        pad = {"padx": 6, "pady": 6}
        top = ttk.Frame(self, padding=(8, 8, 8, 2))
        top.pack(fill="x")
        ttk.Label(top, text="搜索词").pack(side="left")
        self.query_var = tk.StringVar(value=query)
        ent = ttk.Entry(top, textvariable=self.query_var, width=40)
        ent.pack(side="left", padx=(4, 10))
        ent.bind("<Return>", lambda e: self._start_search())
        self.search_btn = ttk.Button(top, text="搜索",
                                     command=self._start_search)
        self.search_btn.pack(side="left")
        ttk.Label(top, text="搜索时同时查询全部来源",
                  foreground="#777").pack(side="left", padx=(8, 0))

        # 四个来源固定显示；点一下只看该来源，不会重新联网搜索。
        src = ttk.Frame(self, padding=(8, 0, 8, 4))
        src.pack(fill="x")
        ttk.Label(src, text="来源：", foreground="#555").pack(side="left")
        for key, label in SOURCE_TABS:
            rb = ttk.Radiobutton(
                src, text=label, value=key, variable=self.source_filter_var,
                style="Toolbutton", command=self._on_source_tab)
            rb.pack(side="left", padx=(0, 4))
            self.source_tabs[key] = rb
        ttk.Label(src, text="点击只显示该来源",
                  foreground="#777").pack(side="left", padx=(8, 0))

        if self.keywords:
            kw = ttk.Frame(self, padding=(8, 0, 8, 4))
            kw.pack(fill="x")
            ttk.Label(kw, text="拆分关键词（点击搜索）：",
                      foreground="#555").pack(side="left", anchor="n")
            words = self.keywords[:9]
            total = sum(len(w) for w in words) + 3 * max(0, len(words) - 1)
            lines = max(1, min(5, (total + 49) // 50))
            bg = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
            kw_text = tk.Text(
                kw, height=lines, wrap="word", relief="flat", borderwidth=0,
                highlightthickness=0, padx=0, pady=0, spacing1=1, spacing3=1,
                font=tkfont.nametofont("TkDefaultFont"),
                background=bg, foreground="#222", cursor="hand2",
                takefocus=0, insertwidth=0)
            kw_text.pack(side="left", fill="x", expand=True)
            self.keyword_text = kw_text
            tag_words: dict[str, str] = {}
            for i, word in enumerate(words):
                tag = f"keyword_{i}"
                tag_words[tag] = word
                if i:
                    kw_text.insert("end", "   ·   ")
                kw_text.insert("end", word, tag)
                kw_text.tag_bind(
                    tag, "<Enter>",
                    lambda e, tg=tag: kw_text.tag_configure(tg, underline=True))
                kw_text.tag_bind(
                    tag, "<Leave>",
                    lambda e, tg=tag: kw_text.tag_configure(
                        tg, underline=False))

            def on_keyword_click(event):
                idx = kw_text.index(f"@{event.x},{event.y}")
                for tag in kw_text.tag_names(idx):
                    word = tag_words.get(tag)
                    if word is not None:
                        self._search_keyword(word)
                        return "break"
                return None

            kw_text.bind("<Button-1>", on_keyword_click)
            # 不用 state=disabled：Text 禁用后标签点击事件不会触发。
            # 保持 normal，但拦掉所有按键/粘贴，效果仍是只读。
            kw_text.bind("<Key>", lambda e: "break")
            for seq in ("<<Paste>>", "<<Cut>>", "<<Clear>>",
                        "<<PasteSelection>>"):
                kw_text.bind(seq, lambda e: "break")

        filters = ttk.Frame(self, padding=(8, 0, 8, 4))
        filters.pack(fill="x")
        ttk.Label(filters, text="筛选：", foreground="#555").pack(side="left")
        ttk.Label(filters, text="类型").pack(side="left", padx=(4, 2))
        self.media_box = ttk.Combobox(
            filters, textvariable=self.media_filter_var, state="readonly",
            width=7, values=[v for _, v in MEDIA_FILTERS])
        self.media_box.pack(side="left", padx=(0, 8))
        ttk.Label(filters, text="内容").pack(side="left", padx=(0, 2))
        self.content_box = ttk.Combobox(
            filters, textvariable=self.content_filter_var, state="readonly",
            width=7, values=[v for _, v in CONTENT_FILTERS])
        self.content_box.pack(side="left", padx=(0, 8))
        ttk.Label(filters, text="地区").pack(side="left", padx=(0, 2))
        self.region_box = ttk.Combobox(
            filters, textvariable=self.region_filter_var, state="readonly",
            width=8, values=[v for _, v in REGION_FILTERS])
        self.region_box.pack(side="left", padx=(0, 8))
        ttk.Button(filters, text="重置筛选",
                   command=self._reset_filters).pack(side="left")
        for box in (self.media_box, self.content_box, self.region_box):
            box.bind("<<ComboboxSelected>>",
                     lambda e: self._apply_filters())
        ttk.Label(self, textvariable=self.filter_hint_var,
                  foreground="#777", wraplength=900, anchor="w",
                  justify="left").pack(fill="x", padx=10)

        self.status_var = tk.StringVar(value="输入片名后搜索；也可直接按回车。")
        ttk.Label(self, textvariable=self.status_var,
                  foreground="#555").pack(fill="x", padx=10)

        table = ttk.Frame(self, padding=(8, 4))
        table.pack(fill="both", expand=True)
        cols = ("source", "title", "original", "year", "kind",
                "content", "region", "sid")
        self.tree = ttk.Treeview(table, columns=cols, show="headings",
                                 selectmode="browse")
        widths = {"source": 68, "title": 208, "original": 208,
                  "year": 50, "kind": 50, "content": 58,
                  "region": 58, "sid": 92}
        heads = {"source": "来源", "title": "标题", "original": "原名",
                 "year": "年份", "kind": "类型", "content": "内容",
                 "region": "地区", "sid": "编号"}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c],
                             anchor="center" if c in
                             ("source", "year", "kind", "content", "region")
                             else "w")
        vs = ttk.Scrollbar(table, orient="vertical",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._use_selected())
        self.tree.bind("<Return>", lambda e: self._use_selected())
        self.tree.bind("<<TreeviewSelect>>",
                       lambda e: self._update_detail())

        detail = ttk.Frame(self, padding=(8, 0, 8, 4))
        detail.pack(fill="x")
        self.detail_var = tk.StringVar(
            value="选择一条结果，可查看地区、首播/上映日期和简介。")
        ttk.Label(detail, textvariable=self.detail_var,
                  foreground="#555", wraplength=900,
                  justify="left").pack(anchor="w")

        bottom = ttk.Frame(self, padding=(8, 4, 8, 8))
        bottom.pack(fill="x")
        ttk.Label(bottom,
                  text="双击结果或点“使用选中结果”。应用时会自动尝试补齐 "
                       "IMDb/TMDB 标识；当前分类不会被自动改动。",
                  foreground="#777").pack(side="left")
        self.use_btn = ttk.Button(bottom, text="使用选中结果",
                                  command=self._use_selected, state="disabled")
        self.use_btn.pack(side="right")
        ttk.Button(bottom, text="关闭",
                   command=self._close).pack(side="right", padx=6)

    def _center(self, parent) -> None:
        try:
            parent.update_idletasks()
            w, h = 940, 620
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x = max(0, min(x, sw - w))
            y = max(0, min(y, sh - h))
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(780, 500)
        except Exception:
            self.geometry("940x620")

    # ------------------------------------------------------------ 搜索
    def _on_source_tab(self) -> None:
        """切换来源只过滤当前结果；还没搜索过时顺手发起一次搜索。"""
        self._apply_filters()
        if not self.all_results and not self._searching and \
                self.query_var.get().strip():
            self._start_search()

    def _update_source_counts(self) -> None:
        counts: dict[str, int] = {}
        for c in self.all_results:
            counts[c.source] = counts.get(c.source, 0) + 1
        total = len(self.all_results)
        for key, label in SOURCE_TABS:
            button = self.source_tabs.get(key)
            if button is None:
                continue
            count = total if key == "all" else counts.get(key, 0)
            button.configure(text=f"{label} ({count})")

    def _search_keyword(self, text: str) -> None:
        if self._searching or self._applying or self._closed:
            return
        self.query_var.set(text)
        self._start_search()

    def _start_search(self) -> None:
        if self._searching or self._applying or self._closed:
            return
        query = self.query_var.get().strip()
        if not query:
            self.status_var.set("请输入搜索词。")
            return
        self._last_query = query
        queries = fuzzy_queries([query] + self.keywords, self.media_type,
                                self.season, self.year, limit=8)
        self._last_queries = queries or [query]
        self._searching = True
        self.search_btn.configure(state="disabled")
        self.use_btn.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.results = []
        self.all_results = []
        self.by_iid = {}
        self._result_notes = []
        self._update_source_counts()
        self.detail_var.set("搜索中…")
        self.status_var.set(f"模糊搜索中…（{len(self._last_queries)} 组关键词）")

        def worker():
            found: list[Candidate] = []
            notes: list[str] = []

            def run_many(label: str, fn, max_queries: int):
                self.q.put(("status", f"{label} 模糊搜索中…"))
                got_all: list[Candidate] = []
                seen: set = set()
                error = ""
                for q in self._last_queries[:max_queries]:
                    try:
                        got = fn(q) or []
                    except Exception as e:
                        error = str(e)
                        continue
                    for c in got:
                        key = ((c.source, c.sid) if c.sid else
                               (c.source, norm_title(c.title), c.year))
                        if key in seen:
                            continue
                        seen.add(key)
                        got_all.append(c)
                    if self.season is not None and any(
                            candidate_season(c) == self.season for c in got):
                        break
                if got_all:
                    found.extend(got_all)
                    notes.append(f"{label} {len(got_all)}")
                elif error:
                    notes.append(f"{label} 失败：{error}")
                else:
                    notes.append(f"{label} 0")

            if getattr(self.meta, "use_bangumi", True):
                run_many("Bangumi", self.meta.search_bangumi, 3)
            else:
                notes.append("Bangumi 已关闭")
            run_many("IMDb", self.meta.search_imdb, 4)
            run_many("豆瓣", self.meta.search_douban, 4)
            if getattr(self.meta, "tmdb_key", ""):
                run_many("TMDB", lambda q: self.meta.search_tmdb(
                    q, self.media_type), 2)
            else:
                notes.append("未配置 TMDB Key")
            # Bangumi 搜索结果本身没有地区/平台字段；补齐后地区筛选和
            # “动画电影/剧集”判断才准确。详情有 30 天缓存。
            bg = [c for c in found if c.source == "bangumi" and c.sid]
            enrich = getattr(self.meta, "enrich_bangumi", None)
            if bg and callable(enrich):
                self.q.put(("status", "补充 Bangumi 地区/类型…"))
                try:
                    enrich(bg, limit=6)
                except Exception:
                    pass
            try:
                self.meta.save_cache()
            except Exception:
                pass
            self.q.put(("results", found, notes))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _filter_key(value: str, pairs) -> str:
        return next((k for k, label in pairs if label == value), pairs[0][0])

    def _filter_state(self) -> tuple[str, str, str]:
        return (self._filter_key(self.media_filter_var.get(), MEDIA_FILTERS),
                self._filter_key(self.content_filter_var.get(),
                                 CONTENT_FILTERS),
                self._filter_key(self.region_filter_var.get(), REGION_FILTERS))

    def _reset_filters(self) -> None:
        self.source_filter_var.set("all")
        self.media_filter_var.set("全部")
        self.content_filter_var.set("全部")
        self.region_filter_var.set("全部")
        self._apply_filters()

    def _show_results(self, found: list[Candidate],
                      notes: Optional[list[str]] = None) -> None:
        self._searching = False
        if self._closed:
            return
        self.search_btn.configure(state="normal")
        self._result_notes = list(notes or [])
        if not self._last_queries:
            self._last_queries = [self._last_query]
        # 先按和拆分关键词的相似度排，再按 Bangumi → 豆瓣 → IMDb → TMDB、年份
        query_norms = [norm_title(q) for q in
                       ([self._last_query] + self.keywords + self._last_queries)
                       if norm_title(q)]

        def relevance(c: Candidate) -> float:
            vals = []
            for t in (c.title, c.original_title):
                tn = norm_title(t)
                if not tn:
                    continue
                if query_norms:
                    vals.append(max(fuzz.WRatio(qn, tn) / 100.0
                                    for qn in query_norms))
            best = max(vals) if vals else 0.0
            cs = candidate_season(c)
            if self.season is not None and cs is not None:
                best += 0.10 if cs == self.season else -0.30
            if self.year and c.year:
                d = abs(self.year - c.year)
                if d == 0:
                    best += 0.04
                elif d > 2:
                    best -= 0.08
            return best

        self.all_results = sorted(
            found, key=lambda c: (-relevance(c),
                                  SOURCE_ORDER.get(c.source, 9),
                                  -(c.year or 0), c.title or ""))
        self.results = []
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        self._update_source_counts()
        self.detail_var.set("选择一条结果，可查看地区、首播/上映日期和简介。")
        if not self.all_results:
            self.status_var.set(
                "没有找到结果；试试日文名/英文名，或换个关键词。")
            self.use_btn.configure(state="disabled")
            return
        self._apply_filters()

    def _apply_filters(self) -> None:
        if self._closed or not self.all_results:
            return
        previous = self._selected_candidate()
        previous_key = ((previous.source, previous.sid) if previous else None)
        source = self.source_filter_var.get()
        source_label = SOURCE_LABELS.get(source, "全部")
        source_pool = [c for c in self.all_results
                       if source == "all" or c.source == source]
        media, content, region = self._filter_state()
        other_active = (media, content, region) != ("all", "all", "all")
        info = {
            id(c): (candidate_kind(c), candidate_animation(c),
                    candidate_country(c))
            for c in source_pool
        }
        unknown_kind = sum(1 for k, _, _ in info.values() if not k)
        unknown_content = sum(1 for _, a, _ in info.values()
                              if a is None)
        unknown_region = sum(1 for _, _, r in info.values() if not r)
        visible: list[Candidate] = []
        for c in source_pool:
            kind, animation, country = info[id(c)]
            if media == "unknown":
                if kind:
                    continue
            elif media != "all" and kind != media:
                continue
            if content == "unknown":
                if animation is not None:
                    continue
            elif content != "all":
                if content == "animation" and animation is not True:
                    continue
                if content == "live" and animation is not False:
                    continue
            if region == "unknown":
                if country:
                    continue
            elif region != "all" and country != region:
                continue
            visible.append(c)
        hidden: list[str] = []
        if media not in ("all", "unknown") and unknown_kind:
            hidden.append(f"类型未知 {unknown_kind} 条")
        if content not in ("all", "unknown") and unknown_content:
            hidden.append(f"内容未知 {unknown_content} 条")
        if region not in ("all", "unknown") and unknown_region:
            hidden.append(f"地区未知 {unknown_region} 条")
        unknown_parts: list[str] = []
        if unknown_kind:
            unknown_parts.append(f"类型未知 {unknown_kind} 条")
        if unknown_content:
            unknown_parts.append(f"内容未知 {unknown_content} 条")
        if unknown_region:
            unknown_parts.append(f"地区未知 {unknown_region} 条")
        if hidden or unknown_parts:
            prefix = ("已隐藏：" + "、".join(hidden) + "；") if hidden else ""
            if unknown_parts:
                suffix = "来源未标注：" + "、".join(unknown_parts)
                suffix += ("；可切换到“未知”查看。"
                           if hidden else "。")
            else:
                suffix = ""
            self.filter_hint_var.set(prefix + suffix)
        else:
            self.filter_hint_var.set(
                "筛选只使用来源明确给出的信息；未知项可在对应筛选中选“未知”。")
        self.results = visible
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        if not visible:
            self.detail_var.set(
                "当前筛选没有结果；可点“重置筛选”查看全部搜索结果。")
            if source != "all":
                self.status_var.set(
                    f"{source_label}：当前筛选没有结果"
                    f"（该来源共 {len(source_pool)} 条）。")
            else:
                self.status_var.set(
                    f"筛选后没有结果（共 {len(self.all_results)} 条）。")
            self.use_btn.configure(state="disabled")
            return
        keep = ""
        for i, c in enumerate(visible):
            iid = f"r{i}"
            self.by_iid[iid] = c
            kind_key, animation, country = info[id(c)]
            kind = "剧集" if kind_key == "tv" else (
                "电影" if kind_key == "movie" else "")
            content_text = ("动画" if animation is True else
                            ("真人" if animation is False else ""))
            region_text = COUNTRY_LABELS.get(country, country.upper()) \
                if country else ""
            self.tree.insert(
                "", "end", iid=iid,
                values=(SOURCE_LABELS.get(c.source, c.source),
                        c.title or "", c.original_title or "",
                        c.year or "", kind, content_text, region_text,
                        c.sid or ""))
            if previous_key and (c.source, c.sid) == previous_key:
                keep = iid
        keep = keep or "r0"
        self.tree.selection_set(keep)
        self.tree.focus(keep)
        self._update_detail()
        counts = "  |  ".join(self._result_notes)
        suffix = f"；{counts}" if counts else ""
        if source != "all" and other_active:
            self.status_var.set(
                f"{source_label}：筛选后显示 {len(visible)}/{len(source_pool)} "
                f"条结果（模糊 {len(self._last_queries)} 组{suffix}）")
        elif source != "all":
            self.status_var.set(
                f"{source_label} 共 {len(visible)} 条结果"
                f"（模糊 {len(self._last_queries)} 组{suffix}）")
        elif other_active:
            self.status_var.set(
                f"筛选后显示 {len(visible)}/{len(source_pool)} 条结果"
                f"（模糊 {len(self._last_queries)} 组{suffix}）")
        else:
            self.status_var.set(
                f"共 {len(visible)} 条结果（模糊 {len(self._last_queries)} 组"
                f"{suffix}）")
        self.use_btn.configure(state="normal")

    def _update_detail(self) -> None:
        c = self._selected_candidate()
        if not c:
            self.detail_var.set(
                "选择一条结果，可查看地区、首播/上映日期和简介。")
            return
        extra = c.extra if isinstance(c.extra, dict) else {}
        parts = []
        kind_key = candidate_kind(c)
        kind = "剧集" if kind_key == "tv" else (
            "电影" if kind_key == "movie" else "")
        parts.append(kind or "类型未知")
        animation = candidate_animation(c)
        parts.append("动画" if animation is True else
                     ("真人" if animation is False else "内容未知"))
        country = candidate_country(c)
        parts.append(COUNTRY_LABELS.get(country, country.upper())
                     if country else "地区未知")
        first = str(extra.get("first_air_date") or "").strip()
        if first:
            parts.append(("上映 " if c.kind == "movie" else "首播 ") + first)
        vote = extra.get("vote_average")
        if isinstance(vote, (int, float)):
            parts.append(f"TMDB {float(vote):.1f}")
        parts.append(SOURCE_LABELS.get(c.source, c.source))
        if c.sid:
            parts.append(f"编号 {c.sid}")
        text = "  |  ".join(parts)
        overview = str(extra.get("overview") or "").strip()
        if len(overview) > 260:
            overview = overview[:259] + "…"
        if overview:
            text += "\n" + overview
        else:
            text += "\n该来源没有提供简介；应用时会继续补齐 IMDb/TMDB 标识。"
        self.detail_var.set(text)

    # ------------------------------------------------------------ 应用
    def _selected_candidate(self) -> Optional[Candidate]:
        sel = self.tree.selection()
        return self.by_iid.get(sel[0]) if sel else None

    def _use_selected(self) -> None:
        if self._searching or self._applying or self._closed:
            return
        cand = self._selected_candidate()
        if not cand:
            messagebox.showinfo("手动搜索", "请先选中一条搜索结果。",
                                parent=self)
            return
        self._applying = True
        self.use_btn.configure(state="disabled")
        self.search_btn.configure(state="disabled")
        self.status_var.set(f"正在补齐标识：{cand.title}…")

        def worker():
            try:
                ids = self.meta.resolve_ids(cand, self.media_type)
            except Exception as e:
                ids = {"imdb_id": "", "tmdb_id": "", "country": ""}
                self.q.put(("log", f"补齐标识失败：{e}"))
            try:
                self.meta.save_cache()
            except Exception:
                pass
            self.q.put(("resolved", cand, ids))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_pick(self, cand: Candidate, ids: dict) -> None:
        if self._closed:
            return
        try:
            self.on_pick(cand, ids or {})
        except Exception as e:
            messagebox.showerror("手动搜索", f"应用失败：{e}", parent=self)
            self._applying = False
            self.use_btn.configure(state="normal")
            self.search_btn.configure(state="normal")
            return
        self._close()

    # ------------------------------------------------------------ 队列
    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "results":
                    self._show_results(msg[1], msg[2] if len(msg) > 2 else [])
                elif kind == "resolved":
                    self._applying = False
                    self._finish_pick(msg[1], msg[2])
                elif kind == "log":
                    try:
                        self.parent.log_threadsafe(msg[1])
                    except Exception:
                        pass
        except queue.Empty:
            pass
        if not self._closed:
            self.after(100, self._poll)

    def _close(self) -> None:
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
