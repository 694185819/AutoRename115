# -*- coding: utf-8 -*-
"""任务质量检查结果（QcResult）：把“为什么需要确认/跳过”结构化成原因码。

背景：以前“需确认”由散落在 planner 各处的 `status = "review"` 决定，
而原因只有一句中文提示。UI 想高亮原因、想按原因批量勾选、想统计
“最多的是哪类问题”，都只能去解析提示字符串。

现在每个判定点产出一个 `QcResult`：
- `code`       稳定的原因码（给程序用，不随文案变化）；
- `message`    给人看的说明；
- `severity`   info / warn / block；
- `action`     none / reselect / confirm / manual_search / review_mapping。

`PlanItem.qc` 汇总所有原因；`PlanItem.status` 仍由
`status_for()` 计算，保持既有展示与勾选逻辑不变。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

INFO = "info"
WARN = "warn"
BLOCK = "block"

SEVERITY_ORDER = {INFO: 0, WARN: 1, BLOCK: 2}

# 原因码 → 短标签（界面展示用；文案改动不影响 code 与判断逻辑）
CODE_LABELS = {
    "no_title": "未识别片名",
    "no_online_title": "联网无标题",
    "search_term_too_short": "搜索词过短",
    "low_confidence": "置信度低",
    "no_match": "无匹配",
    "season_title_conflict": "剧名冲突",
    "duplicate_episodes": "疑似重复集",
    "season_unconfirmed": "季号未确认",
    "special_unmatched": "特别篇补号",
    "special_zero_guessed": "第0集猜测",
    "name_source_no_episodes": "该来源无分集数据",
    "bdmv_inner_dir": "蓝光内部目录",
    "no_series_year": "缺首播年",
}


@dataclass(frozen=True)
class QcResult:
    code: str
    message: str = ""
    severity: str = WARN
    action: str = "none"


@dataclass
class QcReport:
    """一个任务的全部检查结果；顺序即产生顺序，便于按优先级展示。"""
    items: list[QcResult] = field(default_factory=list)

    def add(self, result: Optional[QcResult]) -> None:
        if result is None:
            return
        if result not in self.items:
            self.items.append(result)

    def extend(self, results) -> None:
        for r in results or []:
            self.add(r)

    def codes(self) -> list[str]:
        return [r.code for r in self.items]

    def has(self, code: str) -> bool:
        return any(r.code == code for r in self.items)

    @property
    def worst(self) -> Optional[QcResult]:
        """最严重的一条；同级时取最后加入的（最新判断）。"""
        if not self.items:
            return None
        target = max(SEVERITY_ORDER.get(r.severity, 0) for r in self.items)
        for r in reversed(self.items):
            if SEVERITY_ORDER.get(r.severity, 0) == target:
                return r
        return self.items[-1]

    @property
    def blocked(self) -> bool:
        return any(r.severity == BLOCK for r in self.items)

    @property
    def needs_review(self) -> bool:
        return any(r.severity in (WARN, BLOCK) for r in self.items)

    def messages(self) -> list[str]:
        return [r.message for r in self.items if r.message]


# ------------------------------------------------------------ 预置原因
# 原因码保持稳定；文案可以随时改，不影响判断与测试。
NO_TITLE = QcResult("no_title", "没有识别出片名，请手动填写。", BLOCK,
                    "confirm")
NO_ONLINE_TITLE = QcResult(
    "no_online_title",
    "没有联网获取到标题，已跳过改名；请检查网络或使用手动搜索。",
    BLOCK, "manual_search")
SEARCH_TERM_TOO_SHORT = QcResult(
    "search_term_too_short",
    "搜索词太短（单字或容器名），已跳过自动搜索；"
    "请右键任务使用“手动搜索”。", BLOCK, "manual_search")
LOW_CONFIDENCE = QcResult(
    "low_confidence", "匹配置信度较低，请检查标题/年份或手动修正。", WARN,
    "manual_search")
NO_MATCH = QcResult(
    "no_match", "没有找到匹配，请手动输入标题或改用原名搜索。", WARN,
    "manual_search")
SEASON_TITLE_CONFLICT = QcResult(
    "season_title_conflict",
    "季目录里的视频文件名与上级剧名不一致，已暂停自动改名；"
    "请核对目录，或右键任务手动搜索。", WARN, "confirm")
DUPLICATE_EPISODES = QcResult(
    "duplicate_episodes",
    "疑似重复/错集不会自动勾选，请核对后再改名。", WARN, "review_mapping")
SEASON_UNCONFIRMED = QcResult(
    "season_unconfirmed",
    "季号还没确认，已只保留文件夹/季目录改名；请用“季集映射…”指定季。",
    WARN, "review_mapping")
SPECIAL_UNMATCHED = QcResult(
    "special_unmatched",
    "特别篇没有匹配到 TMDB 标题，已按文件名顺序补号，请用“季集映射…”核对。",
    WARN, "review_mapping")
SPECIAL_ZERO_GUESSED = QcResult(
    "special_zero_guessed",
    "SxxE00 没有找到“第0话”标题，暂按第一个特别篇映射，请核对。", WARN,
    "review_mapping")
BDMV_INNER_DIR = QcResult(
    "bdmv_inner_dir", "这是蓝光结构内部目录，请选择上一级的剧集/电影文件夹。",
    BLOCK, "reselect")


def name_source_no_episodes(label: str) -> QcResult:
    """命名来源有条目号、但该来源拿不到单集标题时的提示（信息级）。"""
    return QcResult(
        "name_source_no_episodes",
        f"{label} 没有可用的单集标题数据（豆瓣分集页需要登录），"
        "副标题暂用原文件名；可换 Bangumi / IMDb / TMDB，"
        "或在“季集映射…”里手工改。",
        INFO, "review_mapping")
NO_SUB_TITLE = QcResult(
    "no_series_year", "已还原主剧名，但没找到首播年份。", INFO, "none")


def status_for(report: QcReport, confidence: float,
               min_confidence: float, has_ops: bool) -> str:
    """由检查结果 + 置信度决定 status：auto / review / skip。

    保持与原来一致：有阻断/警告或置信度不足 → review；
    没有可执行操作且没有阻断 → skip。
    """
    if report.blocked or report.needs_review:
        return "review"
    if confidence < min_confidence:
        return "review"
    if not has_ops:
        return "skip"
    return "auto"


def summarize(report: QcReport) -> str:
    """任务表/详情里的一行摘要，例如“需确认：低置信度、疑似重复”。"""
    if not report.items:
        return ""
    worst = report.worst
    label = {INFO: "提示", WARN: "需确认", BLOCK: "无法自动处理"}.get(
        worst.severity if worst else INFO, "提示")
    reasons = [r.message or r.code for r in report.items
               if r.severity == (worst.severity if worst else INFO)]
    return f"{label}：" + "；".join(reasons)
