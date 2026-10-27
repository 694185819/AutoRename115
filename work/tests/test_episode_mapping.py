# -*- coding: utf-8 -*-
"""手动季集映射：总集编号自动分季 + 将映射写回 PlanItem。"""
import sys
import tkinter as tk

sys.path.insert(0, r"I:\实验\AutoRename115")

import app.episode_mapping as episode_mapping
from app.episode_mapping import EpisodeMappingDialog
from app.models import MatchResult, P115Item
from app.planner import NamingOptions, Planner


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))


class FakeMeta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="测试番", title_original="Test Show",
            year=2020, series_title="测试番", series_year=2020,
            tmdb_id="100", series_imdb_id="tt1234567",
            country="jp", animation=True, confidence=1.0)

    def tmdb_tv_structure(self, tmdb_id):
        return {"seasons": [
            {"season_number": 1, "episode_count": 12},
            {"season_number": 2, "episode_count": 12},
        ]}

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def video(fid, parent, name):
    return P115Item(fid=fid, parent_id=parent, name=name, is_dir=False)


def main():
    root = P115Item(
        fid="show", parent_id="jp", name="测试番", is_dir=True,
        ancestors=["动画", "日番"])
    tree = {"show": [
        video(f"v{i}", "show", f"Test.Show.E{i:02d}.1080p.mkv")
        for i in range(1, 14)
    ]}
    planner = Planner(FakeMeta(), NamingOptions())
    plan = planner.analyze(FakeClient(tree), [root])[0]
    assert plan.season_confirmed is False

    # 屏蔽提示框
    episode_mapping.messagebox.askyesno = lambda *a, **k: True
    episode_mapping.messagebox.showwarning = lambda *a, **k: None
    episode_mapping.messagebox.showinfo = lambda *a, **k: None

    tkroot = tk.Tk()
    tkroot.withdraw()
    captured = []
    dialog = EpisodeMappingDialog(
        tkroot, planner, plan, lambda p: captured.append(p))
    tkroot.update()
    assert len(dialog.rows) == 13, len(dialog.rows)

    # 总集编号：E01-E12 -> S01，E13 -> S02E01
    dialog._auto_total()
    tkroot.update()
    assert (dialog.rows[11]["season"], dialog.rows[11]["episode"]) == (1, 12)
    assert (dialog.rows[12]["season"], dialog.rows[12]["episode"]) == (2, 1)

    dialog._apply()
    tkroot.update()
    assert captured and captured[0] is plan
    assert plan.season_override is None
    assert plan.season_confirmed is True
    assert len(plan.episode_overrides) == 13, plan.episode_overrides

    plan.status = "auto"
    planner.rebuild(plan)
    ep_ops = [o for o in plan.ops if o.role == "episode"]
    assert len(ep_ops) == 13, len(ep_ops)
    assert any(o.fid == "v13" and "S02E01" in o.new_name for o in ep_ops)
    assert plan.season_confirmed is True
    tkroot.destroy()
    print("EPISODE MAPPING OK")


if __name__ == "__main__":
    main()
