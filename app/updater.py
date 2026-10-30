# -*- coding: utf-8 -*-
"""GitHub Releases 检查与同路径覆盖更新。

便携版更新流程：
1. 从 GitHub 最新 Release 下载 AutoRename115-portable.zip；
2. 程序退出，临时 PowerShell 脚本等待旧进程结束后解压；
3. 覆盖 exe / _internal / 使用说明，保留 data 目录；
4. 自动重新启动程序。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from typing import Callable, Optional
from urllib.parse import quote, unquote

import requests

APP_VERSION = "0.30"
REPO_SLUG = "694185819/AutoRename115"
REPO_URL = f"https://github.com/{REPO_SLUG}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
ASSET_NAME = "AutoRename115-portable.zip"
USER_AGENT = f"AutoRename115/{APP_VERSION}"


def version_key(text: str) -> tuple[int, int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", str(text or ""))][:4]
    return tuple((nums + [0, 0, 0, 0])[:4])


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    return version_key(latest) > version_key(current)


def _latest_from_redirect(timeout: float = 15.0) -> dict:
    """API 限流时用 releases/latest 的跳转地址兜底。"""
    r = requests.get(
        f"{REPO_URL}/releases/latest",
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub 返回 HTTP {r.status_code}。")
    final = str(getattr(r, "url", "") or "")
    marker = "/releases/tag/"
    if marker not in final:
        raise RuntimeError("仓库还没有发布版本。")
    tag = unquote(final.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0])
    tag = tag.strip("/")
    if not tag:
        raise RuntimeError("无法识别最新版本号。")
    asset_url = (f"{REPO_URL}/releases/download/"
                 f"{quote(tag, safe='')}/{ASSET_NAME}")
    return {
        "tag": tag,
        "name": tag,
        "url": final,
        "notes": "",
        "asset": {
            "name": ASSET_NAME,
            "browser_download_url": asset_url,
            "size": 0,
        },
    }


def fetch_latest_release(timeout: float = 15.0) -> dict:
    """返回最新 Release 信息；API 不可用时用网页跳转兜底。"""
    api_error = ""
    try:
        r = requests.get(
            LATEST_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout)
        if r.status_code == 404:
            raise RuntimeError("仓库还没有发布版本。")
        if r.status_code >= 400:
            raise RuntimeError(
                "GitHub 接口暂时不可用（可能限流），请稍后再试。"
                if r.status_code == 403 else
                f"GitHub 返回 HTTP {r.status_code}。")
        try:
            data = r.json()
        except Exception:
            raise RuntimeError("GitHub 返回内容无法解析。")
        assets = data.get("assets") or []
        asset = next(
            (a for a in assets if a.get("name") == ASSET_NAME), None)
        if not asset:
            raise RuntimeError(f"最新版本没有找到 {ASSET_NAME}。")
        return {
            "tag": str(data.get("tag_name") or ""),
            "name": str(data.get("name") or data.get("tag_name") or ""),
            "url": str(data.get("html_url") or RELEASES_URL),
            "notes": str(data.get("body") or ""),
            "asset": asset,
        }
    except Exception as e:  # noqa: BLE001
        api_error = str(e)
    try:
        return _latest_from_redirect(timeout)
    except Exception as e:  # noqa: BLE001
        detail = api_error or str(e)
        raise RuntimeError(f"检查更新失败：{detail}")


def download_asset(asset: dict, dest_path: str,
                   progress: Optional[Callable[[int, int], None]] = None
                   ) -> str:
    """下载 Release 附件到 dest_path，返回本地路径。"""
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError("更新附件没有下载地址。")
    part = dest_path + ".part"
    total = int(asset.get("size") or 0)
    done = 0
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT},
                          stream=True, timeout=60) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"下载更新失败：HTTP {r.status_code}")
            if not total:
                try:
                    total = int(r.headers.get("Content-Length") or 0)
                except Exception:
                    total = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if total and done != total:
            raise RuntimeError("更新包下载不完整，请重试。")
        os.replace(part, dest_path)
        return dest_path
    except Exception:
        try:
            if os.path.exists(part):
                os.remove(part)
        except Exception:
            pass
        raise


def current_install_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def can_self_update(install_dir: str = "") -> bool:
    """只有打包后的 Windows 便携版才能安全覆盖当前目录。"""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    target = install_dir or current_install_dir()
    try:
        return os.path.isdir(target) and os.access(target, os.W_OK)
    except Exception:
        return False


_UPDATER_SCRIPT = r'''
param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][string]$ZipPath,
    [Parameter(Mandatory=$true)][int]$WaitPid
)
$ErrorActionPreference = "Stop"
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$dataDir = Join-Path $InstallDir "data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$logPath = Join-Path $dataDir "update.log"
function Log([string]$msg) {
    try {
        $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $msg
        $line | Out-File -FilePath $logPath -Append -Encoding utf8
    } catch { }
}
$stage = Join-Path $env:TEMP ("AutoRename115_update_" + [Guid]::NewGuid().ToString("N"))
$zipOk = $false
try {
    Log "开始更新：wait pid=$WaitPid"
    $deadline = (Get-Date).AddSeconds(60)
    while ($true) {
        $p = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        if ((Get-Date) -gt $deadline) { throw "等待旧进程退出超时" }
        Start-Sleep -Milliseconds 300
    }
    Start-Sleep -Milliseconds 500
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $stage)
    $exe = Get-ChildItem -LiteralPath $stage -Recurse -Filter "AutoRename115.exe" |
        Select-Object -First 1
    if (-not $exe) { throw "更新包内没有 AutoRename115.exe" }
    $src = $exe.Directory.FullName
    $skip = @("data", "cookies.json", "settings.json", "undo.json", "error.log")
    foreach ($item in Get-ChildItem -LiteralPath $src -Force) {
        if ($skip -contains $item.Name) { continue }
        $dest = Join-Path $InstallDir $item.Name
        if ($item.PSIsContainer) {
            if (-not (Test-Path -LiteralPath $dest)) {
                New-Item -ItemType Directory -Path $dest -Force | Out-Null
            }
            Get-ChildItem -LiteralPath $item.FullName -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
            }
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
        }
    }
    $zipOk = $true
    Log "覆盖完成，准备重启"
    $newExe = Join-Path $InstallDir "AutoRename115.exe"
    Start-Process -FilePath $newExe -WorkingDirectory $InstallDir
    Log "更新完成"
} catch {
    Log ("更新失败：" + $_.Exception.Message)
    try {
        $oldExe = Join-Path $InstallDir "AutoRename115.exe"
        if (Test-Path -LiteralPath $oldExe) {
            Start-Process -FilePath $oldExe -WorkingDirectory $InstallDir
        }
    } catch { }
} finally {
    try { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue } catch { }
    if ($zipOk) {
        try { Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue } catch { }
    }
}
'''


def launch_self_update(zip_path: str, install_dir: str = "") -> subprocess.Popen:
    """启动独立 PowerShell 更新器；调用方随后应立即退出当前程序。"""
    if os.name != "nt":
        raise RuntimeError("自动覆盖更新只支持 Windows。")
    target = os.path.abspath(install_dir or current_install_dir())
    if not can_self_update(target):
        raise RuntimeError("当前目录不可写，请把程序放在可写目录后再更新。")
    fd, script_path = tempfile.mkstemp(
        prefix="AutoRename115_update_", suffix=".ps1")
    os.close(fd)
    try:
        with open(script_path, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write(_UPDATER_SCRIPT)
        powershell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.exists(powershell):
            powershell = "powershell.exe"
        flags = 0
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        return subprocess.Popen(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script_path,
             "-InstallDir", target,
             "-ZipPath", os.path.abspath(zip_path),
             "-WaitPid", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True)
    except Exception:
        try:
            os.remove(script_path)
        except Exception:
            pass
        raise
