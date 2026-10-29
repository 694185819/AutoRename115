# -*- coding: utf-8 -*-
"""浏览器内核方案：标题解析、浏览器探测（不联网）。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import douban_browser as db


def main():
    # 标题 → 集名
    cases = [
        ("灵笼 第一季 第1集 灯塔和光影会", "灯塔和光影会"),
        ("灵笼 第一季 第2集 回忆(豆瓣)", "回忆"),
        ("某剧 第12集 终章（上）", "终章（上）"),
        ("某剧 第3集", ""),
        ("豆瓣", ""),
        ("", ""),
    ]
    for raw, expect in cases:
        got = db.episode_name_from_title(raw)
        print(f"{raw!r} -> {got!r}")
        assert got == expect, (raw, got, expect)

    # 是否已加载到“第N集”页面
    assert db.re_ep_title("灵笼 第一季 第1集 灯塔和光影会")
    assert not db.re_ep_title("豆瓣")

    # 浏览器探测：本机应当能找到 Chrome 或 Edge
    exe = db.find_browser()
    print("找到浏览器:", exe or "无")
    assert exe, "本机应有 Chrome 或 Edge"
    assert exe.lower().endswith(".exe")

    # 端口挑选
    port = db._pick_port(9520, 9560)
    assert 9520 <= port < 9560, port

    print("DOUBAN BROWSER OK")


if __name__ == "__main__":
    main()
