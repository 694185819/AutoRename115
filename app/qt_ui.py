# -*- coding: utf-8 -*-
"""Qt 界面（PySide6）：主窗口骨架 —— 任务表、参数栏、状态栏。

迁移策略：与现有 Tk 界面**并存**，用 `--ui=qt` 切换，逐屏替换。
业务逻辑（planner / metadata / scoring / decider / qc / naming_rule）
完全复用，这里只负责视图与交互。

为什么换 Qt：Tk 8.6 在本界面规模下，一次窗口尺寸变化要 ~100~300ms
（cProfile 实测 98.7% 时间在 Tk 原生 update() 内）；Qt 的布局与绘制
在同等规模下是毫秒级。
"""
from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtCore import (QAbstractTableModel, QObject, Qt, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                               QCheckBox, QComboBox, QDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QRadioButton, QSplitter,
                               QTableView, QTableWidget, QTableWidgetItem,
                               QTextEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

# 与 Tk 版共用同一套文案
STATUS_LABELS = {
    "auto": "自动",
    "review": "需确认",
    "skip": "跳过",
    "error": "错误",
}
SHORT_CATEGORY = {
    "auto": "自动", "jp_anime": "日番", "cn_anime": "国产",
    "us_anime": "美漫", "west_anime": "欧美",
    "tv": "电视剧", "movie": "电影",
}
SOURCE_NAMES = {
    "douban": "豆瓣",
    "bangumi": "Bangumi",
    "imdb": "IMDb",
    "tmdb": "TMDB",
}
COLUMNS = ("选", "类型", "分类", "当前名称", "新名称", "季", "集", "置信度", "状态")


def fmt_episodes(plan) -> str:
    """集号摘要，与 Tk 版保持一致。"""
    eps = getattr(plan, "episodes", None) or []
    if not eps:
        return ""
    shown = [e for e in eps if isinstance(e, int)]
    if not shown:
        return ""
    if len(shown) == 1:
        return f"E{shown[0]:02d}"
    return f"E{min(shown):02d}-E{max(shown):02d}"


def _fmt_size(size) -> str:
    """文件大小显示（与 Tk 版 fmt_size 一致）。"""
    try:
        n = float(size)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _call(app, name: str, *args, **kwargs):
    """安全调用业务层方法：不存在或报错时只记日志，不让界面崩。"""
    fn = getattr(app, name, None)
    if not callable(fn):
        return None
    try:
        return fn(*args, **kwargs)
    except Exception as e:      # noqa: BLE001
        log = getattr(app, "log_threadsafe", None)
        if log:
            log(f"{name} 执行失败：{e}")
        return None


class NamingRulePanel(QWidget):
    """命名规则面板：中文主名称 . 来源名 . SxxExx . 副标题 [规格]。

    与 Tk 版共用同一套常量与拼装函数（app.naming_rule），
    这里只负责界面与实时预览。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from app.naming_panel import (JP_FOLDER_OPTIONS, MOVIE_LABELS,
                                      MOVIE_STYLES, NAME_SOURCE_LABELS,
                                      SUBTITLE_LABELS)
        from app.models import PlanItem          # noqa: F401  确保导入路径正确

        self._src_labels = NAME_SOURCE_LABELS
        self._sub_labels = SUBTITLE_LABELS
        self._jp_labels = JP_FOLDER_OPTIONS
        self._movie_labels = MOVIE_LABELS
        self._movie_styles = MOVIE_STYLES

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 第一行：固定项 + 来源名 + 副标题
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row1.addWidget(self._fixed_label("中文主名称 ."))
        self.combo_seg = QComboBox()
        self.combo_seg.addItems(list(self._src_labels.values()))
        self.combo_seg.setMinimumWidth(140)
        row1.addWidget(self.combo_seg)
        row1.addWidget(self._fixed_label(". S01E01 ."))
        self.combo_sub = QComboBox()
        self.combo_sub.addItems(list(self._sub_labels.values()))
        self.combo_sub.setMinimumWidth(170)
        row1.addWidget(self.combo_sub)
        row1.addWidget(QLabel("规格"))
        self.radio_spec_yes = QRadioButton("是")
        self.radio_spec_no = QRadioButton("否")
        self.radio_spec_yes.setChecked(True)
        row1.addWidget(self.radio_spec_yes)
        row1.addWidget(self.radio_spec_no)
        row1.addStretch(1)
        lay.addLayout(row1)

        # 第二行：日番格式 + 电影命名
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        row2.addWidget(QLabel("日番"))
        self.combo_jp = QComboBox()
        self.combo_jp.addItems(list(self._jp_labels.values()))
        self.combo_jp.setMinimumWidth(260)
        row2.addWidget(self.combo_jp)
        row2.addSpacing(10)
        row2.addWidget(QLabel("电影"))
        self.combo_movie = QComboBox()
        self.combo_movie.addItems([self._movie_labels[k]
                                   for k in self._movie_styles])
        self.combo_movie.setMinimumWidth(180)
        row2.addWidget(self.combo_movie)
        row2.addStretch(1)
        lay.addLayout(row2)

        # 预览
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color:#176b33;")
        lay.addWidget(self.preview)

        for w in (self.combo_seg, self.combo_sub, self.combo_jp,
                  self.combo_movie):
            w.currentIndexChanged.connect(self.refresh_preview)
        self.radio_spec_yes.toggled.connect(self.refresh_preview)
        self.refresh_preview()

    @staticmethod
    def _fixed_label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            "color:#8a8a8a; background:#eeeeee; padding:2px 5px;")
        return lab

    # ---------------- 取值
    def _source_key(self) -> str:
        label = self.combo_seg.currentText()
        for key, val in self._src_labels.items():
            if val == label:
                return key
        return "imdb"

    def _subtitle_key(self) -> str:
        label = self.combo_sub.currentText()
        for key, val in self._sub_labels.items():
            if val == label:
                return key
        return "auto"

    def _jp_key(self) -> str:
        label = self.combo_jp.currentText()
        for key, val in self._jp_labels.items():
            if val == label:
                return key
        return "bdremux"

    def values(self) -> dict:
        """与 Tk 版 values() 同名的键，便于统一写回设置。"""
        return {
            "name_segment_source": self._source_key(),
            "subtitle_source": self._subtitle_key(),
            "include_specs": bool(self.radio_spec_yes.isChecked()),
            "jp_folder_style": self._jp_key(),
        }

    def set_values(self, opts) -> None:
        """按 NamingOptions 回填，保持一致。"""
        from app.naming_panel import (JP_FOLDER_OPTIONS, NAME_SOURCE_LABELS,
                                      SUBTITLE_LABELS)
        seg = getattr(opts, "name_segment_source", "imdb")
        sub = getattr(opts, "subtitle_source", "auto")
        jp = getattr(opts, "jp_folder_style", "bdremux")
        if seg in NAME_SOURCE_LABELS:
            self.combo_seg.setCurrentText(NAME_SOURCE_LABELS[seg])
        if sub in SUBTITLE_LABELS:
            self.combo_sub.setCurrentText(SUBTITLE_LABELS[sub])
        if jp in JP_FOLDER_OPTIONS:
            self.combo_jp.setCurrentText(JP_FOLDER_OPTIONS[jp])
        self.radio_spec_yes.setChecked(bool(getattr(opts, "include_specs", True)))
        self.refresh_preview()

    # ---------------- 预览
    def refresh_preview(self) -> None:
        from app.naming_panel import EXAMPLE_SEGMENTS
        from app.naming_rule import build_episode_filename

        seg = EXAMPLE_SEGMENTS.get(self._source_key(), "")
        sample = build_episode_filename(
            "灵笼", 1, 1, ext=".mp4", name_segment=seg,
            subtitle="灯塔和光影会",
            specs="1080p WEB-DL" if self.radio_spec_yes.isChecked() else "")
        if self._jp_key() == "bdremux":
            jp = ("[BD-REMUX]86 -不存在的战区 86―エイティシックス― "
                  "(2021) [imdbid-tt13718450]")
        else:
            jp = "86 -不存在的战区 (2021) [imdbid-tt13718450]"
        movie = "朝花夕拾 (2018) [imdbid-tt9691596]"
        self.preview.setText(
            "灰色为固定项（中文主名称取自任务标题，SxxExx 按文件推断）\n"
            f"剧集：{sample}\n日番文件夹：{jp}\n"
            f"电影：{movie}（目前只有这一种写法）")


class SettingsDialog(QDialog):
    """设置：命名相关、ID 与更新、豆瓣连接、TMDB Key。

    与 Tk 版共用 settings.json 的键名，两边可互通。
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("设置")
        self.setMinimumWidth(680)
        s = getattr(app, "settings", {}) or {}

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # ---- 命名与格式
        box1 = QGroupBox("命名与格式")
        f1 = QFormLayout(box1)
        self.combo_id_style = QComboBox()
        self.combo_id_style.addItems(["jellyfin", "emby", "plex", "none"])
        self.combo_id_style.setCurrentText(
            str(s.get("imdb_id_style", "jellyfin")))
        f1.addRow("ID 写法", self.combo_id_style)

        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["auto", "imdb", "tmdb"])
        self.combo_provider.setCurrentText(str(s.get("id_provider", "auto")))
        f1.addRow("ID 来源", self.combo_provider)

        self.chk_subtitles = QCheckBox("同步重命名同名字幕/音轨")
        self.chk_subtitles.setChecked(bool(s.get("rename_subtitles", True)))
        f1.addRow("", self.chk_subtitles)
        self.chk_season_dir = QCheckBox("把季目录改名为 Season 01")
        self.chk_season_dir.setChecked(bool(s.get("rename_season_folders", True)))
        f1.addRow("", self.chk_season_dir)
        self.chk_bangumi = QCheckBox("使用 Bangumi 作为中文来源")
        self.chk_bangumi.setChecked(bool(s.get("use_bangumi", True)))
        f1.addRow("", self.chk_bangumi)
        lay.addWidget(box1)

        # ---- 豆瓣
        box2 = QGroupBox("豆瓣（单集名走本机浏览器读取）")
        f2 = QVBoxLayout(box2)
        note = QLabel("豆瓣会拦截普通 HTTP 请求，程序会用本机 Chrome/Edge "
                      "读取分集页。Cookie 仅作补充，可不填。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#777;")
        f2.addWidget(note)
        row = QHBoxLayout()
        self.edit_cookie = QLineEdit(str(s.get("douban_cookie", "") or ""))
        self.edit_cookie.setEchoMode(QLineEdit.Password)
        row.addWidget(self.edit_cookie, 1)
        btn_paste = QPushButton("从剪贴板粘贴")
        btn_open = QPushButton("打开豆瓣…")
        btn_test = QPushButton("测试连接")
        row.addWidget(btn_paste)
        row.addWidget(btn_open)
        row.addWidget(btn_test)
        f2.addLayout(row)
        self.lbl_douban = QLabel("")
        self.lbl_douban.setWordWrap(True)
        f2.addWidget(self.lbl_douban)
        btn_paste.clicked.connect(self._paste_cookie)
        btn_open.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://movie.douban.com/")))
        btn_test.clicked.connect(self._test_douban)
        lay.addWidget(box2)

        # ---- 豆瓣登录（读取 IMDb/TMDB 关联）
        box2b = QGroupBox("豆瓣登录（读取 IMDb/TMDB 关联 ID）")
        f2b = QVBoxLayout(box2b)
        tip2 = QLabel("登录后，条目页会显示 IMDb / TMDB 编号，程序可直接用编号"
                      "定位影片，比按标题搜索准确得多。\n"
                      "登录在独立窗口里进行，登录态只保存在本机程序目录。")
        tip2.setWordWrap(True)
        tip2.setStyleSheet("color:#777;")
        f2b.addWidget(tip2)
        row2 = QHBoxLayout()
        self.btn_douban_login = QPushButton("打开登录窗口…")
        self.btn_douban_check = QPushButton("检查登录状态")
        row2.addWidget(self.btn_douban_login)
        row2.addWidget(self.btn_douban_check)
        row2.addStretch(1)
        f2b.addLayout(row2)
        self.lbl_douban_login = QLabel("未检测")
        self.lbl_douban_login.setWordWrap(True)
        f2b.addWidget(self.lbl_douban_login)
        self.btn_douban_login.clicked.connect(self._open_douban_login)
        self.btn_douban_check.clicked.connect(self._check_douban_login)
        lay.addWidget(box2b)

        # ---- TMDB
        box3 = QGroupBox("TMDB（可选）")
        f3 = QHBoxLayout(box3)
        self.edit_tmdb = QLineEdit(str(s.get("tmdb_key", "") or ""))
        f3.addWidget(self.edit_tmdb, 1)
        btn_tmdb = QPushButton("获取 API Key…")
        btn_tmdb.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://www.themoviedb.org/settings/api")))
        f3.addWidget(btn_tmdb)
        lay.addWidget(box3)

        # ---- 其它
        box4 = QGroupBox("其它")
        f4 = QVBoxLayout(box4)
        self.chk_auto_update = QCheckBox("自动检查更新")
        self.chk_auto_update.setChecked(bool(s.get("auto_check_updates", True)))
        f4.addWidget(self.chk_auto_update)
        self.chk_remember = QCheckBox("记住任务列表（下次启动恢复）")
        self.chk_remember.setChecked(bool(s.get("remember_plans", True)))
        f4.addWidget(self.chk_remember)
        lay.addWidget(box4)

        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_ok = QPushButton("保存")
        btn_cancel = QPushButton("取消")
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)
        btn_ok.clicked.connect(self.save)
        btn_cancel.clicked.connect(self.reject)

    def _sig_emit(self, fn) -> None:
        """从后台线程回到界面线程执行。"""
        if getattr(self, "_sig", None) is None:
            self._sig = _UiSignal()
            self._sig.fn.connect(
                lambda f: f() if callable(f) else None)
        self._sig.fn.emit(fn)

    # ---------------- 动作
    def _paste_cookie(self) -> None:
        text = (QApplication.clipboard().text() or "").strip()
        if not text:
            QMessageBox.information(self, "豆瓣 Cookie",
                                    "剪贴板是空的。")
            return
        if not any(k in text for k in ("bid=", "dbcl2=", "ll=")):
            ret = QMessageBox.question(
                self, "豆瓣 Cookie",
                "剪贴板内容看起来不像豆瓣 Cookie（没有 bid/dbcl2/ll）。\n"
                "仍然填入吗？")
            if ret != QMessageBox.Yes:
                return
        self.edit_cookie.setText(text.replace("\n", " "))
        self.lbl_douban.setText(f"已填入 {len(text)} 字符，保存后生效。")

    def _test_douban(self) -> None:
        """用当前 Cookie 实测一次豆瓣分集页。"""
        cookie = self.edit_cookie.text().strip()
        if not cookie:
            self.lbl_douban.setText(
                "没有填 Cookie：程序仍会尝试用本机浏览器读取豆瓣。")
        self.lbl_douban.setText("测试中…")
        btn = self.sender()

        def worker():
            from app.metadata import MetadataClient
            m = MetadataClient("", use_bangumi=False)
            m.douban_cookie = cookie
            m.delays["douban"] = 0.0
            try:
                page = m._douban_episode_page("27121260", 1, 1)
            except Exception as e:      # noqa: BLE001
                page = {"ok": False, "reason": str(e)}
            QTimer.singleShot(0, lambda: self._show_test(page))

        threading.Thread(target=worker, daemon=True).start()

    def _show_test(self, page: dict) -> None:
        if page.get("ok"):
            self.lbl_douban.setText(
                f"豆瓣可读：第1集 = {page.get('title') or '（无集名）'}")
            self.lbl_douban.setStyleSheet("color:#176b33;")
        else:
            self.lbl_douban.setText(
                f"豆瓣不可读：{page.get('reason') or '未知原因'}")
            self.lbl_douban.setStyleSheet("color:#b3261e;")

    def _open_douban_login(self) -> None:
        """开一个可见浏览器窗口让用户登录豆瓣。"""
        self.lbl_douban_login.setText("正在打开登录窗口…")
        self.lbl_douban_login.setStyleSheet("color:#555;")

        def worker():
            from app.douban_browser import open_login_window
            try:
                browser = open_login_window(
                    getattr(self.app, "app_dir", "."), log=lambda s: None)
            except Exception as e:      # noqa: BLE001
                self._sig_emit(lambda: self.lbl_douban_login.setText(
                    f"打开失败：{e}"))
                return
            if browser is None:
                self._sig_emit(lambda: self.lbl_douban_login.setText(
                    "打开失败：找不到 Chrome 或 Edge。"))
                return
            self._sig_emit(lambda: self.lbl_douban_login.setText(
                "登录窗口已打开：请在其中登录豆瓣，完成后点“检查登录状态”。"))

        threading.Thread(target=worker, daemon=True).start()

    def _check_douban_login(self) -> None:
        """检查豆瓣登录态，并试读一个已知条目的关联 ID。"""
        self.lbl_douban_login.setText("检查中…")
        self.lbl_douban_login.setStyleSheet("color:#555;")

        def worker():
            import os

            from app.douban_browser import (DoubanBrowser, is_logged_in,
                                            related_ids_from_douban)
            profile = os.path.join(getattr(self.app, "app_dir", "."),
                                   "data", "browser_profile")
            b = DoubanBrowser(user_dir=profile, headless=True)
            ok = False
            ids = {}
            try:
                if not b.start():
                    self._sig_emit(lambda: self.lbl_douban_login.setText(
                        "检查失败：无法启动浏览器。"))
                    return
                ok = is_logged_in(b)
                if ok:
                    ids = related_ids_from_douban(b, "27121260")
            finally:
                b.stop()
            if ok:
                detail = (f"，示例读到 IMDb {ids['imdb_id']}"
                          if ids.get("imdb_id") else "")
                msg, color = f"已登录豆瓣{detail}。", "#176b33"
            else:
                msg = "未登录。请在登录窗口里登录一次豆瓣。"
                color = "#b3261e"

            def show():
                self.lbl_douban_login.setText(msg)
                self.lbl_douban_login.setStyleSheet(f"color:{color};")
            self._sig_emit(show)

        threading.Thread(target=worker, daemon=True).start()

    def save(self) -> None:
        values = {
            "imdb_id_style": self.combo_id_style.currentText(),
            "id_provider": self.combo_provider.currentText(),
            "rename_subtitles": self.chk_subtitles.isChecked(),
            "rename_season_folders": self.chk_season_dir.isChecked(),
            "use_bangumi": self.chk_bangumi.isChecked(),
            "douban_cookie": self.edit_cookie.text().strip(),
            "tmdb_key": self.edit_tmdb.text().strip(),
            "auto_check_updates": self.chk_auto_update.isChecked(),
            "remember_plans": self.chk_remember.isChecked(),
        }
        app = self.app
        try:
            app.settings.update(values)
            fn = getattr(app, "_save_settings", None)
            if callable(fn):
                fn()
            init = getattr(app, "_init_meta", None)
            if callable(init):
                init()
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "设置", f"保存失败：{e}")
            return
        self.accept()


