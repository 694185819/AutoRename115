# -*- coding: utf-8 -*-
"""统一跑全部测试：并行 + 每个测试独立进程 + 超时，且强制不弹任何模态框。

并行策略：
  - 纯逻辑测试（无 GUI）走多进程池，互不干扰
  - GUI 测试（Tk/Qt 窗口）串行跑，避免窗口焦点与剪贴板争用
这样总耗时从「逐个串行」降到「并行批次 + 少量串行」。
"""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
TIMEOUT = 300
# 并行度：太高会互相抢网络/磁盘，导致依赖真实联网的测试偶发失败
WORKERS = 3

# 快速模式（默认）：只跑覆盖核心行为的测试，约 30 秒。
# 需要联网、渲染窗口或构造大目录的测试放到全量模式。
#   python run_all.py          快速（默认）
#   python run_all.py --all    全量
#   python run_all.py 关键字   只跑名字含关键字的
FAST = (
    "test_parser", "test_naming_rule", "test_planner_cases",
    "test_subtitle_lang_marker", "test_spec_not_subtitle",
    "test_video_first_rule", "test_subs_only_folder",
    "test_subtitle_same_level", "test_multi_subtitle",
    "test_folder_no_season", "test_ep_between_cjk",
    "test_cjk_variants", "test_zero_special",
    "test_english_none_respected", "test_no_duplicate_english",
    "test_naming_panel_layout", "test_startup_reset",
    "test_plan_double_click",
    "test_preview_rename_only", "test_cache_clear",
    "test_settings_safety",
)

RUNNER = r'''
import sys, os
sys.path.insert(0, r"{here}")
import _bootstrap      # noqa: F401  拦截所有弹窗
mod = sys.argv[1]
import runpy
runpy.run_path(mod, run_name="__main__")
'''

# 需要真实窗口的测试：串行，避免互相抢占
GUI_HINTS = ("gui_", "qt_", "preview_layout", "multi_subtitle_ui",
             "note_box", "resize", "dragselect", "doubleclick")


def _is_gui(name: str) -> bool:
    return any(h in name for h in GUI_HINTS)


def run_one(name: str, env: dict) -> tuple[str, bool, float, list[str]]:
    path = os.path.join(HERE, name)
    code = RUNNER.format(here=HERE)
    t0 = time.time()
    try:
        proc = subprocess.run([PY, "-c", code, path], env=env,
                              capture_output=True, timeout=TIMEOUT,
                              encoding="utf-8", errors="replace")
        ok = proc.returncode == 0
        tail = (proc.stdout or "").strip().splitlines()[-3:]
    except subprocess.TimeoutExpired:
        ok = False
        tail = ["TIMEOUT"]
    return name, ok, time.time() - t0, tail


def main() -> None:
    tests = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    args = sys.argv[1:]
    run_all_mode = "--all" in args
    only = [a for a in args if not a.startswith("-")]
    if only:
        tests = [t for t in tests if any(o in t for o in only)]
    elif not run_all_mode:
        # 默认快速模式：只跑覆盖核心行为的测试，几十秒出结果
        wanted = {n if n.endswith(".py") else n + ".py" for n in FAST}
        tests = [t for t in tests if t in wanted]
        print(f"[快速模式] 只跑 {len(tests)} 个核心测试；"
              "要跑全部请加 --all\n")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["ARN115_TEST_NOPOPUP"] = "1"

    gui_tests = [t for t in tests if _is_gui(t)]
    logic_tests = [t for t in tests if not _is_gui(t)]

    results: list[tuple[str, bool, float, list[str]]] = []

    # ① 逻辑测试并行
    if logic_tests:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for res in pool.map(lambda n: run_one(n, env), logic_tests):
                results.append(res)

    # ② GUI 测试串行（窗口相关，避免争用）
    for name in gui_tests:
        results.append(run_one(name, env))

    results.sort(key=lambda r: r[0])
    passed = [r[0] for r in results if r[1]]
    failed = [(r[0], r[3]) for r in results if not r[1]]
    for name, ok, cost, tail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({cost:.1f}s)")
        if not ok:
            for line in tail:
                print("      ", line)

    print(f"\nTOTAL={len(results)} PASS={len(passed)} FAIL={len(failed)}")
    if failed:
        for f, _t in failed:
            print("  失败:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
