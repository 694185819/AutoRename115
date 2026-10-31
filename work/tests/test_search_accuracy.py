# -*- coding: utf-8 -*-
"""强制重搜必须保证准确度，不能抓到无关条目。

历史问题：_fetch_source_candidate 的逻辑是「第一个有结果的词就直接
取 pool[0]」。用英文别名搜时可能命中的是分数 0.17 的完全无关作品
（例：将夜2 → 'Os Normais 2 - A Noite Mais Maluca de Todas'），
却照样被套用。

现行机制：
  1. 所有关键词的候选汇总后统一排序，不再「先命中就锁死」
  2. 分数低于 _MIN_ACCEPT(0.45) 一律拒绝，宁可留空
  3. 年份差 3 年以上拒绝（有更合适的同年候选时改用次优）
  4. 0.45 ~ 0.80 之间先弹窗让用户确认，> 0.80 才自动套用
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

import app.gui as G
from app.gui import App
from app.models import (Candidate, MatchResult, P115Item, ParsedName,
                        PlanItem)


def make_plan(title, year, mt="series", aliases=None):
    match = MatchResult(title_zh=title, series_title=title, year=year,
                        confidence=0.9)
    db = Candidate(source="douban", title=title, original_title="",
                   year=year, sid="1", kind="tv")
    db.extra = {"aliases": aliases or []}
    match.douban = db
    return PlanItem(item=P115Item(fid="r", parent_id="0", name=title,
                                  is_dir=True),
                    media_type=mt,
                    parsed=ParsedName(raw=title, title=title, season=1),
                    match=match, title=title, year=year, category="tv")


def main() -> None:
    app = App(r"I:\实验\AutoRename115")
    app.withdraw()
    app.is_demo = True
    app.busy = False
    for _ in range(40):
        app.update()
        time.sleep(0.05)

    print(f"阈值 _MIN_ACCEPT={G._MIN_ACCEPT} "
          f"_CONFIDENT={G._CONFIDENT}")

    # 1) 阈值必须合理
    assert 0.3 <= G._MIN_ACCEPT <= 0.6, G._MIN_ACCEPT
    assert G._CONFIDENT > G._MIN_ACCEPT, (G._CONFIDENT, G._MIN_ACCEPT)

    # 2) 正常条目仍能搜到
    for title, year in (("将夜", 2018), ("青云志", 2016),
                        ("东离剑游记", 2016), ("生死一剑", 2017)):
        c = app._fetch_source_candidate(make_plan(title, year), "tmdb")
        assert c is not None, f"{title} 搜不到"
        print(f"{title:10s} → {c.title} ({c.year}) 分={c.score:.2f}")
        # 关键：可采用的候选必须过门槛
        assert c.score >= G._MIN_ACCEPT, (title, c.score)
        if c.year:
            assert abs(int(c.year) - year) <= 2, (title, c.year, year)

    # 3) 无关别名不能被抓回来
    c = app._fetch_source_candidate(
        make_plan("将夜 2", 2020, aliases=["Ever Night 2"]), "tmdb")
    print("将夜 2 →", (c.title, c.score) if c else "（已拒绝）")
    if c is not None:
        # 若返回，必须过门槛且年份接近
        assert c.score >= G._MIN_ACCEPT, c.score
        assert not c.year or abs(int(c.year) - 2020) <= 2, c.year

    # 4) 明显不存在的剧 → 无结果
    assert app._fetch_source_candidate(
        make_plan("某部不存在XYZ999", 2020), "tmdb") is None

    app.destroy()
    print("\nFORCED SEARCH ACCURACY OK")


if __name__ == "__main__":
    main()
