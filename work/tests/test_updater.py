# -*- coding: utf-8 -*-
"""GitHub Release 更新：版本比较、附件选择和覆盖脚本约束。"""
import os
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import updater


class FakeResponse:
    def __init__(self, status=200, data=None, content=b"", headers=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}
        self._content = content

    def json(self):
        return self._data

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def main():
    assert updater.version_key("v0.1") == (0, 1, 0, 0)
    assert updater.version_key("0.1.0") == (0, 1, 0, 0)
    assert not updater.is_newer("v0.1", "0.1")
    assert not updater.is_newer("v0.1.0", "0.1")
    assert updater.is_newer("v0.2", "0.1")

    old_get = updater.requests.get
    try:
        updater.requests.get = lambda *a, **k: FakeResponse(
            data={
                "tag_name": "v0.2",
                "name": "v0.2",
                "html_url": updater.RELEASES_URL,
                "assets": [{
                    "name": updater.ASSET_NAME,
                    "browser_download_url": "https://example.invalid/a.zip",
                    "size": 4,
                }],
            })
        rel = updater.fetch_latest_release()
        assert rel["tag"] == "v0.2", rel
        assert rel["asset"]["name"] == updater.ASSET_NAME

        payload = b"test"
        updater.requests.get = lambda *a, **k: FakeResponse(
            content=payload, headers={"Content-Length": "4"})
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "update.zip")
            seen = []
            updater.download_asset(
                {"browser_download_url": "https://example.invalid/a.zip",
                 "size": 4}, dest,
                progress=lambda done, total: seen.append((done, total)))
            assert open(dest, "rb").read() == payload
            assert seen and seen[-1] == (4, 4), seen
    finally:
        updater.requests.get = old_get

    script = updater._UPDATER_SCRIPT
    for need in ("WaitPid", "AutoRename115.exe", '"data"',
                 "Copy-Item", "Start-Process", "Get-ChildItem"):
        assert need in script, need

    print("UPDATER OK")


if __name__ == "__main__":
    main()
