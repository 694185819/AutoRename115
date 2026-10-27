# -*- coding: utf-8 -*-
"""手动季集映射：逐文件修改季/集，检测重复，按总集编号自动分季。

只修改 PlanItem 的预览数据，不直接改 115 网盘。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .episode_versions import analyze_episode_versions
from .models import PlanItem


class EpisodeMappingDialog(tk.Toplevel):
    def __init__(self, parent, planner, plan: PlanItem,
                 on_apply: Callable[[PlanItem], None]):
        super().__init__(parent)
        self.parent = parent
        self.planner = planner
        self.plan = plan
        self.on_apply = on_apply
        self.rows = planner.infer_episode_rows(plan, use_overrides=True)
        self.baseline = {
            r["fid"]: dict(r)
            for r in planner.infer_episode_rows(plan, use_overrides=False)
        }
        self.season_counts = planner.season_counts_for_plan(plan)
        self.by_iid: dict[str, dict] = {}
        self._closed = False

        self.title(f"季集映射 - {plan.display_title or plan.title or '剧集'}")
        self.transient(parent)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_ui()
        self._center(parent)
        try:
            self.grab_set()
        except Exception:
            pass
        self._refresh()

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(10, 8, 10, 2))
        top.pack(fill="x")
        ttk.Label(
            top,
            text="逐文件设置季/集。空白或“未定”表示让程序自动推断；"
                 "这里只影响预览，不会直接修改网盘。",
            foreground="#555", wraplength=940, justify="left").pack(anchor="w")

        table = ttk.Frame(self, padding=(10, 6))
        table.pack(fill="both", expand=True)
        cols = ("file", "season", "episode", "source")
        self.tree = ttk.Treeview(table, columns=cols, show="headings",
                                 selectmode="extended")
        heads = {"file": ("文件", 610), "season": ("季", 70),
                 "episode": ("集", 70), "source": ("来源/状态", 150)}
        for c in cols:
            text, width = heads[c]
            self.tree.heading(c, text=text)
            self.tree.column(c, width=width,
                             anchor="center" if c != "file" else "w")
        vs = ttk.Scrollbar(table, orient="vertical",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("manual", foreground="#176b33")
        self.tree.tag_configure("dup", foreground="#b3261e")
        self.tree.tag_configure("multi", foreground="#1f5fa8")
        self.tree.tag_configure("unmapped", foreground="#a15c00")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())

        controls = ttk.Frame(self, padding=(10, 0, 10, 4))
        controls.pack(fill="x")
        ttk.Label(controls, text="季").pack(side="left")
        self.season_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.season_var,
                  width=5).pack(side="left", padx=(3, 8))
        ttk.Label(controls, text="起始集").pack(side="left")
        self.ep_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.ep_var,
                  width=5).pack(side="left", padx=(3, 8))
        ttk.Button(controls, text="应用到选中（集号递增）",
                   command=self._apply_batch).pack(side="left")
        ttk.Button(controls, text="清除选中映射",
                   command=self._clear_selected).pack(side="left", padx=5)
        ttk.Button(controls, text="总集数自动分季",
                   command=self._auto_total).pack(side="left", padx=(10, 5))
        ttk.Button(controls, text="按文件名重新推断",
                   command=self._reinfer).pack(side="left")

        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, foreground="#555",
                  padding=(10, 0, 10, 2)).pack(fill="x")

        bottom = ttk.Frame(self, padding=(10, 2, 10, 8))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="关闭",
                   command=self._close).pack(side="right")
        self.apply_btn = ttk.Button(bottom, text="应用并重建预览",
                                    command=self._apply)
        self.apply_btn.pack(side="right", padx=6)

    def _center(self, parent) -> None:
        try:
            parent.update_idletasks()
            w, h = 1000, 620
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x = max(0, min(x, sw - w))
            y = max(0, min(y, sh - h))
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(820, 480)
        except Exception:
            self.geometry("1000x620")

    # ------------------------------------------------------------ 显示
    def _current_analysis(self):
        rows = []
        for row in self.rows:
            entry = row.get("entry")
            s, ep = row.get("season"), row.get("episode")
            if entry is not None and s is not None and ep is not None:
                rows.append((entry, int(s), int(ep)))
        return analyze_episode_versions(rows)

    def _refresh(self) -> None:
        selected = {
            self.by_iid[iid]["fid"] for iid in self.tree.selection()
            if iid in self.by_iid
        }
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        analysis = self._current_analysis()
        kinds = {(g.season, g.episode): g.kind for g in analysis.groups}
        for i, r in enumerate(self.rows):
            iid = f"r{i}"
            s, ep = r.get("season"), r.get("episode")
            source = str(r.get("source") or "")
            tags: list[str] = []
            if r.get("manual"):
                tags.append("manual")
            if s is None or ep is None:
                tags.append("unmapped")
            kind = kinds.get((s, ep))
            if kind == "duplicate":
                tags.append("dup")
                source += " · 疑似重复"
            elif kind == "multi_version":
                tags.append("multi")
                source += " · 多版本"
            elif s is None:
                source += " · 未定"
            self.tree.insert(
                "", "end", iid=iid,
                values=(r.get("name", ""),
                        f"{s:02d}" if s is not None else "",
                        f"{ep:02d}" if ep is not None else "",
                        source),
                tags=tuple(tags))
            self.by_iid[iid] = r
        if selected:
            keep = [iid for iid, r in self.by_iid.items()
                    if r["fid"] in selected]
            if keep:
                self.tree.selection_set(keep)
        mapped = sum(1 for r in self.rows
                     if r.get("season") is not None and
                     r.get("episode") is not None)
        unmapped = len(self.rows) - mapped
        multi_files = sum(len(g.fids) for g in analysis.multi_versions)
        dup_files = sum(len(g.fids) for g in analysis.duplicates)
        status = f"已映射 {mapped}/{len(self.rows)}，未定 {unmapped}"
        if multi_files:
            status += f"，多版本 {multi_files} 个文件"
        if dup_files:
            status += f"，疑似重复 {dup_files} 个文件"
        self.status_var.set(status + "。")
        self.apply_btn.configure(
            state="normal" if self.rows else "disabled")

    def _selected_rows(self) -> list[dict]:
        return [self.by_iid[iid] for iid in self.tree.get_children()
                if iid in self.tree.selection() and iid in self.by_iid]

    def _on_select(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        r = rows[0]
        self.season_var.set("" if r.get("season") is None
                            else str(r["season"]))
        self.ep_var.set("" if r.get("episode") is None
                        else str(r["episode"]))

    # ------------------------------------------------------------ 编辑
    @staticmethod
    def _parse_int(value: str, name: str, low: int, high: int) -> Optional[int]:
        text = (value or "").strip()
        if not text:
            return None
        try:
            number = int(text)
        except ValueError:
            raise ValueError(f"{name}必须是数字")
        if not (low <= number <= high):
            raise ValueError(f"{name}应在 {low}-{high} 之间")
        return number

    def _apply_batch(self) -> None:
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo("季集映射", "请先在表格里选择文件。",
                                parent=self)
            return
        try:
            season = self._parse_int(self.season_var.get(), "季", 0, 99)
            start = self._parse_int(self.ep_var.get(), "起始集", 1, 9999)
        except ValueError as exc:
            messagebox.showerror("季集映射", str(exc), parent=self)
            return
        if season is None or start is None:
            messagebox.showinfo("季集映射", "请填写季和起始集。", parent=self)
            return
        for i, row in enumerate(rows):
            row["season"] = season
            row["episode"] = start + i
            row["episode_end"] = None
            row["source"] = "手动"
            row["manual"] = True
        self._refresh()

    def _clear_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        for row in rows:
            base = self.baseline.get(row["fid"])
            if base:
                row["season"] = base.get("season")
                row["episode"] = base.get("episode")
                row["episode_end"] = base.get("episode_end")
                row["source"] = base.get("source")
            row["manual"] = False
        self._refresh()

    def _auto_total(self) -> None:
        positive = sorted((s, c) for s, c in self.season_counts.items()
                          if s > 0 and c > 0)
        if not positive:
            messagebox.showinfo(
                "季集映射",
                "没有 TMDB 季集数据。请先配置 TMDB Key，"
                "或手动填写季/集。", parent=self)
            return
        if not messagebox.askyesno(
                "季集映射",
                "将把所有有集号的文件当作“总集编号”，"
                "按 TMDB 各季集数自动分季。\n"
                "已经写了 Sxx 的文件也会重新映射。\n\n继续？",
                parent=self):
            return
        total = sum(c for _, c in positive)
        mapped = 0
        out_of_range = 0
        for row in self.rows:
            ep = row.get("episode")
            if ep is None:
                continue
            if ep > total:
                out_of_range += 1
                continue
            before = 0
            for season, count in positive:
                if before < ep <= before + count:
                    row["season"] = season
                    row["episode"] = ep - before
                    row["episode_end"] = None
                    row["source"] = "总集分季"
                    row["manual"] = True
                    mapped += 1
                    break
                before += count
        self._refresh()
        if out_of_range:
            messagebox.showwarning(
                "季集映射",
                f"有 {out_of_range} 个文件的集号超过 TMDB 总集数 "
                f"{total}，这些文件没有自动分季。", parent=self)
        if not mapped:
            messagebox.showinfo(
                "季集映射",
                "没有可自动分季的文件；请检查文件是否识别到集号。",
                parent=self)

    def _reinfer(self) -> None:
        self.rows = self.planner.infer_episode_rows(
            self.plan, use_overrides=False)
        self._refresh()

    # ------------------------------------------------------------ 应用
    def _apply(self) -> None:
        overrides: dict[str, tuple[int, int]] = {}
        for row in self.rows:
            s, ep = row.get("season"), row.get("episode")
            if s is None or ep is None:
                continue
            if row.get("manual"):
                overrides[row["fid"]] = (int(s), int(ep))
        analysis = self._current_analysis()
        dup_count = sum(len(g.fids) for g in analysis.duplicates)
        if dup_count and not messagebox.askyesno(
                "季集映射",
                f"有 {dup_count} 个文件规格相同却对应同一季同一集，"
                "疑似重复或错集。\n"
                "继续应用会生成 v2 等区分，并把任务标为需确认。\n\n继续？",
                parent=self):
            return
        self.plan.episode_overrides = overrides
        self.plan.season_override = None
        self.plan.season_confirmed = True
        try:
            self.on_apply(self.plan)
        finally:
            self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