class ManualSearchDialog(QDialog):
    """手动搜索：按关键词在豆瓣/Bangumi/IMDb/TMDB 里找正确条目并应用。"""

    def __init__(self, parent, app, plan):
        super().__init__(parent)
        self.app = app
        self.plan = plan
        self.setWindowTitle("手动搜索正确条目")
        self.resize(820, 520)
        self._candidates: list = []

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("关键词"))
        self.edit_query = QLineEdit(self._initial_keywords())
        row.addWidget(self.edit_query, 1)
        self.btn_search = QPushButton("搜索")
        row.addWidget(self.btn_search)
        lay.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("来源", "标题", "原名", "年份", "ID"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        self.lbl_hint = QLabel("双击结果或点“应用所选”即可套用到当前任务。")
        self.lbl_hint.setStyleSheet("color:#777;")
        lay.addWidget(self.lbl_hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_apply = QPushButton("应用所选")
        self.btn_apply.setEnabled(False)
        btn_cancel = QPushButton("取消")
        btns.addWidget(self.btn_apply)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)

        self.btn_search.clicked.connect(self.start_search)
        self.btn_apply.clicked.connect(self.apply_selected)
        self.table.itemSelectionChanged.connect(
            lambda: self.btn_apply.setEnabled(
                self.table.currentRow() >= 0))
        self.table.itemDoubleClicked.connect(
            lambda *_: self.apply_selected())

    def _initial_keywords(self) -> str:
        p = self.plan
        title = (getattr(p, "title", "") or "").strip()
        year = getattr(p, "year", None)
        return f"{title} {year}" if year else title

    # ---------------- 搜索
    def start_search(self) -> None:
        query = self.edit_query.text().strip()
        if not query:
            return
        self.btn_search.setEnabled(False)
        self.lbl_hint.setText("搜索中…")
        app = self.app
        plan = self.plan
        media = getattr(plan, "media_type", "series")
        season = getattr(plan, "season", None)
        if season is None:
            seasons = getattr(plan, "seasons", None) or []
            season = seasons[0] if len(seasons) == 1 else None
        year = getattr(plan, "year", None)

        def worker():
            from app.search_service import search_all
            meta = getattr(app, "meta", None)
            if meta is None:
                self._sig_emit(lambda: self._show([], "未连接资料来源"))
                return
            try:
                found, notes = search_all(
                    meta, query, keywords=[],
                    media_type=media, season=season, year=year,
                    use_bangumi=bool(getattr(meta, "use_bangumi", True)),
                    tmdb_key=str(getattr(meta, "tmdb_key", "") or ""),
                    status=lambda s: self._sig_emit(
                        lambda: self.lbl_hint.setText(s)))
                self._sig_emit(lambda: self._show(
                    found, "", "；".join(notes)))
            except Exception as e:      # noqa: BLE001
                self._sig_emit(lambda: self._show([], f"搜索失败：{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _sig_emit(self, fn) -> None:
        """从后台线程回到界面线程。"""
        if getattr(self, "_sig", None) is None:
            self._sig = _UiSignal()
            self._sig.fn.connect(
                lambda f: f() if callable(f) else None)
        self._sig.fn.emit(fn)

    def _show(self, cands: list, err: str, notes: str = "") -> None:
        self._candidates = cands
        self.btn_search.setEnabled(True)
        self.table.setRowCount(len(cands))
        for i, c in enumerate(cands):
            vals = (SOURCE_NAMES.get(getattr(c, "source", ""),
                                     getattr(c, "source", "")),
                    getattr(c, "title", ""),
                    getattr(c, "original_title", ""),
                    str(getattr(c, "year", "") or ""),
                    str(getattr(c, "sid", "") or ""))
            for col, v in enumerate(vals):
                self.table.setItem(i, col, QTableWidgetItem(str(v)))
        if cands:
            self.lbl_hint.setText(
                f"共 {len(cands)} 条（已按相关度排序）"
                + (f"｜{notes}" if notes else ""))
        else:
            self.lbl_hint.setText(err or "没有找到结果，换个关键词试试。")

    # ---------------- 应用
    def apply_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._candidates):
            return
        cand = self._candidates[row]
        fn = getattr(self.app, "_apply_manual_candidate", None)
        if not callable(fn):
            self.lbl_hint.setText("当前版本不支持手动应用，请用默认界面。")
            return
        ids = {"imdb_id": "", "tmdb_id": "",
               "country": getattr(cand, "country", "") or ""}
        try:
            fn(self.plan, cand, ids)
            self.lbl_hint.setText(f"已应用：{getattr(cand, 'title', '')}")
            self.accept()
        except Exception as e:      # noqa: BLE001
            self.lbl_hint.setText(f"应用失败：{e}")


class EpisodeMappingDialog(QDialog):
    """季集映射：查看/调整每个视频文件对应的季与集。"""

    def __init__(self, parent, app, plan):
        super().__init__(parent)
        self.app = app
        self.plan = plan
        self.setWindowTitle("季集映射")
        self.resize(720, 480)

        lay = QVBoxLayout(self)
        hint = QLabel("修改后点“应用”只重建预览，不会直接改网盘。")
        hint.setStyleSheet("color:#777;")
        lay.addWidget(hint)

        videos = [e for e in ((getattr(plan, "context", {}) or {})
                              .get("entries") or []) if getattr(e, "is_video",
                                                                False)]
        self.table = QTableWidget(len(videos), 4)
        self.table.setHorizontalHeaderLabels(("文件", "季", "集", "结束集"))
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self._rows = []
        for i, e in enumerate(videos):
            item = getattr(e, "item", None)
            name = getattr(item, "name", "") if item else ""
            parsed = getattr(e, "parsed", None)
            season = getattr(parsed, "season", None) if parsed else None
            ep = getattr(parsed, "episode", None) if parsed else None
            self.table.setItem(i, 0, QTableWidgetItem(str(name)))
            self.table.item(i, 0).setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i, 1, QTableWidgetItem(
                "" if season is None else str(season)))
            self.table.setItem(i, 2, QTableWidgetItem(
                "" if ep is None else str(ep)))
            self.table.setItem(i, 3, QTableWidgetItem(""))
            self._rows.append((e, item))
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_apply = QPushButton("应用")
        btn_cancel = QPushButton("取消")
        btns.addWidget(self.btn_apply)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)
        self.btn_apply.clicked.connect(self.apply)
        btn_cancel.clicked.connect(self.reject)

    def apply(self) -> None:
        """把表格里的季/集写回任务的 episode_overrides，再重建预览。"""
        plan = self.plan
        overrides = dict(getattr(plan, "episode_overrides", {}) or {})
        for i, (entry, item) in enumerate(self._rows):
            fid = getattr(item, "fid", "") if item else ""
            if not fid:
                continue
            try:
                season = int(self.table.item(i, 1).text())
                ep = int(self.table.item(i, 2).text())
            except Exception:
                continue
            overrides[fid] = (season, ep)
        plan.episode_overrides = overrides
        fn = getattr(self.app, "_apply_episode_mapping", None)
        if callable(fn):
            try:
                fn(plan)
            except Exception as e:      # noqa: BLE001
                QMessageBox.warning(self, "季集映射", f"应用失败：{e}")
                return
        self.accept()


