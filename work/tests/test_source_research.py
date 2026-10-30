# -*- coding: utf-8 -*-
"""点击资料来源可重搜；TMDB 剧集/电影类型判错时能自动互换。

用户现象：「明明有秘钥，手动搜索经常是空的」。
真因不是缺 key，而是：
  1. TMDB 对中文长名收录少（豆瓣的「霹雳奇幻 生死一剑」搜不到，
     但「生死一剑」能搜到）
  2. TMDB 把剧集和电影分开收录，任务判成 series 时
     电影条目（东离剑游纪：生死一剑）就搜不到
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.models import (Candidate, MatchResult, P115Item, ParsedName,
                        PlanItem)


def make_plan(title, year, media_type="series"):
    match = MatchResult(title_zh=title, series_title=title, year=year,
                        confidence=0.9)
    db = Candidate(source="douban", title=title, original_title="",
                   year=year, sid="1", kind="tv")
    db.extra = {}
    match.douban = db
    return PlanItem(item=P115Item(fid="r", parent_id="0", name=title,
                                  is_dir=True),
                    media_type=media_type,
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

    # 1) 有 _fetch_source_candidate 方法
    assert hasattr(app, "_fetch_source_candidate"), "缺少重搜实现"
    assert hasattr(app, "_research_info_source"), "缺少重搜入口"

    # 2) movie/series 互换：生死一剑是 movie
    p = make_plan("生死一剑", 2017, "series")
    cand = app._fetch_source_candidate(p, "tmdb")
    print("生死一剑 →", cand.title if cand else None,
          "sid=", cand.sid if cand else None)
    assert cand is not None, "movie/series 互换未生效"
    assert "生死一剑" in cand.title, cand.title

    # 3) 正常条目仍能搜到
    p2 = make_plan("将夜", 2018)
    c2 = app._fetch_source_candidate(p2, "tmdb")
    print("将夜 →", c2.title if c2 else None)
    assert c2 is not None and "将夜" in c2.title, c2

    app.destroy()
    print("\nSOURCE RESEARCH OK")


if __name__ == "__main__":
    main()
