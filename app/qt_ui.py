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

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QRadioButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

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
        media = getattr(self.plan, "media_type", "series")

        def worker():
            out = []
            meta = getattr(app, "meta", None)
            if meta is None:
                QTimer.singleShot(0, lambda: self._show([], "未连接资料来源"))
                return
            for name, fn_name in (("豆瓣", "search_douban"),
                                  ("Bangumi", "search_bangumi"),
                                  ("IMDb", "search_imdb"),
                                  ("TMDB", "search_tmdb")):
                fn = getattr(meta, fn_name, None)
                if not callable(fn):
                    continue
                try:
                    for c in (fn(query) or [])[:15]:
                        out.append(c)
                except Exception as e:      # noqa: BLE001
                    log = getattr(app, "log_threadsafe", None)
                    if log:
                        log(f"{name} 搜索失败：{e}")
            QTimer.singleShot(0, lambda: self._show(out, ""))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _show(self, cands: list, err: str) -> None:
        self._candidates = cands
        self.btn_search.setEnabled(True)
        self.table.setRowCount(len(cands))
        for i, c in enumerate(cands):
            vals = (getattr(c, "source", ""),
                    getattr(c, "title", ""),
                    getattr(c, "original_title", ""),
                    str(getattr(c, "year", "") or ""),
                    str(getattr(c, "sid", "") or ""))
            for col, v in enumerate(vals):
                self.table.setItem(i, col, QTableWidgetItem(str(v)))
        if cands:
            self.lbl_hint.setText(f"共 {len(cands)} 条结果，双击或点“应用所选”。")
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
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([340, 560, 460])
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
        lay.addStretch(1)
        self.btn_manual = QPushButton("手动搜索…")
        self.btn_settings = QPushButton("设置…")
        lay.addWidget(self.btn_manual)
        lay.addWidget(self.btn_settings)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_manual.clicked.connect(self.open_manual_search)
        self.lbl_mode = QLabel("模式：未连接")
        lay.addWidget(self.lbl_mode)
        return bar

    def open_settings(self) -> None:
        SettingsDialog(self, self.app).exec()

    def open_manual_search(self) -> None:
        """手动搜索：先选任务，再按关键词搜各来源。"""
        p = getattr(self.app, "detail_plan", None)
        if p is None:
            QMessageBox.information(self, "手动搜索", "请先选择一个任务。")
            return
        ManualSearchDialog(self, self.app, p).exec()

    def _build_dir_panel(self) -> QWidget:
        """左栏：文件来源、导航、目录树、右键菜单。"""
        box = QWidget()
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

        self.lbl_root = QLabel("")
        self.lbl_root.setStyleSheet("color:#777;")
        self.lbl_root.setWordWrap(True)
        lay.addWidget(self.lbl_root)

        # 导航
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.btn_up = QPushButton("上一级")
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
        """窗口缩放时暂缓目录树逐项重排，停手后一次性刷新。"""
        super().resizeEvent(event)
        try:
            self.dir_tree.setUpdatesEnabled(False)
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

    def _build_plan_panel(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        for text in ("全选自动项", "全选有操作的", "全不选"):
            tools.addWidget(QPushButton(text))
        tools.addStretch(1)
        lay.addLayout(tools)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        widths = (36, 52, 60, 260, 320, 46, 80, 66, 66)
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
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
        keep = self.table.currentRow()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(plans))
        for i, p in enumerate(plans):
            seasons = ",".join(f"S{s:02d}" for s in (p.seasons or []))
            summary = getattr(p, "new_summary", "") or "（无需修改）"
            values = (
                "☑" if getattr(p, "selected", False) else "☐",
                "剧集" if p.media_type == "series" else
                ("电影" if p.media_type == "movie" else "未知"),
                SHORT_CATEGORY.get(p.category, p.category),
                getattr(p, "current_name", ""),
                summary,
                seasons,
                fmt_episodes(p),
                f"{p.confidence * 100:.0f}%",
                STATUS_LABELS.get(p.status, p.status),
            )
            for c, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                if c in (0, 1, 2, 5, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignCenter)
                if p.status == "review":
                    item.setForeground(QColor("#a15c00"))
                elif p.status == "error":
                    item.setForeground(QColor("#b3261e"))
                self.table.setItem(i, c, item)
        self.table.setUpdatesEnabled(True)
        if plans:
            self.table.selectRow(min(keep, len(plans) - 1) if keep >= 0 else 0)
            auto = sum(1 for p in plans if p.status == "auto")
            review = sum(1 for p in plans if p.status == "review")
            self.lbl_counts.setText(
                f"共 {len(plans)} 项 · 可自动 {auto} · 需确认 {review}")
            self.lbl_status.setText(self.lbl_counts.text())

    def _on_row_selected(self) -> None:
        row = self.table.currentRow()
        plans = getattr(self.app, "plans", []) or []
        if row < 0 or row >= len(plans):
            return
        p = plans[row]
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
