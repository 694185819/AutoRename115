# -*- coding: utf-8 -*-
"""套用 IMDb「单集」条目时要自动换成主剧。

IMDb 搜索结果里可能出现 Episode #1.44 这类单集条目，
它的编号不能当整部剧用（分集、年份、英文名都会错）。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.models import Candidate


def main() -> None:
    app = App(r"I:\实验\AutoRename115")
    app.withdraw()
    m = app.meta
    m.delays = {k: 0.0 for k in m.delays}
    m._cache = {}

    print("=== 单集条目 tt6378944 (Episode #1.44) ===")
    cand = Candidate(source="imdb", title="Episode #1.44",
                     original_title="", year=2016, sid="tt6378944",
                     kind="tv")
    cand.extra = {"aliases": ["青云志", "Noble Aspirations"]}
    ids = m.resolve_ids(cand, "series")
    print("  imdb_id:", ids["imdb_id"], "| title:", ids["imdb_title"])
    assert ids["imdb_id"] != "tt6378944", "单集编号没有被修正"
    assert ids["imdb_id"].startswith("tt"), ids

    print("\n=== 对照：正确主剧 tt6284026 ===")
    cand2 = Candidate(source="imdb", title="Noble Aspirations",
                      original_title="", year=2016, sid="tt6284026",
                      kind="tv")
    cand2.extra = {}
    ids2 = m.resolve_ids(cand2, "series")
    print("  imdb_id:", ids2["imdb_id"])
    assert ids2["imdb_id"] == "tt6284026", ids2

    app.destroy()
    print("\nIMDB EPISODE GUARD OK")


if __name__ == "__main__":
    main()
