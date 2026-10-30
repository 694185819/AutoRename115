# -*- coding: utf-8 -*-
"""统一跑全部测试：每个测试独立进程 + 超时，且强制不弹任何模态框。

弹窗会阻塞测试直到人工点掉（用户反馈过卡住）。
这里通过 Python 启动钩子 (_pth 风格) 注入 sitecustomize 不方便，
改用环境变量 ARN115_TEST_NOPOPUP=1，由各 App/窗口创建时感知。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
TIMEOUT = 300

RUNNER = r'''
import sys, os
sys.path.insert(0, r"{here}")
import _bootstrap      # noqa: F401  拦截所有弹窗
mod = sys.argv[1]
import runpy
runpy.run_path(mod, run_name="__main__")
'''


def main() -> None:
    tests = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    if only:
        tests = [t for t in tests if any(o in t for o in only)]

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["ARN115_TEST_NOPOPUP"] = "1"
    # 不用 QT_QPA_PLATFORM=offscreen：Tk 窗口在该模式下行为不同，
    # 会让本可运行的 Tk 测试失败。弹窗已由 _bootstrap 拦截。

    passed, failed = [], []
    for name in tests:
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
        cost = time.time() - t0
        (passed if ok else failed).append(name)
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({cost:.1f}s)")
        if not ok:
            for line in tail:
                print("      ", line)

    print(f"\nTOTAL={len(tests)} PASS={len(passed)} FAIL={len(failed)}")
    if failed:
        for f in failed:
            print("  失败:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
