# -*- coding: utf-8 -*-
"""115 网盘 Web API 客户端：扫码登录、列目录、批量重命名、撤销日志。

只调用与网页版相同的接口：
- 二维码：qrcodeapi.115.com / passportapi.115.com
- 文件：webapi.115.com/files、/files/batch_rename
- NFO/图片：上传到指定目录；清空时移到 115 回收站

默认只重命名；上传/删除只在用户明确点击 NFO 操作并确认后执行。
"""
from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from .models import P115Item, RenameOp, VIDEO_EXTS, SUB_EXTS, AUDIO_EXTS

WEBAPI = "https://webapi.115.com"
APPAPI = "https://proapi.115.com"
APP_LIST_VERSION = "2.0"
APP_LOGIN_APPS = ("ios", "android", "wechatmini", "alipaymini")
QRCODE_API = "https://qrcodeapi.115.com"
PASSPORT_API = "https://passportapi.115.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 保守的 115 请求节奏：宁可慢一点，也不要触发风控/被踢下线。
READ_INTERVAL = 0.45       # 普通读取（列目录、查详情）
WRITE_INTERVAL = 1.15      # 批量改名、删除等写操作
UPLOAD_INTERVAL = 1.30     # 每个 NFO/图片上传初始化
BATCH_CHUNK = 10           # 每次 batch_rename 最多 10 项（原 20）
DELETE_CHUNK = 20          # 每次移入回收站最多 20 项（原 50）
BATCH_PAUSE = (1.0, 1.8)   # 两个写批次之间的随机停顿
RISK_COOLDOWN = 60         # 触发风控后的冷却秒数
RISK_HINTS = (
    "频繁", "过快", "风控", "风险", "验证码", "验证", "限制",
    "稍后再试", "稍后重试", "too many", "rate limit", "captcha",
)
AUTH_HINTS = ("登录已失效", "未登录", "请登录", "重新登录",
              "unauthorized", "invalid token")


class P115Error(Exception):
    pass


class P115AuthError(P115Error):
    pass


class P115RateLimitError(P115Error):
    """115 提示请求过于频繁/触发风控，或正处于冷却期。"""


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", name or "")]


@dataclass
class RenameResult:
    fid: str
    old_name: str
    new_name: str
    ok: bool
    message: str = ""


class CookieStore:
    """把 Cookie 同时保存到程序目录和 %APPDATA%，换 EXE/解压新版本后仍能自动登录。

    读取时选 saved_at 最新的那份，避免旧目录里的过期 Cookie 覆盖新登录。
    """

    def __init__(self, data_dir: str, use_roaming: bool = True):
        self.local_path = os.path.join(data_dir, "cookies.json")
        self.roaming_path = ""
        if use_roaming:
            appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
            if appdata:
                self.roaming_path = os.path.join(
                    appdata, "AutoRename115", "cookies.json")
        self.path = self.local_path
        self.last_path = ""

    def paths(self) -> list[str]:
        out = [self.local_path]
        if self.roaming_path and self.roaming_path != self.local_path:
            out.append(self.roaming_path)
        return out

    def load_with_app(self) -> tuple[dict, str, float]:
        """返回（cookie, 登录设备, 保存时间）。"""
        best_cookie: dict = {}
        best_app = ""
        best_time = -1.0
        for path in self.paths():
            try:
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                cookie = data.get("cookie")
                if not isinstance(cookie, dict) or not cookie:
                    continue
                saved_at = float(data.get("saved_at") or 0)
                if saved_at <= 0:
                    saved_at = os.path.getmtime(path)
                if saved_at > best_time:
                    best_time = saved_at
                    best_cookie = cookie
                    best_app = str(data.get("app") or "")
                    self.last_path = path
            except Exception:
                continue
        return ({str(k): str(v) for k, v in best_cookie.items()},
                best_app, best_time)

    def load(self) -> dict:
        return self.load_with_app()[0]

    def save(self, cookie: dict, app: str = "web") -> None:
        payload = {"cookie": cookie, "saved_at": int(time.time()),
                   "app": app}
        for path in self.paths():
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
            except Exception:
                continue

    def clear(self) -> None:
        for path in self.paths():
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except Exception:
                pass


def parse_cookie_text(text: str) -> dict:
    """支持浏览器复制出来的 `k=v; k=v`，或扫码接口返回的 JSON。"""
    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("cookie", "cookies"):
                    if isinstance(data.get(key), dict):
                        return {str(k): str(v) for k, v in data[key].items()}
                if isinstance(data.get("data"), dict):
                    for key in ("cookie", "cookies"):
                        if isinstance(data["data"].get(key), dict):
                            return {str(k): str(v)
                                    for k, v in data["data"][key].items()}
                return {str(k): str(v) for k, v in data.items()
                        if isinstance(v, (str, int))}
        except Exception:
            pass
    out = {}
    for part in re.split(r"[;\n]", text):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip().strip('"')
            if k:
                out[k] = v
    return out


