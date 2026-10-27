# -*- coding: utf-8 -*-
"""115 风控/限流：识别 429、状态码、停止后续批次、冷却期不再请求。"""
import json
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import RenameOp
from app.p115 import (P115AuthError, P115Client, P115RateLimitError)


class Resp:
    def __init__(self, status=200, data=None, text="", headers=None):
        self.status_code = status
        self._data = data if data is not None else {"state": True}
        self.text = text or json.dumps(self._data, ensure_ascii=False)
        self.headers = headers or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.headers = {}
        self.cookies = None

    def request(self, *args, **kwargs):
        self.calls += 1
        if not self.responses:
            return Resp(data={"state": True})
        return self.responses.pop(0)

    def get(self, *args, **kwargs):
        return self.request(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self.request(*args, **kwargs)


def new_client():
    c = P115Client(tempfile.mkdtemp(prefix="p115risk_"), use_roaming=False)
    c._risk_until = 0.0
    c._last_request = 0.0
    return c


def main():
    # HTTP 429：冷却；冷却期内第二次请求不会打到网络
    c = new_client()
    c.session = FakeSession([
        Resp(429, text="请求过于频繁，请稍后再试",
             headers={"Retry-After": "45"})])
    try:
        c._request("GET", "/files")
        raise AssertionError("should raise rate limit")
    except P115RateLimitError as e:
        assert "风控" in str(e), e
        assert c.risk_cooldown_remaining() >= 30, c.risk_cooldown_remaining()
    calls = c.session.calls
    try:
        c._request("GET", "/files")
        raise AssertionError("cooldown should block request")
    except P115RateLimitError:
        pass
    assert c.session.calls == calls, "must not hit network during cooldown"

    # HTTP 405（WAF 常见拦截）：按疑似风控处理，不能把原始 HTML/解析错误弹给用户
    c = new_client()
    c.session = FakeSession([
        Resp(405, text="<html><title>405 Not Allowed</title></html>")])
    try:
        c._request("GET", "/files")
        raise AssertionError("405 should be treated as risk")
    except P115RateLimitError as e:
        assert "风控" in str(e), e
        assert "405" in str(e), e
        assert "<html>" not in str(e), e
        assert c.risk_cooldown_remaining() > 0

    # 正常 JSON 里出现“限制级”等片名，不能误判成风控
    c = new_client()
    c.session = FakeSession([
        Resp(200, data={"state": True, "data": [{"n": "限制级电影"}]})])
    data = c._request("GET", "/files")
    assert data["data"][0]["n"] == "限制级电影", data

    # 200 + state=false + 风控文案：同样进入冷却
    c = new_client()
    c.session = FakeSession([
        Resp(200, data={"state": False, "error": "操作太频繁，请稍后再试"})])
    try:
        c._request("POST", "/files/batch_rename", data={})
        raise AssertionError("should raise rate limit")
    except P115RateLimitError as e:
        assert "风控" in str(e), e

    # 401：明确的登录失效，并提示设备类型互踢
    c = new_client()
    c._logged_in = None
    c.session = FakeSession([Resp(401, text="unauthorized")])
    try:
        c._request("GET", "/files")
        raise AssertionError("should raise auth error")
    except P115AuthError as e:
        assert "设备类型" in str(e), e
        assert c._logged_in is False

    # 网络异常不能误判成登录失效（避免反复弹扫码）
    c = new_client()
    c.login_app = "web"
    c.cookie_dict = lambda: {"UID": "u"}

    class DownSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("network down")

    c.session = DownSession()
    assert c.is_logged_in(force=True) is True
    assert c._last_auth_error

    # 批量改名遇到风控：只发第一批，剩下全部标失败，不再继续请求
    c = new_client()
    calls = []

    def risk_request(*args, **kwargs):
        calls.append(1)
        raise P115RateLimitError("115 提示请求过于频繁")

    c._request = risk_request
    ops = [RenameOp(fid=str(i), old_name=f"{i}.mkv",
                    new_name=f"new{i}.mkv", is_dir=False, parent_id="0")
           for i in range(15)]
    results = c.rename_many(ops)
    assert len(results) == 15, len(results)
    assert all(not r.ok for r in results), results
    assert calls == [1], calls

    # 正常改名：15 项按每批 10 个拆成 2 次，批间有停顿（测试里跳过）
    c = new_client()
    calls = []

    def ok_request(*args, **kwargs):
        calls.append(1)
        return {"state": True}

    c._request = ok_request
    c._batch_pause = lambda: None
    results = c.rename_many(ops)
    assert all(r.ok for r in results), results
    assert calls == [1, 1], calls

    print("P115 RISK OK")


if __name__ == "__main__":
    main()
