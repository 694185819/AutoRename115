# -*- coding: utf-8 -*-
"""恢复上次任务后，左侧目录必须跟着刷出来。

用户现象：右边有任务时退出，再打开软件，右边显示上次任务，
左边却是空的；即便右键删除任务，左边网盘内容也刷不出来。

根因：`_restore_plans()` 成功后直接 `return`，跳过了
`self.refresh()`，左侧目录树从未加载。
"""
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App


def pump(app, sec=6, until=None):
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


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="arn115_restore_test_")
    app = App(tmp)
    app.withdraw()
    app.is_demo = True
    app.busy = False
    pump(app, 3, until=lambda: not app.busy)

    calls = []
    original = app.refresh
    app.refresh = lambda *a, **k: (calls.append(1), original(*a, **k))[1]

    # 模拟「恢复任务成功」→ 核对完成
    app._pending_dir_refresh = True
    assert app._pending_dir_refresh is True
    app._on_plans_verified((True, ""))
    pump(app, 6, until=lambda: not app.busy)

    print("refresh 调用次数:", len(calls))
    print("_pending_dir_refresh:", app._pending_dir_refresh)
    assert app._pending_dir_refresh is False, "标记未被消费"
    assert calls, "恢复任务后没有刷新左侧目录"

    # 缓存作废的分支同样要刷新
    calls.clear()
    app._pending_dir_refresh = True
    app._on_plans_verified((False, "测试：文件已不在"))
    pump(app, 6, until=lambda: not app.busy)
    print("作废分支 refresh 次数:", len(calls))
    assert calls, "缓存作废后也没有刷新左侧目录"

    app.destroy()
    print("\nRESTORE REFRESHES DIRECTORY OK")


if __name__ == "__main__":
    main()
