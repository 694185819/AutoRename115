# -*- coding: utf-8 -*-
"""启动时清残留状态；恢复任务后不卡 busy 且会刷新目录。

用户现象（反复出现）：
  右边显示上次任务，左边目录空白；日志最后一行是
  「上一个任务还在执行，本次操作已跳过」。

两处根因：
  1. `_restore_plans` 在 run_async 之前先 `_set_busy(True)`，
     run_async 看到 busy 为真直接跳过 → 核对任务没跑，
     目录也永远不刷新，界面卡在 busy。
  2. 启动时若残留 busy 或队列旧消息，后续所有操作都会被跳过。
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


def test_startup_resets_busy():
    """启动重置要清掉 busy 和队列残留。"""
    tmp = tempfile.mkdtemp(prefix="arn115_reset_test_")
    app = App(tmp)
    app.withdraw()
    app.is_demo = True
    app.busy = False
    pump(app, 2, until=lambda: not app.busy)

    app.busy = True
    app.q.put(("log", "旧消息"))
    app._reset_busy_state()

    print("busy:", app.busy, "| 队列:", app.q.qsize())
    assert app.busy is False
    assert app.q.qsize() == 0
    app.destroy()


def test_restore_not_stuck():
    """恢复任务后不能卡在 busy，且要刷新目录。"""
    tmp = tempfile.mkdtemp(prefix="arn115_restore_test2_")
    app = App(tmp)
    app.withdraw()
    app.is_demo = True
    app.busy = False
    pump(app, 2, until=lambda: not app.busy)

    calls = []
    original = app.refresh
    app.refresh = lambda *a, **k: (calls.append(1), original(*a, **k))[1]

    app._pending_dir_refresh = True
    app._on_plans_verified((True, ""))
    pump(app, 6, until=lambda: not app.busy)

    print("refresh:", len(calls), "| busy:", app.busy)
    assert calls, "没有刷新目录"
    assert app.busy is False, "卡在 busy"
    app.destroy()


def test_restore_plans_does_not_preset_busy():
    """_restore_plans 不能提前置 busy（否则 run_async 被拒）。"""
    import inspect
    src = inspect.getsource(App._restore_plans)
    # 忽略注释行，只看真实代码
    code_lines = [ln for ln in src.splitlines()
                  if not ln.strip().startswith("#")]
    body = "\n".join(code_lines)
    i_async = body.find("run_async(")
    i_busy = body.find("_set_busy(True)")
    assert i_async > 0, "没有 run_async 调用"
    assert not (0 <= i_busy < i_async), \
        "_restore_plans 在 run_async 之前调用了 _set_busy(True)"
    print("_restore_plans 未提前置 busy ✅")


def main():
    test_startup_resets_busy()
    test_restore_not_stuck()
    test_restore_plans_does_not_preset_busy()
    print("\nSTARTUP RESET / RESTORE OK")


if __name__ == "__main__":
    main()