class P115Client:
    def __init__(self, data_dir: str,
                 log: Optional[Callable[[str], None]] = None,
                 use_roaming: bool = True):
        self.data_dir = data_dir
        self.log = log or (lambda s: None)
        self.cookie_store = CookieStore(data_dir, use_roaming=use_roaming)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
        })
        self._logged_in: Optional[bool] = None
        self._last_request = 0.0
        self._last_auth_error = ""
        self._risk_until = 0.0
        self._risk_hits = 0
        self._read_interval = READ_INTERVAL
        self._write_interval = WRITE_INTERVAL
        self._upload_interval = UPLOAD_INTERVAL
        self._upload_uid = ""
        self.log(
            f"115 保守请求节奏：读取 {READ_INTERVAL:.2f}s，"
            f"写入 {WRITE_INTERVAL:.2f}s，每批 {BATCH_CHUNK} 项，"
            f"上传 {UPLOAD_INTERVAL:.2f}s/个；触发风控会暂停 "
            f"{RISK_COOLDOWN}s。")
        cookie, app, _ = self.cookie_store.load_with_app()
        self.login_app = app or "web"
        if cookie:
            self.set_cookies(cookie)

    # ------------------------------------------------------------ 登录态
    def _reset_pace(self) -> None:
        self._risk_until = 0.0
        self._risk_hits = 0
        self._read_interval = READ_INTERVAL
        self._write_interval = WRITE_INTERVAL
        self._upload_interval = UPLOAD_INTERVAL

    def set_cookies(self, cookie: dict) -> None:
        self.session.cookies.clear()
        for k, v in cookie.items():
            self.session.cookies.set(str(k), str(v), domain=".115.com")
        self._logged_in = None
        self._upload_uid = ""
        self._reset_pace()

    def set_cookie_text(self, text: str) -> None:
        cookie = parse_cookie_text(text)
        if not cookie:
            raise P115Error("没有识别到 Cookie，请确认复制了完整的 UID/CID/SEID/KID。")
        self.session.cookies.clear()
        for k, v in cookie.items():
            self.session.cookies.set(str(k), str(v), domain=".115.com")
        self.cookie_store.save(cookie, app="web")
        self.login_app = "web"
        self._logged_in = None
        self._upload_uid = ""
        self._reset_pace()

    def cookie_dict(self) -> dict:
        out = {}
        for c in self.session.cookies:
            if "115.com" in (c.domain or ""):
                out[c.name] = c.value
        return out

    def logout(self) -> None:
        self.session.cookies.clear()
        self.cookie_store.clear()
        self._logged_in = False
        self._upload_uid = ""
        self._reset_pace()

    def _throttle(self, seconds: Optional[float] = None,
                  write: bool = False) -> None:
        """请求间隔 + 风控冷却。冷却期内不再发请求，直接给出明确错误。"""
        now = time.time()
        if self._risk_until > now:
            remain = int(self._risk_until - now) + 1
            raise P115RateLimitError(
                f"115 风控/限流冷却中，请约 {remain} 秒后再试。\n"
                "这期间程序不会继续请求 115，避免被踢下线。")
        interval = (self._write_interval if write else self._read_interval) \
            if seconds is None else seconds
        # 加一点随机抖动，避免所有请求都卡在完全相同的节奏上
        wait = self._last_request + interval + random.uniform(0, 0.20) - now
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def risk_cooldown_remaining(self) -> int:
        return max(0, int(self._risk_until - time.time()))

    def _looks_risk(self, text: str) -> bool:
        low = (text or "").casefold()
        return any(h in low for h in RISK_HINTS)

    def _looks_auth(self, text: str) -> bool:
        low = (text or "").casefold()
        return any(h in low for h in AUTH_HINTS)

    @staticmethod
    def _retry_after(resp) -> Optional[float]:
        try:
            value = resp.headers.get("Retry-After")
            return float(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _risk_detail(status: int, text: str = "") -> str:
        """风控提示里不要直接塞 WAF/JSON 解析错误。"""
        if status == 405:
            return "HTTP 405（接口被拦截，疑似风控）"
        detail = (text or "").strip()
        if detail.startswith("<") or "Expecting value" in detail:
            return "接口返回了非正常内容（疑似风控拦截）"
        return detail[:200]

    def _risk_error(self, detail: str,
                    retry_after: Optional[float] = None) -> P115RateLimitError:
        self._risk_hits += 1
        base = RISK_COOLDOWN * (1.5 ** min(self._risk_hits - 1, 2))
        cooldown = retry_after if retry_after and retry_after > 0 else base
        cooldown = min(max(int(cooldown), 30), 180)
        self._risk_until = max(self._risk_until, time.time() + cooldown)
        # 同一会话里反复触发风控时，后续请求自动再放慢。
        factor = 1.2 ** min(self._risk_hits, 3)
        self._read_interval = min(1.5, READ_INTERVAL * factor)
        self._write_interval = min(3.0, WRITE_INTERVAL * factor)
        self._upload_interval = min(3.0, UPLOAD_INTERVAL * factor)
        msg = (
            f"115 提示请求过于频繁或触发风控：{detail or '请稍后再试'}\n"
            f"已暂停约 {cooldown} 秒，期间不会继续请求 115。\n"
            f"后续请求已自动放慢（读取 {self._read_interval:.2f}s / "
            f"写入 {self._write_interval:.2f}s / "
            f"上传 {self._upload_interval:.2f}s）。\n"
            "请稍后再试；如果反复被踢下线，请在登录窗口换一个"
            "设备类型重新扫码（例如 ios ↔ web）。")
        self.log(msg)
        return P115RateLimitError(msg)

    @staticmethod
    def _auth_message(detail: str) -> str:
        return (
            f"115 登录状态已失效或被其他设备踢下线：{detail}\n"
            "115 同一设备类型会互相踢下线。请在登录窗口换一个"
            "设备类型重新扫码（例如 ios ↔ web），再继续操作。")

    def _batch_pause(self) -> None:
        """两个写批次之间停顿，降低连续触发风控的概率。"""
        self._throttle(write=True)
        time.sleep(random.uniform(*BATCH_PAUSE))

    def _app_name(self) -> str:
        app = (getattr(self, "login_app", "") or "web").lower()
        return app if app in APP_LOGIN_APPS else "web"

    def _is_app_login(self) -> bool:
        return self._app_name() != "web"

    def _app_list(self, cid: str, offset: int = 0,
                  limit: int = 200) -> dict:
        app = self._app_name()
        url = f"{APPAPI}/{app}/{APP_LIST_VERSION}/ufile/files"
        self._throttle()
        try:
            r = self.session.get(url, params={
                "cid": cid, "limit": limit, "offset": offset,
                "show_dir": 1, "aid": 1, "cur": 1,
                "count_folders": 1, "record_open_time": 1,
            }, timeout=30)
        except Exception as e:
            raise P115Error(f"115 应用接口请求失败：{e}")
        status = int(getattr(r, "status_code", 0) or 0)
        text = (getattr(r, "text", "") or "")[:500]
        if status == 401:
            self._logged_in = False
            raise P115AuthError(self._auth_message(text or "HTTP 401"))
        if status in (403, 405, 429):
            raise self._risk_error(
                self._risk_detail(status, text), self._retry_after(r))
        try:
            data = r.json()
        except Exception as e:
            if self._looks_risk(text):
                raise self._risk_error(
                    self._risk_detail(status, text), self._retry_after(r))
            raise P115Error(f"115 应用接口返回异常（HTTP {status}）：{e}")
        if isinstance(data, dict) and data.get("state") is False:
            errno = data.get("errno") or data.get("errNo")
            msg = data.get("error") or data.get("message") or text[:300]
            if self._looks_risk(msg):
                raise self._risk_error(msg, self._retry_after(r))
            if str(errno) in ("99", "401", "990001", "990009") or \
                    self._looks_auth(msg):
                self._logged_in = False
                raise P115AuthError(self._auth_message(msg))
            # 列根目录还返回 state=false，多数也是登录态/设备会话问题。
            raise P115AuthError(f"115 应用接口错误：{msg}")
        return data

    def is_logged_in(self, force: bool = False) -> bool:
        if self._logged_in is not None and not force:
            return self._logged_in
        if not self.cookie_dict():
            self._logged_in = False
            return False

        def parse_check(resp) -> dict:
            status = int(getattr(resp, "status_code", 0) or 0)
            text = (getattr(resp, "text", "") or "")[:500]
            if status == 401:
                raise P115AuthError(self._auth_message(text or "HTTP 401"))
            if status in (403, 405, 429):
                raise self._risk_error(
                    self._risk_detail(status, text), self._retry_after(resp))
            try:
                data = resp.json()
            except Exception:
                if self._looks_risk(text):
                    raise self._risk_error(
                        self._risk_detail(status, text), self._retry_after(resp))
                raise P115Error(
                    f"115 登录检查返回异常（HTTP {status}）：{text[:200]}")
            if isinstance(data, dict) and data.get("state") is False:
                msg = (data.get("error") or data.get("message") or
                       text[:300])
                if self._looks_risk(msg):
                    raise self._risk_error(msg, self._retry_after(resp))
                raise P115AuthError(self._auth_message(msg or "未登录"))
            return data

        if self._is_app_login():
            try:
                data = self._app_list("0", 0, 1)
                self._logged_in = bool(data.get("state", True))
                self._last_auth_error = "" if self._logged_in else \
                    "应用接口未返回登录态"
            except P115RateLimitError:
                raise
            except P115AuthError as e:
                self._last_auth_error = str(e)
                self._logged_in = False
            except Exception as e:
                # 网络/服务异常不能当成登录失效，避免误触发重新扫码。
                self._last_auth_error = str(e)
                if self._logged_in is None:
                    self._logged_in = bool(self.cookie_dict())
            return bool(self._logged_in)
        try:
            self._throttle()
            # /user/info 未登录时也会返回 JSON；/files 未登录时容易被 WAF 返回 405
            r = self.session.get(WEBAPI + "/user/info", timeout=20)
            parse_check(r)
            self._logged_in = True
            self._last_auth_error = ""
        except P115RateLimitError:
            raise
        except P115AuthError as e:
            self._last_auth_error = str(e)
            self._logged_in = False
        except Exception:
            try:
                self._throttle()
                r = self.session.get(WEBAPI + "/files", params={
                    "aid": 1, "cid": 0, "limit": 1, "offset": 0,
                    "show_dir": 1, "format": "json"}, timeout=20)
                parse_check(r)
                self._logged_in = True
                self._last_auth_error = ""
            except P115RateLimitError:
                raise
            except P115AuthError as e:
                self._last_auth_error = str(e)
                self._logged_in = False
            except Exception as e:
                self._last_auth_error = str(e)
                if self._logged_in is None:
                    self._logged_in = bool(self.cookie_dict())
        return bool(self._logged_in)

    # ------------------------------------------------------------ 扫码
    def qr_token(self) -> dict:
        r = self.session.get(QRCODE_API + "/api/1.0/web/1.0/token/",
                             timeout=30)
        data = r.json()
        if not data.get("state") or not isinstance(data.get("data"), dict):
            raise P115Error("获取二维码失败：" + str(data.get("message", r.text[:200])))
        return data["data"]

    def qr_image(self, uid: str) -> bytes:
        r = self.session.get(QRCODE_API + "/api/1.0/web/1.0/qrcode",
                             params={"uid": uid}, timeout=30)
        r.raise_for_status()
        return r.content

    def qr_status(self, token: dict) -> int:
        r = self.session.get(QRCODE_API + "/get/status/", params={
            "uid": token.get("uid", ""),
            "time": token.get("time", ""),
            "sign": token.get("sign", ""),
        }, timeout=45)
        data = r.json()
        payload = data.get("data") or {}
        # 未扫码时 data 可能是空对象
        return _int(payload.get("status"), 0)

    def qr_login(self, uid: str, app: str = "ios") -> bool:
        app = (app or "ios").strip().lower()
        if app not in ("web", "android", "ios", "wechatmini", "alipaymini"):
            app = "ios"
        r = self.session.post(
            PASSPORT_API + f"/app/1.0/{app}/1.0/login/qrcode/",
            data={"app": app, "account": uid}, timeout=30)
        data = r.json()
        cookie = {}
        payload = data.get("data") or {}
        raw_cookie = payload.get("cookie")
        if isinstance(raw_cookie, dict):
            cookie = raw_cookie
        elif isinstance(raw_cookie, str):
            cookie = parse_cookie_text(raw_cookie)
        if not cookie and isinstance(payload, dict):
            # 有些返回把 UID/CID/SEID/KID 直接放在 data 里
            cookie = {k: v for k, v in payload.items()
                      if str(k).upper() in ("UID", "CID", "SEID", "KID")}
        if not cookie:
            # 最后从 Set-Cookie 会话里收集
            cookie = self.cookie_dict()
        if not cookie:
            raise P115AuthError("扫码已确认，但没取到登录 Cookie：" +
                                str(data.get("message", r.text[:300])))
        cookie = {str(k): str(v) for k, v in cookie.items()}
        for k, v in cookie.items():
            self.session.cookies.set(k, v, domain=".115.com")
        self.cookie_store.save(cookie, app=app)
        self.login_app = app
        self._logged_in = None
        self._upload_uid = ""
        self._reset_pace()
        if not self.is_logged_in(force=True):
            detail = (self._last_auth_error or "").strip()
            raise P115AuthError(
                f"扫码已确认，但 {app} 设备的 Cookie 未被 115 接口接受。\n"
                + (f"接口返回：{detail}\n" if detail else "") +
                "请在登录窗口换一个设备（例如 web 或 android）再试。")
        return True

    # ------------------------------------------------------------ 文件
    def _request(self, method: str, path: str,
                 base_url: str = WEBAPI, **kwargs) -> dict:
        method_up = method.upper()
        write = method_up != "GET"
        attempts = 1 if write else 2
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            self._throttle(write=write)
            url = base_url + path
            r = None
            try:
                r = self.session.request(method, url, timeout=30, **kwargs)
            except Exception as e:
                last_error = P115Error(f"115 请求失败（网络异常）：{e}")
                if not write and attempt + 1 < attempts:
                    self.log("115 读取失败，稍后自动重试一次…")
                    time.sleep(0.9 + attempt * 0.8)
                    continue
                raise last_error
            status = int(getattr(r, "status_code", 0) or 0)
            text = (getattr(r, "text", "") or "")[:500]
            if status == 401:
                self._logged_in = False
                raise P115AuthError(
                    self._auth_message(text or "HTTP 401"))
            if status in (403, 405, 429):
                raise self._risk_error(
                    self._risk_detail(status, text), self._retry_after(r))
            try:
                data = r.json()
            except Exception:
                # 只有解析失败（例如 WAF 返回 HTML）才按文本判断风控，
                # 不能拿正常 JSON 里的片名（可能含“限制/验证”）误判。
                if self._looks_risk(text):
                    raise self._risk_error(
                        self._risk_detail(status, text), self._retry_after(r))
                if 500 <= status < 600 and not write and \
                        attempt + 1 < attempts:
                    last_error = P115Error(
                        f"115 服务暂时不可用（HTTP {status}）")
                    time.sleep(1.0 + attempt)
                    continue
                raise P115Error(
                    f"115 返回异常（HTTP {status}）："
                    f"{text[:200] or '无响应内容'}")
            if isinstance(data, dict) and data.get("state") is False:
                errno = data.get("errno") or data.get("code")
                msg = data.get("error") or data.get("message") or \
                    text[:300]
                if self._looks_risk(msg):
                    raise self._risk_error(msg, self._retry_after(r))
                if str(errno) in ("401", "99", "990001", "990009") or \
                        self._looks_auth(msg):
                    self._logged_in = False
                    raise P115AuthError(self._auth_message(msg))
                raise P115Error(f"115 返回错误：{msg}")
            return data
        raise last_error or P115Error("115 请求失败")

    def _list_dir_app(self, cid: str, page_size: int = 500) -> list[P115Item]:
        out: list[P115Item] = []
        offset = 0
        while True:
            data = self._app_list(cid, offset, page_size)
            items = data.get("data") or []
            for it in items:
                fc = str(it.get("file_category", it.get("fc", "")))
                is_dir = fc == "0" or bool(it.get("is_dir"))
                fid = it.get("file_id") or it.get("fid")
                if not fid and is_dir:
                    fid = it.get("cid")
                fid = str(fid or "")
                if not fid:
                    continue
                parent = it.get("parent_id") or it.get("pid") or cid
                name = (it.get("file_name") or it.get("fn") or
                        it.get("n") or "")
                size = (it.get("file_size") if it.get("file_size")
                        not in (None, "") else
                        (it.get("fs") if it.get("fs") not in (None, "")
                         else it.get("s")))
                updated = (it.get("user_utime") or it.get("upt") or
                           it.get("uet") or it.get("te") or it.get("t") or "")
                out.append(P115Item(
                    fid=fid,
                    parent_id=str(parent if parent not in (None, "") else cid),
                    name=str(name),
                    is_dir=is_dir,
                    size=_int(size, 0),
                    pickcode=str(it.get("pick_code") or it.get("pc") or ""),
                    updated=str(updated),
                ))
            total = _int(data.get("count"), 0)
            if not total:
                total = (_int(data.get("file_count"), 0) +
                         _int(data.get("folder_count"), 0))
            offset += len(items)
            if not items or offset >= total:
                break
        out.sort(key=lambda x: (not x.is_dir, _natural_key(x.name)))
        return out

    def list_dir(self, cid: str = "0", page_size: int = 500) -> list[P115Item]:
        if self._is_app_login():
            return self._list_dir_app(cid, page_size)
        out: list[P115Item] = []
        offset = 0
        while True:
            data = self._request("GET", "/files", params={
                "aid": 1, "cid": cid, "o": "file_name", "asc": 1,
                "offset": offset, "show_dir": 1, "limit": page_size,
                "snap": 0, "natsort": 1, "record_open_time": 1,
                "cur": 1, "fc_mix": 1, "format": "json",
            })
            items = data.get("data") or []
            for it in items:
                fc = str(it.get("fc", ""))
                if fc in ("0", "1"):
                    is_dir = fc == "0"
                else:
                    is_dir = bool(it.get("is_dir"))
                # 115 网页版接口：文件夹用 cid/n/pc，文件用 fid/n/s/pc；
                # 有些接口版本用 fid/fn/fs。两种都兼容。
                fid = it.get("fid")
                if not fid and is_dir:
                    fid = it.get("cid")
                fid = str(fid or "")
                if not fid:
                    continue
                parent = it.get("pid")
                if parent in (None, ""):
                    parent = it.get("cid") if not is_dir else cid
                name = it.get("fn")
                if not name:
                    name = it.get("n") or it.get("ns") or ""
                size = it.get("fs")
                if size in (None, ""):
                    size = it.get("s")
                updated = (it.get("upt") or it.get("uet") or
                           it.get("te") or it.get("t") or "")
                out.append(P115Item(
                    fid=fid,
                    parent_id=str(parent if parent not in (None, "") else cid),
                    name=str(name),
                    is_dir=is_dir,
                    size=_int(size, 0),
                    pickcode=str(it.get("pc", "")),
                    updated=str(updated),
                ))
            total = _int(data.get("count"), 0)
            offset += len(items)
            if not items or offset >= total:
                break
        out.sort(key=lambda x: (not x.is_dir, _natural_key(x.name)))
        return out

    def download_bytes(self, pickcode: str,
                       max_size: int = 2 * 1024 * 1024) -> bytes:
        """下载小型文件（NFO 等）。只读，不修改网盘。"""
        pickcode = str(pickcode or "").strip()
        if not pickcode:
            return b""
        data = self._request("GET", "/files/download",
                             params={"pickcode": pickcode})
        url = str(data.get("file_url") or data.get("url") or "")
        if not url:
            return b""
        declared = _int(data.get("file_size"), 0)
        if max_size and declared > max_size:
            return b""
        self._throttle()
        try:
            r = self.session.get(url, timeout=60, stream=True)
        except Exception as e:
            raise P115Error(f"下载文件失败：{e}")
        if r.status_code in (403, 429):
            raise self._risk_error(
                f"下载文件触发限制（HTTP {r.status_code}）",
                self._retry_after(r))
        if r.status_code != 200:
            raise P115Error(f"下载文件失败（HTTP {r.status_code}）")
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if max_size and total > max_size:
                    raise P115Error(f"文件超过大小限制（>{max_size} 字节）")
                chunks.append(chunk)
        finally:
            try:
                r.close()
            except Exception:
                pass
        return b"".join(chunks)

    def list_tree(self, cid: str = "0", max_depth: int = 1,
                  include_files: bool = True) -> list[P115Item]:
        """列出目录；max_depth=1 表示只列下一层，2 表示再进一层文件夹。"""
        result: list[P115Item] = []

        def walk(parent: str, depth: int):
            for it in self.list_dir(parent):
                if it.is_dir:
                    result.append(it)
                    if depth < max_depth:
                        walk(it.fid, depth + 1)
                elif include_files:
                    result.append(it)

        walk(cid, 1)
        return result

    def rename_many(self, ops: list[RenameOp], chunk_size: int = BATCH_CHUNK,
                    progress: Optional[Callable[[int, int], None]] = None
                    ) -> list[RenameResult]:
        results: list[RenameResult] = []
        total = len(ops)
        chunk_size = max(1, min(int(chunk_size or BATCH_CHUNK), BATCH_CHUNK))
        for start in range(0, total, chunk_size):
            if start:
                try:
                    self._batch_pause()
                except P115RateLimitError as e:
                    for op in ops[start:]:
                        results.append(RenameResult(
                            op.fid, op.old_name, op.new_name, False, str(e)))
                    if progress:
                        progress(total, total)
                    break
            chunk = ops[start:start + chunk_size]
            form = {f"files_new_name[{op.fid}]": op.new_name for op in chunk}
            try:
                if self._is_app_login():
                    app = self._app_name()
                    last_err = None
                    data = None
                    for path in (f"/{app}/files/batch_rename",
                                 f"/{app}/2.0/files/batch_rename",
                                 f"/{app}/1.0/files/batch_rename"):
                        try:
                            data = self._request("POST", path,
                                                 base_url=APPAPI, data=form)
                            last_err = None
                            break
                        except Exception as e:
                            last_err = e
                            if "HTTP 404" not in str(e):
                                break
                    if last_err is not None:
                        raise last_err
                    if data is None:
                        raise P115Error("115 应用接口未返回结果")
                else:
                    data = self._request("POST", "/files/batch_rename",
                                         data=form)
                ok_all = bool(data.get("state", True))
                payload = data.get("data")
                per: dict = {}
                if isinstance(payload, dict):
                    per = payload
                elif isinstance(payload, list):
                    for entry in payload:
                        if isinstance(entry, dict):
                            fid = str(entry.get("fid") or entry.get("file_id") or "")
                            if fid:
                                per[fid] = entry
                for op in chunk:
                    info = per.get(op.fid)
                    if isinstance(info, dict):
                        ok = bool(info.get("state", ok_all))
                        msg = str(info.get("error") or info.get("message") or "")
                    else:
                        ok, msg = ok_all, "" if ok_all else str(
                            data.get("error") or data.get("message") or "")
                    results.append(RenameResult(op.fid, op.old_name,
                                                op.new_name, ok, msg))
            except (P115RateLimitError, P115AuthError) as e:
                # 风控/登录失效后不要继续发后面的批次，剩下的直接标失败。
                for op in ops[start:]:
                    results.append(RenameResult(
                        op.fid, op.old_name, op.new_name, False, str(e)))
                if progress:
                    progress(total, total)
                break
            except Exception as e:
                for op in chunk:
                    results.append(RenameResult(op.fid, op.old_name,
                                                op.new_name, False, str(e)))
            if progress:
                progress(min(start + len(chunk), total), total)
        return results

    # ------------------------------------------------------------ NFO/图片
    def _upload_user_id(self) -> str:
        uid = str(getattr(self, "_upload_uid", "") or "")
        if uid:
            return uid
        try:
            data = self._request("GET", "/app/uploadinfo", base_url=APPAPI)
            uid = str(data.get("user_id") or data.get("userid") or "")
        except (P115RateLimitError, P115AuthError):
            raise
        except Exception:
            uid = ""
        if not uid:
            for c in self.session.cookies:
                if c.name.upper() == "UID":
                    uid = str(c.value)
                    break
        self._upload_uid = uid
        return uid

    def upload_bytes(self, cid: str, filename: str, data: bytes,
                     mime: str = "") -> bool:
        """上传一个小文件（NFO/图片）到指定目录。"""
        if not data:
            return False
        uid = self._upload_user_id()
        if not uid:
            raise P115Error("无法获取 115 用户 ID，可能登录已失效。")
        mime = mime or mimetypes.guess_type(filename)[0] or \
            "application/octet-stream"
        self._throttle(self._upload_interval, write=True)
        try:
            r = self.session.post(
                "https://uplb.115.com/3.0/sampleinitupload.php",
                data={"userid": uid, "filename": filename,
                      "filesize": str(len(data)),
                      "target": f"U_1_{cid}"},
                timeout=30)
        except Exception as e:
            raise P115Error(f"115 上传初始化失败：{e}")
        status = int(getattr(r, "status_code", 0) or 0)
        text = (getattr(r, "text", "") or "")[:500]
        if status == 401:
            self._logged_in = False
            raise P115AuthError(self._auth_message(text or "HTTP 401"))
        if status in (403, 405, 429):
            raise self._risk_error(
                self._risk_detail(status, text), self._retry_after(r))
        try:
            info = r.json()
        except Exception as e:
            if self._looks_risk(text):
                raise self._risk_error(
                    self._risk_detail(status, text), self._retry_after(r))
            raise P115Error(f"115 上传初始化返回异常：{e}")
        if not isinstance(info, dict) or info.get("state") is False:
            msg = info.get("error") if isinstance(info, dict) else ""
            if self._looks_risk(str(msg)):
                raise self._risk_error(str(msg))
            raise P115Error(f"115 上传初始化失败：{msg or '返回异常'}")
        if not info.get("host") or \
                not (info.get("object") or info.get("objectid")):
            msg = info.get("error") if isinstance(info, dict) else ""
            raise P115Error(f"115 上传初始化失败：{msg or '返回异常'}")
        obj = info.get("object") or info.get("objectid")
        fields = {
            "name": (None, filename),
            "key": (None, str(obj)),
            "policy": (None, str(info.get("policy") or "")),
            "OSSAccessKeyId": (None, str(info.get("accessid") or "")),
            "success_action_status": (None, "200"),
            "callback": (None, str(info.get("callback") or "")),
            "signature": (None, str(info.get("signature") or "")),
            "file": (filename, data, mime),
        }
        # 上传文件本身也稍作停顿，避免 NFO/图片短时间内成批上传。
        self._throttle(0.6, write=True)
        try:
            up = requests.post(str(info["host"]), files=fields,
                               headers={"User-Agent": UA}, timeout=120)
        except Exception as e:
            raise P115Error(f"115 上传失败：{e}")
        if up.status_code in (403, 429):
            raise self._risk_error(
                f"上传文件触发限制（HTTP {up.status_code}）",
                self._retry_after(up))
        if not (200 <= up.status_code < 300):
            raise P115Error(
                f"115 上传失败：HTTP {up.status_code} {up.text[:200]}")
        return True

    def delete_to_recycle(self, fids: list[str]) -> int:
        """把文件移到 115 回收站（不是永久删除）。"""
        fids = [str(f) for f in fids if f]
        if not fids:
            return 0
        paths = []
        if self._is_app_login():
            app = self._app_name()
            paths += [(f"/{app}/rb/delete", APPAPI),
                      (f"/{app}/1.0/rb/delete", APPAPI)]
        paths.append(("/rb/delete", WEBAPI))
        total = 0
        for start in range(0, len(fids), DELETE_CHUNK):
            if start:
                self._batch_pause()
            chunk = fids[start:start + DELETE_CHUNK]
            form = [("fid[]", f) for f in chunk]
            data = None
            last_err = None
            for path, base in paths:
                try:
                    data = self._request("POST", path, base_url=base,
                                         data=form)
                    last_err = None
                    break
                except (P115RateLimitError, P115AuthError):
                    raise
                except Exception as e:
                    last_err = e
                    if "HTTP 404" in str(e):
                        continue
                    break
            if last_err is not None or data is None:
                raise P115Error(
                    f"移入回收站失败：{last_err or '没有返回结果'}")
            if data.get("state") is False:
                raise P115Error(str(data.get("error") or "移入回收站失败"))
            total += len(chunk)
        return total

    def find_item(self, fid: str, parent_id: str) -> Optional[P115Item]:
        try:
            for it in self.list_dir(parent_id):
                if it.fid == fid:
                    return it
        except Exception as e:
            self.log(f"查找文件失败：{e}")
        return None


class MockP115Client:
    """演示/测试用：内存里模拟一棵 115 目录树，不会访问网络。"""

    def __init__(self, data_dir: str = "",
                 log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda s: None)
        self.session = None
        self._items: dict[str, P115Item] = {}
        self._children: dict[str, list[str]] = {}
        self._next = 1000
        self._build_demo()

    def _add(self, parent: str, name: str, is_dir: bool,
             size: int = 0) -> str:
        fid = str(self._next)
        self._next += 1
        item = P115Item(fid=fid, parent_id=parent, name=name,
                        is_dir=is_dir, size=size)
        self._items[fid] = item
        self._children.setdefault(parent, []).append(fid)
        return fid

    def _build_demo(self) -> None:
        anime = self._add("0", "日番", True)
        frieren = self._add(anime, "[喵萌奶茶屋&LoliHouse] 葬送的芙莉莲", True)
        self._add(frieren,
                  "[喵萌奶茶屋&LoliHouse] 葬送的芙莉莲 - 01 "
                  "[WebRip 1080p HEVC-10bit AAC][简繁日内封字幕].mkv", False,
                  1_500_000_000)
        self._add(frieren,
                  "[喵萌奶茶屋&LoliHouse] 葬送的芙莉莲 - 02 "
                  "[WebRip 1080p HEVC-10bit AAC][简繁日内封字幕].mkv", False,
                  1_500_000_000)
        self._add(frieren, "葬送的芙莉莲 - 01.ass", False, 50_000)

        aot = self._add(anime, "[Group] 进击的巨人 最终季 Part.2", True)
        self._add(aot, "[Group] 进击的巨人 最终季 Part.2 - 01 [1080p].mkv",
                  False, 2_000_000_000)

        tv = self._add("0", "电视剧", True)
        qyn = self._add(tv, "庆余年.第二季.2024.2160p.WEB-DL", True)
        self._add(qyn, "庆余年.第二季.S02E01.2160p.WEB-DL.mkv", False,
                  3_000_000_000)

        movies = self._add("0", "电影", True)
        self._add(movies, "朝花夕誓.2018.1080p.BluRay.mkv", False,
                  4_000_000_000)

    # ---- 与 P115Client 相同的接口
    def is_logged_in(self, force: bool = False) -> bool:
        return True

    def cookie_dict(self) -> dict:
        return {"UID": "demo"}

    def logout(self) -> None:
        pass

    def set_cookie_text(self, text: str) -> None:
        pass

    def list_dir(self, cid: str = "0", page_size: int = 500) -> list[P115Item]:
        items = [self._items[f] for f in self._children.get(str(cid), [])]
        items.sort(key=lambda x: (not x.is_dir, _natural_key(x.name)))
        return items

    def download_bytes(self, pickcode: str,
                       max_size: int = 2 * 1024 * 1024) -> bytes:
        return b""

    def list_tree(self, cid: str = "0", max_depth: int = 1,
                  include_files: bool = True) -> list[P115Item]:
        result: list[P115Item] = []

        def walk(parent: str, depth: int):
            for it in self.list_dir(parent):
                if it.is_dir:
                    result.append(it)
                    if depth < max_depth:
                        walk(it.fid, depth + 1)
                elif include_files:
                    result.append(it)

        walk(cid, 1)
        return result

    def rename_many(self, ops: list[RenameOp], chunk_size: int = 20,
                    progress=None) -> list[RenameResult]:
        results = []
        for i, op in enumerate(ops, 1):
            item = self._items.get(op.fid)
            if not item:
                results.append(RenameResult(op.fid, op.old_name,
                                            op.new_name, False, "演示数据中不存在"))
                continue
            # 模拟同名冲突
            siblings = [self._items[f] for f in self._children.get(item.parent_id, [])]
            if any(s.fid != item.fid and s.name == op.new_name for s in siblings):
                results.append(RenameResult(op.fid, op.old_name,
                                            op.new_name, False, "同名文件已存在"))
            else:
                item.name = op.new_name
                results.append(RenameResult(op.fid, op.old_name,
                                            op.new_name, True))
            if progress:
                progress(i, len(ops))
        return results

    def find_item(self, fid: str, parent_id: str) -> Optional[P115Item]:
        return self._items.get(fid)
