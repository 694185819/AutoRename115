# -*- coding: utf-8 -*-
"""Tkinter 界面：登录 115、浏览目录、分析、预览、应用、撤销。"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import pickle
import queue
import re
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import nfo, qc, qq_channel, updater
from .episode_mapping import EpisodeMappingDialog
from .local import LocalClient, is_valid_local_name
from .manual_search import SOURCE_LABELS, ManualSearchDialog
from .metadata import (MetadataClient, cn_season_number, norm_title,
                       strip_season_markers, titles_agree)
from .models import (Candidate, MatchResult, P115Item, PlanItem, RenameOp)
from .p115 import (MockP115Client, P115AuthError, P115Client, P115Error,
                   P115RateLimitError, RenameResult)
from .parser import parse_name
from .planner import (CATEGORY_LABELS, NamingOptions, Planner, _usable_query,
                      sanitize_name)
from .undo import UndoManager

APP_TITLE = "115 海报墙重命名助手"
# 启动后自动检查一次；运行期间每 2 小时再检查一次。只访问 GitHub，
# 失败时静默记录，不打断正在进行的扫描/改名。
AUTO_UPDATE_DELAY_MS = 5000
AUTO_UPDATE_PERIOD_SECONDS = 2 * 60 * 60
ROLE_LABELS = {
    "show": "剧集文件夹",
    "season": "季目录",
    "episode": "视频",
    "subtitle": "字幕/音轨",
    "movie": "电影",
}
STATUS_LABELS = {
    "auto": "自动",
    "review": "需确认",
    "skip": "跳过",
    "error": "错误",
}
CATEGORY_KEYS = list(CATEGORY_LABELS.keys())
CATEGORY_TO_LABEL = {k: v for k, v in CATEGORY_LABELS.items()}
LABEL_TO_CATEGORY = {v: k for k, v in CATEGORY_LABELS.items()}
SHORT_CATEGORY = {
    "auto": "自动", "jp_anime": "日番", "cn_anime": "国产",
    "us_anime": "美漫", "west_anime": "欧美",
    "tv": "电视剧", "movie": "电影",
}
# 豆瓣 Cookie 的获取提示与填空模板（设置里直接展示，降低上手门槛）
DOUBAN_COOKIE_HINT = (
    "获取方式：Chrome 打开 movie.douban.com 并登录 → F12 → "
    "Application（应用）→ Cookies → https://movie.douban.com，"
    "在右侧列表里找到 dbcl2、bid、ck 三项，把它们的值填进上面的框里即可。\n"
    "格式模板（直接照着填）："
    "dbcl2=这里填dbcl2的值; bid=这里填bid的值; ck=这里填ck的值"
)
import re

DOUBAN_COOKIE_TEMPLATE = (
    "dbcl2=这里填dbcl2的值; bid=这里填bid的值; ck=这里填ck的值")


def clean_douban_cookie(text: str) -> str:
    """把输入框内容清洗成“可保存的 Cookie”。

    输入框预置的是拼接模板（含「这里填dbcl2的值」这类占位符）。
    如果用户没改就保存，绝不能把模板当成真值写进设置——
    否则会把用户原先填好的真实 Cookie 覆盖掉，豆瓣功能直接失效。
    """
    t = str(text or "").strip()
    if not t:
        return ""
    # 含占位符 → 视为“没填”，保存空串（保留原有值）
    if "这里填" in t or ("这里" in t and "的值" in t):
        return ""
    return t


def merge_settings_safely(old: dict, new: dict) -> dict:
    """把新设置合并到旧设置上，但**空值不覆盖已有值**。

    Cookie、TMDB Key 这类内容是用户手填的，一旦被清空很难自己发现；
    而界面上“留空”往往只是表示“这次没改”。所以空串时保留旧值，
    只有用户明确填了新内容才覆盖。
    """
    merged = dict(old or {})
    for k, v in (new or {}).items():
        if v in ("", None) and merged.get(k) not in ("", None):
            continue          # 空值不覆盖已有的非空值
        merged[k] = v
    return merged
# 日番文件夹格式：设置里只提供两种。历史上还有 bdremux_suffix /
# bdremux_no_year 两种写法，planner 仍能识别，但不再出现在下拉框中；
# 旧配置落到这里时按默认“你的风格”处理。
JP_FOLDER_LABELS = {
    "standard": "标准：中文名 (年份) [ID]",
    "bdremux": "[BD-REMUX]中文名 日文名 (年份) [ID]",
    # 不使用专门的日番规则：识别为日番时也按普通剧集规则命名
    "none": "不使用（日番按普通规则命名）",
}
JP_LABEL_TO_KEY = {v: k for k, v in JP_FOLDER_LABELS.items()}

DEFAULT_SETTINGS = {
    "include_imdb_id": True,
    "imdb_id_style": "jellyfin",
    "id_provider": "auto",
    "jp_folder_style": "bdremux",
    "rename_subtitles": True,
    "rename_season_folders": True,
    "nfo_existing": "rename",
    "auto_nfo_after_rename": False,
    "use_bangumi": True,
    "tmdb_key": "",
    "douban_cookie": "",
    "douban_delay": 2.2,
    "login_app": "ios",
    "local_root": "",
    "auto_check_updates": True,
    "update_ignored_version": "",
    "update_last_check": 0,
    # 首次使用（还没有 Cookie）时显示 115 风控提醒；勾选“只显示一次”后
    # 这里变为 True，下次启动不再打扰。
    "risk_notice_dismissed": False,
    # 记住上次分析结果：账号/模式/根目录/视频文件都没变时，重启后直接
    # 恢复等待列表，不必重新联网分析。执行改名或切换根目录后自动作废。
    "remember_plans": True,
}


def fmt_size(n: int) -> str:
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return ""


RE_ANCILLARY_DIR = re.compile(
    r"(?i)^(?:s\d{1,2}|season\s*\d+|第\s*"
    r"[0-9一二三四五六七八九十]+\s*[季期部]|specials?)(?:$|[-_.\s])"
    r"|(?:字幕|音轨|特典|扫图|花絮|subs?|sups?|scans?|extras?|bonus)(?!\w)")


def _is_ancillary_dir_name(name: str) -> bool:
    """季目录/字幕音轨目录：目录名本身不是作品名，搜索时先看上级目录。"""
    return bool(RE_ANCILLARY_DIR.search(name or ""))


def fmt_episodes(plan: PlanItem) -> str:
    pairs = []
    for op in plan.ops:
        if op.role != "episode":
            continue
        m = re.search(r"S(\d+)E(\d+)", op.new_name)
        if m:
            pairs.append((int(m.group(1)), int(m.group(2))))
    if not pairs:
        return ""
    pairs = sorted(set(pairs))
    seasons = sorted({s for s, _ in pairs})
    if len(pairs) == 1:
        s, e = pairs[0]
        return f"S{s:02d}E{e:02d}"
    if len(seasons) == 1:
        e0, e1 = pairs[0][1], pairs[-1][1]
        return f"E{e0:02d}-E{e1:02d}"
    return (f"S{seasons[0]:02d}E{pairs[0][1]:02d}…"
            f"S{seasons[-1]:02d}E{pairs[-1][1]:02d}（{len(pairs)}集）")


class App(tk.Tk):
    def __getattr__(self, name):
        """安全兜底：缺失属性抛 AttributeError，而不是无限递归。

        tkinter.Misc.__getattr__ 在取不到属性时会转去读 self.tk，
        而 self.tk 同样不存在，于是无限递归直到 RecursionError
        （报错就是 “maximum recursion depth exceeded”）。

        getattr(app, "某个还没初始化的属性", 默认值) 是最常见的触发方式：
        测试用 App.__new__ 造半成品实例、或界面在 __init__ 完成前读属性。

        这里直接抛出 AttributeError，语义正确（getattr 会返回默认值），
        也让 hasattr 正常工作。
        """
        raise AttributeError(name)

    def __init__(self, app_dir: str, demo: bool = False):
        super().__init__()
        self.app_dir = app_dir
        self.data_dir = os.path.join(app_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.start_demo = demo
        self.settings = self._load_settings()
        self.client = None
        self.cloud_client = None
        self.local_client: LocalClient | None = None
        self.local_root = str(self.settings.get("local_root") or "")
        self.is_demo = False
        self.is_local = False
        self.busy = False
        self._update_checking = False
        self._update_release: dict | None = None
        self._update_after_id: str | None = None
        self._update_banner_tag = ""
        self.q: queue.Queue = queue.Queue()
        self.plans: list[PlanItem] = []
        self.plan_rows: dict[str, PlanItem] = {}
        self.dir_items: dict[str, P115Item] = {}
        # 记住每个文件夹上次的位置/选中项，返回上一级时恢复
        self.dir_view_state: dict[str, tuple] = {}
        self.path_stack: list[tuple[str, str]] = [("0", "根目录")]
        self.current_cid = "0"
        self.current_item: P115Item | None = None
        self.detail_plan: PlanItem | None = None
        self.undo = UndoManager(self.data_dir)
        # 预览缓存：最近一次成功写盘的时间戳，用于避免重复保存
        self._plans_saved_stamp: float | None = None

        self._init_meta()
        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(250, self._startup)
        if bool(self.settings.get("auto_check_updates", True)):
            self._schedule_update_check(AUTO_UPDATE_DELAY_MS)

    # ------------------------------------------------------------ 基础
    def _load_settings(self) -> dict:
        s = dict(DEFAULT_SETTINGS)
        try:
            p = os.path.join(self.data_dir, "settings.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    s.update(json.load(f))
        except Exception:
            pass
        if s.get("login_app") not in ("ios", "android", "web",
                                      "wechatmini", "alipaymini"):
            s["login_app"] = "ios"
        return s

    def _save_settings(self) -> None:
        p = os.path.join(self.data_dir, "settings.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=1)

    def _pick_browser_profile(self) -> str:
        """挑选带“用户登录态 + 暴力猴”的浏览器配置目录。

        优先级：
        1. 装过暴力猴扩展（jinjaccalgkegednnccohejagnlnfdag）且已有 Cookie 的；
        2. 装过暴力猴的；
        3. 任意带 Default 的配置。
        都没有就返回空串（此时程序走普通标题搜索）。
        """
        base = os.path.join(self.data_dir, "browser_profile")
        vm_id = "jinjaccalgkegednnccohejagnlnfdag"
        best = ""
        best_rank = -1
        try:
            names = sorted(os.listdir(base))
        except Exception:
            return ""
        for name in names:
            prof = os.path.join(base, name)
            default = os.path.join(prof, "Default")
            if not os.path.isdir(default):
                continue
            has_vm = os.path.isdir(os.path.join(default, "Extensions",
                                                vm_id))
            cookie = os.path.join(default, "Cookies")
            has_cookie = os.path.isfile(cookie) and \
                os.path.getsize(cookie) > 1000
            rank = (2 if has_vm and has_cookie else
                    1 if has_vm else 0)
            if rank > best_rank:
                best, best_rank = prof, rank
        return best

    def _init_meta(self) -> None:
        self.meta = MetadataClient(
            os.path.join(self.data_dir, "metadata_cache.json"),
            log=self.log_threadsafe,
            tmdb_key=self.settings.get("tmdb_key", ""),
            use_bangumi=bool(self.settings.get("use_bangumi", True)),
            douban_delay=float(self.settings.get("douban_delay", 2.2)))
        # 豆瓣分集页需要登录 Cookie 才能读“本集中文名”
        self.meta.douban_cookie = str(
            self.settings.get("douban_cookie", "") or "")
        # 豆瓣登录态所在的浏览器配置目录：登录后条目页会显示
        # IMDb / TMDB 关联编号，程序据此直接定位，避免标题模糊匹配。
        # 优先用“装过暴力猴且登录过”的配置，其次才是默认配置。
        self.meta.browser_profile_dir = self._pick_browser_profile()
        self.options = NamingOptions(
            include_imdb_id=bool(self.settings.get("include_imdb_id", True)),
            imdb_id_style=self.settings.get("imdb_id_style", "jellyfin"),
            id_provider=self.settings.get("id_provider", "auto"),
            jp_folder_style=self.settings.get("jp_folder_style", "bdremux"),
            rename_subtitles=bool(self.settings.get("rename_subtitles", True)),
            rename_season_folders=bool(self.settings.get("rename_season_folders", True)),
            name_segment_source=self.settings.get("name_segment_source", "imdb"),
            subtitle_source=self.settings.get("subtitle_source", "auto"),
            include_specs=bool(self.settings.get("include_specs", True)))
        self.planner = Planner(self.meta, self.options, log=self.log_threadsafe)
        # 主界面“命名规则”面板编辑的就是这份草稿；保存后才写回 settings。
        import copy as _copy
        self._draft_options = _copy.copy(self.options)

    # ------------------------------------------------------------ 界面
    @staticmethod
    def _center_window(win, width: int, height: int, parent=None) -> None:
        """把窗口放到屏幕中央；给了 parent 就放到父窗口正中央。"""
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        width = min(width, max(320, sw - 40))
        height = min(height, max(240, sh - 80))
        if parent is not None:
            parent.update_idletasks()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            if pw <= 1 or ph <= 1:
                pw, ph = parent.winfo_reqwidth(), parent.winfo_reqheight()
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
        else:
            x = (sw - width) // 2
            y = (sh - height) // 2
        x = max(0, min(x, sw - width))
        y = max(0, min(y, sh - height))
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _cm_to_px(self, cm: float) -> int:
        """按当前屏幕 DPI 把厘米换算成像素。"""
        try:
            return int(round(self.winfo_fpixels("1i") * cm / 2.54))
        except Exception:
            return int(round(96 * cm / 2.54))

    def _build_ui(self) -> None:
        """组装主界面：各面板分别由 _ui_* 方法构建，便于单独修改。"""
        self._ui_window()
        self._ui_top_bar()
        self._ui_main_split()
        self._ui_left_panel()
        self._ui_right_panel()
        self._ui_status_bar()
        # 界面全部构建完、控件尺寸确定后再居中一次：只在建窗口时居中，
        # 之后内容把窗口撑大时 Tk 会保持左上角不动，窗口就偏了。
        self.after(0, self._center_after_layout)

    def _center_after_layout(self) -> None:
        """按内容的实际需要定窗口大小，并放到屏幕正中。

        窗口比内容大一圈没有意义：越大，拖动时 Tk 要重绘的像素越多
        （实测 1658x1148 → 1280x800 约快 40%）。这里取“内容请求尺寸”
        与最小可用尺寸的较大者，再收敛到屏幕范围内，最后居中。
        """
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            width = max(self.winfo_reqwidth() + 16, 1360)
            height = max(self.winfo_reqheight() + 24, 820)
            width = min(width, sw - 40)
            height = min(height, sh - 80)
            x = max(0, (sw - width) // 2)
            # 略偏上比正中对眼睛更舒服，也避开任务栏
            y = max(0, (sh - height) // 3)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            pass

    def _apply_window_icon(self) -> None:
        """给窗口和任务栏设置图标（资源缺失时静默跳过）。"""
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets")
        ico = os.path.join(base, "icon.ico")
        # 优先用 .ico（Windows 任务栏认它），退回 PNG
        for path in (ico, os.path.join(base, "icon_64.png"),
                     os.path.join(base, "icon_256.png")):
            if not os.path.isfile(path):
                continue
            try:
                if path.endswith(".ico"):
                    self.iconbitmap(default=path)
                else:
                    self._icon_image = tk.PhotoImage(file=path)
                    self.iconphoto(True, self._icon_image)
                return
            except Exception:      # noqa: BLE001
                continue

    def _ui_window(self) -> None:
        """窗口、主题与树形控件样式。"""
        self.title(APP_TITLE)
        self._apply_window_icon()
        # 宽度：在 1280 的基础上左右各加 5cm（按屏幕 DPI 换算）。
        # 高度：右栏内容（任务表 + 选中项详情 + 命名规则面板 + 影片资料 +
        # 运行日志）自然需要约 951px，再加上顶栏与状态栏；在屏幕允许的
        # 范围内尽量给足高度，内容才能完整显示（以前固定 800 + 1cm，
        # 加入命名规则面板后下方被压缩到看不见）。任务表会吃掉多余高度。
        width = 1280 + self._cm_to_px(10)
        screen_h = self.winfo_screenheight()
        height = min(1110 + self._cm_to_px(1), screen_h - 60)
        self._center_window(self, width, height)
        # 最小高度同步放宽，避免缩小窗口后下方再次被压扁
        self.minsize(1000, min(900, self.winfo_screenheight() - 80))
        try:
            self.iconname(APP_TITLE)
        except Exception:
            pass
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 9))
        style.configure("TLabel", font=("Microsoft YaHei UI", 9))

    def _ui_top_bar(self) -> None:
        """顶部栏与更新提示条。"""
        # 顶部
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        self.top_bar = top
        ttk.Label(top, text=APP_TITLE,
                  font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        self.login_label = ttk.Label(top, text="未登录", foreground="#888")
        self.login_label.pack(side="left", padx=(12, 0))
        ttk.Button(top, text="设置", command=self.open_settings).pack(side="right", padx=3)
        ttk.Button(top, text="刷新", command=self.refresh).pack(side="right", padx=3)
        self.demo_btn = ttk.Button(top, text="演示模式", command=self.enable_demo)
        self.demo_btn.pack(side="right", padx=3)
        self.cookie_btn = ttk.Button(top, text="导入 Cookie",
                                     command=self.open_cookie)
        self.cookie_btn.pack(side="right", padx=3)
        self.login_btn = ttk.Button(top, text="登录 115",
                                    command=self.open_login)
        self.login_btn.pack(side="right", padx=3)

        # 更新提示条：发现新版本后从顶部推出来，不阻塞当前操作。
        self.update_banner = tk.Frame(
            self, background="#fff3cd", highlightthickness=0, bd=0)
        self.update_banner_label = tk.Label(
            self.update_banner, text="", background="#fff3cd",
            foreground="#7a4f00", anchor="w", justify="left",
            font=("Microsoft YaHei UI", 9), padx=10)
        self.update_banner_label.pack(
            side="left", fill="x", expand=True, pady=5)
        ttk.Button(self.update_banner, text="忽略此版本",
                   command=self._ignore_update).pack(
                       side="right", padx=(4, 8), pady=3)
        ttk.Button(self.update_banner, text="查看更新",
                   command=self.open_update_notice).pack(
                       side="right", pady=3)


    def _ui_main_split(self) -> None:
        """左右分栏容器。"""
        # 主体
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self.paned = paned
        # 拖动窗口边缘时 Tk 会连续触发 <Configure>；默认每像素都重排整棵
        # 控件树，任务多时会明显卡顿。这里把重排节流到停止拖动之后。
        self._resize_job = None
        self._last_size = (self.winfo_width(), self.winfo_height())
        self.bind("<Configure>", self._on_window_configure)

    def _on_window_configure(self, event) -> None:
        """窗口尺寸变化时记录尺寸，供停手后统一收尾。

        实测结论（Tk 8.6）：重排成本与控件数近似线性，本界面 115 个控件
        约 36~38ms/步，是 Tk 自身布局引擎的开销；试过逐类隐藏控件、
        减少控件数量、更换主题、调整 DPI 缩放、拖动时隐藏或冻结右栏，
        都无法在不影响观感的前提下明显改善（隐藏会闪、冻结反而更慢）。

        因此这里不做任何“偷工减料”的处理，界面在拖动中保持完整可见；
        只避免在同一个尺寸上重复触发收尾逻辑。
        """
        if event.widget is not self:
            return
        size = (event.width, event.height)
        if size == self._last_size:
            return
        self._last_size = size
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(150, self._finish_resize)

    def _suspend_right_panel(self) -> None:
        """保留旧接口（拖动期间不隐藏、不冻结右侧，保证界面始终可见）。"""
        return

    def _finish_resize(self) -> None:
        """拖动结束后的收尾（一次性）。"""
        self._resize_job = None
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _ui_left_panel(self) -> None:
        """左侧：文件来源、导航、目录树与右键菜单。"""
        # 左侧目录：和右侧任务表紧挨着，只留一条细分隔线
        left = ttk.Frame(self.paned)
        self.paned.add(left, weight=2)

        # 文件来源：网盘 / 本地文件夹。放在文件列表正上方。
        mode_bar = ttk.Frame(left)
        mode_bar.pack(fill="x", pady=(0, 3))
        ttk.Label(mode_bar, text="文件来源：").pack(side="left")
        self.mode_var = tk.StringVar(value="cloud")
        self.cloud_mode_btn = ttk.Radiobutton(
            mode_bar, text="网盘模式", value="cloud",
            variable=self.mode_var,
            command=lambda: self._switch_mode("cloud"))
        self.cloud_mode_btn.pack(side="left")
        self.local_mode_btn = ttk.Radiobutton(
            mode_bar, text="本地模式", value="local",
            variable=self.mode_var,
            command=lambda: self._switch_mode("local"))
        self.local_mode_btn.pack(side="left", padx=(4, 0))
        self.choose_local_btn = ttk.Button(
            mode_bar, text="选择文件夹…", command=self.choose_local_root,
            state="disabled")
        self.choose_local_btn.pack(side="left", padx=(8, 4))
        self.local_root_label = ttk.Label(
            mode_bar, text="", foreground="#777", anchor="w")
        self.local_root_label.pack(side="left", fill="x", expand=True)

        nav = ttk.Frame(left)
        nav.pack(fill="x", pady=(0, 4))
        ttk.Button(nav, text="上一级", width=7, command=self.go_up).pack(side="left")
        ttk.Button(nav, text="分析当前目录",
                   command=self.analyze_current).pack(side="right", padx=(4, 0))
        ttk.Button(nav, text="分析选中",
                   command=self.analyze_selected).pack(side="right")
        self.dir_sel_label = ttk.Label(nav, text="", foreground="#176b33")
        self.dir_sel_label.pack(side="right", padx=8)
        self.path_label = ttk.Label(nav, text="根目录", foreground="#333")
        self.path_label.pack(side="left", padx=8, fill="x", expand=True)

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        cols = ("kind", "size")
        self.dir_tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings",
                                     selectmode="extended")
        self.dir_tree.heading("#0", text="名称")
        self.dir_tree.heading("kind", text="类型")
        self.dir_tree.heading("size", text="大小")
        self.dir_tree.column("#0", width=250, minwidth=160)
        self.dir_tree.column("kind", width=56, anchor="center", stretch=False)
        self.dir_tree.column("size", width=74, anchor="e", stretch=False)
        vs = ttk.Scrollbar(tree_frame, orient="vertical", command=self.dir_tree.yview)
        hs = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.dir_tree.xview)
        self.dir_tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.dir_tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.dir_tree.tag_configure("dir", font=("Microsoft YaHei UI", 9, "bold"))
        self.dir_tree.bind("<Double-1>", self._dir_double_click)
        self.dir_tree.bind("<Return>", lambda e: self.analyze_selected())
        # 左键拖动多选 + Ctrl 单击切换 + Shift 连选
        self.dir_tree.bind("<Button-1>", self._dir_press)
        self.dir_tree.bind("<B1-Motion>", self._dir_motion)
        self.dir_tree.bind("<ButtonRelease-1>", self._dir_release)
        self.dir_tree.bind("<<TreeviewSelect>>", self._dir_selection_changed)
        self.dir_tree.bind("<Button-3>", self._dir_context)
        self.dir_tree.bind("<F2>", lambda e: self.rename_dir_item())
        self._dir_anchor: str | None = None
        self._dir_drag = False
        self._dir_last = ""
        self._dir_menu_item: P115Item | None = None
        self._pending_dir_select: tuple[str, str] | None = None

        # 左侧文件/文件夹右键菜单：进入、分析、单独改名、刷新
        self.dir_menu = tk.Menu(self, tearoff=0)
        self.dir_menu.add_command(label="进入文件夹",
                                  command=self._dir_menu_enter)
        self.dir_menu.add_command(label="分析选中",
                                  command=self.analyze_selected)
        self.dir_menu.add_separator()
        self.dir_menu.add_command(label="重命名此项（立即生效）…",
                                  command=self.rename_dir_item)
        self.dir_menu.add_command(label="刷新当前目录",
                                  command=self.refresh)

    def _ui_right_panel(self) -> None:
        """右侧：任务表、详情、影片资料与日志。"""
        # 右侧计划
        right = ttk.Frame(self.paned)
        self.paned.add(right, weight=5)
        self._right_frame = right
        ptool = ttk.Frame(right)
        ptool.pack(fill="x", pady=(0, 4))
        ttk.Button(ptool, text="全选自动项", command=self.select_auto).pack(side="left")
        ttk.Button(ptool, text="全选有操作的",
                   command=self.select_all_ops).pack(side="left", padx=4)
        ttk.Button(ptool, text="全不选", command=self.select_none).pack(side="left", padx=4)
        ttk.Button(ptool, text="切换选中", command=self.toggle_selected).pack(side="left")
        self.apply_btn = ttk.Button(ptool, text="应用选中重命名", command=self.apply_selected)
        self.apply_btn.pack(side="right")
        self.undo_btn = ttk.Button(ptool, text="撤销上一次", command=self.undo_last)
        self.undo_btn.pack(side="right", padx=6)
        ttk.Label(ptool, text="左键拖动 / Ctrl / Shift 多选 · 右键任务可移除",
                  foreground="#777").pack(side="left", padx=12)
        plan_header = ttk.Frame(right)
        plan_header.pack(fill="x", pady=(0, 2))
        ttk.Label(plan_header, text="等待处理的任务", foreground="#333",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        # 进度条放在“等待处理的任务”右侧、任务表上方，靠近实际处理区域
        self.progress_stage = ttk.Label(plan_header, text="",
                                        foreground="#555")
        self.progress_stage.pack(side="left", padx=(16, 6))
        self.progress = ttk.Progressbar(
            plan_header, mode="determinate", length=240)
        self.progress.pack(side="left")
        self.progress_label = ttk.Label(plan_header, text="", width=10)
        self.progress_label.pack(side="left", padx=(6, 0))

        plan_frame = ttk.Frame(right)
        plan_frame.pack(fill="both", expand=True)
        pcols = ("sel", "type", "cat", "current", "new", "season", "ep",
                 "conf", "status")
        self.plan_tree = ttk.Treeview(plan_frame, columns=pcols, show="headings",
                                      selectmode="browse", height=8)
        headings = {
            "sel": ("选", 30), "type": ("类型", 40), "cat": ("分类", 56),
            "current": ("当前名称", 190), "new": ("新名称", 220),
            "season": ("季", 38), "ep": ("集", 68), "conf": ("置信度", 44),
            "status": ("状态", 44),
        }
        for key, (text, width) in headings.items():
            self.plan_tree.heading(key, text=text)
            self.plan_tree.column(key, width=width,
                                  anchor="center" if key in
                                  ("sel", "type", "season", "ep", "conf", "status")
                                  else "w",
                                  stretch=key in ("current", "new"))
        pvs = ttk.Scrollbar(plan_frame, orient="vertical",
                            command=self.plan_tree.yview)
        phs = ttk.Scrollbar(plan_frame, orient="horizontal",
                            command=self.plan_tree.xview)
        self.plan_tree.configure(yscrollcommand=pvs.set, xscrollcommand=phs.set)
        self.plan_tree.grid(row=0, column=0, sticky="nsew")
        pvs.grid(row=0, column=1, sticky="ns")
        phs.grid(row=1, column=0, sticky="ew")
        plan_frame.rowconfigure(0, weight=1)
        plan_frame.columnconfigure(0, weight=1)
        self.plan_tree.tag_configure("auto", foreground="#176b33")
        self.plan_tree.tag_configure("review", foreground="#a15c00")
        self.plan_tree.tag_configure("error", foreground="#b3261e")
        self.plan_tree.tag_configure("skip", foreground="#777777")
        self.plan_tree.bind("<<TreeviewSelect>>", self._plan_selected)
        self.plan_tree.bind("<Button-1>", self._plan_click)
        self.plan_tree.bind("<Button-3>", self._plan_context)
        self.plan_tree.bind("<Delete>", lambda e: self.remove_current_plan())

        self.plan_menu = tk.Menu(self, tearoff=0)
        self.plan_menu.add_command(label="选中 / 取消选中",
                                   command=self.toggle_selected)
        self.plan_menu.add_command(label="手动搜索正确条目",
                                   command=self.open_manual_search)
        self.plan_menu.add_command(label="季集映射…",
                                   command=self.open_episode_mapping)
        self.plan_menu.add_command(label="临时改名（立即生效）…",
                                   command=self.temp_rename)
        self.plan_menu.add_command(label="预览操作", command=self.preview_ops)
        self.plan_menu.add_separator()
        self.plan_menu.add_command(label="从等待列表移除",
                                   command=self.remove_current_plan)
        self.plan_menu.add_separator()
        self.plan_menu.add_command(label="清空等待列表",
                                   command=self.clear_plans)
        self.plan_menu.add_command(label="恢复上次分析结果（不联网）",
                                   command=self.restore_plans_manual)

        # 详情
        detail = ttk.LabelFrame(right, text="选中项详情（可修改标题/年份/季后重新预览；命名格式见下方“命名规则”）",
                                padding=6)
        detail.pack(fill="x", pady=(6, 4))
        row = ttk.Frame(detail)
        row.pack(fill="x")
        ttk.Label(row, text="标题").pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.title_var, width=32).pack(side="left", padx=(3, 10))
        ttk.Label(row, text="年份").pack(side="left")
        self.year_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.year_var, width=7).pack(side="left", padx=(3, 10))
        ttk.Label(row, text="季").pack(side="left")
        self.season_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.season_var, width=5).pack(side="left", padx=(3, 10))
        # 分类下拉已移除：命名格式由主界面“命名规则”面板统一决定，
        # 这里只保留标题/年份/季的修正与预览按钮。
        ttk.Button(row, text="重新生成预览",
                   command=self.rebuild_detail).pack(side="left")
        ttk.Button(row, text="手动搜索",
                   command=self.open_manual_search).pack(side="left", padx=4)
        ttk.Button(row, text="预览操作",
                   command=self.preview_ops).pack(side="left", padx=4)
        self.meta_label = ttk.Label(detail, text="", foreground="#555")
        self.meta_label.pack(fill="x", pady=(4, 0))
        # 顺序：元信息 → 季集映射 → 备注。
        # NFO/图片操作已移出详情区，放到“命名规则”与“影片资料”之间。
        map_row = ttk.Frame(detail)
        map_row.pack(fill="x", pady=(4, 0))
        self.map_btn = ttk.Button(map_row, text="季集映射…",
                                  command=self.open_episode_mapping,
                                  state="disabled")
        self.map_btn.pack(side="left")
        self.map_label = ttk.Label(map_row, text="", foreground="#777")
        self.map_label.pack(side="left", padx=8)
        # 备注常常很长（搜索诊断 + 疑似重复 + 冲突说明），以前直接用 Label
        # 撑开会挤压下方内容；改成固定高度、可滚动的文本框，并放在最后。
        # 备注框直接放在 detail 里（省掉一层只做排版的 Frame）
        self.note_label = tk.Text(
            detail, height=3, wrap="word", foreground="#a15c00",
            background="#fbfaf5", relief="solid", bd=1,
            font=("Microsoft YaHei UI", 9), padx=4, pady=2,
            cursor="arrow")
        note_sb = ttk.Scrollbar(detail, orient="vertical",
                                command=self.note_label.yview)
        self.note_label.configure(yscrollcommand=note_sb.set,
                                  state="disabled")
        note_sb.pack(side="right", fill="y", pady=(4, 0))
        self.note_label.pack(side="left", fill="x", expand=True, pady=(4, 0))
        self.note_label.bind("<MouseWheel>", self._on_note_wheel)
        self._note_sb = note_sb

        # 命名规则：直接放在主界面，改完可以对当前任务立即重建预览。
        naming = ttk.LabelFrame(right, text="命名规则（修改后点“按此规则重建”或重新分析）",
                                padding=6)
        naming.pack(fill="x", pady=(0, 4))
        try:
            from .naming_panel import NamingRulePanel
            self.naming_panel = NamingRulePanel(
                naming, lambda: self._draft_options,
                lambda o: setattr(self, "_draft_options", o))
            self.naming_panel.pack(fill="x")
            ttk.Button(naming, text="保存为默认并重建当前任务",
                       command=self.apply_naming_rule).pack(
                anchor="e", pady=(6, 0))
        except Exception as e:      # noqa: BLE001
            self.naming_panel = None
            ttk.Label(naming, text=f"命名规则面板加载失败：{e}",
                      foreground="#b3261e").pack(anchor="w")

        # NFO/图片操作：放在“命名规则”与“影片资料”之间。
        nfo_row = ttk.Frame(right)
        nfo_row.pack(fill="x", pady=(0, 4))
        ttk.Button(nfo_row, text="保存 NFO/图片",
                   command=self.save_nfo_artwork).pack(side="left")
        ttk.Button(nfo_row, text="清空 NFO/图片…",
                   command=self.clear_nfo_artwork).pack(side="left", padx=6)
        self.auto_nfo_var = tk.BooleanVar(
            value=bool(self.settings.get("auto_nfo_after_rename", False)))
        ttk.Checkbutton(
            nfo_row, text="应用改名后自动存 NFO/图片",
            variable=self.auto_nfo_var,
            command=self._on_auto_nfo_toggle).pack(side="left", padx=(4, 0))
        self.nfo_mode_label = ttk.Label(
            nfo_row, text=self._nfo_mode_text(), foreground="#777")
        self.nfo_mode_label.pack(side="left", padx=8)

        # 影片资料：评分 / 封面 / 简介 / 演员；来源用单选，不用下拉框
        info = ttk.LabelFrame(right, text="影片资料", padding=6)
        info.pack(fill="x", pady=(0, 4))
        self.info_frame = info
        src_row = ttk.Frame(info)
        src_row.pack(fill="x")
        ttk.Label(src_row, text="资料来源").pack(side="left")
        self.info_source_var = tk.StringVar()
        self.info_radios: dict[str, ttk.Radiobutton] = {}
        for key, text in (("douban", "豆瓣"), ("bangumi", "Bangumi"),
                          ("imdb", "IMDb"), ("tmdb", "TMDB")):
            rb = ttk.Radiobutton(src_row, text=text, value=key,
                                 variable=self.info_source_var,
                                 command=self._on_info_source_pick)
            rb.pack(side="left", padx=(8, 0))
            # ttk.Radiobutton 点击「已经选中」的那一项时，有些平台不会
            # 触发 command（值没变）。这里补一条鼠标事件，保证再点一次
            # 一定能走到重搜逻辑。
            rb.bind("<ButtonRelease-1>",
                    lambda e, k=key: self._on_info_source_clicked(k),
                    add="+")
            self.info_radios[key] = rb
        self._attach_info_hint(src_row)
        self.info_status = ttk.Label(src_row, text="", foreground="#777")
        self.info_status.pack(side="left", padx=10)
        # 命名来源：勾选后标题、单集副标题、特别篇顺序都按上面选中的来源取，
        # 不再借用 TMDB。切换来源时自动跟着换。
        self.name_by_source_var = tk.BooleanVar(value=False)
        self.name_by_source_btn = ttk.Checkbutton(
            src_row, text="按此来源命名", variable=self.name_by_source_var,
            command=self._toggle_naming_source)
        self.name_by_source_btn.pack(side="right", padx=(8, 0))

        body = ttk.Frame(info)
        body.pack(fill="x", pady=(5, 0))
        poster_box = tk.Frame(body, width=90, height=130,
                              background="#f0f0f0", relief="groove", bd=1)
        poster_box.pack(side="left", padx=(0, 10))
        poster_box.pack_propagate(False)
        self.info_poster = tk.Label(poster_box, text="封面",
                                    background="#f0f0f0", foreground="#999")
        self.info_poster.pack(fill="both", expand=True)
        self._info_photo = None

        text_box = ttk.Frame(body)
        text_box.pack(side="left", fill="both", expand=True)
        self.info_title_var = tk.StringVar()
        self.info_rating_var = tk.StringVar()
        self.info_title_label = ttk.Label(
            text_box, textvariable=self.info_title_var,
            font=("Microsoft YaHei UI", 10, "bold"))
        self.info_title_label.pack(anchor="w")
        self.info_rating_label = ttk.Label(
            text_box, textvariable=self.info_rating_var,
            foreground="#a15c00", font=("Microsoft YaHei UI", 9, "bold"))
        self.info_rating_label.pack(anchor="w", pady=(1, 2))
        # 简介框直接放进 text_box（省掉一层只做排版的 Frame）
        self.info_overview = tk.Text(
            text_box, height=3, wrap="word",
            font=("Microsoft YaHei UI", 9), state="disabled",
            relief="flat", background="#fbfbfb", foreground="#333")
        ovs = ttk.Scrollbar(text_box, orient="vertical",
                            command=self.info_overview.yview)
        self.info_overview.configure(yscrollcommand=ovs.set)
        ovs.pack(side="right", fill="y")
        self.info_overview.pack(side="left", fill="x", expand=True)
        self.info_cast = ttk.Label(text_box, text="", foreground="#555",
                                   wraplength=820, justify="left")
        self.info_cast.pack(anchor="w", pady=(2, 0))
        self._info_seq = 0
        self._poster_cache: dict[str, bytes] = {}

        # 日志 + 进度
        log_frame = ttk.LabelFrame(right, text="运行日志", padding=3)
        log_frame.pack(fill="both", expand=False, pady=(0, 2))
        self.log_frame = log_frame
        self.log_text = tk.Text(log_frame, height=4, wrap="word",
                                font=("Consolas", 9), state="disabled",
                                background="#fafafa", relief="flat")
        lvs = ttk.Scrollbar(log_frame, orient="vertical",
                            command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lvs.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        lvs.pack(side="right", fill="y")

        # 折叠开关：把“影片资料”和“运行日志”收起后，这些控件会从布局里
        # 移除，Tk 每次窗口缩放要遍历的节点明显变少，拖动更顺。
        # 需要看的时候就展开，展开状态会被记住。
        toggle = ttk.Frame(right)
        toggle.pack(fill="x", pady=(0, 2))
        self._toggle_frame = toggle
        self._info_collapsed = tk.BooleanVar(
            value=bool(self.settings.get("info_panel_collapsed", False)))
        self._log_collapsed = tk.BooleanVar(
            value=bool(self.settings.get("log_panel_collapsed", False)))
        ttk.Checkbutton(toggle, text="收起影片资料",
                        variable=self._info_collapsed,
                        command=self._apply_panel_visibility).pack(side="left")
        ttk.Checkbutton(toggle, text="收起运行日志",
                        variable=self._log_collapsed,
                        command=self._apply_panel_visibility).pack(
            side="left", padx=(10, 0))
        self.after(50, self._apply_panel_visibility)

    def _apply_panel_visibility(self) -> None:
        """按勾选状态挂上/摘下两个折叠区块（摘下后不参与布局）。"""
        for frame, collapsed, packer in (
                (self.info_frame, self._info_collapsed,
                 lambda: self.info_frame.pack(fill="x", pady=(0, 4),
                                              before=self._toggle_frame)),
                (self.log_frame, self._log_collapsed,
                 lambda: self.log_frame.pack(fill="both", expand=False,
                                             pady=(0, 2)))):
            try:
                if collapsed.get():
                    frame.pack_forget()
                elif not frame.winfo_manager():
                    packer()
            except Exception:
                pass
        self.settings["info_panel_collapsed"] = bool(self._info_collapsed.get())
        self.settings["log_panel_collapsed"] = bool(self._log_collapsed.get())

    def _ui_status_bar(self) -> None:
        """底部状态栏与收尾。"""
        status = ttk.Frame(self, padding=(8, 4))
        status.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.after(300, self._set_sash)
        self._refresh_mode_controls()


    def _set_sash(self) -> None:
        # 左栏默认拉宽一些；两栏之间只用 Panedwindow 自带的细分隔条
        try:
            self.paned.sashpos(0, 480)
        except Exception:
            pass

    # ------------------------------------------------------------ 队列
    def post(self, kind: str, payload=None) -> None:
        self.q.put((kind, payload))

    def log_threadsafe(self, text: str) -> None:
        self.post("log", text)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                try:
                    self._handle(kind, payload)
                except Exception as e:
                    self._log(f"界面处理异常：{e}")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    @staticmethod
    def _is_risk_error(text: str) -> bool:
        t = str(text or "")
        return any(k in t for k in (
            "HTTP 405", "应用接口返回异常", "登录检查返回异常",
            "Expecting value", "风控", "请求过于频繁", "接口被拦截",
            "操作太频繁"))

    def _show_task_error(self, payload) -> None:
        """任务异常弹窗：疑似 115 风控时只给等待提醒，不展示原始报错。"""
        raw = str(payload)
        self._log("错误：" + raw)
        if self._is_risk_error(raw):
            messagebox.showwarning(
                APP_TITLE,
                "疑似触发 115 风控，本次操作已暂停。\n\n"
                "建议先等待几分钟到十几分钟，期间不要连续刷新、重试或"
                "反复登录。\n"
                "如果长时间仍然出现，可以在登录窗口换一个设备类型重新扫码"
                "（例如 ios ↔ web）。\n\n"
                "详细错误已记录在运行日志。",
                parent=self)
        else:
            messagebox.showerror(APP_TITLE, raw, parent=self)

    # 后台线程 → 界面的消息路由。每个 kind 对应一个 _on_<kind> 方法；
    # 新增消息类型时只加一行路由，不用再增长 _handle 的 if/elif 链。
    KIND_HANDLERS = {
        "log": "_on_log",
        "busy": "_on_busy",
        "progress": "_on_progress",
        "indeterminate": "_on_indeterminate",
        "listing": "_on_listing",
        "login_check": "_on_login_check",
        "plans": "_on_plans",
        "plans_verified": "_on_plans_verified",
        "qr_token": "_on_qr_token",
        "qr_status": "_on_qr_status",
        "qr_done": "_on_qr_done",
        "qr_expired": "_on_qr_expired",
        "qr_error": "_on_qr_error",
        "cookie_check": "_on_cookie_check",
        "apply": "_on_apply",
        "temp_rename": "_on_temp_rename",
        "dir_rename": "_on_dir_rename",
        "undo": "_on_undo",
        "error": "_on_error",
        "status": "_on_status",
        "update_check": "_on_update_check",
        "media_details": "_on_media_details",
        "nfo_save": "_on_nfo_save",
        "nfo_clear": "_on_nfo_clear",
        "rebuild_done": "_on_rebuild_done",
        "naming_applied": "_on_naming_applied",
        "research_source": "_on_research_source",
        "douban_test": "_on_douban_test",
    }

    def _handle(self, kind: str, payload) -> None:
        """按消息类型分发到 _on_<kind>；未知类型忽略。"""
        name = self.KIND_HANDLERS.get(kind)
        if name:
            getattr(self, name)(payload)

    def _on_log(self, payload) -> None:
        self._log(payload)

    def _on_busy(self, payload) -> None:
        self._set_busy(bool(payload))

    def _on_progress(self, payload) -> None:
        done, total, text = payload
        text = str(text or "")
        if total and total > 0:
            try:
                if str(self.progress.cget("mode")) != "determinate":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                self.progress.configure(
                    maximum=max(1, total),
                    value=min(max(0, done), total))
                self.progress_label.configure(text=f"{done}/{total}")
            except Exception:
                pass
        else:
            # 总数未知：保留当前进度，只更新阶段文字，避免来回抽动
            self.progress_label.configure(text="…")
        short = text if len(text) <= 36 else text[:35] + "…"
        # 详细阶段只显示在“等待处理的任务”右侧的上方进度区，
        # 不再同步到底部状态栏，避免同一句话上下各出现一次。
        self.progress_stage.configure(text=short)

    def _on_indeterminate(self, payload) -> None:
        if payload:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)

    def _on_listing(self, payload) -> None:
        self._set_busy(False)
        cid, items = payload
        # 快速连点“上一级/进入文件夹”时，忽略已经过期的目录响应
        if cid != self.current_cid:
            return
        self._fill_dir_tree(items)
        self.status_var.set(f"已加载 {len(items)} 项")

    def _on_login_check(self, payload) -> None:
        self._set_busy(False)
        # 用户可能在登录检查返回前就切到本地/演示模式，不能把
        # “已登录”状态和刷新动作带到本地目录上。
        if self.is_local or self.is_demo:
            return
        if payload:
            self._set_login_status("已登录", "#176b33")
            # 先恢复上次等待列表，再刷新目录；恢复成功后不能再
            # 立刻发起新的忙碌任务（会互相覆盖进度状态）。
            if self._restore_plans():
                return
            self.refresh()
        else:
            self._set_login_status("登录已失效", "#b3261e")
            self.open_login()

    def _on_plans(self, payload) -> None:
        self.plans = payload
        self._render_plans()
        self._set_busy(False)
        auto = sum(1 for p in self.plans if p.status == "auto")
        review = sum(1 for p in self.plans if p.status == "review")
        self.status_var.set(f"分析完成：{len(self.plans)} 项，可自动 {auto}，需确认 {review}")
        self._log(self.status_var.get())
        self._save_plans_cache()

    def _on_plans_verified(self, payload) -> None:
        ok, reason = payload
        self._set_busy(False)
        if ok:
            self._log("离线恢复完成：文件均仍在原处，可以直接应用重命名。")
            self.status_var.set(
                f"已恢复 {len(self.plans)} 个等待任务（缓存）")
        else:
            self.plans = []
            self._render_plans()
            self._discard_plans_cache()
            self._log(f"预览缓存已作废：{reason}。请重新分析选中。")
            self.status_var.set("缓存已作废，请重新分析")

    def _on_qr_token(self, payload) -> None:
        dialog, token, image = payload
        if dialog.winfo_exists():
            dialog.show_token(token, image)

    def _on_qr_status(self, payload) -> None:
        dialog, status = payload
        if dialog.winfo_exists():
            dialog.show_status(status)

    def _on_qr_done(self, payload) -> None:
        dialog, ok, login_app = payload
        if dialog.winfo_exists():
            dialog.destroy()
        if ok:
            self.settings["login_app"] = login_app
            self._save_settings()
            self._set_login_status("已登录", "#176b33")
            self._log(f"115 扫码登录成功（设备：{login_app}），"
                      "Cookie 已保存，下次启动会自动登录。")
            self.refresh()

    def _on_qr_expired(self, payload) -> None:
        dialog, status = payload
        if dialog.winfo_exists():
            dialog.show_expired(status)

    def _on_qr_error(self, payload) -> None:
        dialog, msg = payload
        if dialog.winfo_exists():
            dialog.show_error(msg)

    def _on_cookie_check(self, payload) -> None:
        dialog, ok, msg = payload
        if dialog.winfo_exists():
            if ok:
                dialog.destroy()
                self._set_login_status("已登录", "#176b33")
                self._log("Cookie 验证成功。")
                self.refresh()
            else:
                dialog.show_error(msg or "Cookie 无效或已过期。")

    def _on_apply(self, payload) -> None:
        ops, results, auto_nfo, nfo_infos = payload
        self._after_apply(ops, results, auto_nfo, nfo_infos)

    def _on_temp_rename(self, payload) -> None:
        plan, old_op, new_op, results = payload
        self._after_temp_rename(plan, old_op, new_op, results)

    def _on_dir_rename(self, payload) -> None:
        item, op, results = payload
        self._after_dir_rename(item, op, results)

    def _on_undo(self, payload) -> None:
        results = payload
        self._after_undo(results)

    def _on_error(self, payload) -> None:
        self._set_busy(False)
        self._show_task_error(payload)

    def _on_status(self, payload) -> None:
        self.status_var.set(str(payload))

    def _on_update_check(self, payload) -> None:
        release, error = payload
        self._on_update_result(release, error)

    def _on_media_details(self, payload) -> None:
        self._show_media_details(*payload)

    def _on_nfo_save(self, payload) -> None:
        self._set_busy(False)
        s = payload
        action = "写入本地" if s.get("local") else "上传"
        msg = (f"NFO/图片保存完成：{action} {s['uploads']}，"
               f"改名 {s['renames']}，删除 {s['deleted']}，"
               f"跳过 {s['skipped']}。")
        self._log(msg)
        messagebox.showinfo(APP_TITLE, msg, parent=self)

    def _on_nfo_clear(self, payload) -> None:
        self._set_busy(False)
        s = payload
        where = "当前文件夹" if s.get("scope") == "current" else "所选任务"
        msg = f"{where}：已移入 115 回收站的 NFO/图片 {s['count']} 个。"
        self._log(msg)
        messagebox.showinfo(APP_TITLE, msg, parent=self)


    # ------------------------------------------------------------ 日志/忙碌
    def _log(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {text}\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 400:
            self.log_text.delete("1.0", f"{lines - 350}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _progress_begin(self, determinate: bool) -> None:
        try:
            self.progress.stop()
            if determinate:
                self.progress.configure(
                    mode="determinate", maximum=1, value=0)
            else:
                self.progress.configure(mode="indeterminate")
                self.progress.start(15)
            self.progress_stage.configure(text="准备中…")
            self.progress_label.configure(text="")
        except Exception:
            pass

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.apply_btn.configure(state=state)
        self.undo_btn.configure(state=state)
        if not busy:
            try:
                self.progress.stop()
                self.progress.configure(
                    mode="determinate", maximum=1, value=0)
            except Exception:
                pass
            self.progress_label.configure(text="")
            self.progress_stage.configure(text="")

    def _set_login_status(self, text: str, color: str = "#888") -> None:
        self.login_label.configure(text=text, foreground=color)

    def run_async(self, fn, success_kind: str = "done",
                  determinate: bool = False) -> None:
        remain_fn = getattr(self.client, "risk_cooldown_remaining", None) \
            if self.client is not None else None
        if callable(remain_fn):
            remain = remain_fn()
            if remain > 0:
                messagebox.showinfo(
                    APP_TITLE,
                    f"115 风控冷却中，请约 {remain} 秒后再试。\n"
                    "期间程序不会继续请求 115，避免被踢下线。",
                    parent=self)
                return
        if self.busy:
            # 不弹窗：连续点按钮时弹窗会堆积并打断操作。
            self._log("上一个任务还在执行，本次操作已跳过。")
            self.status_var.set("有任务在执行，本次操作已跳过")
            return
        self._set_busy(True)
        self._progress_begin(determinate)

        def worker():
            try:
                result = fn()
                self.post(success_kind, result)
            except Exception as e:
                self.post("error", str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ 启动
    def _startup(self) -> None:
        if self.start_demo:
            self.enable_demo()
            return
        if self.is_demo or self.is_local:
            return
        self.cloud_client = P115Client(self.data_dir, log=self.log_threadsafe)
        self.client = self.cloud_client
        if self.cloud_client.cookie_dict():
            self._set_login_status("检查登录…", "#888")
            self.run_async(lambda: self.client.is_logged_in(force=True),
                           "login_check")
        else:
            self._set_login_status("未登录", "#b3261e")
            self._log("请扫码登录 115；也可以关闭登录窗口，点“演示模式”先看效果。")
            self.after(350, self._open_login_after_notice)

    def _open_login_after_notice(self) -> None:
        """首次使用（还没有 Cookie）先提醒风控，再打开扫码窗口。"""
        if self.is_local or self.is_demo:
            return
        if not self.settings.get("risk_notice_dismissed", False):
            dlg = RiskNoticeDialog(self)
            self.wait_window(dlg)
        self.open_login()

    # ------------------------------------------------------------ 文件来源
    def _refresh_mode_controls(self) -> None:
        if self.is_local:
            mode = "local"
        elif self.is_demo:
            mode = "demo"
        else:
            mode = "cloud"
        self.mode_var.set(mode)
        self.choose_local_btn.configure(
            state="normal" if self.is_local else "disabled")
        local_name = ""
        if self.is_local and self.local_root:
            local_name = (os.path.basename(self.local_root.rstrip("\\/"))
                          or self.local_root)
        self.local_root_label.configure(text=local_name)
        # 本地模式不碰 115，把网盘登录入口灰掉，避免误以为在改网盘。
        cloud_state = "disabled" if self.is_local else "normal"
        self.login_btn.configure(state=cloud_state)
        self.cookie_btn.configure(state=cloud_state)
        self.demo_btn.configure(state=cloud_state)
        if hasattr(self, "nfo_mode_label"):
            self.nfo_mode_label.configure(text=self._nfo_mode_text())

    def _discard_plans_for_switch(self) -> bool:
        if not self.plans:
            return True
        return messagebox.askyesno(
            APP_TITLE,
            "切换文件来源会清空“等待处理的任务”（只清界面，不会修改"
            "网盘或本地文件）。\n\n继续切换吗？",
            parent=self)

    def _clear_dir_tree(self) -> None:
        self.dir_tree.delete(*self.dir_tree.get_children())
        self.dir_items.clear()
        self._dir_menu_item = None
        self._pending_dir_select = None
        self.dir_sel_label.configure(text="")
        self.path_label.configure(
            text=" / ".join(name for _, name in self.path_stack))

    def _switch_mode(self, mode: str, check_login: bool = True) -> bool:
        if mode == "local":
            if self.is_local:
                return True
            if self.busy:
                self._refresh_mode_controls()
                return False
            root = self.local_root
            if not root or not os.path.isdir(root):
                root = filedialog.askdirectory(
                    title="选择本地媒体文件夹", parent=self,
                    initialdir=root if root and os.path.isdir(root) else
                    os.path.expanduser("~"))
                if not root:
                    self._refresh_mode_controls()
                    return False
            if not self._discard_plans_for_switch():
                self._refresh_mode_controls()
                return False
            return self._enter_local(root)

        if mode == "cloud":
            if not self.is_local and not self.is_demo:
                self._refresh_mode_controls()
                return True
            if self.busy:
                self._refresh_mode_controls()
                return False
            if not self._discard_plans_for_switch():
                self._refresh_mode_controls()
                return False
            self._enter_cloud(check_login=check_login)
            return True
        self._refresh_mode_controls()
        return False

    def choose_local_root(self) -> None:
        if self.busy:
            return
        if not self.is_local:
            self._switch_mode("local")
            return
        root = filedialog.askdirectory(
            title="选择本地媒体文件夹", parent=self,
            initialdir=self.local_root if os.path.isdir(self.local_root)
            else os.path.expanduser("~"))
        if not root:
            return
        if os.path.normcase(os.path.abspath(root)) == \
                os.path.normcase(os.path.abspath(self.local_root)):
            return
        if not self._discard_plans_for_switch():
            return
        self._enter_local(root)

    def _enter_local(self, root: str) -> bool:
        try:
            client = LocalClient(
                root,
                index_path=os.path.join(self.data_dir, "local_index.json"),
                log=self.log_threadsafe)
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self)
            self._refresh_mode_controls()
            return False
        self.local_client = client
        self.local_root = client.root
        self.settings["local_root"] = self.local_root
        self._save_settings()
        self.client = client
        self.is_local = True
        self.is_demo = False
        self.dir_view_state = {}
        self.plans = []
        self._render_plans()
        self.current_cid = client.root_id
        self.current_item = client.root_item()
        root_name = os.path.basename(client.root.rstrip("\\/")) or client.root
        self.path_stack = [(client.root_id, root_name)]
        self._clear_dir_tree()
        self._refresh_mode_controls()
        self._set_login_status("本地模式（不改 115）", "#176b33")
        self._log(f"已切换到本地模式：{client.root}；"
                  "只重命名本机文件，不会修改 115 网盘。"
                  "分析时仍会联网查询豆瓣/Bangumi/IMDb/TMDB。")
        if self._restore_plans():
            return True
        self.refresh()
        return True

    def _enter_cloud(self, check_login: bool = True) -> None:
        self.is_local = False
        self.is_demo = False
        if self.cloud_client is None:
            self.cloud_client = P115Client(
                self.data_dir, log=self.log_threadsafe)
        self.client = self.cloud_client
        self.dir_view_state = {}
        self.plans = []
        self._render_plans()
        self.current_cid = "0"
        self.current_item = None
        self.path_stack = [("0", "根目录")]
        self._clear_dir_tree()
        self._refresh_mode_controls()
        if self.cloud_client.cookie_dict():
            if check_login:
                self._set_login_status("检查登录…", "#888")
                self._log("已切回 115 网盘，正在检查登录状态…")
                self.run_async(
                    lambda: self.cloud_client.is_logged_in(force=True),
                    "login_check")
            else:
                self._set_login_status("已登录", "#176b33")
        else:
            self._set_login_status("未登录", "#b3261e")
            self._log("已切回 115 网盘；请先登录后再浏览文件。")

    def _undo_scope(self) -> str:
        if self.is_local and self.local_client is not None:
            return "local:" + os.path.normcase(self.local_client.root)
        if self.is_demo:
            return "demo"
        return "cloud"

    # ------------------------------------------------------------ 预览缓存
    def _plans_cache_path(self) -> str:
        return os.path.join(self.data_dir, "plans_cache.pkl")

    def _current_scope(self) -> tuple[str, str]:
        """当前数据来源的指纹：模式 + 账号/路径，防止把 A 网盘的预览
        恢复到 B 网盘或另一个本地目录上。"""
        if self.is_local and self.local_client is not None:
            return "local", os.path.normcase(
                os.path.abspath(self.local_client.root))
        if self.is_demo:
            return "demo", "demo"
        uid = ""
        if self.cloud_client is not None:
            try:
                uid = str((self.cloud_client.cookie_dict() or {}).get("UID")
                          or "")
            except Exception:
                uid = ""
        return "cloud", uid

    def _signature_of(self, plans: list[PlanItem]) -> str:
        """文件清单指纹：任何一项被改名/增删，指纹都会变化。"""
        rows = sorted(
            f"{getattr(p.item, 'fid', '')}\x1f{p.item.name}"
            for p in plans if getattr(p, "item", None) is not None)
        return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()

    def _save_plans_cache(self) -> None:
        """把当前等待列表写到 data/plans_cache.pkl（本机数据，不联网）。"""
        if not self.settings.get("remember_plans", True):
            self._discard_plans_cache()
            return
        p = self._plans_cache_path()
        if not self.plans or self.is_demo:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            self._plans_saved_stamp = None
            return
        mode, root_id = self._current_scope()
        payload = {
            "version": 1,
            "stamp": time.time(),
            "mode": mode,
            "root_id": root_id,
            "paths": list(self.path_stack),
            "current_cid": self.current_cid,
            "signature": self._signature_of(self.plans),
            "plans": self.plans,
        }
        tmp = p + ".tmp"
        try:
            with open(tmp, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, p)
            self._plans_saved_stamp = payload["stamp"]
        except Exception as e:
            self._log(f"保存预览缓存失败：{e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _load_plans_cache(self) -> dict | None:
        p = self._plans_cache_path()
        if not os.path.exists(p):
            return None
        try:
            with open(p, "rb") as f:
                data = pickle.load(f)
        except Exception:
            return None
        if not isinstance(data, dict) or data.get("version") != 1:
            return None
        plans = data.get("plans")
        if not isinstance(plans, list) or not plans:
            return None
        return data

    def _restore_plans(self) -> bool:
        """启动/切回时尝试恢复上次的等待列表。

        前提：账号或根目录一致；恢复后仍会在后台逐项核对文件是否还在、
        名字是否没变，任何一项对不上就整批丢弃，绝不在过期数据上改名。
        """
        if self.busy or not self.settings.get("remember_plans", True):
            return False
        data = self._load_plans_cache()
        if data is None:
            return False
        mode, root_id = self._current_scope()
        if data.get("mode") != mode or data.get("root_id") != root_id:
            return False
        plans = data["plans"]
        if data.get("signature") != self._signature_of(plans):
            return False
        self.plans = plans
        self._render_plans()
        self._log(f"已恢复上次的 {len(plans)} 个等待任务（本机缓存，"
                  "正在核对文件是否仍在原处…）")
        self._set_busy(True)
        client = self.client
        self.run_async(lambda: self._verify_plans(client),
                       "plans_verified", determinate=True)
        return True

    def _verify_plans(self, client) -> tuple[bool, str]:
        """逐项确认缓存中的文件仍在原目录、名字未变。"""
        cache: dict[str, list[P115Item]] = {}
        for p in self.plans:
            parent = str(getattr(p.item, "parent_id", "") or "")
            if parent not in cache:
                try:
                    cache[parent] = client.list_dir(parent)
                except Exception as e:
                    return False, f"无法读取目录（{parent}）：{e}"
            names = {it.name for it in cache[parent]}
            for op in (p.ops or []):
                if op.old_name not in names:
                    return False, f"「{op.old_name}」已不在原文件夹（可能已被改名）"
        return True, ""

    def _discard_plans_cache(self) -> None:
        """改名/撤销/切换数据源后，旧预览必须作废，避免下次误恢复。"""
        p = self._plans_cache_path()
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
        self._plans_saved_stamp = None

    def forget_plans(self) -> None:
        """手动清空等待列表与缓存。"""
        if not self.plans:
            messagebox.showinfo(APP_TITLE, "当前没有等待中的任务。", parent=self)
            return
        if not messagebox.askyesno(APP_TITLE, "清空当前等待列表？\n"
                                   "不会修改网盘/本地文件，重新分析即可恢复。",
                                   parent=self):
            return
        self.plans = []
        self._render_plans()
        self._discard_plans_cache()
        self._log("已清空等待列表。")

    # ------------------------------------------------------------ 自动更新
    def _schedule_update_check(self, delay_ms: int) -> None:
        if self._update_after_id:
            try:
                self.after_cancel(self._update_after_id)
            except Exception:
                pass
        self._update_after_id = self.after(
            max(1000, int(delay_ms)), self._auto_update_tick)

    def _auto_update_tick(self) -> None:
        """启动后自动查一次；运行期间按周期再查，结果只做顶部提示。"""
        self._update_after_id = None
        if not bool(self.settings.get("auto_check_updates", True)):
            return
        if self._update_checking:
            self._schedule_update_check(AUTO_UPDATE_PERIOD_SECONDS * 1000)
            return
        # 测试/后台窗口不发起网络请求，避免无窗口时弹更新提示。
        try:
            if not self.winfo_viewable():
                self._schedule_update_check(
                    AUTO_UPDATE_PERIOD_SECONDS * 1000)
                return
        except Exception:
            return
        self._update_checking = True
        self.settings["update_last_check"] = int(time.time())
        try:
            self._save_settings()
        except Exception:
            pass

        def worker():
            try:
                release = updater.fetch_latest_release()
                error = ""
            except Exception as e:  # noqa: BLE001
                release, error = None, str(e)
            self.post("update_check", (release, error))

        threading.Thread(target=worker, daemon=True).start()
        self._schedule_update_check(AUTO_UPDATE_PERIOD_SECONDS * 1000)

    def _on_update_result(self, release, error: str) -> None:
        self._update_checking = False
        if error:
            short = str(error).replace("\n", " ")[:160]
            self._log(f"自动检查更新未完成（不影响使用）：{short}")
            return
        if not isinstance(release, dict):
            return
        if not bool(self.settings.get("auto_check_updates", True)):
            return
        tag = str(release.get("tag") or "")
        if not tag or not updater.is_newer(tag, updater.APP_VERSION):
            return
        ignored = str(self.settings.get("update_ignored_version") or "")
        if tag == ignored:
            return
        self._update_release = release
        self._show_update_banner(release)
        self._log(f"发现新版本 {tag}（当前 {updater.APP_VERSION}），"
                  "已显示顶部更新提示。")

    def _show_update_banner(self, release: dict) -> None:
        tag = str(release.get("tag") or "")
        notes = str(release.get("notes") or "").strip().splitlines()
        detail = notes[0].strip() if notes else ""
        detail = re.sub(r"^[#*\-\s]+", "", detail)[:70]
        text = (f"发现新版本 {tag}（当前 {updater.APP_VERSION}）"
                + (f"：{detail}" if detail else ""))
        self._update_banner_tag = tag
        self.update_banner_label.configure(text=text)
        if not self.update_banner.winfo_manager():
            self.update_banner.pack(fill="x", after=self.top_bar)

    def _hide_update_banner(self) -> None:
        try:
            self.update_banner.pack_forget()
        except Exception:
            pass

    def _ignore_update(self) -> None:
        tag = self._update_banner_tag
        if tag:
            self.settings["update_ignored_version"] = tag
            try:
                self._save_settings()
            except Exception:
                pass
            self._log(f"已忽略版本 {tag} 的更新提示；仍可在“关于”中手动检查。")
        self._hide_update_banner()

    def open_update_notice(self) -> None:
        AboutDialog(self, release=self._update_release)

    def _sync_update_schedule(self) -> None:
        if not bool(self.settings.get("auto_check_updates", True)):
            if self._update_after_id:
                try:
                    self.after_cancel(self._update_after_id)
                except Exception:
                    pass
                self._update_after_id = None
            self._hide_update_banner()
            return
        if not self._update_after_id:
            self._schedule_update_check(3000)

    # ------------------------------------------------------------ 目录
    @staticmethod
    def _dir_state_key(it: P115Item) -> tuple:
        return (it.fid or "", it.name or "", bool(it.is_dir))

    def _save_dir_view(self) -> None:
        """离开当前文件夹前，记住选中项和滚动位置。"""
        if not self.current_cid:
            return
        selected = []
        for iid in self.dir_tree.selection():
            it = self.dir_items.get(iid)
            if it is not None:
                selected.append(self._dir_state_key(it))
        focus = ()
        iid = self.dir_tree.focus()
        if iid in self.dir_items:
            focus = self._dir_state_key(self.dir_items[iid])
        try:
            top = float(self.dir_tree.yview()[0])
        except Exception:
            top = 0.0
        self.dir_view_state[self.current_cid] = (tuple(selected), focus, top)

    def _restore_dir_view(self, cid: str) -> None:
        """回到某个文件夹时，恢复上次的选中项和滚动位置。"""
        state = self.dir_view_state.get(cid)
        if not state:
            return
        selected, focus, top = state
        wanted = set(selected)
        iids: list[str] = []
        focus_iid = ""
        for iid, it in self.dir_items.items():
            key = self._dir_state_key(it)
            if key in wanted:
                iids.append(iid)
            if focus and key == focus:
                focus_iid = iid
        if iids:
            self.dir_tree.selection_set(*iids)
            self._dir_anchor = iids[0]
            self._dir_last = iids[0]
        if focus_iid:
            self.dir_tree.focus(focus_iid)
        try:
            self.dir_tree.yview_moveto(top)
        except Exception:
            pass
        self._dir_selection_changed()

    def _fill_dir_tree(self, items: list[P115Item]) -> None:
        self.dir_tree.delete(*self.dir_tree.get_children())
        self.dir_items.clear()
        # 当前所在路径（不含根目录）：分析时用它回溯上级文件夹名
        ancestors = [name for _, name in self.path_stack[1:]]
        for idx, it in enumerate(items):
            it.ancestors = list(ancestors)
            # 不用 fid 当 iid：115 偶尔会返回重复/为空的文件 ID，
            # 直接拿来当 Treeview 的 iid 会报 "Item already exists"。
            iid = f"d{idx}"
            try:
                self.dir_tree.insert(
                    "", "end", iid=iid, text=it.name,
                    values=("文件夹" if it.is_dir else
                            (it.ext.lstrip(".") or "文件"),
                            "" if it.is_dir else fmt_size(it.size)),
                    tags=("dir",) if it.is_dir else ())
                self.dir_items[iid] = it
            except Exception as e:
                self._log(f"目录项显示失败：{it.name}：{e}")
        self._dir_anchor = None
        self._dir_last = ""
        self._dir_drag = False
        self._dir_selection_changed()
        self.path_label.configure(
            text=" / ".join(name for _, name in self.path_stack))
        self._restore_dir_view(self.current_cid)
        pending = self._pending_dir_select
        if pending:
            self._pending_dir_select = None
            fid, _ = pending
            for iid, it in self.dir_items.items():
                if it.fid == fid:
                    self.dir_tree.selection_set(iid)
                    self.dir_tree.focus(iid)
                    self._dir_anchor = iid
                    self._dir_last = iid
                    break
            self._dir_selection_changed()

    def _dir_context(self, event):
        iid = self.dir_tree.identify_row(event.y)
        if not iid:
            return "break"
        if iid not in self.dir_tree.selection():
            self.dir_tree.selection_set(iid)
        self.dir_tree.focus(iid)
        self._dir_anchor = iid
        self._dir_last = iid
        item = self.dir_items.get(iid)
        self._dir_menu_item = item
        self.dir_menu.entryconfigure(
            0, state="normal" if item and item.is_dir else "disabled")
        self.dir_menu.entryconfigure(
            3, state="normal" if item else "disabled")
        try:
            self.dir_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.dir_menu.grab_release()
            except Exception:
                pass
        return "break"

    def _dir_menu_enter(self) -> None:
        self._enter_dir_item(self._dir_menu_item)

    def rename_dir_item(self) -> None:
        """左侧文件/文件夹右键“重命名”：立即改这一项。"""
        item = self._dir_menu_item
        current_fids = {x.fid for x in self.dir_items.values()}
        if item is None or item.fid not in current_fids:
            iid = self.dir_tree.focus()
            if iid not in self.dir_items:
                selected = [x for x in self.dir_tree.selection()
                            if x in self.dir_items]
                iid = selected[0] if len(selected) == 1 else ""
            item = self.dir_items.get(iid)
        if item is None:
            messagebox.showinfo(APP_TITLE,
                                "请先在左侧选中一个文件或文件夹。",
                                parent=self)
            return
        if self.busy:
            messagebox.showinfo(APP_TITLE, "当前有任务在执行，请稍候。",
                                parent=self)
            return
        if not self.client:
            messagebox.showinfo(
                APP_TITLE,
                "请先登录 115、使用演示模式，或切换到本地模式。",
                parent=self)
            return
        DirRenameDialog(self, item, self._start_dir_rename)

    def _start_dir_rename(self, item: P115Item, new_name: str) -> None:
        if self.busy:
            return
        if not self.client:
            return
        new_name = sanitize_name(new_name, 255)
        if not new_name or new_name in (".", ".."):
            messagebox.showerror(APP_TITLE, "名称不能为空。", parent=self)
            return
        if new_name == item.name:
            messagebox.showinfo(APP_TITLE, "名称没有变化。", parent=self)
            return
        clash = next(
            (x for x in self.dir_items.values()
             if x.fid != item.fid and x.parent_id == item.parent_id and
             x.name.casefold() == new_name.casefold()), None)
        if clash is not None:
            messagebox.showerror(
                APP_TITLE,
                f"同一目录下已经有同名项目：\n{clash.name}",
                parent=self)
            return
        op = RenameOp(fid=item.fid, old_name=item.name, new_name=new_name,
                      is_dir=item.is_dir, parent_id=item.parent_id)
        problem = self._validate_ops([op])
        if problem:
            messagebox.showerror(APP_TITLE, problem, parent=self)
            return
        client = self.client
        self._log(f"左侧目录改名：{op.old_name} → {new_name}")

        def task():
            results = client.rename_many(
                [op],
                progress=lambda a, b: self.post(
                    "progress", (a, b, "正在改名…")))
            return item, op, results

        self.run_async(task, "dir_rename", determinate=True)

    def _after_dir_rename(self, item: P115Item, op: RenameOp,
                          results) -> None:
        self._set_busy(False)
        ok = bool(results) and all(r.ok for r in results)
        if not ok:
            fail = "；".join(
                f"{r.old_name}: {r.message}" for r in results if not r.ok)
            fail = fail or "未返回改名结果"
            self._log(f"左侧目录改名失败：{fail}")
            messagebox.showerror(
                APP_TITLE, f"改名失败：\n{fail}", parent=self)
            return
        self.undo.record([op], results, scope=self._undo_scope())
        self._sync_renamed_item(item, op.fid, op.old_name, op.new_name)
        self._log(f"改名成功：{op.old_name} → {op.new_name}")
        if item.is_dir and item.fid == self.current_cid:
            self.path_stack[-1] = (item.fid, op.new_name)
            self.path_label.configure(
                text=" / ".join(name for _, name in self.path_stack))
        self._pending_dir_select = (item.fid, op.new_name)
        self.refresh()

    def _sync_plan_refs(self, new_names: dict[str, str],
                        old_names: dict[str, str] | None = None) -> None:
        """把等待任务里同一 fid 的旧名称替换成实际新名称。"""
        for p in self.plans:
            refs = [p.item]
            mr = p.context.get("mr") if isinstance(p.context, dict) else None
            if mr is not None:
                refs.append(mr.item)
                refs += list(mr.season_dirs) + list(mr.part_dirs)
                refs += [e.item for e in mr.entries]
                refs += list(getattr(mr, "nfo_files", []) or [])
            entries = (p.context.get("entries", [])
                       if isinstance(p.context, dict) else [])
            refs += [e.item for e in entries]
            for ref in refs:
                new = new_names.get(ref.fid) if ref is not None else None
                if new is not None:
                    ref.name = new
            for op in p.ops:
                new = new_names.get(op.fid)
                if new is None:
                    continue
                if old_names is not None and op.old_name != old_names.get(op.fid):
                    continue
                op.old_name = new

    def _sync_renamed_item(self, item: P115Item, fid: str,
                           old_name: str, new_name: str) -> None:
        """手动改名后，同步左侧列表和右侧等待任务里的旧名称。"""
        item.name = new_name
        self._sync_plan_refs({fid: new_name}, {fid: old_name})
        if self.plans:
            self._render_plans()

    def refresh(self) -> None:
        if not self.client:
            return
        cooldown = getattr(self.client, "risk_cooldown_remaining", None)
        if callable(cooldown):
            remain = cooldown()
            if remain > 0:
                self._log(
                    f"115 风控冷却中，暂不刷新目录（约 {remain} 秒）。")
                self.status_var.set(
                    f"115 风控冷却中，约 {remain} 秒后再操作")
                return
        cid = self.current_cid
        self.run_async(lambda: (cid, self.client.list_dir(cid)), "listing",
                       determinate=True)

    # ---- 左侧多选：拖动 / Ctrl 单击 / Shift 连选
    def _dir_selection_changed(self, event=None) -> None:
        # 选择变化后，旧的右键目标作废；F2 跟随当前焦点/选择。
        self._dir_menu_item = None
        n = len(self.dir_tree.selection())
        self.dir_sel_label.configure(text=f"已选 {n} 项" if n else "")

    def _row_ids(self) -> list[str]:
        return list(self.dir_tree.get_children())

    def _select_range(self, a: str, b: str, replace: bool = True,
                      add: bool = False) -> None:
        rows = self._row_ids()
        try:
            ia, ib = rows.index(a), rows.index(b)
        except ValueError:
            return
        if ia > ib:
            ia, ib = ib, ia
        ids = rows[ia:ib + 1]
        if not ids:
            return
        if add:
            self.dir_tree.selection_add(*ids)
        elif replace:
            self.dir_tree.selection_set(*ids)

    def _dir_press(self, event):
        region = self.dir_tree.identify_region(event.x, event.y)
        if region in ("heading", "separator"):
            return None
        iid = self.dir_tree.identify_row(event.y)
        if not iid:
            if region == "nothing":
                self.dir_tree.selection_set(())
            return "break"
        ctrl = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        self._dir_last = iid
        if ctrl:
            if iid in self.dir_tree.selection():
                self.dir_tree.selection_remove(iid)
            else:
                self.dir_tree.selection_add(iid)
            self._dir_anchor = iid
            self._dir_drag = False
            return "break"
        if shift and self._dir_anchor:
            if self._dir_anchor not in self._row_ids():
                self._dir_anchor = iid
            self._select_range(self._dir_anchor, iid, replace=True)
            self._dir_drag = False
            return "break"
        self._dir_anchor = iid
        self._dir_drag = True
        self.dir_tree.selection_set(iid)
        return "break"

    def _dir_motion(self, event):
        if not self._dir_drag or not self._dir_anchor:
            return "break"
        iid = self.dir_tree.identify_row(event.y)
        if not iid or iid == self._dir_last:
            return "break"
        if event.state & 0x0004:
            self._select_range(self._dir_last, iid, add=True)
        else:
            self._select_range(self._dir_anchor, iid, replace=True)
        self._dir_last = iid
        return "break"

    def _dir_release(self, event):
        if self._dir_drag:
            iid = self.dir_tree.identify_row(event.y)
            if iid:
                self._dir_anchor = iid
        self._dir_drag = False
        return "break"

    def _enter_dir_item(self, it: P115Item) -> None:
        if not it or not it.is_dir:
            return
        self._save_dir_view()
        self.path_stack.append((it.fid, it.name))
        self.current_cid = it.fid
        self.current_item = it
        self.refresh()

    def _dir_double_click(self, event) -> None:
        # Ctrl/Shift 连点同一行是为了加/减选，不应触发“进入文件夹”
        if event.state & (0x0004 | 0x0001):
            return
        iid = self.dir_tree.identify_row(event.y)
        if not iid:
            return
        it = self.dir_items.get(iid)
        if it and it.is_dir:
            self._enter_dir_item(it)

    def go_up(self) -> None:
        if len(self.path_stack) <= 1:
            return
        self._save_dir_view()
        self.path_stack.pop()
        self.current_cid, _ = self.path_stack[-1]
        self.current_item = None
        self.refresh()

    def _analyze(self, roots: list[P115Item]) -> None:
        if not self.client:
            messagebox.showinfo(
                APP_TITLE,
                "请先登录 115、使用演示模式，或切换到本地模式。",
                parent=self)
            return
        if not roots:
            messagebox.showinfo(APP_TITLE, "请先在左侧选择要分析的文件夹或文件。", parent=self)
            return
        planner = self.planner
        client = self.client
        trace_lines: list[str] = []

        def trace_plan(p: PlanItem) -> None:
            mt = str(getattr(p.match, "trace", "") or "")
            if not mt:
                return
            line = f"[搜索诊断] {p.item.name}：{mt}"
            trace_lines.append(line)
            self.post("log", line)

        def task():
            plans = planner.analyze(
                client, roots,
                progress=lambda a, b, m: self.post("progress", (a, b, m)),
                trace=trace_plan)
            return plans

        self.run_async(task, "plans", determinate=True)

    def analyze_selected(self) -> None:
        roots = [self.dir_items[i] for i in self.dir_tree.selection()
                 if i in self.dir_items]
        self._analyze(roots)

    def analyze_current(self) -> None:
        if self.current_item:
            item = self.current_item
        else:
            # 没有 current_item 时（例如刚“上一级”回来），补上完整上级路径
            parent_id = (self.path_stack[-2][0]
                         if len(self.path_stack) > 1 else "0")
            item = P115Item(
                fid=self.current_cid, parent_id=parent_id,
                name=self.path_stack[-1][1], is_dir=True,
                ancestors=[name for _, name in self.path_stack[1:-1]])
        self._analyze([item])

    # ------------------------------------------------------------ 计划表
    def _render_plans(self) -> None:
        selected_iid = self.plan_tree.selection()
        keep = selected_iid[0] if selected_iid else ""
        self.plan_tree.delete(*self.plan_tree.get_children())
        self.plan_rows.clear()
        for i, p in enumerate(self.plans):
            iid = f"p{i}"
            self.plan_rows[iid] = p
            seasons = ",".join(f"S{s:02d}" for s in p.seasons) if p.seasons else ""
            summary = p.new_summary or ("（待确认季数）" if not p.season_confirmed
                                        and p.media_type == "series" else "（无需修改）")
            self.plan_tree.insert(
                "", "end", iid=iid,
                values=("☑" if p.selected else "☐",
                        "剧集" if p.media_type == "series" else
                        ("电影" if p.media_type == "movie" else "未知"),
                        SHORT_CATEGORY.get(p.category, p.category),
                        p.current_name, summary, seasons, fmt_episodes(p),
                        f"{p.confidence * 100:.0f}%",
                        STATUS_LABELS.get(p.status, p.status)),
                tags=(p.status,))
        if keep and self.plan_tree.exists(keep):
            self.plan_tree.selection_set(keep)
        elif self.plans:
            self.plan_tree.selection_set("p0")
        if self.plans:
            self._plan_selected()
        else:
            self.detail_plan = None
            for var in (self.title_var, self.year_var, self.season_var):
                var.set("")
            self.meta_label.configure(text="")
            self._set_note("")
            self._clear_info_panel()

    def _plan_by_iid(self, iid: str) -> PlanItem | None:
        return self.plan_rows.get(iid)

    def _plan_selected(self, event=None) -> None:
        sel = self.plan_tree.selection()
        if not sel:
            self.detail_plan = None
            for var in (self.title_var, self.year_var, self.season_var):
                var.set("")
            self._set_note("")
            self.meta_label.configure(text="")
            self.map_btn.configure(state="disabled")
            self.map_label.configure(text="")
            self._clear_info_panel()
            return
        p = self._plan_by_iid(sel[0])
        self.detail_plan = p
        if not p:
            self._clear_info_panel()
            return
        self.title_var.set(p.display_title)
        self.year_var.set(str(p.display_year or ""))
        if p.season_override is not None:
            self.season_var.set(str(p.season_override))
        elif len(p.seasons) == 1:
            self.season_var.set(str(p.seasons[0]))
        else:
            self.season_var.set("")
        videos = [e for e in ((p.context or {}).get("entries") or [])
                  if e.is_video]
        if p.media_type == "series" and videos:
            self.map_btn.configure(state="normal")
            manual_n = len(p.episode_overrides or {})
            self.map_label.configure(
                text=f"{len(videos)} 个视频"
                     + (f"，已手动映射 {manual_n} 个" if manual_n else ""))
        else:
            self.map_btn.configure(state="disabled")
            self.map_label.configure(text="")
        parts = []
        if p.match.douban:
            parts.append(f"豆瓣：{p.match.douban.title} ({p.match.douban.year or '?'})")
        if p.match.bangumi:
            parts.append(f"Bangumi：{p.match.bangumi.title} ({p.match.bangumi.year or '?'})")
        if p.match.imdb:
            parts.append(f"IMDb：{p.match.imdb.title} ({p.match.imdb.sid})")
        ident = p.identity
        if ident.imdb_id:
            parts.append(f"IMDb ID：{ident.imdb_id}")
        if ident.tmdb_id:
            parts.append(f"TMDB ID：{ident.tmdb_id}")
        multi = sum(1 for g in p.version_groups if not g.is_duplicate)
        dup = sum(1 for g in p.version_groups if g.is_duplicate)
        if multi:
            parts.append(f"同集多版本：{multi} 组")
        if dup:
            parts.append(f"疑似重复集：{dup} 组")
        if p.folder_version > 1:
            parts.append(f"版本目录：V{p.folder_version}")
        parts.append(f"置信度：{p.confidence * 100:.0f}%")
        codes = list(getattr(p, "qc_codes", None) or [])
        if codes:
            # 结构化原因码：直接显示“需确认的原因”，不再靠解析备注文字。
            parts.append("原因：" + "、".join(
                qc.CODE_LABELS.get(c, c) for c in codes))
        self.meta_label.configure(text="  |  ".join(parts))
        self._set_note(p.note or "")
        self._refresh_info_sources(p)

    # ------------------------------------------------------------ 影片资料
    @staticmethod
    def _info_source_details(plan: PlanItem, source: str):
        """返回（ID、TMDB 类型、豆瓣封面备用 URL）。"""
        m = plan.match
        if source == "douban":
            c = m.douban
            return ((c.sid if c else "") or m.douban_id, "tv",
                    str(c.extra.get("img", "")) if c and isinstance(c.extra, dict) else "")
        if source == "bangumi":
            c = m.bangumi
            return (c.sid if c else "") or m.bangumi_id, "tv", ""
        ident = plan.identity
        if source == "imdb":
            c = m.imdb
            return (c.sid if c else "") or ident.imdb_id, "tv", ""
        if source == "tmdb":
            c = m.tmdb
            sid = (c.sid if c else "") or ident.tmdb_id
            kind = "tv" if plan.media_type == "series" else "movie"
            if c and c.kind in ("tv", "movie"):
                kind = c.kind
            return sid, kind, ""
        return "", "tv", ""

    def _attach_info_hint(self, parent) -> None:
        """给资料来源行的每个单选加悬浮提示：再点一次会重新搜索。"""
        tip = ("点击切换来源；再点一次已选中的来源会重新搜索一次"
               "（某个来源为空时用它换一次请求）")

        class _Tip:
            def __init__(self, widget):
                self.widget = widget
                self.win = None

            def show(self, _e=None):
                if self.win is not None:
                    return
                try:
                    x = self.widget.winfo_rootx()
                    y = self.widget.winfo_rooty() + 24
                    self.win = tk.Toplevel(self.widget)
                    self.win.wm_overrideredirect(True)
                    self.win.wm_geometry(f"+{x}+{y}")
                    tk.Label(self.win, text=tip, justify="left",
                             background="#ffffe0", relief="solid",
                             borderwidth=1,
                             font=("Microsoft YaHei UI", 9),
                             wraplength=320).pack()
                except Exception:      # noqa: BLE001
                    self.win = None

            def hide(self, _e=None):
                if self.win is not None:
                    try:
                        self.win.destroy()
                    except Exception:      # noqa: BLE001
                        pass
                    self.win = None

        for rb in self.info_radios.values():
            t = _Tip(rb)
            rb.bind("<Enter>", t.show, add="+")
            rb.bind("<Leave>", t.hide, add="+")

    def _on_info_source_clicked(self, key: str) -> None:
        """鼠标点击来源（补 command 失效的情况）。

        command 在「点已选中项」时不可靠，这里统一按点击处理：
        如果点的是当前已选中的来源 → 重搜；否则切换来源。
        """
        sel = self.info_source_var.get()
        if key == sel and key == getattr(self, "_last_info_source", None):
            # 已经是这个来源 → 再点一次表示重搜
            p = self.detail_plan
            if p is not None:
                self._research_info_source(p, key)
            return
        # 点击的是新来源：让 command 去处理切换（避免重复执行）
        if key != sel:
            self.info_source_var.set(key)
            self._on_info_source_pick()

    def _on_info_source_pick(self) -> None:
        """切换资料来源。

        再次点击「已经选中」的来源时，对该来源重新搜索一次：
        用户常常发现某个来源是空的（例如 TMDB 没有收录），
        希望手动换关键词重搜，而不是被迫去右键菜单。
        """
        p = self.detail_plan
        if p is None:
            return
        source = self.info_source_var.get()
        # 点的是当前已选中的来源 → 视为“刷新/重搜”
        if source and source == getattr(self, "_last_info_source", None):
            self._research_info_source(p, source)
            return
        self._last_info_source = source

        if self.name_by_source_var.get():
            if source and p.name_source != source:
                self._set_naming_source(p, source)
                return
        self._load_info()

    def _research_info_source(self, p: PlanItem, source: str) -> None:
        """对指定来源重新搜一次（用当前任务的关键词）。

        「再点一次已选中的来源」就是这个入口。为了让用户确认真的在搜，
        这里进入忙碌状态并在状态栏显示进度，搜索结束再恢复。
        """
        _, _, label = self._source_candidate_for(p, source)
        full_label = {"douban": "豆瓣", "bangumi": "Bangumi",
                      "imdb": "IMDb", "tmdb": "TMDB"}.get(source, source)
        self._log(f"重新搜索 {full_label}：{p.title}…")
        if self.busy:
            self._log("有任务在执行，稍后再试。")
            return

        # 明确的进行中状态：来源状态文字 + 忙碌禁用按钮
        try:
            self.info_status.configure(text=f"正在重新搜索 {full_label}…",
                                       foreground="#b26a00")
        except Exception:      # noqa: BLE001
            pass

        def task():
            try:
                cand = self._fetch_source_candidate(p, source)
            except Exception as e:      # noqa: BLE001
                return f"搜索失败：{e}"
            if cand is None:
                return (f"{label} 仍无结果：该来源可能没有收录"
                        f"《{p.title}》，可用右键「手动搜索」换关键词。")
            return cand

        def finish(payload) -> None:
            self._set_busy(False)
            if isinstance(payload, str):
                self._log(payload)
                try:
                    self.info_status.configure(text="该来源无结果",
                                               foreground="#b3261e")
                except Exception:      # noqa: BLE001
                    pass
                self._load_info()
                return
            self._apply_manual_candidate(
                p, payload, self.meta.resolve_ids(payload, p.media_type))
            self._log(f"已从 {full_label} 取回：{payload.title}"
                      f"（{payload.year or '?'}）")
            self._render_plans()

        # run_async 自己会置 busy；这里不能提前置位，否则会被当成
        # 「上一个任务还在执行」而直接跳过。
        self._research_hook = finish
        self.run_async(task, "research_source")

    @staticmethod
    def _source_candidate_for(p: PlanItem, source: str):
        cand = {"douban": p.match.douban, "bangumi": p.match.bangumi,
                "imdb": p.match.imdb, "tmdb": p.match.tmdb}.get(source)
        label = {"douban": "豆瓣", "bangumi": "Bangumi",
                 "imdb": "IMDb", "tmdb": "TMDB"}.get(source, source)
        return cand, source, label

    def _fetch_source_candidate(self, p: PlanItem, source: str):
        """按任务的片名在指定来源搜一条最佳结果。

        会依次尝试多个关键词，直到有结果：
        片名 → 片名+年份 → 其它来源已拿到的标题/英文名 → 异体字变体。
        TMDB 常只认英文名（「Thunderbolt Fantasy」能搜到，
        「霹雳奇幻 生死一剑」搜不到），所以必须多试几个词。
        """
        from app.metadata import _cjk_variants
        from app.models import ParsedName
        query = p.title or p.parsed.title
        parsed = ParsedName(raw=query, title=query, queries=[query],
                            year=p.year, season=(p.seasons or [None])[0])
        fn = {"douban": self.meta.search_douban,
              "bangumi": self.meta.search_bangumi,
              "imdb": self.meta.search_imdb,
              "tmdb": lambda q: self.meta.search_tmdb(q, p.media_type),
              }.get(source)
        if fn is None:
            return None

        # 收集候选关键词：本任务已有的名字优先，其次变体
        words: list[str] = [query]
        if p.year:
            words.append(f"{query} {p.year}")
        for c in (p.match.imdb, p.match.tmdb, p.match.douban,
                  p.match.bangumi):
            if c is None:
                continue
            for w in (getattr(c, "original_title", ""),
                      getattr(c, "title", "")):
                if w:
                    words.append(str(w))
            if isinstance(c.extra, dict):
                words += [str(a) for a in (c.extra.get("aliases") or [])]
        words += _cjk_variants(query)

        seen = set()
        pool = []
        for w in words:
            w = w.strip()
            if not w or w in seen:
                continue
            seen.add(w)
            pool = fn(w) or []
            # TMDB 的剧集/电影是分开收录的：任务判成剧集但条目其实是
            # 电影（例如《东离剑游纪：生死一剑》是 movie）时会搜空。
            # 查不到就换另一个类型再试一次。
            if not pool and source == "tmdb":
                other = "movie" if p.media_type != "movie" else "series"
                pool = self.meta.search_tmdb(w, other) or []
            if pool:
                break
        if not pool:
            return None
        for c in pool:
            c.score = self.meta._score(parsed, c, p.media_type)
        pool.sort(key=lambda c: c.score, reverse=True)
        return pool[0]

    def _toggle_naming_source(self) -> None:
        """勾选/取消“按此来源命名”。"""
        p = self.detail_plan
        if p is None:
            self.name_by_source_var.set(False)
            return
        if not getattr(p, "qc_ops_pending", False) and self.busy:
            self.name_by_source_var.set(bool(p.name_source))
            return
        if self.name_by_source_var.get():
            source = self.info_source_var.get()
            if not source:
                self.name_by_source_var.set(False)
                messagebox.showinfo(APP_TITLE, "请先选择一个资料来源。",
                                    parent=self)
                return
            self._set_naming_source(p, source)
        else:
            self._set_naming_source(p, "")

    def _set_naming_source(self, p: PlanItem, source: str) -> None:
        """把任务改成按某个来源命名（空 = 回到自动），并重建预览。"""
        label = SOURCE_LABELS.get(source, source) if source else "自动"
        p.name_source = source
        p.title_override = ""       # 来源标题优先，清掉旧的人工标题覆盖
        self.name_by_source_var.set(bool(source))

        def done(ok: bool, err: str) -> None:
            if not ok:
                self._log(f"按来源重建失败：{err}")
            self._render_plans()
            self._plan_selected()
            if source:
                self._log(f"已改为按 {label} 命名：标题、单集副标题、"
                          "特别篇顺序都以该来源为准。")
                self.status_var.set(f"命名来源：{label}")
            else:
                self._log("已取消按来源命名，恢复自动匹配。")
                self.status_var.set("命名来源：自动匹配")

        self.rebuild_in_background(p, done)

    def rebuild_in_background(self, p: PlanItem, done=None,
                              determinate: bool = False) -> None:
        """在后台线程重建预览，避免联网取单集标题时把界面卡死。

        以前 rebuild 直接在 Tk 主线程里跑；按来源命名要请求豆瓣/Bangumi/
        IMDb 的单集页，网络一慢整个窗口就会无响应（并一直提示“有任务在执行”）。
        """
        if self.busy:
            # 只记日志、不弹窗：弹窗会打断批量操作，也会卡住自动化测试。
            self._log("上一个操作还在进行，本次重建已跳过；完成后再试。")
            self.status_var.set("有任务在执行，本次重建已跳过")
            if done:
                done(False, "busy")
            return
        planner = self.planner

        def task():
            try:
                planner.rebuild(p)
                return True, ""
            except Exception as e:
                return False, str(e)

        self._rebuild_callback = done
        self.run_async(task, "rebuild_done", determinate=determinate)

    def wait_for_rebuild(self, timeout: float = 20.0) -> bool:
        """等待后台重建结束（测试与脚本用；界面里不需要调用）。"""
        import time as _time
        end = _time.time() + max(0.1, float(timeout))
        while _time.time() < end:
            self.update()
            if not self.busy:
                return True
            _time.sleep(0.02)
        return False

    def _on_rebuild_done(self, payload) -> None:
        ok, err = payload if isinstance(payload, tuple) else (True, "")
        # 后台重建结束后必须解除忙碌，否则后续操作会一直被
        # “当前有任务在执行”挡住（这次卡死问题的一半原因）。
        self._set_busy(False)
        fn = getattr(self, "_rebuild_callback", None)
        self._rebuild_callback = None
        if ok:
            self._render_plans()
            self._plan_selected()
        elif err and err != "busy":
            # 只有真正的异常才用户可见；"busy" 是调用方主动放弃，不弹窗。
            self._log(f"重建预览失败：{err}")
        if callable(fn):
            fn(ok, err)

    def _on_douban_test(self, payload) -> None:
        dialog, page = payload
        try:
            if dialog.winfo_exists():
                dialog._show_douban_test(page)
        except Exception:
            pass

    def apply_naming_rule(self) -> None:
        """主界面“命名规则”面板：保存为默认设置，并重建所有任务预览。

        只重建“当前选中项”的话，其他任务仍显示旧名字，
        会让人以为选项没生效。
        """
        if self.naming_panel is None:
            return
        values = self.naming_panel.values()
        self.settings.update(values)
        try:
            self._save_settings()
        except Exception as e:      # noqa: BLE001
            self._log(f"保存命名规则失败：{e}")
        self._init_meta()
        # 记下“已应用”的值，面板据此把「已改但未应用」的提示清掉
        try:
            if self.naming_panel is not None:
                self.naming_panel.mark_applied()
        except Exception:      # noqa: BLE001
            pass
        plans = list(self.plans or [])
        if not plans:
            self._log("命名规则已保存；分析任务后即按新规则命名。")
            return
        planner = self.planner

        def task():
            ok = 0
            for p in plans:
                try:
                    planner.rebuild(p)
                    ok += 1
                except Exception:      # noqa: BLE001
                    pass
            return ok

        if self.busy:
            self._log("有任务在执行，命名规则已保存；请稍后重新分析。")
            return

        def finish(payload) -> None:
            self._set_busy(False)
            self._render_plans()
            self._log(f"命名规则已应用，重建 {payload} 个任务。")

        self.run_async(task, "naming_applied")
        self._naming_applied_hook = finish

    def _on_research_source(self, payload) -> None:
        """来源重搜完成：交给 _research_hook 收尾。"""
        hook = getattr(self, "_research_hook", None)
        self._research_hook = None
        if callable(hook):
            hook(payload)
        else:
            self._set_busy(False)

    def _on_naming_applied(self, payload) -> None:
        hook = getattr(self, "_naming_applied_hook", None)
        self._naming_applied_hook = None
        if callable(hook):
            hook(payload)
        else:
            self._set_busy(False)
            self._render_plans()

    def _set_note(self, text: str) -> None:
        """把备注写进限高的可滚动框（内容多于 3 行时可滚动查看）。"""
        widget = self.note_label
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if text:
            widget.insert("1.0", text)
        widget.configure(state="disabled")
        # 有内容时滚回顶部，避免停留在上一次的滚动位置
        widget.yview_moveto(0.0)

    def _on_note_wheel(self, event) -> str:
        """备注框内滚轮只滚动备注内容，不带动外层窗口。"""
        try:
            self.note_label.yview_scroll(
                -1 if getattr(event, "delta", 0) > 0 else 1, "units")
        except Exception:
            pass
        return "break"

    def _refresh_info_sources(self, plan: PlanItem) -> None:
        available = {
            "douban": bool(self._info_source_details(plan, "douban")[0]),
            "bangumi": bool(self._info_source_details(plan, "bangumi")[0]),
            "imdb": bool(self._info_source_details(plan, "imdb")[0]),
            "tmdb": bool(self._info_source_details(plan, "tmdb")[0]),
        }
        for key, rb in self.info_radios.items():
            rb.configure(state="normal" if available[key] else "disabled")
        current = self.info_source_var.get()
        if not available.get(current):
            best = plan.match.best
            preferred = (best.source if best and best.source != "imdb"
                         and available.get(best.source) else "")
            if not preferred:
                for key in ("douban", "bangumi", "tmdb", "imdb"):
                    if available[key]:
                        preferred = key
                        break
            self.info_source_var.set(preferred)
        # “按此来源命名”跟随当前任务：没选过时默认不勾；已选时保持勾选。
        self.name_by_source_var.set(bool(getattr(plan, "name_source", "")))
        self.name_by_source_btn.configure(
            state="normal" if any(available.values()) else "disabled")
        if not any(available.values()):
            self.info_status.configure(
                text="没有可用的资料来源，可先手动搜索",
                foreground="#777")
            self._clear_info()
            return
        self._load_info()

    def _clear_info(self) -> None:
        self._info_seq += 1
        self.info_title_var.set("")
        self.info_rating_var.set("")
        self._set_overview("")
        self.info_cast.configure(text="")
        self._set_info_poster(None)

    def _clear_info_panel(self) -> None:
        self._info_seq += 1
        self.info_source_var.set("")
        for rb in self.info_radios.values():
            rb.configure(state="disabled")
        self.info_status.configure(text="")
        self._clear_info()

    def _set_overview(self, text: str) -> None:
        self.info_overview.configure(state="normal")
        self.info_overview.delete("1.0", "end")
        if text:
            self.info_overview.insert("1.0", text)
        self.info_overview.configure(state="disabled")

    def _set_info_poster(self, data: bytes) -> None:
        self._info_photo = None
        if data:
            try:
                img = Image.open(io.BytesIO(data))
                img.thumbnail((86, 126))
                self._info_photo = ImageTk.PhotoImage(img)
                self.info_poster.configure(image=self._info_photo, text="")
                return
            except Exception:
                pass
        self.info_poster.configure(image="", text="封面")

    def _load_info(self) -> None:
        p = self.detail_plan
        if not p:
            return
        source = self.info_source_var.get()
        self._last_info_source = source
        sid, kind, fallback_poster = self._info_source_details(p, source)
        if not sid:
            self._clear_info()
            self.info_status.configure(text="该渠道没有可用 ID")
            return
        self._info_seq += 1
        seq = self._info_seq
        self.info_status.configure(text="加载中…", foreground="#777")
        self.info_title_var.set("")
        self.info_rating_var.set("")
        self._set_overview("")
        self.info_cast.configure(text="")
        self._set_info_poster(None)
        meta = self.meta

        def worker():
            try:
                info = meta.media_details(
                    source, sid, kind, fallback_poster, p.display_title)
                image = b""
                poster_url = str(info.get("poster") or "")
                if poster_url:
                    image = self._poster_cache.get(poster_url, b"")
                    if not image:
                        image = meta.fetch_image(poster_url)
                        if image:
                            self._poster_cache[poster_url] = image
                self.post("media_details",
                          (seq, p, source, sid, info, image))
            except Exception as e:
                self.post("media_details",
                          (seq, p, source, sid,
                           {"error": str(e)}, b""))

        threading.Thread(target=worker, daemon=True).start()

    def _show_media_details(self, seq: int, plan: PlanItem, source: str,
                            sid: str, info: dict, image: bytes) -> None:
        if seq != self._info_seq or self.detail_plan is not plan or \
                self.info_source_var.get() != source:
            return
        poster_data = image or b""
        if "error" in info:
            self.info_status.configure(
                text=f"{SOURCE_LABELS.get(source, source)}：{info['error']}",
                foreground="#b3261e")
        else:
            label = SOURCE_LABELS.get(source, source)
            self.info_status.configure(text=f"{label} · 已加载",
                                       foreground="#176b33")
        title = str(info.get("title") or plan.display_title or "")
        year = info.get("year")
        self.info_title_var.set(
            f"{title} ({year})" if title and year else title)
        rating = info.get("rating")
        self.info_rating_var.set(
            f"评分：{rating:.1f}" if isinstance(rating, (int, float))
            else "评分：暂无")
        self._set_overview(str(info.get("overview") or "暂无简介"))
        cast = info.get("cast") or []
        if isinstance(cast, str):
            cast = [cast]
        self.info_cast.configure(
            text="演员/配音：" + ("、".join(map(str, cast[:12]))
                                  if cast else "暂无演员信息"))
        self._set_info_poster(poster_data)
        try:
            self.meta.save_cache()
        except Exception:
            pass

    # ------------------------------------------------------------ NFO/图片
    def _nfo_mode_text(self) -> str:
        if self.is_local:
            return "本地模式：已有 NFO/图片只跟随改名，不删除"
        return ("已有 NFO/图片：删除后重存"
                if self.settings.get("nfo_existing") == "replace"
                else "已有 NFO/图片：跟随改名")

    def _on_auto_nfo_toggle(self) -> None:
        self.settings["auto_nfo_after_rename"] = bool(
            self.auto_nfo_var.get())
        self._save_settings()

    def _nfo_source(self, plan: PlanItem):
        source = self.info_source_var.get() if self.detail_plan is plan else ""
        sid, kind, fallback = self._info_source_details(plan, source) \
            if source else ("", "", "")
        if not sid:
            for key in ("douban", "bangumi", "tmdb", "imdb"):
                sid, kind, fallback = self._info_source_details(plan, key)
                if sid:
                    source = key
                    break
        return source, sid, kind, fallback

    @staticmethod
    def _jpeg_bytes(data: bytes, size: tuple[int, int]) -> bytes:
        if not data:
            return b""
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail(size)
            out = io.BytesIO()
            img.save(out, "JPEG", quality=90)
            return out.getvalue()
        except Exception:
            return b""

    def _prepare_nfo_task(self, plan: PlanItem, progress=None) -> dict:
        """获取资料、生成待上传文件，并找出已有 NFO/图片。"""
        def report(text: str) -> None:
            if progress:
                progress(0, 0, text)

        report("正在获取影片资料…")
        source, sid, kind, fallback = self._nfo_source(plan)
        details = self.meta.media_details(
            source, sid, kind, fallback, plan.display_title) if sid else {
            "title": plan.display_title, "year": plan.display_year,
            "rating": None, "overview": "", "cast": [], "genres": []}
        poster = fanart = b""
        for key, size in (("poster", (1000, 1500)),
                          ("fanart", (1920, 1080))):
            url = str(details.get(key) or "")
            if not url:
                continue
            raw = self._poster_cache.get(url, b"")
            if not raw:
                raw = self.meta.fetch_image(url)
                if raw:
                    self._poster_cache[url] = raw
            data = self._jpeg_bytes(raw, size)
            if key == "poster":
                poster = data
            else:
                fanart = data
        if not fanart:
            fanart = poster
        # NFO 也只跟随预览里勾选的项目；未勾选的视频/目录不生成/不改 NFO。
        nfo_plan = copy.copy(plan)
        nfo_plan.ops = [op for op in plan.ops if op.selected]
        selected_fids = {op.fid for op in nfo_plan.ops
                         if not op.is_dir and op.role in ("episode", "movie")}
        if isinstance(plan.context, dict):
            context = dict(plan.context)
            context["entries"] = [
                e for e in (context.get("entries") or [])
                if getattr(getattr(e, "item", None), "fid", "") in selected_fids]
            nfo_plan.context = context
        desired = nfo.desired_files(nfo_plan, details, poster, fanart)

        report("正在读取已有 NFO/图片…")
        mr = (plan.context or {}).get("mr")
        root_cid = (mr.item.fid if mr is not None else
                    plan.item.parent_id or "0")
        files = [it for it in self.client.list_tree(
            root_cid, max_depth=5) if not it.is_dir]
        # 本地模式不提供删除/回收站操作，已有附件统一跟随改名。
        mode = ("rename" if self.is_local else
                self.settings.get("nfo_existing", "rename"))
        pairs: list[tuple] = []
        info_files: list[P115Item] = []
        if mode == "replace":
            info_files = nfo.matching_info_files(nfo_plan, files)
        else:
            pairs = nfo.sidecar_renames(nfo_plan, files)
        return {"plan": plan, "source": source, "mode": mode,
                "desired": desired, "files": files, "pairs": pairs,
                "info_files": info_files}

    def _finish_nfo_task(self, prep: dict, progress=None) -> dict:
        """执行已有 NFO 改名/删除，并逐个上传缺失的 NFO/图片。"""
        plan = prep["plan"]
        mode = prep["mode"]
        desired = list(prep.get("desired") or [])
        files = list(prep.get("files") or [])
        pairs = list(prep.get("pairs") or [])
        info_files = list(prep.get("info_files") or [])
        units = len(pairs) + len(info_files) + len(desired)
        total = max(1, units)
        done = 0

        def report(text: str, add: int = 0) -> None:
            nonlocal done
            done += add
            if progress:
                progress(min(done, total), total, text)

        report("正在保存 NFO/图片…")
        deleted = 0
        renames = 0
        if mode == "replace" and info_files:
            deleted = self.client.delete_to_recycle(
                [f.fid for f in info_files])
            gone = {f.fid for f in info_files}
            files = [f for f in files if f.fid not in gone]
            report(f"已清理旧 NFO/图片 {deleted} 个", len(info_files))
        elif pairs:
            ops = [RenameOp(
                fid=it.fid, old_name=it.name, new_name=new_name,
                is_dir=False, role="nfo", parent_id=it.parent_id)
                for it, new_name in pairs]
            results = self.client.rename_many(ops)
            bad = [r for r in results if not r.ok]
            if bad:
                raise RuntimeError(
                    "已有 NFO/图片改名失败：" +
                    "；".join(f"{r.old_name}: {r.message}"
                             for r in bad[:3]))
            renames = len(results)
            for it, new_name in pairs:
                it.name = new_name
            report(f"已有 NFO/图片跟随改名 {renames} 个", len(pairs))

        existing = {(f.parent_id, f.name.casefold()) for f in files}
        uploads = 0
        skipped = 0
        for idx, item in enumerate(desired, 1):
            cid = str(item.get("cid") or "")
            filename = str(item.get("filename") or "")
            data = item.get("data") or b""
            if not cid or not filename or not data or \
                    (cid, filename.casefold()) in existing:
                skipped += 1
                report(f"跳过已存在的 NFO/图片 {idx}/{len(desired)}", 1)
                continue
            self.client.upload_bytes(
                cid, filename, data,
                str(item.get("mime") or "application/octet-stream"))
            existing.add((cid, filename.casefold()))
            uploads += 1
            action = "写入本地" if self.is_local else "上传"
            report(f"正在{action} NFO/图片 {idx}/{len(desired)}", 1)
        if not units:
            report("没有需要保存的 NFO/图片", 1)
        return {"plan": plan, "source": prep.get("source", ""),
                "mode": mode, "renames": renames, "deleted": deleted,
                "uploads": uploads, "skipped": skipped, "units": units,
                "local": bool(self.is_local)}

    def _save_nfo_task(self, plan: PlanItem, progress=None) -> dict:
        prep = self._prepare_nfo_task(plan, progress)
        return self._finish_nfo_task(prep, progress)

    def _save_nfo_batch(self, plans: list[PlanItem], progress=None,
                        phase_label: str = "2/2", base_done: int = 0,
                        base_total: int = 0) -> list[dict]:
        """多个任务一起保存 NFO：先准备，再按文件总数统一推进进度。

        base_done/base_total 用于和“重命名阶段”共用同一根进度条：
        准备 NFO 时保持重命名已完成的进度，NFO 文件总数确定后
        把总分母加上去，进度条不会先归零再重跑。
        """
        preps = []
        n = max(1, len(plans))
        for idx, p in enumerate(plans, 1):
            if progress:
                if base_total:
                    progress(base_done, base_total,
                             f"阶段 {phase_label}：准备 NFO/图片 "
                             f"{idx}/{n}：{p.title}")
                else:
                    progress(0, 0,
                             f"阶段 {phase_label}：准备 NFO/图片 "
                             f"{idx}/{n}：{p.title}")
            def prep_progress(d, t, m, base_done=base_done,
                              base_total=base_total):
                if not progress:
                    return
                if base_total:
                    progress(base_done, base_total, m)
                else:
                    progress(0, 0, m)

            preps.append(self._prepare_nfo_task(
                p, progress=prep_progress if progress else None))
        units = sum(len(x.get("pairs") or []) +
                    len(x.get("info_files") or []) +
                    len(x.get("desired") or []) for x in preps)
        overall_total = max(1, base_total + units)
        base = base_done
        infos: list[dict] = []
        for prep in preps:
            def report(done, total_local, text, base=base):
                if progress:
                    progress(min(base + done, overall_total),
                             overall_total, f"阶段 {phase_label}：{text}")
            info = self._finish_nfo_task(prep, report)
            base += int(info.get("units", 0))
            infos.append(info)
        if progress:
            progress(overall_total, overall_total, "NFO/图片保存完成")
        return infos

    def save_nfo_artwork(self) -> None:
        p = self.detail_plan
        if not p:
            messagebox.showinfo(APP_TITLE, "请先在右侧选择一个任务。",
                                parent=self)
            return
        if not self.client or self.is_demo:
            messagebox.showinfo(APP_TITLE, "演示模式不会保存 NFO/图片。",
                                parent=self)
            return
        if not p.ops:
            messagebox.showinfo(APP_TITLE, "这个任务还没有可用的新名称。",
                                parent=self)
            return
        mode = self._nfo_mode_text()
        extra = ("\n注意：会先删除与当前任务匹配的旧 .nfo/图片"
                 "（移到 115 回收站），同目录其他影片的资料不动。"
                 if not self.is_local and
                 self.settings.get("nfo_existing") == "replace" else "")
        target = "本地文件夹" if self.is_local else "115"
        if not messagebox.askyesno(
                APP_TITLE,
                f"将为「{p.title}」保存 NFO/图片到{target}。\n{mode}\n"
                f"会生成 tvshow/每集 NFO 和 poster/fanart，只补齐缺失文件。"
                f"{extra}\n\n是否继续？", parent=self):
            return
        def task():
            return self._save_nfo_task(
                p, progress=lambda d, t, m: self.post(
                    "progress", (d, t, m)))

        self.run_async(task, "nfo_save", determinate=True)

    def _clear_nfo_scope(self, plan: PlanItem | None, root_cid: str,
                         scope: str) -> dict:
        files = [it for it in self.client.list_tree(
            root_cid, max_depth=5) if not it.is_dir]
        if plan is not None:
            # 只清和当前任务匹配的 NFO/图片；电影库同样只动这一部。
            info_files = nfo.matching_info_files(plan, files)
        else:
            # 当前文件夹：按里面每个视频名匹配；多电影根目录下的
            # 共享 poster.jpg/tvshow.nfo 不会被误当成某部电影的附件。
            info_files = nfo.matching_info_files_for_root(files)
        if info_files:
            self.client.delete_to_recycle([f.fid for f in info_files])
        return {"count": len(info_files),
                "names": [f.name for f in info_files[:12]],
                "scope": scope}

    def _start_clear_nfo(self, scope: str) -> None:
        p = self.detail_plan
        if scope == "selected" and p is not None:
            mr = (p.context or {}).get("mr")
            root_cid = mr.item.fid if mr is not None else p.item.parent_id or "0"
            plan = p
        else:
            root_cid = self.current_cid
            plan = None
        self.run_async(
            lambda: self._clear_nfo_scope(plan, root_cid, scope), "nfo_clear")

    def clear_nfo_artwork(self) -> None:
        if self.is_local:
            messagebox.showinfo(
                APP_TITLE,
                "本地模式不会删除或移动文件。\n"
                "如需清理 NFO/图片，请在本机文件夹里手动处理。",
                parent=self)
            return
        if not self.client or self.is_demo:
            messagebox.showinfo(APP_TITLE, "演示模式不会删除文件。",
                                parent=self)
            return
        if not self.detail_plan and self.current_cid == "0":
            messagebox.showinfo(
                APP_TITLE, "请先进入一个剧集/电影文件夹，或选中一个任务。",
                parent=self)
            return
        ClearInfoDialog(self, bool(self.detail_plan), self._start_clear_nfo)

    def _plan_click(self, event) -> None:
        if self.plan_tree.identify_column(event.x) != "#1":
            return
        iid = self.plan_tree.identify_row(event.y)
        if not iid:
            return
        p = self._plan_by_iid(iid)
        if not p:
            return
        p.selected = not p.selected
        self.plan_tree.set(iid, "sel", "☑" if p.selected else "☐")
        return "break"

    def select_auto(self) -> None:
        for p in self.plans:
            p.selected = p.status == "auto" and bool(p.ops)
        self._render_plans()

    def select_all_ops(self) -> None:
        for p in self.plans:
            p.selected = bool(p.ops)
        self._render_plans()

    def select_none(self) -> None:
        for p in self.plans:
            p.selected = False
        self._render_plans()

    def toggle_selected(self) -> None:
        sel = self.plan_tree.selection()
        if not sel:
            return
        p = self._plan_by_iid(sel[0])
        if p:
            p.selected = not p.selected
            self.plan_tree.set(sel[0], "sel", "☑" if p.selected else "☐")

    def _plan_context(self, event):
        iid = self.plan_tree.identify_row(event.y)
        if not iid:
            return "break"
        self.plan_tree.selection_set(iid)
        self._plan_selected()
        try:
            self.plan_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.plan_menu.grab_release()
        return "break"

    def remove_current_plan(self) -> None:
        sel = self.plan_tree.selection()
        if not sel:
            return
        p = self._plan_by_iid(sel[0])
        if not p:
            return
        self.plans = [x for x in self.plans if x is not p]
        self._render_plans()
        self._save_plans_cache()
        self._log(f"已从等待列表移除：{p.title or p.current_name}")

    def clear_plans(self) -> None:
        if not self.plans:
            return
        if len(self.plans) > 3 and not messagebox.askyesno(
                APP_TITLE,
                f"清空等待列表中的 {len(self.plans)} 项？\n"
                "只清空界面列表，不会修改网盘。",
                parent=self):
            return
        self.plans = []
        self._render_plans()
        self._discard_plans_cache()
        self._log("已清空等待列表（未修改网盘）。")

    def restore_plans_manual(self) -> None:
        """右键菜单：不重新分析，直接恢复上次保存的等待列表。"""
        if self.busy:
            messagebox.showinfo(APP_TITLE, "当前有任务在执行，请稍候。",
                                parent=self)
            return
        if self.plans and not messagebox.askyesno(
                APP_TITLE, "当前已有等待列表。\n用上次保存的结果替换它？",
                parent=self):
            return
        if not self.settings.get("remember_plans", True):
            messagebox.showinfo(
                APP_TITLE, "设置里关闭了“记住上次分析结果”，无法恢复。",
                parent=self)
            return
        if not self._restore_plans():
            messagebox.showinfo(
                APP_TITLE,
                "没有可用的上次分析结果。\n可能是刚改过名、撤回过，"
                "或者换过账号/文件夹。请重新分析。", parent=self)

    def rebuild_detail(self) -> None:
        p = self.detail_plan
        if not p:
            return
        title = self.title_var.get().strip()
        year_text = self.year_var.get().strip()
        season_text = self.season_var.get().strip()
        try:
            year = int(year_text) if year_text else None
            season = int(season_text) if season_text else None
            if year is not None and not (1900 <= year <= 2100):
                raise ValueError("年份应在 1900-2100 之间")
            if season is not None and not (0 <= season <= 99):
                raise ValueError("季数应在 0-99 之间")
        except ValueError as e:
            messagebox.showerror(APP_TITLE, f"输入有误：{e}", parent=self)
            return
        if season is not None and len(p.seasons) > 1:
            if not messagebox.askyesno(
                    APP_TITLE,
                    f"这是多季剧集（已有季：{p.seasons}）。\n"
                    f"填季 {season} 会把所有集数都改成 S{season:02d}，\n"
                    "通常只应在“最终季/Part”无法自动判断时使用。\n\n继续？",
                    parent=self):
                return
        p.title_override = title
        p.year_override = year
        p.season_override = season
        # 分类不再由界面下拉指定：保留任务原有分类（自动判断结果）。
        if season is not None:
            p.season_confirmed = True

        def done(ok: bool, err: str) -> None:
            if not ok:
                self._log(f"重新生成预览失败：{err}")
                return
            if p.ops:
                p.selected = True
            self._render_plans()
            self._log(f"已重新生成预览：{p.title}（{len(p.ops)} 个操作）")

        self.rebuild_in_background(p, done)

    # ------------------------------------------------------------ 季集映射
    def open_episode_mapping(self) -> None:
        p = self.detail_plan
        if not p:
            messagebox.showinfo(APP_TITLE, "请先选择一个任务。", parent=self)
            return
        if p.media_type != "series":
            messagebox.showinfo(APP_TITLE, "只有剧集任务可以设置季集映射。",
                                parent=self)
            return
        videos = [e for e in ((p.context or {}).get("entries") or [])
                  if e.is_video]
        if not videos:
            messagebox.showinfo(APP_TITLE, "这个任务没有可映射的视频文件。",
                                parent=self)
            return
        EpisodeMappingDialog(self, self.planner, p,
                             self._apply_episode_mapping)

    def _apply_episode_mapping(self, p: PlanItem) -> None:
        """季集映射只重建预览，不直接改网盘。"""
        drop = ("没有识别到集数", "的集号是 0", "季号和目录不一致",
                "总集编号", "无法自动确定季号", "TMDB 第")
        parts = [x for x in (p.note.split("；") if p.note else [])
                 if x and not any(k in x for k in drop)]
        p.note = "；".join(parts)
        p.status = ("auto" if p.confidence >= self.options.min_auto_confidence
                    else "review")

        def done(ok: bool, err: str) -> None:
            if not ok:
                self._log(f"季集映射重建失败：{err}")
                return
            self._log(f"季集映射已应用：{p.title}（{len(p.ops)} 个操作）")

        self.rebuild_in_background(p, done)

    # ------------------------------------------------------------ 手动搜索
    @staticmethod
    def _manual_season(p: PlanItem):
        if p.season_override is not None:
            return p.season_override
        if len(p.seasons) == 1:
            return p.seasons[0]
        return p.season

    def _manual_keywords(self, p: PlanItem) -> list[str]:
        """从任务/文件名拆出可点击的搜索词。

        本地目录名是用户实际存放的作品名，优先于自动匹配结果：
        自动匹配可能已经匹配错，不能让它把本地完整标题挤掉。
        """
        season = self._manual_season(p)
        local: list[str] = []
        meta: list[str] = []
        seen: set[str] = set()

        def variants(text: str) -> list[str]:
            raw = (text or "").strip(" ._-–—:：·")
            if not raw:
                return []
            out = [raw]
            if p.media_type == "series":
                base = strip_season_markers(raw).strip(" ._-–—:：·")
                if base and norm_title(base) != norm_title(raw):
                    out.append(base)
            return out

        def agrees(word: str, primary: str) -> bool:
            """别名和本地主标题是否一致；过短的词（SAC）不作数。"""
            nw, np = norm_title(word), norm_title(primary)
            if not nw or not np:
                return False
            if nw == np:
                return True
            if len(nw) < 4:
                return False
            return titles_agree(word, primary)

        def add(bucket: list[str], text: str,
                must_agree: str = "") -> None:
            for word in variants(text):
                key = norm_title(word)
                if len(key) < 2 or key in seen:
                    continue
                if not _usable_query(word):
                    continue
                if must_agree and not agrees(word, must_agree):
                    continue
                seen.add(key)
                bucket.append(word)

        ancillary = _is_ancillary_dir_name(p.item.name)
        # 用户手动改过的标题最优先；其次是本地目录/文件名。
        add(local, p.title_override)
        if not ancillary:
            add(local, p.parsed.title)
            for q in p.parsed.queries:
                add(local, q)
        # 自动匹配的标题只作补充，而且必须和本地主标题对得上；
        # 否则匹配错的别名会混进模糊搜索，越搜越偏。
        primary = local[0] if local else ""
        # 上级目录从近到远，例如“攻壳机动队 SAC 2045 / S2-美版…”。
        # 只加入与本地主标题一致的那一级（以及它的别名）；不能把
        # “其他布袋戏（全系列）/布袋戏系列”这类合集容器也做成关键词。
        for name in reversed([a for a in (p.item.ancestors or []) if a]):
            parsed = parse_name(name, is_dir=True)
            if not _usable_query(parsed.title):
                continue
            if primary and not agrees(parsed.title, primary):
                continue
            add(local, parsed.title)
            for q in parsed.queries:
                add(local, q)
            if not primary:
                primary = parsed.title
        if ancillary:
            # “S2-美版暂无日语字幕”这类目录名只是说明，只有和上级
            # 作品名对得上时才作为关键词。
            add(local, p.parsed.title, primary)
            for q in p.parsed.queries:
                add(local, q, primary)
        else:
            # 目录名里的英文名/副标题也可能没进 p.parsed
            parsed = parse_name(p.item.name, is_dir=True)
            for q in parsed.queries:
                add(local, q)
        for text in (p.title, p.match.title_zh, p.match.series_title,
                     p.match.title_original, p.match.series_original_title):
            add(meta, text, primary)
        for cand in (p.match.douban, p.match.bangumi,
                     p.match.imdb, p.match.tmdb):
            if not cand:
                continue
            add(meta, cand.title, primary)
            add(meta, cand.original_title, primary)
            if isinstance(cand.extra, dict):
                for alias in (cand.extra.get("aliases") or [])[:3]:
                    add(meta, alias, primary)

        # 把“降世神通：科拉传奇”拆出副标题“科拉传奇”，也做成可点击关键词
        extras: list[str] = []
        for base in local + meta:
            for sep in ("：", ":"):
                if sep in base:
                    tail = base.rsplit(sep, 1)[1].strip(" ._-–—")
                    if tail and len(norm_title(tail)) >= 2:
                        extras.append(tail)
                    break
        for extra in extras:
            if all(norm_title(extra) != norm_title(b) for b in local + meta):
                meta.append(extra)

        bases = (local + meta)[:6]
        out: list[str] = []
        out_seen: set[str] = set()

        def add_out(text: str) -> None:
            text = (text or "").strip(" ._-–—:：·")
            key = norm_title(text)
            if len(key) < 2 or key in out_seen:
                return
            out_seen.add(key)
            out.append(text)

        for base in bases:
            add_out(base)
        if p.media_type == "series" and season is not None:
            cn = cn_season_number(season)
            for base in bases:
                if re.search(r"(?i)第\s*\d+\s*[季期部]|Season\s*\d+|"
                             r"S\d{1,2}|最终季|Part\s*\d+|Cour\s*\d+",
                             base):
                    continue
                if re.search(r"[㐀-鿿]", base):
                    add_out(f"{base} 第{cn}季")
                    if cn != str(season):
                        add_out(f"{base} 第{season}季")
                if re.search(r"[A-Za-z]", base):
                    add_out(f"{base} Season {season}")
                    add_out(f"{base} S{season:02d}")
        return out[:9]

    def open_manual_search(self) -> None:
        p = self.detail_plan
        if not p:
            messagebox.showinfo(APP_TITLE, "请先在右侧选择一个任务。",
                                parent=self)
            return
        if self.busy:
            messagebox.showinfo(APP_TITLE, "当前有任务在执行，请稍候。",
                                parent=self)
            return
        if self.is_demo:
            messagebox.showinfo(
                APP_TITLE,
                "演示模式不联网。请用正式模式登录后再手动搜索。",
                parent=self)
            return
        keywords = self._manual_keywords(p)
        title_val = self.title_var.get().strip()
        auto_title = (p.title or "").strip()
        # 标题框还是自动匹配的标题时，优先用本地目录名作为搜索词；
        # 用户自己改过标题（或已有标题覆盖）才以输入框为准。
        if title_val and title_val != auto_title:
            query = title_val
        elif keywords:
            query = keywords[0]
        else:
            query = (title_val or p.display_title or
                     p.parsed.title or p.item.name)
        ManualSearchDialog(
            self, self.meta, query, p.media_type,
            lambda cand, ids: self._apply_manual_candidate(p, cand, ids),
            keywords=keywords,
            season=self._manual_season(p),
            year=p.display_year)

    def _apply_manual_candidate(self, p: PlanItem, cand,
                                ids: dict) -> None:
        """把手动选中的搜索结果应用到当前任务并重新生成预览。"""
        if not any(x is p for x in self.plans):
            return
        old = p.match
        old_title = (old.series_title or old.title_zh or
                     old.title_original or p.title)
        old_year = old.series_year or old.year or p.year
        cand_title = (cand.title or "").strip()
        if p.media_type == "series":
            base = strip_season_markers(cand_title) or cand_title
        else:
            base = cand_title
        base = base.strip() or old_title or p.title

        year = cand.year
        same_show = bool(
            old_title and base and titles_agree(base, old_title) and
            (not old_year or not year or abs(old_year - year) <= 1))
        # 选中的是“第二季”条目时，目录年份仍优先用主剧首播年
        if p.media_type == "series" and same_show and old_year and \
                (year is None or old_year < year):
            year = old_year

        imdb_id = str(ids.get("imdb_id") or "")
        tmdb_id = str(ids.get("tmdb_id") or "")
        if cand.source == "imdb" and not imdb_id and \
                str(cand.sid).startswith("tt"):
            imdb_id = cand.sid
        if cand.source == "tmdb" and not tmdb_id:
            tmdb_id = str(cand.sid or "")
        if same_show:
            imdb_id = imdb_id or old.series_imdb_id or old.imdb_id
            tmdb_id = tmdb_id or old.tmdb_id

        m = MatchResult()
        # 中文主名称不能被英文顶掉：手动选 IMDb 条目时 cand.title 是
        # 「Ever Night 2」，直接赋给 title_zh 会让整部剧变成英文名。
        # 优先级：旧结果里的中文名（同一部剧时）→ 新条目自带中文名
        # → 本地片名 → 英文名。
        def _has_cjk(x: str) -> bool:
            import re as _re
            return bool(_re.search(r"[\u4e00-\u9fff]", x or ""))

        new_title = (cand.title or "").strip()
        old_cn = old.title_zh if _has_cjk(old.title_zh) else ""
        if same_show and old_cn:
            m.title_zh = old_cn
        elif _has_cjk(new_title):
            m.title_zh = new_title
        elif _has_cjk(p.title or ""):
            m.title_zh = p.title
        else:
            m.title_zh = new_title or old.title_zh
        m.title_original = cand.original_title or (
            old.title_original if same_show else "")
        m.year = cand.year
        m.imdb_id = imdb_id
        m.tmdb_id = tmdb_id
        m.douban_id = cand.sid if cand.source == "douban" else ""
        m.bangumi_id = cand.sid if cand.source == "bangumi" else ""
        m.country = str(ids.get("country") or "") or old.country
        m.animation = bool(ids.get("animation")) or old.animation
        m.confidence = 1.0
        if cand.source == "douban":
            m.douban = cand
        elif cand.source == "bangumi":
            m.bangumi = cand
        elif cand.source == "imdb":
            m.imdb = cand
        elif cand.source == "tmdb":
            m.tmdb = cand
        # 手动选 Bangumi/豆瓣时，也把补齐到的 IMDb/TMDB 条目挂上，
        # 这样目录第二段可以用它们的英文名。
        # 关键：只要**有 ID 就挂**，标题可以留空后补。
        # 以前要求必须同时有标题，导致手动套用 IMDb 后 match.tmdb 为
        # None，「副标题 = TMDB」查不到任何分集名。
        imdb_title = str(ids.get("imdb_title") or "")
        if not m.imdb and imdb_id:
            m.imdb = Candidate(source="imdb", title=imdb_title,
                               original_title=imdb_title,
                               year=cand.year, sid=imdb_id)
        tmdb_title = str(ids.get("tmdb_title") or "")
        if not m.tmdb and tmdb_id:
            m.tmdb = Candidate(source="tmdb", title=tmdb_title,
                               original_title=str(ids.get("tmdb_original") or
                                                  tmdb_title),
                               year=cand.year, sid=tmdb_id)
        # 方案 1：搜索阶段已经为每个候选预取了它自己的「英文名/分集名」，
        # 这里直接把这些词句挂到对应来源上，双击即可套用，无需再联网。
        pre = cand.extra if isinstance(cand.extra, dict) else {}
        pre_en = str(pre.get("english_title") or "")
        pre_eps = pre.get("episode_titles") or {}
        if pre_en:
            src = cand.source
            holder = {"imdb": m.imdb, "tmdb": m.tmdb,
                      "douban": m.douban, "bangumi": m.bangumi}.get(src)
            if holder is None:
                holder = Candidate(source=src, title=cand.title,
                                   original_title=pre_en,
                                   year=cand.year, sid=cand.sid)
                holder.extra = {}
                if src == "imdb":
                    m.imdb = holder
                elif src == "tmdb":
                    m.tmdb = holder
                elif src == "douban":
                    m.douban = holder
                elif src == "bangumi":
                    m.bangumi = holder
            if isinstance(holder.extra, dict):
                holder.extra.setdefault("english_title", pre_en)
                if not holder.original_title:
                    holder.original_title = pre_en
                if pre_eps:
                    holder.extra.setdefault("episode_titles", pre_eps)
        # series_title 决定最终显示/命名的剧名，同样不能变成纯英文：
        # 手动选 IMDb 条目时 base 是 Ever Night 2，而这部剧的中文名
        # 是「将夜」，主标题必须继续用中文。
        if _has_cjk(new_title):
            m.series_title = new_title
        elif _has_cjk(old.title_zh or "") and same_show:
            m.series_title = old.title_zh
        elif _has_cjk(p.title or ""):
            m.series_title = p.title
        else:
            m.series_title = base
        m.series_year = year
        m.series_imdb_id = imdb_id if p.media_type == "series" else ""
        m.is_season_entry = bool(
            p.media_type == "series" and
            strip_season_markers(cand_title) != cand_title)
        if p.category == "auto":
            if m.country == "jp":
                p.category = "jp_anime"
            elif m.country == "cn":
                p.category = "cn_anime" if m.animation else "tv"
            elif m.country == "us" and m.animation:
                p.category = "us_anime"
            elif m.country in ("uk", "ca", "west") and m.animation:
                p.category = "west_anime"
        note = (f"手动搜索：{SOURCE_LABELS.get(cand.source, cand.source)}"
                f"「{cand.title}」"
                + (f" ({cand.year})" if cand.year else ""))
        m.notes = [note]
        if cand.kind and (
                (p.media_type == "series" and cand.kind == "movie") or
                (p.media_type == "movie" and cand.kind == "tv")):
            m.notes.append("该结果的数据源类型与当前任务不同，请核对分类。")
        if not imdb_id and not tmdb_id:
            m.notes.append("没有找到可写入的 IMDb/TMDB 标识，目录名会省略 ID。")

        p.match = m
        # p.title 决定最终文件名的中文主名称：手动选 IMDb 条目时
        # base 是英文（Ever Night 2），不能拿它覆盖中文剧名。
        p.title = m.series_title if _has_cjk(m.series_title or "") else base
        p.year = year
        p.series_imdb_id = m.series_imdb_id
        p.confidence = 1.0
        p.status = "auto"
        p.title_override = ""
        p.year_override = None
        if not isinstance(p.context, dict):
            p.context = {}
        p.context["imdb_id"] = (m.series_imdb_id if p.media_type == "series"
                                else m.imdb_id)
        p.context["tmdb_id"] = m.tmdb_id
        # 手动选过条目后，原目录里的日/英文名可能属于另一部剧，不能再优先使用
        p.context["manual_match"] = True
        drop = ("没有找到匹配", "置信度较低", "请手动", "已还原主剧名",
                "缺少首播年份", "缺少年份", "没有识别出剧名", "目录名会省略")
        kept = [n for n in (p.note or "").split("；")
                if n and not any(d in n for d in drop)]
        p.note = "；".join(dict.fromkeys(kept + m.notes))

        def done(ok: bool, err: str) -> None:
            if not ok:
                self._log(f"应用手动搜索结果失败：{err}")
                return
            if p.ops:
                p.selected = True
            self._render_plans()
            self._log(f"已应用手动搜索结果：{base}"
                      + (f" ({year})" if year else "")
                      + f"，{len(p.ops)} 个操作")

        self.rebuild_in_background(p, done)

    # ------------------------------------------------------------ 临时改名
    def temp_rename(self) -> None:
        p = self.detail_plan
        if not p:
            messagebox.showinfo(APP_TITLE, "请先在右侧选择一个任务。",
                                parent=self)
            return
        if not p.ops:
            messagebox.showinfo(APP_TITLE, "这个任务没有可改名的项目。",
                                parent=self)
            return
        if self.busy:
            messagebox.showinfo(APP_TITLE, "当前有任务在执行，请稍候。",
                                parent=self)
            return
        if not self.client:
            messagebox.showinfo(
                APP_TITLE,
                "请先登录 115、使用演示模式，或切换到本地模式。",
                parent=self)
            return
        TempRenameDialog(self, p, self._start_temp_rename)

    def _start_temp_rename(self, plan: PlanItem, op, new_name: str) -> None:
        if self.busy:
            return
        clash = [o for o in plan.ops
                 if o.fid != op.fid and o.parent_id == op.parent_id and
                 o.new_name.casefold() == new_name.casefold()]
        if clash:
            messagebox.showerror(
                APP_TITLE,
                f"同一目录下已经有同名目标：\n{clash[0].new_name}",
                parent=self)
            return
        new_op = RenameOp(fid=op.fid, old_name=op.old_name,
                          new_name=new_name, is_dir=op.is_dir,
                          role=op.role, parent_id=op.parent_id)
        problem = self._validate_ops([new_op])
        if problem:
            messagebox.showerror(APP_TITLE, problem, parent=self)
            return
        client = self.client
        self._log(f"临时改名：{op.old_name} → {new_name}")

        def task():
            results = client.rename_many(
                [new_op],
                progress=lambda a, b: self.post(
                    "progress", (a, b, "正在临时改名…")))
            return plan, op, new_op, results

        self.run_async(task, "temp_rename", determinate=True)

    def _after_temp_rename(self, plan: PlanItem, old_op, new_op,
                           results) -> None:
        self._set_busy(False)
        ok = bool(results) and all(r.ok for r in results)
        if not ok:
            fail = "；".join(
                f"{r.old_name}: {r.message}" for r in results if not r.ok)
            self._log(f"临时改名失败：{fail}")
            messagebox.showerror(APP_TITLE, f"临时改名失败：\n{fail}",
                                 parent=self)
            return
        self.undo.record([new_op], results)
        self._log(f"临时改名成功：{old_op.old_name} → {new_op.new_name}")

        # 更新内存里的名字，避免界面继续显示旧名
        targets = [plan.item]
        mr = plan.context.get("mr") if isinstance(plan.context, dict) else None
        if mr:
            targets.append(mr.item)
            targets += list(mr.season_dirs) + list(mr.part_dirs)
            targets += [e.item for e in mr.entries]
        for it in targets:
            if it is not None and it.fid == old_op.fid:
                it.name = new_op.new_name
        entries = (plan.context.get("entries", [])
                   if isinstance(plan.context, dict) else [])
        for e in entries:
            if e.item.fid == old_op.fid:
                e.item.name = new_op.new_name

        # 被临时改名的项目从等待任务里移除；对应字幕也一并移除，
        # 避免之后批量应用时把字幕改成与视频不匹配的名字。
        gone = {old_op.fid}
        if not old_op.is_dir:
            old_stem = os.path.splitext(old_op.new_name)[0].casefold()
            for s in plan.ops:
                if (s.role == "subtitle" and s.parent_id == old_op.parent_id
                        and s.new_name.casefold().startswith(old_stem)):
                    gone.add(s.fid)
        plan.ops = [o for o in plan.ops if o.fid not in gone]

        if plan.ops:
            self._render_plans()
        else:
            self.plans = [x for x in self.plans if x is not plan]
            self._render_plans()

        # 当前正在浏览的目录/文件夹被改名时，同步路径显示
        if old_op.is_dir and old_op.fid == self.current_cid:
            self.path_stack[-1] = (self.current_cid, new_op.new_name)
            self.path_label.configure(
                text=" / ".join(name for _, name in self.path_stack))
            if self.current_item is not None and \
                    self.current_item.fid == old_op.fid:
                self.current_item.name = new_op.new_name
        self.refresh()

    def preview_ops(self) -> None:
        p = self.detail_plan
        if not p:
            return
        win = tk.Toplevel(self)
        win.title(f"重命名预览 - {p.title}")
        win.transient(self)
        win.minsize(900, 420)
        self._center_window(win, 1260, 560, parent=self)

        style = ttk.Style(win)
        style.configure("Preview.Treeview", rowheight=22,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Preview.Treeview.Heading",
                        font=("Microsoft YaHei UI", 9, "bold"))

        ttk.Label(win, text=f"当前：{p.current_name}",
                  font=("Microsoft YaHei UI", 10, "bold"),
                  wraplength=1220, justify="left").pack(
                      anchor="w", padx=12, pady=(10, 2))
        if p.note:
            ttk.Label(win, text=p.note, foreground="#a15c00",
                      wraplength=1220, justify="left").pack(
                          anchor="w", padx=12, pady=(0, 2))
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=12, pady=(6, 6))
        cols = ("sel", "role", "old", "new")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                            style="Preview.Treeview")
        tree.heading("sel", text="选")
        tree.heading("role", text="类型")
        tree.heading("old", text="原名称")
        tree.heading("new", text="新名称")
        # “选”列固定窄；原名称/新名称各占一半并随窗口拉伸
        tree.column("sel", width=40, minwidth=36, stretch=False,
                    anchor="center")
        tree.column("role", width=76, minwidth=64, stretch=False, anchor="w")
        tree.column("old", width=560, minwidth=260, stretch=True, anchor="w")
        tree.column("new", width=560, minwidth=260, stretch=True, anchor="w")
        vs = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        by_iid: dict[str, RenameOp] = {}
        count_var = tk.StringVar()

        def refresh_count() -> None:
            total = len(p.ops)
            chosen = sum(1 for op in p.ops if op.selected)
            count_var.set(f"已选 {chosen}/{total}")

        def set_tree_value(iid: str) -> None:
            op = by_iid.get(iid)
            if op is not None:
                tree.set(iid, "sel", "☑" if op.selected else "☐")

        def toggle(iid: str) -> None:
            op = by_iid.get(iid)
            if op is None:
                return
            op.selected = not op.selected
            set_tree_value(iid)
            refresh_count()

        def set_all(value: bool) -> None:
            for op in p.ops:
                op.selected = value
            for iid in by_iid:
                set_tree_value(iid)
            refresh_count()

        def on_click(event):
            if tree.identify_region(event.x, event.y) == "cell" and \
                    tree.identify_column(event.x) == "#1":
                iid = tree.identify_row(event.y)
                if iid in by_iid:
                    toggle(iid)
                    return "break"
            return None

        def on_space(event):
            for iid in tree.selection():
                if iid in by_iid:
                    toggle(iid)
            return "break"

        if p.ops:
            for idx, op in enumerate(p.ops):
                iid = f"o{idx}"
                by_iid[iid] = op
                tree.insert("", "end", iid=iid, values=(
                    "☑" if op.selected else "☐",
                    ROLE_LABELS.get(op.role, op.role),
                    op.old_name, op.new_name),
                    tags=("odd",) if idx % 2 else ())
        else:
            tree.insert("", "end", values=(
                "", "—", "没有需要修改的项目", ""))
        tree.tag_configure("odd", background="#f7f7f7")
        tree.bind("<Button-1>", on_click)
        tree.bind("<space>", on_space)
        refresh_count()

        footer = ttk.Frame(win)
        footer.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Label(footer, text="默认全选；点“选”列可单独取消",
                  foreground="#777").pack(side="left")
        ttk.Label(footer, textvariable=count_var,
                  foreground="#176b33").pack(side="left", padx=12)
        ttk.Button(footer, text="关闭", command=win.destroy).pack(
            side="right")
        ttk.Button(footer, text="全不选",
                   command=lambda: set_all(False)).pack(
                       side="right", padx=6)
        ttk.Button(footer, text="全选",
                   command=lambda: set_all(True)).pack(
                       side="right")

    # ------------------------------------------------------------ 应用/撤销
    def _validate_ops(self, ops) -> str:
        seen: dict[tuple[str, str], str] = {}
        for op in ops:
            if not op.new_name or op.new_name.strip() in ("", ".", ".."):
                return f"目标名称为空：{op.old_name}"
            if self.is_local and not is_valid_local_name(op.new_name):
                return (f"目标名称包含 Windows 不允许的字符，"
                        f"或以空格/句点结尾：\n{op.old_name} → {op.new_name}")
            if not op.is_dir:
                old_ext = os.path.splitext(op.old_name)[1].lower()
                new_ext = os.path.splitext(op.new_name)[1].lower()
                if old_ext != new_ext:
                    return (f"扩展名不一致（不允许改扩展名）：\n"
                            f"{op.old_name} → {op.new_name}")
            key = (op.parent_id, op.new_name.casefold())
            if key in seen:
                return (f"同一目录下会出现重名：\n{seen[key]}\n{op.new_name}")
            seen[key] = op.new_name
        return ""

    def apply_selected(self) -> None:
        if self.busy:
            return
        selected = [
            p for p in self.plans
            if p.selected and any(
                op.selected and op.old_name != op.new_name
                for op in p.ops)]
        if not selected:
            messagebox.showinfo(
                APP_TITLE,
                "没有选中的可应用项目（请检查任务勾选和预览里的项目勾选）。",
                parent=self)
            return
        ops = []
        by_fid = {}
        for p in selected:
            for op in p.ops:
                if not op.selected or op.old_name == op.new_name:
                    continue
                if op.fid in by_fid:
                    if by_fid[op.fid].new_name != op.new_name:
                        messagebox.showerror(
                            APP_TITLE,
                            f"同一文件出现两个不同的目标名，已中止：\n{op.old_name}",
                            parent=self)
                        return
                    continue
                by_fid[op.fid] = op
                ops.append(op)
        if not ops:
            messagebox.showinfo(APP_TITLE,
                                "没有需要改名的项目（可能都已经改好了）。",
                                parent=self)
            return
        problem = self._validate_ops(ops)
        if problem:
            messagebox.showerror(APP_TITLE, problem, parent=self)
            return
        sample = "\n".join(f"  {o.old_name}\n    → {o.new_name}" for o in ops[:6])
        if len(ops) > 6:
            sample += f"\n  … 共 {len(ops)} 项"
        auto_nfo = bool(self.auto_nfo_var.get()) and not self.is_demo
        auto_note = ("\n\n完成后会自动保存 NFO/图片。" if auto_nfo else
                     ("\n\n演示模式：只模拟改名，不会自动保存 NFO/图片。"
                      if self.auto_nfo_var.get() else ""))
        if not messagebox.askyesno(
                APP_TITLE,
                f"将重命名 {len(ops)} 个文件/文件夹（涉及 {len(selected)} 个条目）。\n\n"
                f"{sample}\n\n只改名，不删除、不移动。{auto_note}是否继续？",
                parent=self):
            return
        client = self.client
        self._log(f"开始应用：{len(ops)} 个操作…")
        if auto_nfo:
            self._log("已勾选“改名后自动存 NFO/图片”，完成后会继续保存。")

        def task():
            results = client.rename_many(
                ops, progress=lambda a, b: self.post(
                    "progress", (a, b, "阶段 1/2：正在重命名…")))
            nfo_infos: list[dict] = []
            if auto_nfo:
                success = {r.fid for r in results if r.ok}
                nfo_plans: list[PlanItem] = []
                for p in selected:
                    pending = {op.fid for op in p.ops
                               if op.selected and
                               op.old_name != op.new_name}
                    if not pending:
                        continue
                    if not pending <= success:
                        nfo_infos.append({
                            "plan": p,
                            "error": "部分文件改名失败，未自动保存 NFO/图片"})
                        continue
                    nfo_plans.append(p)
                if nfo_plans:
                    try:
                        nfo_infos.extend(self._save_nfo_batch(
                            nfo_plans,
                            progress=lambda d, t, m: self.post(
                                "progress", (d, t, m)),
                            base_done=len(ops), base_total=len(ops)))
                    except (P115RateLimitError, P115AuthError) as e:
                        nfo_infos.append({"plan": nfo_plans[0],
                                          "error": str(e)})
                        self.post(
                            "log",
                            "115 风控/登录失效，已停止自动保存后续 NFO/图片。")
                    except Exception as e:  # noqa: BLE001
                        nfo_infos.append({"plan": nfo_plans[0],
                                          "error": str(e)})
            return ops, results, auto_nfo, nfo_infos

        self.run_async(task, "apply", determinate=True)

    def _after_apply(self, ops, results, auto_nfo: bool,
                     nfo_infos: list[dict]) -> None:
        self._set_busy(False)
        ok = sum(1 for r in results if r.ok)
        fail = len(results) - ok
        self.undo.record(ops, results, scope=self._undo_scope())
        self._log(f"重命名完成：成功 {ok}，失败 {fail}。")
        # 如果当前目录本身被改名，更新路径显示
        for op in ops:
            if op.is_dir and op.fid == self.current_cid:
                self.path_stack[-1] = (self.current_cid, op.new_name)

        nfo_ok = [x for x in nfo_infos if not x.get("error")]
        nfo_bad = [x for x in nfo_infos if x.get("error")]
        nfo_msg = ""
        if auto_nfo:
            uploads = sum(int(x.get("uploads", 0)) for x in nfo_ok)
            renames = sum(int(x.get("renames", 0)) for x in nfo_ok)
            deleted = sum(int(x.get("deleted", 0)) for x in nfo_ok)
            skipped = sum(int(x.get("skipped", 0)) for x in nfo_ok)
            action = "写入本地" if self.is_local else "上传"
            nfo_msg = (f"自动保存 NFO/图片：{len(nfo_ok)} 个任务，"
                       f"{action} {uploads}，改名 {renames}，删除 {deleted}，"
                       f"跳过 {skipped}。")
            if nfo_bad:
                nfo_msg += f"失败 {len(nfo_bad)} 个。"
            self._log(nfo_msg)
        if fail or nfo_bad:
            parts: list[str] = []
            if fail:
                errors = []
                for r in [x for x in results if not x.ok][:10]:
                    message = str(r.message)
                    if self._is_risk_error(message):
                        message = "疑似 115 风控，已停止后续请求，请稍后再试。"
                    errors.append(f"{r.old_name} → {r.new_name}\n  {message}")
                parts.append(f"重命名成功 {ok} 个，失败 {fail} 个。\n\n" +
                             "\n".join(errors))
            if nfo_bad:
                errs = []
                for x in nfo_bad[:10]:
                    title = getattr(x.get("plan"), "title", "任务")
                    error = str(x.get("error"))
                    if self._is_risk_error(error):
                        error = "疑似 115 风控，已暂停自动保存，请稍后再试。"
                    errs.append(f"  {title}: {error}")
                parts.append("自动保存 NFO/图片失败：\n" + "\n".join(errs))
            messagebox.showwarning(APP_TITLE, "\n\n".join(parts),
                                   parent=self)
        else:
            text = f"已完成 {ok} 个重命名。"
            if auto_nfo:
                text += "\n\n" + (nfo_msg or "自动保存 NFO/图片：没有可保存的任务。")
            messagebox.showinfo(APP_TITLE, text, parent=self)
        self.plans = []
        self._render_plans()
        self._discard_plans_cache()
        self.refresh()

    def undo_last(self) -> None:
        if self.busy:
            return
        scope = self._undo_scope()
        found = self.undo.last_undoable(scope)
        if not found:
            messagebox.showinfo(APP_TITLE, "没有可以撤销的记录。", parent=self)
            return
        _, batch = found
        if not messagebox.askyesno(
                APP_TITLE,
                f"撤销上一次应用（{len(batch['ops'])} 个操作）？\n"
                "只会改回名字仍然匹配的项目。",
                parent=self):
            return
        client = self.client
        self.run_async(
            lambda: self.undo.undo_last(
                client, log=self.log_threadsafe, scope=scope),
            "undo")

    def _after_undo(self, results) -> None:
        self._set_busy(False)
        ok = sum(1 for r in results if r.ok)
        self._log(f"撤销结果：成功 {ok} 个。")
        self._discard_plans_cache()
        self.refresh()

    # ------------------------------------------------------------ 登录
    def open_login(self) -> None:
        if self.busy:
            return
        if (self.is_local or self.is_demo) and not self._switch_mode(
                "cloud", check_login=False):
            return
        if not isinstance(self.client, P115Client):
            self.client = P115Client(self.data_dir, log=self.log_threadsafe)
            self.cloud_client = self.client
        LoginDialog(self, self.client)

    def open_cookie(self) -> None:
        if self.busy:
            return
        if (self.is_local or self.is_demo) and not self._switch_mode(
                "cloud", check_login=False):
            return
        if not isinstance(self.client, P115Client):
            self.client = P115Client(self.data_dir, log=self.log_threadsafe)
            self.cloud_client = self.client
        CookieDialog(self, self.client)

    def logout(self) -> None:
        if not messagebox.askyesno(
                APP_TITLE,
                "退出 115 登录并删除已保存的 Cookie？\n"
                "下次使用需要重新扫码（或导入 Cookie）。",
                parent=self):
            return
        if isinstance(self.client, P115Client):
            self.client.logout()
        self._set_login_status("未登录", "#b3261e")
        self._log("已退出 115 登录，Cookie 已清除。")

    def enable_demo(self) -> None:
        if self.busy:
            return
        if not self._discard_plans_for_switch():
            return
        self.client = MockP115Client(log=self.log_threadsafe)
        self.is_demo = True
        self.is_local = False
        self._set_login_status("演示模式（不改网盘）", "#176b33")
        self.dir_view_state = {}
        self.path_stack = [("0", "根目录（演示）")]
        self.current_cid = "0"
        self.current_item = None
        self.plans = []
        self._render_plans()
        self._clear_dir_tree()
        self._refresh_mode_controls()
        self._log("已进入演示模式：数据是内存里的示例，不会登录或修改你的 115。")
        self.refresh()

    # ------------------------------------------------------------ 设置
    def open_settings(self) -> None:
        SettingsDialog(self)

    def apply_settings(self, new_settings: dict) -> None:
        # 空值不覆盖已有值：避免用户“没填/没改”时把已保存的
        # Cookie、TMDB Key 清空。
        self.settings = merge_settings_safely(self.settings, new_settings)
        self._save_settings()
        self._init_meta()
        # 主界面的命名规则面板跟随最新设置刷新
        try:
            if self.naming_panel is not None:
                self.naming_panel.reload()
        except Exception:
            pass
        self.nfo_mode_label.configure(text=self._nfo_mode_text())
        self._sync_update_schedule()
        self._log("设置已保存。")


# ---------------------------------------------------------------- 对话框
class RiskNoticeDialog(tk.Toplevel):
    """首次使用时的 115 风控提醒；可勾选只显示一次。"""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("115 风控提醒")
        self.geometry("560x330")
        App._center_window(self, 560, 330, parent=app)
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._ok)

        ttk.Label(self, text="请放慢操作，避免触发 115 风控",
                  font=("Microsoft YaHei UI", 13, "bold"),
                  foreground="#b35c00").pack(anchor="w", padx=22, pady=(20, 8))
        text = (
            "不要在软件里频繁刷新、连续分析/改名，或短时间反复点击。\n\n"
            "操作过快可能触发 115 风控：手机端还能登录，但电脑、电视端"
            "可能暂时看不到文件。\n\n"
            "建议每次操作之间稍等片刻；遇到“疑似风控”提示时，先暂停"
            "几分钟再试。"
        )
        ttk.Label(self, text=text, justify="left", wraplength=510,
                  foreground="#333").pack(anchor="w", padx=22)
        self.once_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self, text="只显示一次（下次启动不再提示）",
            variable=self.once_var).pack(anchor="w", padx=22, pady=(18, 8))
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=22, pady=(4, 16))
        ttk.Button(btns, text="知道了", command=self._ok).pack(side="right")

    def _ok(self) -> None:
        self.app.settings["risk_notice_dismissed"] = bool(self.once_var.get())
        try:
            self.app._save_settings()
        except Exception:
            pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class LoginDialog(tk.Toplevel):
    def __init__(self, app: App, client: P115Client):
        super().__init__(app)
        self.app = app
        self.client = client
        self.stop = threading.Event()
        self.token = None
        self.photo = None
        self.title("登录 115")
        self.geometry("400x610")
        app._center_window(self, 400, 610, parent=app)
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)
        ttk.Label(self, text="请用 115 手机 App 扫码登录",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(14, 2))
        ttk.Label(self, text="扫码一次后会记住登录；换新版本也不用再扫。",
                  foreground="#176b33").pack()
        dev = ttk.Frame(self)
        dev.pack(pady=(8, 2))
        ttk.Label(dev, text="登录设备").pack(side="left")
        self.app_var = tk.StringVar(
            value=app.settings.get("login_app", "ios"))
        self.app_box = ttk.Combobox(
            dev, textvariable=self.app_var, state="readonly", width=12,
            values=["ios", "android", "web"])
        self.app_box.pack(side="left", padx=6)
        self.app_box.bind("<<ComboboxSelected>>",
                          lambda e: self.refresh_qr())
        ttk.Label(self, text="建议 ios：不影响安卓手机和网页登录。\n"
                             "android 可能踢掉手机 App；web 会踢掉网页登录。\n"
                             "同一设备类型会互相踢下线；反复被踢就换一种设备重扫。",
                  foreground="#777", justify="center").pack(pady=(2, 4))
        self.qr_label = ttk.Label(self, text="正在获取二维码…", anchor="center")
        self.qr_label.pack(pady=6, fill="both", expand=True)
        self.status_label = ttk.Label(self, text="", foreground="#555")
        self.status_label.pack(pady=4)
        btns = ttk.Frame(self)
        btns.pack(pady=10)
        ttk.Button(btns, text="刷新二维码", command=self.refresh_qr).pack(side="left", padx=4)
        ttk.Button(btns, text="关闭", command=self._close).pack(side="left", padx=4)
        self._login_app = self.app_var.get()
        self._start()

    def _start(self) -> None:
        self.stop.clear()
        self._login_app = self.app_var.get()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            token = self.client.qr_token()
            image = self.client.qr_image(token["uid"])
            self.app.post("qr_token", (self, token, image))
            while not self.stop.is_set():
                status = self.client.qr_status(token)
                self.app.post("qr_status", (self, status))
                if status == 2:
                    ok = self.client.qr_login(token["uid"],
                                              app=self._login_app)
                    self.app.post("qr_done",
                                  (self, ok, self._login_app))
                    return
                if status in (-1, -2):
                    self.app.post("qr_expired", (self, status))
                    return
                time.sleep(2)
        except Exception as e:
            self.app.post("qr_error", (self, str(e)))

    def show_token(self, token: dict, image: bytes) -> None:
        if not self.winfo_exists():
            return
        self.token = token
        try:
            img = Image.open(io.BytesIO(image)).resize((280, 280),
                                                       Image.Resampling.NEAREST)
            self.photo = ImageTk.PhotoImage(img)
            self.qr_label.configure(image=self.photo, text="")
        except Exception as e:
            self.qr_label.configure(text=f"二维码图片加载失败：{e}")
        self.status_label.configure(text="等待扫码…", foreground="#555")

    def show_status(self, status: int) -> None:
        if status == 1:
            self.status_label.configure(text="已扫码，请在手机上确认登录",
                                        foreground="#176b33")
        elif status not in (0,):
            self.status_label.configure(text=f"二维码状态：{status}",
                                        foreground="#555")

    def show_expired(self, status: int) -> None:
        self.status_label.configure(
            text="二维码已过期" if status == -1 else "已取消登录",
            foreground="#b3261e")

    def show_error(self, msg: str) -> None:
        self.status_label.configure(text=f"登录失败：{msg}", foreground="#b3261e")

    def refresh_qr(self) -> None:
        self.stop.set()
        self.qr_label.configure(image="", text="正在刷新二维码…")
        self.status_label.configure(text="")
        self.after(300, self._start)

    def _close(self) -> None:
        self.stop.set()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class CookieDialog(tk.Toplevel):
    def __init__(self, app: App, client: P115Client):
        super().__init__(app)
        self.app = app
        self.client = client
        self.title("导入 115 Cookie")
        self.geometry("620x360")
        self.transient(app)
        app._center_window(self, 620, 360, parent=app)
        self.grab_set()
        ttk.Label(self, text="把浏览器里 115.com 的 Cookie 粘贴到下面（至少包含 UID、CID、SEID、KID）。",
                  wraplength=580).pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(self, text="格式示例：UID=123_CID=abc_SEID=def_KID=ghi（分号或换行分隔均可）",
                  foreground="#777").pack(anchor="w", padx=12)
        self.text = tk.Text(self, height=10, font=("Consolas", 9))
        self.text.pack(fill="both", expand=True, padx=12, pady=8)
        self.msg = ttk.Label(self, text="", foreground="#b3261e")
        self.msg.pack(anchor="w", padx=12)
        btns = ttk.Frame(self)
        btns.pack(pady=8)
        ttk.Button(btns, text="验证并保存", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)

    def save(self) -> None:
        text = self.text.get("1.0", "end").strip()
        if not text:
            self.show_error("请先粘贴 Cookie。")
            return
        try:
            self.client.set_cookie_text(text)
        except Exception as e:
            self.show_error(str(e))
            return
        self.msg.configure(text="正在验证…", foreground="#555")

        def worker():
            ok = self.client.is_logged_in(force=True)
            self.app.post("cookie_check", (self, ok, "Cookie 无效或已过期。"))
        threading.Thread(target=worker, daemon=True).start()

    def show_error(self, msg: str) -> None:
        self.msg.configure(text=msg, foreground="#b3261e")


class AboutDialog(tk.Toplevel):
    """版本、仓库和在线更新入口。"""

    def __init__(self, app: App, release: dict | None = None):
        super().__init__(app)
        self.app = app
        self._checking = False
        self._downloading = False
        self._release = None
        self._events: queue.Queue = queue.Queue()
        self.title("关于 AutoRename115")
        self.resizable(False, False)
        self.transient(app)
        app._center_window(self, 620, 470, parent=app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="115 海报墙重命名助手",
                  font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        self.version_label = ttk.Label(
            frame, text=f"版本 {updater.APP_VERSION}",
            foreground="#176b33")
        self.version_label.pack(anchor="w", pady=(4, 10))
        repo_row = ttk.Frame(frame)
        repo_row.pack(anchor="w", pady=(0, 10))
        ttk.Label(repo_row, text="GitHub 仓库：").pack(side="left")
        self.repo_link = ttk.Label(
            repo_row, text=updater.REPO_URL, foreground="#0563c1",
            cursor="hand2", font=("Microsoft YaHei UI", 9, "underline"))
        self.repo_link.pack(side="left")
        self.repo_link.bind("<Button-1>", self._open_repo)
        self.repo_link.bind("<Return>", self._open_repo)
        self.repo_link.bind("<space>", self._open_repo)
        self.repo_link.configure(takefocus=True)
        qq_row = ttk.Frame(frame)
        qq_row.pack(anchor="w", pady=(0, 10))
        ttk.Label(qq_row, text="QQ 频道：").pack(side="left")
        self.qq_link = ttk.Label(
            qq_row, text=qq_channel.QQ_CHANNEL_NAME, foreground="#0563c1",
            cursor="hand2", font=("Microsoft YaHei UI", 9, "underline"))
        self.qq_link.pack(side="left")
        self.qq_link.bind("<Button-1>", self._open_qq)
        self.qq_link.bind("<Return>", self._open_qq)
        self.qq_link.bind("<space>", self._open_qq)
        self.qq_link.configure(takefocus=True)
        ttk.Button(qq_row, text="二维码",
                   command=self._show_qq_qr).pack(side="left", padx=(8, 4))
        ttk.Button(qq_row, text="在 QQ 中打开",
                   command=self._open_qq).pack(side="left")
        ttk.Label(
            frame,
            text="在线更新：从 GitHub Release 下载便携包，退出后覆盖当前程序目录；"
                 "登录数据 data/ 会保留。更新完成后程序会自动重新打开。",
            foreground="#555", wraplength=570, justify="left").pack(
                anchor="w", pady=(0, 10))
        ttk.Separator(frame).pack(fill="x", pady=6)
        self.status_var = tk.StringVar(value="可以检查 GitHub 上的最新版本。")
        ttk.Label(frame, textvariable=self.status_var, foreground="#555",
                  wraplength=570, justify="left").pack(anchor="w", pady=(4, 12))
        btns = ttk.Frame(frame)
        btns.pack(side="bottom", fill="x")
        self.check_btn = ttk.Button(btns, text="检查更新",
                                    command=self.check_update)
        self.check_btn.pack(side="left")
        self.install_btn = ttk.Button(
            btns, text="下载并安装", command=self._install_available,
            state="disabled")
        self.install_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="打开仓库",
                   command=self._open_repo).pack(side="left")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")
        self.after(100, self._poll_events)
        if release:
            self._apply_available_release(release)

    def _post_event(self, fn, *args) -> None:
        """后台线程只能投递事件，Tk 控件只由主线程操作。"""
        self._events.put((fn, args))

    def _poll_events(self) -> None:
        try:
            if not self.winfo_exists():
                return
            while True:
                try:
                    fn, args = self._events.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn(*args)
                except Exception:
                    pass
            self.after(100, self._poll_events)
        except Exception:
            pass

    def _open_qq(self, event=None) -> str:
        # 优先走 QQ 的频道 WebView；没装 QQ 或协议不可用时再交给浏览器。
        if qq_channel.open_in_qq():
            return "break"
        try:
            opened = webbrowser.open(qq_channel.QQ_CHANNEL_URL)
        except Exception:
            opened = False
        if not opened:
            messagebox.showinfo(
                "QQ 频道",
                f"未能唤起 QQ，请手动在 QQ 中打开：\n"
                f"{qq_channel.QQ_CHANNEL_URL}",
                parent=self)
        return "break"

    def _show_qq_qr(self) -> None:
        QQChannelDialog(self.app)

    def _open_repo(self, event=None) -> str:
        try:
            opened = webbrowser.open(updater.REPO_URL)
        except Exception:
            opened = False
        if not opened:
            messagebox.showinfo(
                "GitHub 仓库", f"请手动打开：\n{updater.REPO_URL}",
                parent=self)
        return "break"

    def _apply_available_release(self, release: dict) -> bool:
        tag = str(release.get("tag") or "")
        if not tag or not updater.is_newer(tag, updater.APP_VERSION):
            self._release = None
            self.install_btn.configure(text="下载并安装", state="disabled")
            return False
        self._release = release
        self.install_btn.configure(
            text=f"下载并安装 {tag}", state="normal")
        notes = str(release.get("notes") or "").strip().splitlines()
        detail = re.sub(r"^[#*\-\s]+", "",
                        notes[0].strip())[:80] if notes else ""
        self.status_var.set(
            f"发现新版本 {tag}（当前 {updater.APP_VERSION}）。"
            + (f" {detail}" if detail else "")
            + " 可点击“下载并安装”。")
        return True

    def _install_available(self) -> None:
        if self._checking or self._downloading or not self._release:
            return
        tag = str(self._release.get("tag") or "")
        if not messagebox.askyesno(
                "下载更新",
                f"现在下载新版本 {tag}？\n"
                "下载完成后会询问是否关闭程序并覆盖更新；"
                "登录数据 data/ 会保留。",
                parent=self):
            return
        self._start_download(self._release)

    def check_update(self) -> None:
        if self._checking or self._downloading:
            return
        self._checking = True
        self.check_btn.configure(state="disabled")
        self.status_var.set("正在检查 GitHub 最新版本…")

        def worker():
            try:
                release = updater.fetch_latest_release()
                err = ""
            except Exception as e:  # noqa: BLE001
                release, err = None, str(e)
            self._post_event(self._check_done, release, err)

        threading.Thread(target=worker, daemon=True).start()

    def _check_done(self, release, error: str) -> None:
        if not self.winfo_exists():
            return
        self._checking = False
        self.check_btn.configure(state="normal")
        if error:
            self.status_var.set(f"检查更新失败：{error}")
            return
        if not self._apply_available_release(release):
            self.status_var.set(
                f"当前已是最新版本（{updater.APP_VERSION}）。")
            return
        tag = str(release.get("tag") or "")
        notes = str(release.get("notes") or "").strip()
        detail = f"\n\n{notes[:400]}" if notes else ""
        if not messagebox.askyesno(
                "发现新版本",
                f"发现新版本 {tag}（当前 {updater.APP_VERSION}）。"
                f"{detail}\n\n是否现在下载并覆盖更新？",
                parent=self):
            self.status_var.set(
                f"发现新版本 {tag}，可点击“下载并安装 {tag}”。")
            return
        self._start_download(release)

    def _start_download(self, release) -> None:
        self._downloading = True
        self._release = release
        self.check_btn.configure(state="disabled")
        self.install_btn.configure(state="disabled")
        tag = re.sub(r"[^0-9A-Za-z._-]+", "_",
                     str(release.get("tag") or "latest"))
        path = os.path.join(
            tempfile.gettempdir(), f"AutoRename115-update-{tag}.zip")
        self.status_var.set("正在下载更新包…")
        last = {"pct": -1}

        def progress(done: int, total: int) -> None:
            if total > 0:
                pct = int(done * 100 / total)
                if pct == last["pct"]:
                    return
                last["pct"] = pct
                text = f"正在下载更新包… {pct}%（{done // 1024} KB）"
            else:
                text = f"正在下载更新包… {done // 1024} KB"
            self._post_event(self._set_status, text)

        def worker():
            try:
                updater.download_asset(release["asset"], path, progress)
                err = ""
            except Exception as e:  # noqa: BLE001
                path2, err = "", str(e)
            else:
                path2 = path
            self._post_event(self._download_done, path2, err)

        threading.Thread(target=worker, daemon=True).start()

    def _set_status(self, text: str) -> None:
        try:
            self.status_var.set(text)
        except Exception:
            pass

    def _download_done(self, path: str, error: str) -> None:
        if not self.winfo_exists():
            return
        self._downloading = False
        self.check_btn.configure(state="normal")
        if error:
            self.install_btn.configure(state="normal")
            self.status_var.set(f"下载更新失败：{error}")
            return
        tag = str((self._release or {}).get("tag") or "")
        self.status_var.set(f"更新包已下载：{tag}")
        if not updater.can_self_update(self.app.app_dir):
            messagebox.showinfo(
                "更新包已下载",
                "当前是源码运行，或程序目录不可写，不能自动覆盖。\n\n"
                f"更新包：{path}\n"
                f"也可以打开仓库手动下载：\n{updater.RELEASES_URL}",
                parent=self)
            return
        if not messagebox.askyesno(
                "安装更新",
                "将关闭当前程序，用新版本覆盖程序目录，保留 data/，"
                "然后自动重新打开。\n\n是否继续？",
                parent=self):
            self.status_var.set("已取消安装更新。")
            return
        try:
            updater.launch_self_update(path, self.app.app_dir)
        except Exception as e:  # noqa: BLE001
            self.status_var.set(f"启动更新失败：{e}")
            return
        messagebox.showinfo(
            "正在更新",
            "程序即将关闭并覆盖更新，完成后会自动重新打开。\n"
            "如果更新失败，请查看 data/update.log。",
            parent=self)
        self.destroy()
        self.app.after(150, self.app.destroy)


class QQChannelDialog(tk.Toplevel):
    """按需显示 QQ 频道二维码，避免关于窗口一直占着大图。"""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("QQ 频道 · 115资源互助小据点")
        self.resizable(False, False)
        self.transient(app)
        app._center_window(self, 420, 590, parent=app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=qq_channel.QQ_CHANNEL_NAME,
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="center")
        ttk.Label(frame, text=f"频道号：{qq_channel.QQ_CHANNEL_ID}",
                  foreground="#777").pack(anchor="center", pady=(3, 8))
        self.photo = None
        try:
            raw = base64.b64decode(qq_channel.QR_PNG_BASE64)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            image = image.resize((300, 300), Image.Resampling.NEAREST)
            self.photo = ImageTk.PhotoImage(image)
            ttk.Label(frame, image=self.photo, relief="solid",
                      borderwidth=1).pack(pady=4)
        except Exception:
            ttk.Label(frame, text="二维码加载失败，请直接打开频道链接。",
                      foreground="#b3261e", wraplength=360).pack(pady=20)
        url_label = ttk.Label(
            frame, text=qq_channel.QQ_CHANNEL_URL, foreground="#0563c1",
            cursor="hand2", font=("Microsoft YaHei UI", 9, "underline"))
        url_label.pack(anchor="center", pady=(8, 3))
        url_label.bind("<Button-1>", self._open)
        url_label.bind("<Return>", self._open)
        url_label.bind("<space>", self._open)
        ttk.Label(
            frame, text="用 QQ 扫码加入；点击频道链接会在 QQ 中打开，"
                        "未安装 QQ 时改用浏览器。",
            foreground="#777", wraplength=360, justify="center").pack(
                anchor="center", pady=(4, 10))
        btns = ttk.Frame(frame)
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="在 QQ 中打开",
                   command=self._open).pack(side="left")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")

    def _open(self, event=None) -> str:
        # 优先唤起 QQ 自带的频道 WebView；失败再退回默认浏览器。
        if qq_channel.open_in_qq():
            return "break"
        try:
            opened = webbrowser.open(qq_channel.QQ_CHANNEL_URL)
        except Exception:
            opened = False
        if not opened:
            messagebox.showinfo(
                "QQ 频道",
                f"未能唤起 QQ，请手动在 QQ 中打开：\n"
                f"{qq_channel.QQ_CHANNEL_URL}",
                parent=self)
        return "break"


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("设置")
        self.resizable(False, False)
        self.transient(app)
        # 先占位，内容构建完再按实际高度调整（见文件末尾的 _fit_window）
        app._center_window(self, 560, 610, parent=app)
        self.grab_set()
        s = app.settings
        self.vars = {
            "include_imdb_id": tk.BooleanVar(value=bool(s.get("include_imdb_id", True))),
            "rename_subtitles": tk.BooleanVar(value=bool(s.get("rename_subtitles", True))),
            "rename_season_folders": tk.BooleanVar(value=bool(s.get("rename_season_folders", True))),
            "use_bangumi": tk.BooleanVar(value=bool(s.get("use_bangumi", True))),
            "auto_check_updates": tk.BooleanVar(
                value=bool(s.get("auto_check_updates", True))),
            "remember_plans": tk.BooleanVar(
                value=bool(s.get("remember_plans", True))),
        }
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Checkbutton(frame, text="在剧集/电影文件夹名中写入 TMDB/IMDb 标识",
                        variable=self.vars["include_imdb_id"]).pack(anchor="w", pady=3)
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=3)
        ttk.Label(row, text="标识写法").pack(side="left")
        self.style_var = tk.StringVar(value=s.get("imdb_id_style", "jellyfin"))
        ttk.Combobox(row, textvariable=self.style_var, state="readonly", width=12,
                     values=["jellyfin", "emby", "plex", "none"]).pack(side="left", padx=8)
        ttk.Label(row, text="标识优先级").pack(side="left", padx=(12, 0))
        self.provider_var = tk.StringVar(value=s.get("id_provider", "auto"))
        ttk.Combobox(row, textvariable=self.provider_var, state="readonly", width=8,
                     values=["auto", "tmdb", "imdb"]).pack(side="left", padx=6)
        ttk.Label(frame, text="Jellyfin 建议 auto/tmdb（自带 TMDB 提供器）；Emby 选 emby 写法；IMDb 标识需要 OMDb 插件。",
                  foreground="#777", wraplength=520).pack(anchor="w")
        # 日番文件夹格式已移到主界面“命名规则”面板，这里不再重复设置。
        ttk.Label(frame, text="日番文件夹格式、剧集各段来源、是否写规格，"
                              "都在主界面“命名规则”面板里配置。",
                  foreground="#777", wraplength=520).pack(anchor="w", pady=3)
        ttk.Checkbutton(frame, text="同步重命名同名字幕/音轨文件",
                        variable=self.vars["rename_subtitles"]).pack(anchor="w", pady=3)
        ttk.Checkbutton(frame, text="把季目录改名为 Season 01（不新建目录）",
                        variable=self.vars["rename_season_folders"]).pack(anchor="w", pady=3)
        ttk.Checkbutton(frame, text="使用 Bangumi 辅助识别日番/国产动画/美漫",
                        variable=self.vars["use_bangumi"]).pack(anchor="w", pady=3)
        ttk.Checkbutton(
            frame,
            text="启动和运行中自动检查更新（只访问 GitHub，失败不打扰）",
            variable=self.vars["auto_check_updates"]).pack(anchor="w", pady=3)
        ttk.Checkbutton(
            frame,
            text="记住上次分析结果（重启后直接恢复等待列表，自动核对文件）",
            variable=self.vars["remember_plans"]).pack(anchor="w", pady=3)
        nfo_row = ttk.Frame(frame)
        nfo_row.pack(anchor="w", pady=3)
        ttk.Label(nfo_row, text="已有 NFO/图片").pack(side="left")
        self.nfo_mode_var = tk.StringVar(
            value=s.get("nfo_existing", "rename"))
        ttk.Radiobutton(nfo_row, text="跟随媒体改名",
                        variable=self.nfo_mode_var,
                        value="rename").pack(side="left", padx=(8, 0))
        ttk.Radiobutton(nfo_row, text="删除后重存",
                        variable=self.nfo_mode_var,
                        value="replace").pack(side="left", padx=(6, 0))
        login_row = ttk.Frame(frame)
        login_row.pack(anchor="w", pady=3)
        ttk.Label(login_row, text="扫码登录设备").pack(side="left")
        self.login_app_var = tk.StringVar(value=s.get("login_app", "ios"))
        ttk.Combobox(login_row, textvariable=self.login_app_var,
                     state="readonly", width=12,
                     values=["ios", "android", "web"]).pack(
            side="left", padx=8)
        ttk.Button(login_row, text="退出登录",
                   command=self.app.logout).pack(side="left", padx=8)
        ttk.Label(frame, text="建议 ios：不影响安卓手机和网页登录。"
                              "android 可能踢掉手机 App；web 会踢掉网页登录。"
                              "同一设备类型会互踢，反复被踢就换一种设备重扫。",
                  foreground="#777", wraplength=520).pack(anchor="w")
        ttk.Separator(frame).pack(fill="x", pady=10)
        ttk.Label(frame, text="TMDB API Key（可选，填写后多一个数据源）").pack(anchor="w")
        self.tmdb_var = tk.StringVar(value=s.get("tmdb_key", ""))
        ttk.Entry(frame, textvariable=self.tmdb_var, width=60).pack(anchor="w", pady=3)
        # 没填 key 时 TMDB 一栏必然是空的，这里直接说清楚，免得当成搜索出错
        self.tmdb_state_label = ttk.Label(frame, text="", foreground="#b3261e")
        self.tmdb_state_label.pack(anchor="w")
        self._sync_tk_tmdb_state()
        try:
            self.tmdb_var.trace_add(
                "write", lambda *a: self._sync_tk_tmdb_state())
        except Exception:
            pass
        api_link = ttk.Label(
            frame, text="获取 TMDB API Key（点击打开官网）",
            foreground="#0563c1", cursor="hand2",
            font=("Microsoft YaHei UI", 9, "underline"))
        api_link.pack(anchor="w", pady=(0, 3))
        api_link.bind("<Button-1>", self._open_tmdb_api)
        api_link.bind("<Return>", self._open_tmdb_api)
        api_link.bind("<space>", self._open_tmdb_api)
        api_link.configure(takefocus=True)
        ttk.Label(frame,
                  text="豆瓣单集名：使用本机已安装的 Chrome / Edge 读取"
                       "（豆瓣会拦截普通 HTTP 请求，必须走浏览器）。"
                       "浏览器信息只在本机使用，不上传。"
                       "Cookie 仅在浏览器取不到时作为补充，可不填。",
                  foreground="#555", wraplength=520).pack(anchor="w", pady=(8, 0))
        cookie_row = ttk.Frame(frame)
        cookie_row.pack(fill="x", pady=3)
        # 框里预置拼接模板，用户按提示把值填进去即可
        default_cookie = str(s.get("douban_cookie", "") or "")
        if not default_cookie:
            default_cookie = DOUBAN_COOKIE_TEMPLATE
        self.douban_cookie_var = tk.StringVar(value=default_cookie)
        ttk.Entry(cookie_row, textvariable=self.douban_cookie_var,
                  width=44).pack(side="left")
        ttk.Button(cookie_row, text="打开豆瓣…",
                   command=lambda: webbrowser.open(
                       "https://movie.douban.com/")).pack(side="left", padx=6)
        ttk.Button(cookie_row, text="从剪贴板粘贴",
                   command=self._paste_douban_cookie).pack(side="left")
        self.douban_test_btn = ttk.Button(
            cookie_row, text="测试豆瓣连接", command=self._test_douban_cookie)
        self.douban_test_btn.pack(side="left", padx=6)
        # 获取提示：告诉用户去哪里复制、按什么格式拼接
        ttk.Label(frame, text=DOUBAN_COOKIE_HINT,
                  foreground="#777", wraplength=520,
                  justify="left").pack(anchor="w", pady=(2, 0))
        self.douban_test_label = ttk.Label(frame, text="", foreground="#777")
        self.douban_test_label.pack(anchor="w")
        # 命名规则已移到主界面（可折叠区块），这里不再重复放置。
        self.naming_panel = None
        ttk.Separator(frame).pack(fill="x", pady=(10, 8))
        # 按钮区改为正常顺序靠底，不再用 side="bottom" 与内容争抢空间：
        # 以前内容自然高度超过 610px 时，按钮会被压成一条细条。
        btns = ttk.Frame(frame)
        btns.pack(fill="x")
        ttk.Button(btns, text="关于…", command=self.open_about).pack(side="left")
        ttk.Button(btns, text="保存", command=self.save).pack(side="right", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        self._fit_to_content(frame)

    def _fit_to_content(self, frame) -> None:
        """按内容实际需要的高度调整窗口，按钮区不再被挤压。"""
        self.update_idletasks()
        need_h = frame.winfo_reqheight()
        need_w = max(560, frame.winfo_reqwidth())
        self.geometry(f"{need_w}x{need_h}")
        self.minsize(need_w, need_h)
        self.app._center_window(self, need_w, need_h, parent=self.app)
        self.after(30, lambda: self.app._center_window(
            self, need_w, need_h, parent=self.app))

    def open_about(self) -> None:
        AboutDialog(self.app)

    def _sync_tk_tmdb_state(self) -> None:
        """提示 TMDB Key 是否已填：没填时 TMDB 来源必然为空。"""
        lbl = getattr(self, "tmdb_state_label", None)
        if lbl is None:
            return
        has = bool((self.tmdb_var.get() or "").strip())
        if has:
            lbl.configure(text="已填写 Key：保存后可查询 TMDB。",
                          foreground="#176b33")
        else:
            lbl.configure(
                text="未填写 Key：TMDB 来源将一直为空（手动搜索里 TMDB(0) "
                     "就是这个原因）。不填也能正常使用 IMDb/豆瓣/Bangumi。",
                foreground="#b3261e")

    def _open_tmdb_api(self, event=None) -> str:
        url = "https://www.themoviedb.org/settings/api"
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            messagebox.showinfo(
                "TMDB API Key", f"请手动在浏览器打开：\n{url}", parent=self)
        return "break"

    def _paste_douban_cookie(self) -> None:
        """从剪贴板填入豆瓣 Cookie，并做基本校验与提示。"""
        try:
            text = self.clipboard_get()
        except Exception:
            text = ""
        text = (text or "").strip().replace("\n", " ")
        if not text:
            messagebox.showinfo(
                APP_TITLE,
                "剪贴板是空的。\n请先在浏览器里复制 "
                "movie.douban.com 请求头的 Cookie。", parent=self)
            return
        if not any(k in text for k in ("bid=", "dbcl2=", "ll=")):
            if not messagebox.askyesno(
                    APP_TITLE,
                    "剪贴板内容看起来不像豆瓣 Cookie"
                    "（没有 bid / dbcl2 / ll）。\n仍然填入吗？", parent=self):
                return
        self.douban_cookie_var.set(text)
        self.app._log(f"已填入豆瓣 Cookie（{len(text)} 字符），保存后生效。")

    def _test_douban_cookie(self) -> None:
        """用当前输入框里的 Cookie 实测一次豆瓣分集页，结果直接显示。"""
        cookie = self.douban_cookie_var.get().strip()
        if not cookie:
            self.douban_test_label.configure(
                text="没有填 Cookie：软件不会请求豆瓣，副标题只能用原文件名。",
                foreground="#b3261e")
            return
        self.douban_test_label.configure(text="测试中…", foreground="#555")
        self.douban_test_btn.configure(state="disabled")
        dialog = self

        def worker():
            from .metadata import MetadataClient
            m = MetadataClient("", use_bangumi=False)
            m.douban_cookie = cookie
            m.delays["douban"] = 0.0
            try:
                # 用一份稳定的剧集条目做探针（灵笼 第一季 第1集）
                page = m._douban_episode_page("27121260", 1, 1)
            except Exception as e:      # noqa: BLE001
                page = {"ok": False, "reason": str(e)}
            dialog.app.post("douban_test", (dialog, page))

        threading.Thread(target=worker, daemon=True).start()

    def _show_douban_test(self, page: dict) -> None:
        self.douban_test_btn.configure(state="normal")
        if page.get("ok"):
            title = page.get("title") or "（该集没有集名）"
            self.douban_test_label.configure(
                text=f"豆瓣可读：第1集 = {title}", foreground="#176b33")
        else:
            self.douban_test_label.configure(
                text="豆瓣不可读：" + str(page.get("reason") or "未知原因"),
                foreground="#b3261e")

    def save(self) -> None:
        self.app.apply_settings({
            "include_imdb_id": bool(self.vars["include_imdb_id"].get()),
            "rename_subtitles": bool(self.vars["rename_subtitles"].get()),
            "rename_season_folders": bool(self.vars["rename_season_folders"].get()),
            "nfo_existing": self.nfo_mode_var.get(),
            "use_bangumi": bool(self.vars["use_bangumi"].get()),
            "auto_check_updates": bool(
                self.vars["auto_check_updates"].get()),
            "remember_plans": bool(self.vars["remember_plans"].get()),
            "imdb_id_style": self.style_var.get(),
            "id_provider": self.provider_var.get(),
            "tmdb_key": self.tmdb_var.get().strip(),
            "douban_cookie": clean_douban_cookie(
                self.douban_cookie_var.get()),
            "login_app": self.login_app_var.get(),
            **(self.naming_panel.values() if self.naming_panel else {}),
        })
        self.destroy()


class ClearInfoDialog(tk.Toplevel):
    """可选：清空所选任务或当前文件夹里匹配的 NFO/图片。"""

    def __init__(self, app: App, has_plan: bool, on_confirm):
        super().__init__(app)
        self.app = app
        self.on_confirm = on_confirm
        self.title("清空 NFO/图片")
        self.resizable(False, False)
        self.transient(app)
        app._center_window(self, 580, 300, parent=app)
        self.grab_set()
        self.scope_var = tk.StringVar(
            value="selected" if has_plan else "current")
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="清空范围",
                  font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Radiobutton(
            frame, text="所选任务（只处理与它匹配的 NFO/图片）",
            variable=self.scope_var, value="selected",
            state="normal" if has_plan else "disabled").pack(
                anchor="w", pady=(6, 2))
        ttk.Radiobutton(
            frame, text="当前文件夹（按里面的视频名匹配）",
            variable=self.scope_var, value="current").pack(anchor="w")
        ttk.Label(
            frame,
            text="只把匹配到的 .nfo/图片移到 115 回收站，不永久删除。\n"
                 "电影库根目录有多部电影时，所选任务模式不会误删其他电影；\n"
                 "当前文件夹模式也只会匹配有同名视频的 NFO/图片。",
            foreground="#777", justify="left", wraplength=540).pack(
                anchor="w", pady=(10, 0))
        btns = ttk.Frame(frame)
        btns.pack(side="bottom", fill="x", pady=(16, 0))
        ttk.Button(btns, text="移入回收站", command=self._ok).pack(
            side="right", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")

    def _ok(self) -> None:
        scope = self.scope_var.get()
        self.destroy()
        self.on_confirm(scope)


class DirRenameDialog(tk.Toplevel):
    """左侧列表里单个文件/文件夹改名，立即在 115 上生效。"""

    def __init__(self, app: App, item: P115Item, on_submit):
        super().__init__(app)
        self.app = app
        self.item = item
        self.on_submit = on_submit
        kind = "文件夹" if item.is_dir else "文件"
        self.title(f"{kind}重命名（立即生效）")
        self.transient(app)
        self.grab_set()
        self.minsize(560, 240)
        App._center_window(self, 720, 300, parent=app)
        self.bind("<Escape>", lambda e: self.destroy())

        ttk.Label(
            self,
            text=f"会立即修改 115 网盘上的{kind}名；只改这一项，"
                 "不删除、不移动。",
            foreground="#a15c00", wraplength=660,
            justify="left").pack(anchor="w", padx=12, pady=(10, 4))
        cur = ttk.Frame(self, padding=(12, 2))
        cur.pack(fill="x")
        ttk.Label(cur, text="当前名称：", foreground="#555").pack(anchor="w")
        ttk.Label(cur, text=item.name, wraplength=660, justify="left",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")

        edit = ttk.Frame(self, padding=(12, 8))
        edit.pack(fill="x")
        ttk.Label(edit, text="新名称").pack(side="left")
        self.name_var = tk.StringVar(value=item.name)
        self.entry = ttk.Entry(edit, textvariable=self.name_var)
        self.entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.entry.bind("<Return>", lambda e: self._submit())

        btns = ttk.Frame(self, padding=(12, 4, 12, 10))
        btns.pack(fill="x")
        ttk.Label(btns, text="文件的扩展名不能修改。",
                  foreground="#777").pack(side="left")
        ttk.Button(btns, text="立即改名",
                   command=self._submit).pack(side="right")
        ttk.Button(btns, text="取消",
                   command=self.destroy).pack(side="right", padx=6)
        self.after(80, self._focus_entry)

    def _focus_entry(self) -> None:
        self.entry.focus_set()
        # 全选旧名：直接输入新名不会残留旧扩展名；没写扩展名时自动补回。
        self.entry.select_range(0, "end")
        self.entry.icursor("end")

    def _submit(self) -> None:
        new = sanitize_name(self.name_var.get().strip(), 255)
        if not new or new in (".", ".."):
            messagebox.showerror("重命名", "名称不能为空。", parent=self)
            return
        if not self.item.is_dir:
            old_ext = os.path.splitext(self.item.name)[1]
            new_ext = os.path.splitext(new)[1]
            if old_ext and not new_ext:
                new += old_ext
                self.name_var.set(new)
            elif old_ext and new_ext.lower() != old_ext.lower():
                messagebox.showerror(
                    "重命名",
                    "115 不允许修改扩展名。\n"
                    f"原扩展名：{old_ext}\n新扩展名：{new_ext}",
                    parent=self)
                return
        if new == self.item.name:
            messagebox.showinfo("重命名", "名称没有变化。", parent=self)
            return
        siblings = [x for x in self.app.dir_items.values()
                    if x.fid != self.item.fid and
                    x.parent_id == self.item.parent_id]
        if any(x.name.casefold() == new.casefold() for x in siblings):
            messagebox.showerror("重命名", "同一目录下已经有同名项目。",
                                 parent=self)
            return
        kind = "文件夹" if self.item.is_dir else "文件"
        if not messagebox.askyesno(
                "重命名",
                f"将在 115 上立即修改这个{kind}的名字：\n\n"
                f"{self.item.name}\n→ {new}\n\n"
                "只改这一项，不删除、不移动。继续？",
                parent=self):
            return
        self.destroy()
        self.on_submit(self.item, new)


class TempRenameDialog(tk.Toplevel):
    """选中一个计划里的项目，立即在 115 上改名（只改这一项）。"""

    def __init__(self, app: App, plan: PlanItem, on_submit):
        super().__init__(app)
        self.app = app
        self.plan = plan
        self.on_submit = on_submit
        self.ops = list(plan.ops)
        self.by_iid = {}
        self.title("临时改名（立即生效）")
        self.geometry("820x450")
        self.minsize(720, 380)
        self.transient(app)
        App._center_window(self, 820, 450, parent=app)
        self.grab_set()

        ttk.Label(
            self,
            text="这里会立即修改 115 网盘上的名字，只改选中的这一项；"
                 "不会删除、移动，也不会写成命名规则。",
            foreground="#a15c00", wraplength=780,
            justify="left").pack(anchor="w", padx=12, pady=(10, 4))

        frame = ttk.Frame(self, padding=(12, 4))
        frame.pack(fill="both", expand=True)
        cols = ("role", "old", "new")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 selectmode="browse")
        for key, text, width in (("role", "类型", 100),
                                 ("old", "当前名称", 300),
                                 ("new", "计划中的新名称", 380)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")
        vs = ttk.Scrollbar(frame, orient="vertical",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._pick)
        for i, op in enumerate(self.ops):
            iid = f"o{i}"
            self.by_iid[iid] = op
            self.tree.insert("", "end", iid=iid, values=(
                ROLE_LABELS.get(op.role, op.role), op.old_name,
                op.new_name))

        edit = ttk.Frame(self, padding=(12, 4))
        edit.pack(fill="x")
        ttk.Label(edit, text="新名称").pack(side="left")
        self.name_var = tk.StringVar()
        self.entry = ttk.Entry(edit, textvariable=self.name_var)
        self.entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.entry.bind("<Return>", lambda e: self._submit())

        btns = ttk.Frame(self, padding=(12, 4, 12, 10))
        btns.pack(fill="x")
        ttk.Label(btns, text="文件会保留原扩展名。",
                  foreground="#777").pack(side="left")
        ttk.Button(btns, text="立即改名",
                   command=self._submit).pack(side="right")
        ttk.Button(btns, text="取消",
                   command=self.destroy).pack(side="right", padx=6)

        if self.ops:
            self.tree.selection_set("o0")
            self.tree.focus("o0")
            self._pick()

    def _pick(self, event=None) -> None:
        sel = self.tree.selection()
        if sel:
            op = self.by_iid.get(sel[0])
            if op:
                self.name_var.set(op.new_name)
                self.entry.focus_set()

    def _submit(self) -> None:
        sel = self.tree.selection()
        op = self.by_iid.get(sel[0]) if sel else None
        if not op:
            messagebox.showinfo("临时改名", "请先选中一项。", parent=self)
            return
        new = sanitize_name(self.name_var.get().strip(), 255)
        if not new or new in (".", ".."):
            messagebox.showerror("临时改名", "名称不能为空。", parent=self)
            return
        if not op.is_dir:
            old_ext = os.path.splitext(op.old_name)[1]
            new_ext = os.path.splitext(new)[1]
            if old_ext and not new_ext:
                new += old_ext
            elif old_ext and new_ext.lower() != old_ext.lower():
                messagebox.showerror(
                    "临时改名",
                    "115 不允许修改扩展名。\n"
                    f"原扩展名：{old_ext}\n新扩展名：{new_ext}",
                    parent=self)
                return
        if any(o.fid != op.fid and o.parent_id == op.parent_id and
               o.new_name.casefold() == new.casefold()
               for o in self.plan.ops):
            messagebox.showerror("临时改名", "同一目录下已经有同名目标。",
                                 parent=self)
            return
        if not messagebox.askyesno(
                "临时改名",
                f"将在 115 上立即改名：\n\n{op.old_name}\n→ {new}\n\n"
                "只改这一项，不删除、不移动。继续？",
                parent=self):
            return
        self.destroy()
        self.on_submit(self.plan, op, new)


def main(app_dir: str, demo: bool = False) -> None:
    app = App(app_dir, demo=demo)
    app.mainloop()
