# -*- coding: utf-8 -*-
import json
import sys
import tempfile

import os
import time

from requests.cookies import RequestsCookieJar

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.p115 import CookieStore, P115Client


class Resp:
    def __init__(self, data, content=b""):
        self._data = data
        self.content = content
        self.status_code = 200
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.cookies = RequestsCookieJar()

    def get(self, url, params=None, headers=None, timeout=None):
        if "/token/" in url:
            return Resp({"state": 1, "data": {
                "uid": "uid123", "time": 1, "sign": "sig",
                "qrcode": "https://115.com/scan/dg-uid123"}})
        if "/get/status/" in url:
            return Resp({"state": 1, "data": {"status": 2}})
        if url.endswith("/qrcode"):
            return Resp({}, content=b"fake-png")
        if "proapi.115.com" in url and "/ufile/files" in url:
            return Resp({"state": True, "count": 0, "data": []})
        if url.endswith("/files"):
            return Resp({"state": True, "count": 0, "data": []})
        raise AssertionError(url)

    def post(self, url, data=None, timeout=None):
        assert "login/qrcode" in url
        self.post_url = url
        self.post_data = data
        return Resp({"state": 1, "data": {"cookie": {
            "UID": "u1", "CID": "c1", "SEID": "s1", "KID": "k1"}}})


tmp = tempfile.mkdtemp(prefix="p115login_")
c = P115Client(tmp, use_roaming=False)
c.session = FakeSession()
token = c.qr_token()
print("token:", token)
assert token["uid"] == "uid123"
assert c.qr_image("uid123") == b"fake-png"
assert c.qr_status(token) == 2
assert c.qr_login("uid123") is True
saved = c.cookie_store.load()
print("saved cookie:", saved)
assert saved == {"UID": "u1", "CID": "c1", "SEID": "s1", "KID": "k1"}
assert c.is_logged_in(force=True) is True
assert "/ios/" in c.session.post_url, c.session.post_url
assert c.session.post_data["app"] == "ios"
_, saved_app, _ = c.cookie_store.load_with_app()
assert saved_app == "ios", saved_app
print("P115 LOGIN FLOW OK")

# 持久化：同时写程序目录和 %APPDATA%，读取最新
tmp2 = tempfile.mkdtemp(prefix="p115data_")
tmp3 = tempfile.mkdtemp(prefix="p115appdata_")
old_appdata = os.environ.get("APPDATA")
os.environ["APPDATA"] = tmp3
try:
    store = CookieStore(tmp2, use_roaming=True)
    store.save({"UID": "old"})
    assert os.path.exists(os.path.join(tmp2, "cookies.json"))
    assert os.path.exists(os.path.join(tmp3, "AutoRename115", "cookies.json"))
    time.sleep(1.1)
    # 模拟新版程序写入更新的 roaming cookie
    import json
    rp = os.path.join(tmp3, "AutoRename115", "cookies.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"cookie": {"UID": "new"}, "saved_at": int(time.time()) + 5}, f)
    got = CookieStore(tmp2, use_roaming=True).load()
    print("newest cookie:", got)
    assert got == {"UID": "new"}
    CookieStore(tmp2, use_roaming=True).clear()
    assert not os.path.exists(os.path.join(tmp2, "cookies.json"))
    assert not os.path.exists(rp)
finally:
    if old_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = old_appdata
print("COOKIE PERSIST OK")