class _UiSignal(QObject):
    """把后台线程的回调排队交给界面线程执行。"""

    fn = Signal(object)


class LoginDialog(QDialog):
    """115 扫码登录：与 Tk 版同一套接口（qr_token / qr_image / qr_status）。

    二维码在后台线程里轮询，界面线程只负责刷新显示。
    """

    def __init__(self, parent, app, client):
        super().__init__(parent)
        self.app = app
        self.client = client
        self.stop = threading.Event()
        self.token = None
        self._login_app = "ios"
        # 后台线程 → 界面线程：用信号排队，比在子线程里调 singleShot 可靠
        self._sig = _UiSignal()
        self._sig.fn.connect(self._run_ui)
        self.setWindowTitle("登录 115")
        self.setFixedSize(420, 620)

        lay = QVBoxLayout(self)
        title = QLabel("请用 115 手机 App 扫码登录")
        f = QFont(self.font())
        f.setPointSize(12)
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        tip = QLabel("扫码一次后会记住登录；换新版本也不用再扫。")
        tip.setStyleSheet("color:#176b33;")
        tip.setAlignment(Qt.AlignCenter)
        lay.addWidget(tip)

        dev_row = QHBoxLayout()
        dev_row.addStretch(1)
        dev_row.addWidget(QLabel("登录设备"))
        self.combo_app = QComboBox()
        self.combo_app.addItems(["ios", "android", "web"])
        self.combo_app.setCurrentText(
            str((getattr(app, "settings", {}) or {}).get("login_app", "ios")))
        self.combo_app.currentTextChanged.connect(lambda _t: self.refresh_qr())
        dev_row.addWidget(self.combo_app)
        dev_row.addStretch(1)
        lay.addLayout(dev_row)

        hint = QLabel("建议 ios：不影响安卓手机和网页登录。\n"
                      "android 可能踢掉手机 App；web 会踢掉网页登录。")
        hint.setStyleSheet("color:#777;")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        self.qr_label = QLabel("正在获取二维码…")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setMinimumHeight(300)
        lay.addWidget(self.qr_label, 1)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.status_label)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_refresh = QPushButton("刷新二维码")
        self.btn_cookie = QPushButton("用 Cookie 登录…")
        self.btn_cancel = QPushButton("取消")
        btns.addWidget(self.btn_refresh)
        btns.addWidget(self.btn_cookie)
        btns.addWidget(self.btn_cancel)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.btn_refresh.clicked.connect(self.refresh_qr)
        self.btn_cookie.clicked.connect(self._open_cookie)
        self.btn_cancel.clicked.connect(self.reject)

        QTimer.singleShot(50, self.start_login)

    # ---------------- 登录流程
    def start_login(self) -> None:
        self._login_app = self.combo_app.currentText()
        self.stop.clear()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        """后台轮询（与 Tk 版逻辑一致）。"""
        try:
            token = self.client.qr_token()
            image = self.client.qr_image(token["uid"])
            self._ui(lambda: self.show_token(token, image))
            while not self.stop.is_set():
                status = self.client.qr_status(token)
                self._ui(lambda s=status: self.show_status(s))
                if status == 2:
                    ok = self.client.qr_login(token["uid"],
                                              app=self._login_app)
                    self._ui(lambda ok=ok: self._on_login(ok))
                    return
                if status in (-1, -2, -3):
                    self._ui(lambda s=status: self.show_expired(s))
                    return
                time.sleep(1.0)
        except Exception as e:      # noqa: BLE001
            self._ui(lambda: self.show_error(str(e)))

    def _ui(self, fn) -> None:
        """从后台线程回到界面线程执行。"""
        self._sig.fn.emit(fn)

    def _run_ui(self, fn) -> None:
        try:
            fn()
        except Exception:
            pass

    def show_token(self, token: dict, image: bytes) -> None:
        self.token = token
        try:
            from PySide6.QtGui import QPixmap
            pix = QPixmap()
            if pix.loadFromData(image):
                self.qr_label.setPixmap(pix.scaled(
                    280, 280, Qt.KeepAspectRatio, Qt.FastTransformation))
            else:
                self.qr_label.setText("二维码图片加载失败")
        except Exception as e:      # noqa: BLE001
            self.qr_label.setText(f"二维码显示失败：{e}")
        self.status_label.setText("请用手机扫描上方二维码")

    def show_status(self, status: int) -> None:
        if status == 1:
            self.status_label.setText("已扫码，请在手机上确认登录")
            self.status_label.setStyleSheet("color:#176b33;")

    def show_expired(self, status: int) -> None:
        self.status_label.setText(
            "二维码已过期" if status == -1 else "已取消登录")
        self.status_label.setStyleSheet("color:#b3261e;")

    def show_error(self, msg: str) -> None:
        self.status_label.setText(f"登录失败：{msg}")
        self.status_label.setStyleSheet("color:#b3261e;")

    def _on_login(self, ok: bool) -> None:
        if ok:
            self.status_label.setText("登录成功")
            self.status_label.setStyleSheet("color:#176b33;")
            # 通知业务层刷新状态
            post = getattr(self.app, "post", None)
            if callable(post):
                try:
                    post("login_check", True)
                except Exception:
                    pass
            QTimer.singleShot(400, self.accept)
        else:
            self.show_expired(-2)

    def refresh_qr(self) -> None:
        self.stop.set()
        self.qr_label.setPixmap(QPixmap())
        self.qr_label.setText("正在刷新二维码…")
        self.status_label.setText("")
        QTimer.singleShot(300, self.start_login)

    def _open_cookie(self) -> None:
        CookieDialog(self, self.app, self.client).exec()

    def closeEvent(self, event) -> None:
        self.stop.set()
        super().closeEvent(event)


