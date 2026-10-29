# -*- coding: utf-8 -*-
"""豆瓣分集名（浏览器内核方案）。

豆瓣分集页对普通 HTTP 客户端返回 JS 挑战页（server: dae），只靠 Cookie
拿不到内容；用本机已安装的 Chrome / Edge 通过 CDP 打开页面，就能读到
真实的“本集中文名”。

实现只用标准库（urllib + websocket 最小帧），不额外打包浏览器：
- 首次使用时启动一个独立配置的浏览器实例（无界面、独立 user-data-dir），
  监听本机端口；
- 打开分集页，等页面标题变成“第N集 …”，从标题里取集名；
- 批量时对每个集号重复上述步骤，结果缓存。
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Optional


BROWSER_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for p in BROWSER_PATHS:
        if p and os.path.isfile(p):
            return p
    return ""


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _pick_port(start: int = 9510, end: int = 9580) -> int:
    for p in range(start, end):
        if _port_free(p):
            return p
    return 0


class _WS:
    """极简 WebSocket 客户端（只用于 CDP 的文本消息）。"""

    def __init__(self, url: str):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection(
            (u.hostname or "127.0.0.1", u.port or 80), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (("?" + u.query) if u.query else "")
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手失败")
            buf += chunk
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0

    def send(self, text: str) -> None:
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("连接已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self) -> str:
        while True:
            b1, b2 = self._read(2)
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if masked else b""
            payload = self._read(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("连接被关闭")
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8", "ignore")

    def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        self._id += 1
        mid = self._id
        self.send(json.dumps({"id": mid, "method": method,
                              "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.recv())
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(method)

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


class DoubanBrowser:
    """按需启动的本机浏览器，用于读取豆瓣页面。

    默认无界面（headless），适合后台取分集名；
    `headless=False` 时开一个可见窗口，供用户手动登录豆瓣，
    登录态保存在 `user_dir` 里，后续读取条目页就能看到“关联站点”。
    """

    def __init__(self, log=None, user_dir: Optional[str] = None,
                 headless: bool = True):
        self.log = log or (lambda s: None)
        self.proc: Optional[subprocess.Popen] = None
        self.port = 0
        self.user_dir = user_dir or os.path.join(
            tempfile.gettempdir(), "AutoRename115_browser")
        self.headless = headless
        self.ws: Optional[_WS] = None
        self.tab_ws: Optional[_WS] = None

    # ---------------- 生命周期
    def start(self) -> bool:
        exe = find_browser()
        if not exe:
            self.log("没有找到 Chrome 或 Edge，无法读取豆瓣分集页。")
            return False
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.port = _pick_port()
        if not self.port:
            self.log("没有可用的本机端口，无法读取豆瓣分集页。")
            return False
        try:
            os.makedirs(self.user_dir, exist_ok=True)
        except Exception:
            self.user_dir = tempfile.mkdtemp(prefix="arn115_browser_")
        args = [exe, f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.user_dir}"]
        if self.headless:
            args += ["--headless=new", "--disable-gpu"]
        else:
            # 可见模式：用于让用户手动登录豆瓣，登录态会存进 user_dir。
            args += ["--window-size=1100,820", "--window-position=80,60"]
        args += ["--no-first-run", "--no-default-browser-check",
                 "about:blank"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) \
            if self.headless else 0
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     creationflags=flags)
        end = time.time() + 25
        while time.time() < end:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/json/version",
                        timeout=1) as r:
                    info = json.loads(r.read().decode())
                self.ws = _WS(info["webSocketDebuggerUrl"])
                self.log(f"浏览器内核已就绪：{os.path.basename(exe)}")
                return True
            except Exception:
                time.sleep(0.3)
        self.stop()
        return False

    def stop(self) -> None:
        for ws in (self.tab_ws, self.ws):
            try:
                ws.close() if ws else None
            except Exception:
                pass
        self.tab_ws = None
        self.ws = None
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None

    # ---------------- 取页面
    def _open(self, url: str) -> Optional[_WS]:
        if not self.start():
            return None
        try:
            self.ws.call("Target.createTarget", {"url": "about:blank"})
        except Exception:
            pass
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request("PUT", "/json/new?" + urllib.parse.quote(url, safe=""))
        raw = conn.getresponse().read().decode()
        conn.close()
        tab = json.loads(raw)
        return _WS(tab["webSocketDebuggerUrl"])

    def _title(self, tab: _WS) -> str:
        msg = tab.call("Runtime.evaluate",
                       {"expression": "document.title",
                        "returnByValue": True}, timeout=15)
        return str(((msg.get("result") or {}).get("result") or {})
                   .get("value") or "")

    def episode_title(self, sid: str, ep: int) -> str:
        """返回该集标题；失败返回空串。"""
        url = (f"https://movie.douban.com/subject/{sid}/episode/{ep}/")
        tab = self._open(url)
        if tab is None:
            return ""
        try:
            end = time.time() + 20
            title = ""
            while time.time() < end:
                title = self._title(tab)
                if re_ep_title(title):
                    break
                time.sleep(0.5)
            return episode_name_from_title(title)
        except Exception as e:      # noqa: BLE001
            self.log(f"读取豆瓣分集页失败（第{ep}集）：{e}")
            return ""
        finally:
            try:
                tab.close()
            except Exception:
                pass


def re_ep_title(title: str) -> bool:
    import re
    return bool(re.search(r"第\s*\d+\s*集", title or ""))


# ---------------------------------------------------------------- 登录与关联 ID
def open_login_window(app_dir: str, log=None) -> Optional[DoubanBrowser]:
    """开一个可见浏览器让用户登录豆瓣，登录态保存在程序目录下。

    返回已启动的浏览器对象（调用方负责 `stop()`），失败返回 None。
    """
    profile = os.path.join(app_dir, "data", "browser_profile")
    os.makedirs(profile, exist_ok=True)
    browser = DoubanBrowser(log=log, user_dir=profile, headless=False)
    if not browser.start():
        return None
    tab = browser._open("https://accounts.douban.com/passport/login")
    if tab is None:
        browser.stop()
        return None
    try:
        tab.close()
    except Exception:
        pass
    return browser


def _read_page_text(browser: "DoubanBrowser", url: str,
                    timeout: float = 25.0,
                    ready=lambda text: bool(text.strip())) -> str:
    """打开页面并等它真正渲染出内容，返回正文文本。"""
    tab = browser._open(url)
    if tab is None:
        return ""
    try:
        end = time.time() + timeout
        while time.time() < end:
            msg = tab.call("Runtime.evaluate",
                           {"expression": "document.body ? "
                                          "document.body.innerText : ''",
                            "returnByValue": True}, timeout=15)
            text = ((msg.get("result") or {}).get("result") or {}) \
                .get("value") or ""
            if ready(text):
                return str(text)
            time.sleep(0.6)
        return str(text or "")
    except Exception as e:      # noqa: BLE001
        browser.log(f"读取页面失败：{e}")
        return ""
    finally:
        try:
            tab.close()
        except Exception:
            pass


def is_logged_in(browser: "DoubanBrowser") -> bool:
    """检查浏览器当前是否已登录豆瓣。"""
    text = _read_page_text(browser, "https://www.douban.com/",
                           timeout=15)
    if not text:
        return False
    # 登录后首页不再显示“登录/注册”
    return "登录/注册" not in text[:400]


def related_ids_from_douban(browser: "DoubanBrowser",
                            sid: str) -> dict:
    """从豆瓣条目页读取关联的 IMDb / TMDB ID。

    登录状态下条目页有“关联站点”区，形如：
        IMDb: tt5370118   TMDB: 65844
    未登录时该区域不渲染，此时返回空 dict。
    """
    import re
    url = f"https://movie.douban.com/subject/{sid}/"
    text = _read_page_text(browser, url, timeout=25,
                           ready=lambda t: "IMDb" in t or "TMDB" in t
                           or "又名" in t)
    if not text:
        return {}
    out: dict[str, str] = {}
    m = re.search(r"IMDb:\s*(tt\d{6,9})", text)
    if m:
        out["imdb_id"] = m.group(1)
    m = re.search(r"TMDB:\s*(\d{2,9})", text)
    if m:
        out["tmdb_id"] = m.group(1)
    # 兜底：页面上任何 IMDb/TMDB 链接
    if "imdb_id" not in out:
        m = re.search(r"tt\d{6,9}", text)
        if m:
            out["imdb_id"] = m.group(0)
    return out


def episode_name_from_title(title: str) -> str:
    """从“灵笼 第一季 第1集 灯塔和光影会”里取“灯塔和光影会”。"""
    import re
    text = str(title or "").strip()
    m = re.search(r"第\s*\d+\s*集\s*[：:]?\s*(.*)$", text)
    if not m:
        return ""
    name = m.group(1).strip()
    name = re.sub(r"\s*[(（]豆瓣[)）]\s*$", "", name)
    return name.strip()


def fetch_douban_episode_titles(sid: str, season: int, log=None,
                                max_ep: int = 60) -> dict[int, str]:
    """用浏览器内核抓一季的豆瓣集名：{集号: 集名}。"""
    if not str(sid).isdigit():
        return {}
    browser = DoubanBrowser(log=log)
    out: dict[int, str] = {}
    try:
        if not browser.start():
            return {}
        for ep in range(1, max_ep + 1):
            if season > 1:
                # 多季条目：豆瓣分集页序号按条目自身编号
                pass
            name = browser.episode_title(sid, ep)
            if not name:
                break
            out[ep] = name
    finally:
        browser.stop()
    return out


def selftest() -> None:
    log = lambda s: print("[log]", s)   # noqa: E731
    print("browser:", find_browser())
    titles = fetch_douban_episode_titles("27121260", 1, log=log, max_ep=4)
    print("titles:", titles)


if __name__ == "__main__":
    selftest()
