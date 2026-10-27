# -*- coding: utf-8 -*-
"""qc.py 单测：原因码、严重度、status 推导，以及 planner 实际产出的原因码。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import qc
from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner


def test_report_basics():
    r = qc.QcReport()
    r.add(qc.LOW_CONFIDENCE)
    r.add(qc.DUPLICATE_EPISODES)
    r.add(qc.LOW_CONFIDENCE)          # 幂等
    assert r.codes() == ["low_confidence", "duplicate_episodes"], r.codes()
    assert r.has("duplicate_episodes")
    assert r.needs_review and not r.blocked
    assert r.worst.code == "duplicate_episodes"
    assert qc.summarize(r).startswith("需确认：")


def test_status_for():
    empty = qc.QcReport()
    assert qc.status_for(empty, 0.9, 0.7, has_ops=True) == "auto"
    # 置信度不足
    assert qc.status_for(empty, 0.5, 0.7, has_ops=True) == "review"
    # 没有可执行操作 → skip
    assert qc.status_for(empty, 0.9, 0.7, has_ops=False) == "skip"
    # 阻断优先
    blocked = qc.QcReport([qc.NO_TITLE])
    assert blocked.blocked
    assert qc.status_for(blocked, 1.0, 0.7, has_ops=True) == "review"


def test_info_only_does_not_block():
    r = qc.QcReport([qc.NO_SUB_TITLE])
    assert not r.needs_review and not r.blocked
    assert qc.status_for(r, 1.0, 0.7, has_ops=True) == "auto"


class FakeClient:
    def list_dir(self, cid, page_size=500):
        if cid == "root":
            return [P115Item(fid=f"v{i}", parent_id="root",
                             name=f"某剧.E{i:02d}.mkv", is_dir=False, size=10)
                    for i in (1, 2)]
        return []


class LowConfidenceMeta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(title_zh=parsed.title, series_title=parsed.title,
                           year=2020, confidence=0.2)

    def save_cache(self):
        pass

    def season_episode_titles(self, *a, **k):
        return {}


class NoTitleMeta(LowConfidenceMeta):
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(confidence=0.0)


def test_planner_records_codes():
    root = P115Item(fid="root", parent_id="0", name="某剧", is_dir=True,
                    ancestors=["动画"])
    plan = Planner(LowConfidenceMeta(), NamingOptions()).analyze(
        FakeClient(), [root])[0]
    assert plan.status == "review", plan.status
    assert "low_confidence" in plan.qc_codes, plan.qc_codes
    assert "低" in plan.note or "置信度" in plan.note, plan.note


def test_duplicate_and_season_codes():
    """疑似重复集与季号未确认都能被结构化记录。"""
    from app.models import ParsedName, PlanItem
    planner = Planner(None, NamingOptions())
    plan = PlanItem(item=P115Item(fid="x", parent_id="0", name="某剧",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="x", title="某剧"))
    plan.status = "auto"
    plan.season_confirmed = False
    planner._mark(plan, qc.SEASON_UNCONFIRMED)
    assert plan.status == "review"
    assert "season_unconfirmed" in plan.qc_codes, plan.qc_codes
    assert "季集映射" in plan.note, plan.note
    # 重复记录不会重复写入
    planner._mark(plan, qc.SEASON_UNCONFIRMED)
    assert plan.qc_codes.count("season_unconfirmed") == 1


def main():
    test_report_basics()
    test_status_for()
    test_info_only_does_not_block()
    test_planner_records_codes()
    test_duplicate_and_season_codes()
    print("QC OK")


if __name__ == "__main__":
    main()