class CookieDialog(QDialog):
    """导入 115 Cookie 并验证。"""

    def __init__(self, parent, app, client):
        super().__init__(parent)
        self.app = app
        self.client = client
        self.setWindowTitle("导入 115 Cookie")
        self.resize(620, 360)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "把浏览器里 115.com 的 Cookie 粘贴到下面"
            "（至少包含 UID、CID、SEID、KID）。"))
        hint = QLabel("格式示例：UID=123_CID=abc_SEID=def_KID=ghi"
                      "（分号或换行分隔均可）")
        hint.setStyleSheet("color:#777;")
        lay.addWidget(hint)
        self.text = QTextEdit()
        lay.addWidget(self.text, 1)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#b3261e;")
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_ok = QPushButton("验证并保存")
        btn_cancel = QPushButton("取消")
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)
        btn_ok.clicked.connect(self.save)
        btn_cancel.clicked.connect(self.reject)

    def save(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            self.msg.setText("请先粘贴 Cookie。")
            return
        try:
            self.client.set_cookie_text(text)
        except Exception as e:      # noqa: BLE001
            self.msg.setText(str(e))
            return
        self.msg.setStyleSheet("color:#555;")
        self.msg.setText("正在验证…")
        self._sig = _UiSignal()
        self._sig.fn.connect(self._run_ui)

        def worker():
            ok = self.client.is_logged_in(force=True)
            self._sig.fn.emit(lambda: self._done(ok))

        threading.Thread(target=worker, daemon=True).start()

    def _run_ui(self, fn) -> None:
        try:
            fn()
        except Exception:
            pass

    def _done(self, ok: bool) -> None:
        if ok:
            self.accept()
        else:
            self.msg.setStyleSheet("color:#b3261e;")
            self.msg.setText("Cookie 无效或已过期。")


class PlanTableModel(QAbstractTableModel):
    """任务表的模型/视图实现。

    不用 QTableWidget：它为每个单元格创建独立控件，150 行 × 9 列
    实测一次重绘要 20ms，拖动窗口明显发涩；用模型视图后 Qt 只绘制
    可见行，开销大幅下降。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plans: list = []

    def set_plans(self, plans: list) -> None:
        self.beginResetModel()
        self._plans = list(plans or [])
        # 预先把每行要显示的文本算好：Qt 绘制一帧会对同一单元格反复
        # 调用 data()（实测单次 12us），每次重新拼字符串会把重绘拖慢一倍。
        self._cache = [self._row_values(p) for p in self._plans]
        self._seasons = [",".join(f"S{s:02d}" for s in (p.seasons or []))
                         for p in self._plans]
        self._summaries = [getattr(p, "new_summary", "") or "（无需修改）"
                           for p in self._plans]
        self._eps = [fmt_episodes(p) for p in self._plans]
        self._conf = [f"{p.confidence * 100:.0f}%" for p in self._plans]
        self.endResetModel()

    @staticmethod
    def _row_values(p) -> tuple:
        return (
            "☑" if getattr(p, "selected", False) else "☐",
            "剧集" if p.media_type == "series" else
            ("电影" if p.media_type == "movie" else "未知"),
            SHORT_CATEGORY.get(p.category, p.category),
            str(getattr(p, "current_name", "") or ""),
            str(getattr(p, "new_summary", "") or "（无需修改）"),
            ",".join(f"S{s:02d}" for s in (p.seasons or [])),
            fmt_episodes(p),
            f"{p.confidence * 100:.0f}%",
            STATUS_LABELS.get(p.status, p.status),
        )

    def plan_at(self, row: int):
        if 0 <= row < len(self._plans):
            return self._plans[row]
        return None

    def rowCount(self, parent=None) -> int:      # noqa: N802
        return 0 if parent and parent.isValid() else len(self._plans)

    def columnCount(self, parent=None) -> int:   # noqa: N802
        return 0 if parent and parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if not 0 <= row < len(self._cache):
            return None
        col = index.column()
        if role == Qt.DisplayRole:
            return self._cache[row][col]
        if role == Qt.TextAlignmentRole and col in (0, 1, 2, 5, 6, 7, 8):
            return int(Qt.AlignCenter)
        if role == Qt.ForegroundRole:
            p = self._plans[row]
            if p.status == "review":
                return QColor("#a15c00")
            if p.status == "error":
                return QColor("#b3261e")
        return None


class MainWindow(QMainWindow):
    """主窗口：左侧目录 + 右侧任务表（第一阶段只实现右侧）。"""

    def __init__(self, app, app_dir: str):
        super().__init__()
        self.app = app                 # 复用 Tk 版 App 的业务方法与状态
        self.app_dir = app_dir
        self.setWindowTitle("115 海报墙重命名助手")
        self.resize(1360, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        root.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_dir_panel())
        splitter.addWidget(self._build_plan_panel())
        splitter.addWidget(self._build_side_panel())
        # 任务表是主体，给它最大权重；左栏/右栏只取够用的宽度。
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 720, 460])
        splitter.setChildrenCollapsible(False)
        # 关键：左右两栏固定宽度，窗口变宽时全部给任务表。
        # 否则每次缩放三栏都要重新分配，任务表视口宽度不停变化，
        # 每帧都要重排所有可见行，这正是拖动发涩的原因。
        try:
            splitter.setCollapsible(0, False)
            splitter.setCollapsible(2, False)
        except Exception:
            pass
        self._splitter = splitter
        root.addWidget(splitter, 1)

        root.addWidget(self._build_statusbar())

        # 定时拉取后台队列（业务线程投递的消息）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(80)

    # ------------------------------------------------------------ 构建
    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.btn_analyze_dir = QPushButton("分析当前目录")
        self.btn_analyze_sel = QPushButton("分析所选")
        self.btn_preview = QPushButton("预览操作")
        self.btn_apply = QPushButton("应用改名")
        self.btn_undo = QPushButton("撤销")
        for b in (self.btn_analyze_dir, self.btn_analyze_sel, self.btn_preview,
                  self.btn_apply, self.btn_undo):
            lay.addWidget(b)
        # 逐个接到业务层（Tk 版 App 的对应方法，均无参数）
        self.btn_analyze_dir.clicked.connect(
            lambda: _call(self.app, "analyze_current"))
        self.btn_analyze_sel.clicked.connect(
            lambda: _call(self.app, "analyze_selected"))
        self.btn_preview.clicked.connect(
            lambda: _call(self.app, "preview_ops"))
        self.btn_apply.clicked.connect(
            lambda: _call(self.app, "apply_selected"))
        self.btn_undo.clicked.connect(
            lambda: _call(self.app, "undo_last"))
        lay.addStretch(1)
        self.btn_manual = QPushButton("手动搜索…")
        self.btn_settings = QPushButton("设置…")
        self.btn_login = QPushButton("登录 115…")
        lay.addWidget(self.btn_login)
        lay.addWidget(self.btn_manual)
        lay.addWidget(self.btn_settings)
        self.btn_login.clicked.connect(self.open_login)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_manual.clicked.connect(self.open_manual_search)
        self.lbl_mode = QLabel("模式：未连接")
        lay.addWidget(self.lbl_mode)
        return bar

    def open_settings(self) -> None:
        SettingsDialog(self, self.app).exec()

    def open_login(self) -> None:
        """115 登录：优先扫码，也可改用 Cookie。"""
        client = getattr(self.app, "client", None)
        if client is None:
            QMessageBox.information(
                self, "登录 115",
                "尚未创建客户端连接。\n"
                "请检查网络或先用默认界面完成登录。")
            return
        LoginDialog(self, self.app, client).exec()

    def open_manual_search(self) -> None:
        """手动搜索：先选任务，再按关键词搜各来源。"""
        p = getattr(self.app, "detail_plan", None)
        if p is None:
            QMessageBox.information(self, "手动搜索", "请先选择一个任务。")
            return
        ManualSearchDialog(self, self.app, p).exec()

    def open_episode_mapping(self) -> None:
        p = getattr(self.app, "detail_plan", None)
        if p is None:
            QMessageBox.information(self, "季集映射", "请先选择一个任务。")
            return
        if getattr(p, "media_type", "") != "series":
            QMessageBox.information(self, "季集映射",
                                    "只有剧集任务可以设置季集映射。")
            return
        EpisodeMappingDialog(self, self.app, p).exec()

    def _on_auto_nfo_toggled(self, checked: bool) -> None:
        """写回“改名后自动存 NFO”设置。"""
        app = self.app
        try:
            settings = getattr(app, "settings", {})
            settings["auto_nfo_after_rename"] = bool(checked)
            fn = getattr(app, "_save_settings", None)
            if callable(fn):
                fn()
        except Exception as e:      # noqa: BLE001
            self.append_log(f"保存自动 NFO 设置失败：{e}")

    def _build_dir_panel(self) -> QWidget:
        """左栏：文件来源、导航、目录树、右键菜单。"""
        box = QWidget()
        # 左栏固定宽度：窗口变宽时宽度不变，避免每帧重新分配
        box.setMinimumWidth(240)
        box.setMaximumWidth(460)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 文件来源：网盘 / 本地
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(QLabel("文件来源"))
        self.radio_cloud = QRadioButton("网盘")
        self.radio_cloud.setChecked(True)
        self.radio_local = QRadioButton("本地")
        mode_row.addWidget(self.radio_cloud)
        mode_row.addWidget(self.radio_local)
        self.btn_choose_root = QPushButton("选择文件夹…")
        self.btn_choose_root.setEnabled(False)
        mode_row.addWidget(self.btn_choose_root)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)
        self.radio_cloud.toggled.connect(
            lambda on: on and _call(self.app, "_switch_mode", "cloud", True))
        self.radio_local.toggled.connect(
            lambda on: on and self._switch_local())
        self.btn_choose_root.clicked.connect(
            lambda: _call(self.app, "choose_local_root"))

        self.lbl_root = QLabel("")
        self.lbl_root.setStyleSheet("color:#777;")
        self.lbl_root.setWordWrap(True)
        lay.addWidget(self.lbl_root)

        # 导航
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.btn_up = QPushButton("上一级")
        self.btn_up.clicked.connect(
            lambda: _call(self.app, "go_up"))
        nav.addWidget(self.btn_up)
        self.lbl_path = QLabel("根目录")
        self.lbl_path.setStyleSheet("color:#333;")
        nav.addWidget(self.lbl_path, 1)
        lay.addLayout(nav)

        # 目录树
        self.dir_tree = QTreeWidget()
        self.dir_tree.setColumnCount(3)
        self.dir_tree.setHeaderLabels(("名称", "类型", "大小"))
        self.dir_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.dir_tree.setRootIsDecorated(False)
        self.dir_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.dir_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.dir_tree.header().resizeSection(1, 56)
        self.dir_tree.header().resizeSection(2, 76)
        self.dir_tree.itemDoubleClicked.connect(self._on_dir_double_click)
        self.dir_tree.customContextMenuRequested.connect(self._on_dir_menu)
        # 缩放时目录树的重绘占了大部分开销（实测隐藏它 16.5ms → 4.5ms）：
        # 让它在拉伸过程中只撑背景、不重排每一项，停手后再整体刷新。
        self.dir_tree.setUniformRowHeights(True)
        lay.addWidget(self.dir_tree, 1)
        return box

    def resizeEvent(self, event) -> None:
        """窗口缩放：任务表与目录树延后重排，停手后一次性刷新。

        实测重绘成本 ≈ 列数 × 可见行数（9 列 60 行约 15~20ms），
        拖动大窗口时每帧都要重排可见单元格，手感发涩。
        拖动期间先不刷新这两个大控件，停手 60ms 后统一刷新一次，
        界面始终可见、不闪烁。
        """
        super().resizeEvent(event)
        for w in (getattr(self, "table", None), getattr(self, "dir_tree", None)):
            try:
                if w is not None:
                    w.setUpdatesEnabled(False)
            except Exception:
                pass
        if getattr(self, "_resize_timer", None) is None:
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._after_resize)
        self._resize_timer.start(60)

    def _after_resize(self) -> None:
        try:
            self.dir_tree.setUpdatesEnabled(True)
            self.dir_tree.viewport().update()
        except Exception:
            pass
        try:
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
        except Exception:
            pass

    def _switch_local(self) -> None:
        """切到本地模式：没有根目录时先让用户选一个。"""
        app = self.app
        root = str(getattr(app, "local_root", "") or "")
        if not root:
            _call(app, "choose_local_root")
            root = str(getattr(app, "local_root", "") or "")
            if not root:
                # 没选成，退回网盘模式
                self.radio_cloud.setChecked(True)
                return
        _call(app, "_switch_mode", "local", False)
        self.lbl_root.setText(root)
        _call(app, "refresh")

    def _build_plan_panel(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        for text, meth in (("全选自动项", "select_auto"),
                           ("全选有操作的", "select_all_ops"),
                           ("全不选", "select_none")):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, m=meth: _call(self.app, m))
            tools.addWidget(b)
        tools.addStretch(1)
        lay.addLayout(tools)

        # 模型/视图：只绘制可见行，150 行时重绘开销远低于 QTableWidget
        self.plan_model = PlanTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.plan_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setHorizontalScrollMode(
            QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # 重绘成本≈列数×可见行数（实测 9 列 60 行约 15ms）。把行高压到 20px
        # 并限制表格高度，让同屏行数更少，拖动窗口时更跟手。
        self.table.verticalHeader().setDefaultSectionSize(20)
        header = self.table.horizontalHeader()
        # 全部固定列宽：只要有任何一列设成 Stretch，窗口一变宽 Qt 就要为
        # 该列重新计算宽度并重排所有可见行（实测把 21ms 放大到 75ms）。
        # 固定列宽下，变宽只是多显示空白或出现横向滚动，代价很小。
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        widths = (36, 52, 60, 220, 300, 46, 70, 62, 66)
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_row_selected())
        lay.addWidget(self.table, 1)
        return box

    # ------------------------------------------------------------ 目录树
    def render_dir_items(self) -> None:
        """把当前目录内容刷到左栏（对应 Tk 版 _fill_dir_tree）。"""
        items = getattr(self.app, "dir_items", {}) or {}
        self.dir_tree.clear()
        entries = list(items.values())
        # 文件夹在前，文件在后，各自按名称排序
        entries.sort(key=lambda it: (not getattr(it, "is_dir", False),
                                     str(getattr(it, "name", ""))))
        bold = QFont(self.font())
        bold.setBold(True)
        for it in entries:
            is_dir = bool(getattr(it, "is_dir", False))
            node = QTreeWidgetItem([
                str(getattr(it, "name", "")),
                "文件夹" if is_dir else "文件",
                "" if is_dir else _fmt_size(getattr(it, "size", 0) or 0),
            ])
            if is_dir:
                node.setFont(0, bold)
                node.setIcon(0, self.style().standardIcon(
                    self.style().StandardPixmap.SP_DirIcon))
            else:
                node.setIcon(0, self.style().standardIcon(
                    self.style().StandardPixmap.SP_FileIcon))
            # 记住对应的业务对象，交互时直接取用
            node.setData(0, Qt.UserRole, getattr(it, "fid", ""))
            self.dir_tree.addTopLevelItem(node)
        path = " / ".join(name for _cid, name in
                          (getattr(self.app, "path_stack", None) or
                           [("0", "根目录")]))
        self.lbl_path.setText(path)

    def selected_dir_items(self) -> list:
        """当前在左栏选中的文件/文件夹对象列表。"""
        items = getattr(self.app, "dir_items", {}) or {}
        out = []
        for node in self.dir_tree.selectedItems():
            fid = node.data(0, Qt.UserRole)
            it = items.get(fid)
            if it is not None:
                out.append(it)
        return out

    def _on_dir_double_click(self, node, _col) -> None:
        fid = node.data(0, Qt.UserRole)
        items = getattr(self.app, "dir_items", {}) or {}
        it = items.get(fid)
        if it is not None and getattr(it, "is_dir", False):
            fn = getattr(self.app, "_enter_dir_item", None)
            if fn:
                fn(it)

    def _on_dir_menu(self, pos) -> None:
        """右键菜单：进入、分析、重命名、刷新。"""
        node = self.dir_tree.itemAt(pos)
        menu = QMenu(self)
        act_enter = menu.addAction("进入文件夹")
        act_analyze = menu.addAction("分析选中")
        menu.addSeparator()
        act_rename = menu.addAction("重命名此项（立即生效）…")
        act_refresh = menu.addAction("刷新当前目录")
        if node is None:
            act_enter.setEnabled(False)
            act_rename.setEnabled(False)
        chosen = menu.exec(self.dir_tree.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_enter and node is not None:
            self._on_dir_double_click(node, 0)
        elif chosen is act_analyze:
            _call(self.app, "analyze_selected")
        elif chosen is act_rename and node is not None:
            # 先让业务层知道当前选中项，再走它的改名流程
            items = getattr(self.app, "dir_items", {}) or {}
            it = items.get(node.data(0, Qt.UserRole))
            if it is not None:
                setattr(self.app, "current_item", it)
                _call(self.app, "rename_dir_item")
        elif chosen is act_refresh:
            _call(self.app, "refresh")

    def _build_side_panel(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lay.addWidget(QLabel("选中项详情"))

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("标题"))
        self.edit_title = QLineEdit()
        row.addWidget(self.edit_title, 2)
        row.addWidget(QLabel("年份"))
        self.edit_year = QLineEdit()
        self.edit_year.setMaximumWidth(80)
        row.addWidget(self.edit_year)
        row.addWidget(QLabel("季"))
        self.edit_season = QLineEdit()
        self.edit_season.setMaximumWidth(60)
        row.addWidget(self.edit_season)
        lay.addLayout(row)

        self.lbl_meta = QLabel("")
        self.lbl_meta.setWordWrap(True)
        lay.addWidget(self.lbl_meta)

        self.note = QTextEdit()
        self.note.setReadOnly(True)
        self.note.setMaximumHeight(90)
        lay.addWidget(self.note)

        # 季集映射
        map_row = QHBoxLayout()
        map_row.setSpacing(6)
        self.btn_map = QPushButton("季集映射…")
        self.btn_map.clicked.connect(self.open_episode_mapping)
        map_row.addWidget(self.btn_map)
        self.lbl_map = QLabel("")
        self.lbl_map.setStyleSheet("color:#777;")
        map_row.addWidget(self.lbl_map, 1)
        lay.addLayout(map_row)

        # 命名规则面板
        lay.addWidget(QLabel("命名规则"))
        self.naming_panel = NamingRulePanel()
        lay.addWidget(self.naming_panel)
        btn_save_rule = QPushButton("保存为默认")
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn_save_rule)
        lay.addLayout(btn_row)
        btn_save_rule.clicked.connect(self.save_naming_rule)

        # NFO / 图片
        nfo_row = QHBoxLayout()
        nfo_row.setSpacing(6)
        self.btn_nfo_save = QPushButton("保存 NFO/图片")
        self.btn_nfo_clear = QPushButton("清空 NFO/图片…")
        self.chk_auto_nfo = QCheckBox("应用改名后自动存")
        self.btn_nfo_save.clicked.connect(
            lambda: _call(self.app, "save_nfo_artwork"))
        self.btn_nfo_clear.clicked.connect(
            lambda: _call(self.app, "clear_nfo_artwork"))
        self.chk_auto_nfo.toggled.connect(self._on_auto_nfo_toggled)
        nfo_row.addWidget(self.btn_nfo_save)
        nfo_row.addWidget(self.btn_nfo_clear)
        nfo_row.addWidget(self.chk_auto_nfo)
        nfo_row.addStretch(1)
        lay.addLayout(nfo_row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log)
        lay.addStretch(1)
        return box

    def save_naming_rule(self) -> None:
        """把命名规则写回设置（对应 Tk 版 apply_naming_rule）。"""
        values = self.naming_panel.values()
        app = self.app
        try:
            settings = getattr(app, "settings", {})
            settings.update(values)
            fn = getattr(app, "_save_settings", None)
            if callable(fn):
                fn()
            opts = getattr(app, "options", None)
            if opts is not None:
                for k, v in values.items():
                    setattr(opts, k, v)
            self.append_log("命名规则已保存：" + ", ".join(
                f"{k}={v}" for k, v in values.items()))
        except Exception as e:      # noqa: BLE001
            self.append_log(f"保存命名规则失败：{e}")

    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_status = QLabel("就绪")
        lay.addWidget(self.lbl_status)
        lay.addStretch(1)
        self.lbl_counts = QLabel("")
        lay.addWidget(self.lbl_counts)
        return bar

    # ------------------------------------------------------------ 数据
    def render_plans(self) -> None:
        """把业务层的 plan 列表刷到表格（对应 Tk 版 _render_plans）。"""
        plans = getattr(self.app, "plans", []) or []
        current = self.table.currentIndex().row()
        self.plan_model.set_plans(plans)
        if plans:
            row = current if 0 <= current < len(plans) else 0
            self.table.selectRow(row)
            auto = sum(1 for p in plans if p.status == "auto")
            review = sum(1 for p in plans if p.status == "review")
            self.lbl_counts.setText(
                f"共 {len(plans)} 项 · 可自动 {auto} · 需确认 {review}")
            self.lbl_status.setText(self.lbl_counts.text())
        else:
            self.lbl_counts.setText("")

    def _on_row_selected(self) -> None:
        row = self.table.currentIndex().row()
        p = self.plan_model.plan_at(row)
        if p is None:
            return
        self.app.detail_plan = p
        self.edit_title.setText(getattr(p, "display_title", "")
                                or getattr(p, "title", ""))
        self.edit_year.setText(str(getattr(p, "display_year", "") or ""))
        seasons = p.seasons or []
        self.edit_season.setText(str(seasons[0]) if len(seasons) == 1 else "")
        parts = []
        if p.match:
            for label, src in (("豆瓣", "douban"), ("Bangumi", "bangumi"),
                               ("IMDb", "imdb"), ("TMDB", "tmdb")):
                cand = getattr(p.match, src, None)
                if cand:
                    parts.append(f"{label}：{cand.title}")
        if parts:
            parts.append(f"置信度：{p.confidence * 100:.0f}%")
        self.lbl_meta.setText("  |  ".join(parts))
        self.note.setPlainText(getattr(p, "note", "") or "")

    # ------------------------------------------------------------ 队列
    def _poll(self) -> None:
        """处理业务层投递进来的消息。"""
        try:
            app = self.app
            while True:
                kind, payload = app.q.get_nowait()
                if kind == "plans":
                    app.plans = payload
                    self.render_plans()
                elif kind == "listing":
                    # 目录内容变化：刷新左栏
                    if payload and isinstance(payload, dict):
                        app.dir_items = payload
                    self.render_dir_items()
                elif kind == "log":
                    self.append_log(str(payload))
                elif kind == "status":
                    self.lbl_status.setText(str(payload))
                elif kind == "busy":
                    self._set_busy(bool(payload))
        except Exception:
            pass

    def append_log(self, text: str) -> None:
        self.log.append(text)

    def _set_busy(self, busy: bool) -> None:
        for b in (self.btn_analyze_dir, self.btn_analyze_sel,
                  self.btn_preview, self.btn_apply, self.btn_undo):
            b.setEnabled(not busy)


def main(app_dir: str, demo: bool = False) -> int:
    """Qt 版启动入口。业务层暂时复用 Tk 版 App 的方法与状态。"""
    sys.path.insert(0, app_dir)
    from app.gui import App          # 复用业务方法（不构建 Tk 界面）

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    qapp.setFont(QFont("Microsoft YaHei UI", 9))

    helper = App.__new__(App)        # 不调用 Tk 版 __init__，避免建窗口
    # 只初始化数据相关状态
    helper.app_dir = app_dir
    helper.data_dir = os.path.join(app_dir, "data")
    os.makedirs(helper.data_dir, exist_ok=True)
    helper.settings = App._load_settings(helper)
    helper.q = __import__("queue").Queue()
    helper.plans = []
    helper.plan_rows = {}
    helper.detail_plan = None
    helper.busy = False
    helper.is_demo = demo
    helper.log_threadsafe = lambda text: helper.q.put(("log", text))

    win = MainWindow(helper, app_dir)
    win.show()
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
