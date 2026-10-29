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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMenu, QPushButton,
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
        self.lbl_mode = QLabel("模式：未连接")
        lay.addWidget(self.lbl_mode)
        return bar

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
        self.note.setMaximumHeight(96)
        lay.addWidget(self.note)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        lay.addWidget(self.log)
        lay.addStretch(1)
        return box

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
