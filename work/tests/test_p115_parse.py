# -*- coding: utf-8 -*-
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.models import RenameOp
from app.p115 import P115Client

tmp = tempfile.mkdtemp(prefix="p115test_")
c = P115Client(tmp, use_roaming=False)

PAGE = {
    "state": True, "count": 3,
    "data": [
        {"fid": "1", "pid": "0", "fc": "0", "fn": "文件夹", "fs": "0"},
        {"fid": "2", "pid": "0", "fc": "1", "fn": "视频.mkv", "fs": "123",
         "pc": "abc", "upt": 1700000000},
        {"fid": "3", "pid": "0", "fc": "1", "fn": "字幕.ass", "fs": "10"},
    ],
}


def fake_request(method, path, **kwargs):
    if path == "/files":
        offset = int(kwargs.get("params", {}).get("offset", 0))
        data = PAGE["data"][offset:offset + 2]
        return {"state": True, "count": 3, "data": data}
    if path == "/files/batch_rename":
        print("FORM:", kwargs.get("data"))
        return {"state": True}
    raise AssertionError(path)


c._request = fake_request
items = c.list_dir("0", page_size=2)
print([(x.fid, x.name, x.is_dir, x.size) for x in items])
assert len(items) == 3
by_id = {x.fid: x for x in items}
assert by_id["1"].is_dir and by_id["1"].name == "文件夹"
assert not by_id["2"].is_dir and by_id["2"].size == 123
assert by_id["2"].pickcode == "abc"
assert by_id["2"].ext == ".mkv"

ops = [RenameOp(fid="2", old_name="视频.mkv", new_name="新名.mkv",
                is_dir=False, parent_id="0", role="episode")]
res = c.rename_many(ops)
assert res[0].ok

# 失败响应
def fail_request(method, path, **kwargs):
    if path == "/files/batch_rename":
        return {"state": False, "error": "同名文件已存在"}
    raise AssertionError(path)

c._request = fail_request
res = c.rename_many(ops)
print(res[0])
assert not res[0].ok and "同名" in res[0].message

print("P115 PARSE OK")
