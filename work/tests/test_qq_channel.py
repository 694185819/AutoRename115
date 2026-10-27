# -*- coding: utf-8 -*-
"""QQ 频道入口：深链编码与唤起失败时的回退信号。"""
import os
import sys
from urllib.parse import unquote

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import qq_channel


def main():
    scheme = qq_channel.QQ_CHANNEL_SCHEME
    assert scheme.startswith(
        "tencent://ExWindow?subcmd=forwardUrl&url="), scheme
    encoded = scheme.split("url=", 1)[1]
    decoded = unquote(encoded)
    assert decoded == qq_channel.QQ_CHANNEL_APP_URL, decoded
    assert f"/g/{qq_channel.QQ_CHANNEL_ID}" in decoded, decoded

    original_name = os.name
    original_startfile = getattr(os, "startfile", None)
    try:
        calls = []
        os.name = "nt"
        os.startfile = calls.append
        assert qq_channel.open_in_qq() is True
        assert calls == [scheme], calls

        def broken(path):
            raise OSError("no handler")

        os.startfile = broken
        assert qq_channel.open_in_qq() is False

        os.name = "posix"
        os.startfile = calls.append
        assert qq_channel.open_in_qq() is False
        assert calls == [scheme], calls
    finally:
        os.name = original_name
        if original_startfile is None:
            try:
                del os.startfile
            except AttributeError:
                pass
        else:
            os.startfile = original_startfile

    print("QQ CHANNEL OK")


if __name__ == "__main__":
    main()
