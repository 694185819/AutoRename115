# -*- coding: utf-8 -*-
"""再点一次已选中的资料来源 → 真正进入搜索状态并出结果。

用户反馈：悬停提示写着「再点一次已选中的来源会重新搜索一次」，
但实际点了没有反应（只是单选按钮看起来选中了）。

根因三处：
  1. ttk.Radiobutton 点已选中项时不保证触发 command
  2. _research_hook 只赋值、没有在消息分发里调用 → finish 永不执行，
     任务一直卡在 busy
  3. 重搜前先置 busy，导致 run_async 认为「上一个任务还在执行」直接跳过
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.models import (Candidate, MatchResult, P115Item, ParsedName,
                        PlanItem)


def pump(app, sec=20, until=None):
    end = time.time() + sec
    while time.time() < end:
        try:
            app.update()
        except Exception:      # noqa: BLE001
            break
        if until is not None and until():
            return True
        time.sleep(0.05)
    return False


def make_plan():
    match = MatchResult(title_zh="生死一剑", series_title="生死一剑",
                        year=2017, confidence=0.9)
    db = Candidate(source="douban", title="生死一剑", original_title="",
                   year=2017, sid="1", kind="tv")
    db.extra = {}
    match.douban = db
    return PlanItem(item=P115Item(fid="r", parent_id="0", name="生死一剑",
                                  is_dir=True),
                    media_type="series",
                    parsed=ParsedName(raw="生死一剑", title="生死一剑",
                                      season=1),
                    match=match, title="生死一剑", year=2017,
                    category="tv")


def main() -> None:
    app = App(r"I:\实验\AutoRename115")
    app.withdraw()
    app.is_demo = True
    app.busy = False
    pump(app, 3)

    # 消息分发必须注册 research_source
    assert "research_source" in app.KIND_HANDLERS, "未注册消息类型"
    assert hasattr(app, "_on_research_source"), "缺少消息处理方法"
    assert hasattr(app, "_on_info_source_clicked"), "缺少点击处理"

    p = make_plan()
    app.plans = [p]
    app.detail_plan = p
    app.info_source_var.set("tmdb")
    app._load_info()
    pump(app, 2)

    # 再点一次已选中的 TMDB
    app._on_info_source_clicked("tmdb")
    pump(app, 0.4)
    status = app.info_status.cget("text")
    print("状态栏:", repr(status), "| busy:", app.busy)
    assert "正在重新搜索" in status, status
    assert app.busy is True, "没有进入搜索忙碌状态"

    ok = pump(app, 40, until=lambda: not app.busy)
    print("搜索完成:", ok)
    assert ok, "搜索没有结束（finish 未回调）"
    assert p.match.tmdb is not None, "重搜没有取到 TMDB 条目"
    print("取回:", p.match.tmdb.title, "sid=", p.match.tmdb.sid)
    assert "生死一剑" in p.match.tmdb.title, p.match.tmdb.title

    # 点击未选中的来源只切换
    app._on_info_source_clicked("imdb")
    pump(app, 2)
    assert app.info_source_var.get() == "imdb", app.info_source_var.get()

    app.destroy()
    print("\nRESEARCH FLOW OK")


if __name__ == "__main__":
    main()
