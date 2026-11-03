# -*- coding: utf-8 -*-
"""AutoRename115 一键发版。

用法（在项目根目录执行）：
    python 发版.py                  # 自动 +1 版本号，打包并发布
    python 发版.py 0.39             # 指定版本号
    python 发版.py --dry-run        # 只检查不发布
    python 发版.py --skip-tests     # 跳过回归（不推荐）
    python 发版.py --notes 文件.md  # 用文件内容作为 Release 说明

它会依次：
    1. 检查环境（GitHub token、打包工具）
    2. 跑快速回归（失败则中止）
    3. 改版本号 → PyInstaller 打包 → 压缩 zip
    4. 创建/更新 GitHub Release 并上传资产
    5. 更新 Release 说明和 README
    6. 通过 GitHub API 提交源码
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "dist", "AutoRename115")
ZIP = os.path.join(BASE, "AutoRename115-portable.zip")
OWNER, NAME = "694185819", "AutoRename115"
REF = "main"
PY = os.path.join(BASE, ".venv", "Scripts", "python.exe")
PYINSTALLER = os.path.join(BASE, ".venv", "Scripts", "pyinstaller.exe")
SPEC = os.path.join(BASE, "packaging", "AutoRename115.spec")
UPDATER = os.path.join(BASE, "app", "updater.py")

# 每次发版要提交到仓库的源码文件（相对路径）。
SOURCE_FILES = [
    "app/updater.py",
    "app/gui.py",
    "app/planner.py",
    "app/parser.py",
    "app/metadata.py",
    "app/naming_rule.py",
    "app/naming_panel.py",
    "app/models.py",
    "app/textnorm.py",
    "app/naming_template.py",
    # 许可协议必须随源码一起提交，否则仓库里看不到、等于没声明
    "LICENSE",
    "发版.py",
]


# ---------------------------------------------------------------- 工具
def run(cmd: list[str], cwd: str = BASE, check: bool = True,
        capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, check=check, text=True, encoding="utf-8",
        errors="replace",
        capture_output=capture)


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def warn(msg: str) -> None:
    print(f"  !   {msg}")


def die(msg: str) -> None:
    print(f"\n[中止] {msg}")
    sys.exit(1)


# ---------------------------------------------------------------- GitHub
def token() -> str:
    t = os.environ.get("GH_TOKEN", "").strip()
    if t:
        return t
    try:
        r = run(["gh", "auth", "token"])
        t = (r.stdout or "").strip()
        if t:
            return t
    except Exception:      # noqa: BLE001
        pass
    die("找不到 GitHub token。请先执行 `gh auth login`，"
        "或设置环境变量 GH_TOKEN。")


def api(path: str, method: str = "GET", data=None, tok: str = "",
        retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.github.com" + path, method=method)
            req.add_header("Authorization", "Bearer " + tok)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", f"AutoRename115/{get_version()}")
            body = None
            if data is not None:
                body = json.dumps(data).encode("utf-8")
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, body, timeout=300) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            if e.code == 422 and method == "POST":
                return None
            last = e
            warn(f"重试 {attempt + 1}/{retries}: {e}")
        except Exception as e:      # noqa: BLE001
            last = e
            warn(f"重试 {attempt + 1}/{retries}: {e}")
    raise last


def upload_asset(upload_url: str, payload: bytes, tok: str) -> dict:
    req = urllib.request.Request(
        upload_url.split("{")[0] + "?name=AutoRename115-portable.zip",
        data=payload, method="POST")
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"AutoRename115/{get_version()}")
    req.add_header("Content-Type", "application/zip")
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- 版本
def get_version() -> str:
    s = open(UPDATER, encoding="utf-8").read()
    m = re.search(r'APP_VERSION = "([^"]+)"', s)
    return m.group(1) if m else "0.0"


def bump_version() -> str:
    cur = get_version()
    parts = cur.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def set_version(v: str) -> None:
    s = open(UPDATER, encoding="utf-8").read()
    s = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{v}"', s)
    open(UPDATER, "w", encoding="utf-8", newline="").write(s)


# ---------------------------------------------------------------- 步骤
def check_env() -> str:
    step("检查环境")
    if not os.path.isfile(PY):
        die(f"找不到 Python：{PY}")
    ok(f"Python: {PY}")
    if not os.path.isfile(PYINSTALLER):
        die(f"找不到 PyInstaller：{PYINSTALLER}\n"
            "  请先运行「安装依赖.bat」")
    ok("PyInstaller 就绪")
    if not os.path.isfile(SPEC):
        die(f"找不到打包配置：{SPEC}")
    ok("打包配置就绪")
    tok = token()
    ok("GitHub token 就绪")
    return tok


def run_tests() -> None:
    step("跑快速回归")
    r = run([PY, os.path.join(BASE, "work", "tests", "run_all.py")],
            check=False)
    tail = (r.stdout or "").strip().splitlines()
    for line in tail[-8:]:
        print("  " + line)
    if r.returncode != 0:
        die("回归未通过，已中止发布。\n"
            "  确认要强制发布请加 --skip-tests")
    ok("回归通过")


def write_build_info(version: str) -> None:
    """把构建指纹写进 dist\\AutoRename115\\data\\build.json。"""
    import datetime
    import hashlib
    import json
    data_dir = os.path.join(DIST, "data")
    os.makedirs(data_dir, exist_ok=True)
    now = datetime.datetime.now()
    seed = f"{version}|{now.isoformat()}|{os.environ.get('COMPUTERNAME','')}"
    build_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    info = {
        "version": version,
        "build_id": build_id,
        "built_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "copyright": "(C) 2026 694185819. All rights reserved.",
    }
    path = os.path.join(data_dir, "build.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    ok(f"构建指纹 {build_id}（{info['built_at']}）")


def build(version: str) -> tuple[str, float]:
    step("打包")
    print("  正在运行 PyInstaller（约 1 分钟）…")
    r = run([PYINSTALLER, "--noconfirm", "--clean", SPEC,
             "--distpath", os.path.join(BASE, "dist"),
             "--workpath", os.path.join(BASE, "build")], check=False)
    out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for line in out[-2:]:
        print("  " + line)
    if not os.path.isdir(DIST):
        die("打包失败：没有生成 dist\\AutoRename115")

    # 写构建指纹：版本 + 唯一 ID + 编译时间。
    # 装进安装包的 data/build.json，供「关于」显示与事后溯源。
    write_build_info(version)

    print("  正在压缩…")
    import glob
    docs = glob.glob(os.path.join(BASE, "packaging", "*.txt"))
    tmp = ZIP + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for name in ("AutoRename115.exe", "_internal"):
            src = os.path.join(DIST, name)
            if os.path.isdir(src):
                for root, _d, files in os.walk(src):
                    for fn in files:
                        full = os.path.join(root, fn)
                        z.write(full, os.path.relpath(full, DIST))
            elif os.path.isfile(src):
                z.write(src, name)
        # 构建指纹必须进包，否则「关于」里读不到。
        # 只放 build.json 这一个文件：data 目录里可能有用户凭据，
        # 绝不能整目录打包（这是公开下载的安装包）。
        build_json = os.path.join(DIST, "data", "build.json")
        if os.path.isfile(build_json):
            z.write(build_json, "data/build.json")
        else:
            die("打包失败：没有生成 data/build.json（构建指纹）")
        if docs:
            z.write(docs[0], os.path.basename(docs[0]))
        for extra in ("演示模式.bat", "AutoRename115.ico"):
            p = os.path.join(BASE, "packaging", extra)
            if os.path.isfile(p):
                z.write(p, extra)
    os.replace(tmp, ZIP)

    # 打包后自检：确认构建指纹真的在压缩包里（否则「关于」显示不出来）。
    with zipfile.ZipFile(ZIP) as z:
        names = set(z.namelist())
    if "data/build.json" not in names:
        die("打包失败：压缩包里没有 data/build.json")
    # 凭据绝不能进公开安装包
    leaked = [n for n in names
              if os.path.basename(n) in ("settings.json", "cookies.json",
                                         "cookie.txt", "115cookie.txt")]
    if leaked:
        die(f"打包失败：安装包里混入了凭据文件 {leaked}")

    data = open(ZIP, "rb").read()
    digest = hashlib.sha256(data).hexdigest().upper()
    size = len(data) / 1024 / 1024
    with open(os.path.join(BASE, "SHA256.txt"), "w",
              encoding="utf-8") as f:
        f.write(f"AutoRename115-portable.zip\nVersion: {version}\n"
                f"SHA256: {digest}\nSize: {size:.2f} MB\n"
                f"Built: {time.strftime('%Y-%m-%d')}\n")
    ok(f"zip {size:.2f} MB | SHA256 {digest[:16]}…")
    return digest, size


def publish(version: str, digest: str, size: float, tok: str,
            notes: str) -> None:
    tag = f"v{version}"
    step(f"发布 {tag}")
    body = notes or f"## v{version}\n\n请在 Release 说明中补充本版改动。\n"
    rel = api(f"/repos/{OWNER}/{NAME}/releases", "POST", {
        "tag_name": tag,
        "name": f"{tag}",
        "body": body,
        "draft": False,
        "prerelease": False,
        "target_commitish": REF,
    }, tok)
    if rel is None:
        warn(f"{tag} 已存在，改为覆盖资产与说明")
        rel = api(f"/repos/{OWNER}/{NAME}/releases/tags/{tag}", tok=tok)
        for asset in rel.get("assets", []):
            api(f"/repos/{OWNER}/{NAME}/releases/assets/{asset['id']}",
                "DELETE", tok=tok)
        api(f"/repos/{OWNER}/{NAME}/releases/{rel['id']}", "PATCH",
            {"body": body, "name": f"{tag}"}, tok)
    ok(f"Release 就绪：{tag}")

    print("  正在上传资产…")
    info = upload_asset(rel["upload_url"], open(ZIP, "rb").read(), tok)
    ok(f"已上传 {info['name']}（{info['size']} 字节）")


def update_readme(version: str, tok: str, summary: str) -> None:
    step("更新 README")
    if not summary:
        warn("没有提供摘要（--notes），跳过 README 更新")
        return
    cur = api(f"/repos/{OWNER}/{NAME}/contents/README.md", tok=tok)
    txt = base64.b64decode(cur["content"]).decode("utf-8")
    txt = re.sub(r"当前版本：\*\*[\d.]+\*\*",
                 f"当前版本：**{version}**", txt)
    section = (f"## {version} 更新摘要\n\n{summary}\n\n---\n\n")
    marker = f"## {version} 更新摘要"
    if marker in txt:
        i = txt.find(marker)
        j = txt.find("\n---\n", i)
        txt = txt[:i] + section + (txt[j + 5:] if j > 0 else "")
    else:
        anchor = "## 历史更新摘要\n\n"
        txt = (txt.replace(anchor, anchor + section, 1)
               if anchor in txt else section + txt)

    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{NAME}/contents/README.md",
        method="PUT")
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"AutoRename115/{version}")
    req.add_header("Content-Type", "application/json")
    payload = json.dumps({
        "message": f"README: v{version}",
        "content": base64.b64encode(txt.encode("utf-8")).decode("ascii"),
        "sha": cur["sha"],
    }).encode("utf-8")
    with urllib.request.urlopen(req, payload, timeout=120) as r:
        res = json.loads(r.read().decode())
    ok(f"README 已更新 {res['commit']['sha'][:12]}")


def commit_source(version: str, tok: str) -> None:
    step("提交源码")
    head = api(f"/repos/{OWNER}/{NAME}/git/ref/heads/{REF}",
               tok=tok)["object"]["sha"]
    base = api(f"/repos/{OWNER}/{NAME}/git/commits/{head}",
               tok=tok)["tree"]["sha"]
    items = []
    for rel in SOURCE_FILES:
        full = os.path.join(BASE, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        data = open(full, "rb").read()
        sha = api(f"/repos/{OWNER}/{NAME}/git/blobs", "POST", {
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64"}, tok)["sha"]
        print(f"  M {rel}")
        items.append({"path": rel, "mode": "100644", "type": "blob",
                      "sha": sha})
    if not items:
        warn("没有找到要提交的源码文件")
        return
    tree = api(f"/repos/{OWNER}/{NAME}/git/trees", "POST", {
        "base_tree": base, "tree": items}, tok)["sha"]
    ident = {"name": OWNER,
             "email": f"{OWNER}@users.noreply.github.com"}
    commit = api(f"/repos/{OWNER}/{NAME}/git/commits", "POST", {
        "message": f"v{version}",
        "tree": tree, "parents": [head],
        "author": ident, "committer": ident,
    }, tok)["sha"]
    api(f"/repos/{OWNER}/{NAME}/git/refs/heads/{REF}", "PATCH",
        {"sha": commit, "force": False}, tok)
    ok(f"已提交 {commit[:12]}")


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser(
        description="AutoRename115 一键发版")
    ap.add_argument("version", nargs="?",
                    help="版本号，省略则自动 +1")
    ap.add_argument("--dry-run", action="store_true",
                    help="只检查，不打包不发布")
    ap.add_argument("--skip-tests", action="store_true",
                    help="跳过回归测试")
    ap.add_argument("--notes", help="Release 说明的 Markdown 文件路径")
    args = ap.parse_args()

    cur = get_version()
    version = args.version or bump_version()
    print(f"当前版本 {cur} → 目标版本 {version}")

    tok = check_env()

    if not args.skip_tests:
        run_tests()
    else:
        warn("已跳过回归测试")

    if args.dry_run:
        step("演练模式")
        ok("环境检查通过，未打包、未发布")
        return

    notes = ""
    if args.notes and os.path.isfile(args.notes):
        notes = open(args.notes, encoding="utf-8").read()
    summary = notes

    set_version(version)
    ok(f"版本号已改为 {version}")

    digest, size = build(version)
    publish(version, digest, size, tok, notes)
    update_readme(version, tok, summary)
    commit_source(version, tok)

    step("完成")
    print(f"  版本   {version}")
    print(f"  SHA256 {digest}")
    print(f"  体积   {size:.2f} MB")
    print(f"  链接   https://github.com/{OWNER}/{NAME}/releases/tag/v{version}")


if __name__ == "__main__":
    main()
