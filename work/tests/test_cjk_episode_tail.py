# -*- coding: utf-8 -*-
"""中文片名紧贴集号（无分隔符）的解析。

用户反馈：文件名「将夜01.mkv」被当成片名「将夜01」，导致拿
「将夜01」去搜索，搜回一堆无关结果（米奇的大歌剧、火星需要妈妈…）。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name

# (文件名, 期望片名, 期望集号)
CASES = [
    ("将夜01.mkv", "将夜", 1),
    ("将夜03.mkv", "将夜", 3),
    ("犬夜叉01.mkv", "犬夜叉", 1),
    ("繁花01.mkv", "繁花", 1),
    # 片名本身带数字，不能被拆成集号
    ("琅琊榜2.mkv", "琅琊榜2", None),
    ("机动战士高达00.mkv", "机动战士高达00", None),
    ("1984.mkv", "1984", None),
    ("三体.mkv", "三体", None),
    # 原有的写法不能退化
    ("我的英雄学院 第01集.mkv", "我的英雄学院", 1),
    ("将夜 01.mkv", "将夜", 1),
    ("将夜 - 01.mkv", "将夜", 1),
    ("将夜.S01E01.mkv", "将夜", 1),
]


def main():
    bad = []
    for name, want_title, want_ep in CASES:
        p = parse_name(name, is_dir=False)
        if p.title != want_title or p.episode != want_ep:
            bad.append(f"{name}: 得到 title={p.title!r} ep={p.episode}，"
                       f"期望 {want_title!r}/{want_ep}")
    assert not bad, "\n".join(bad)
    print("CJK EPISODE TAIL OK")


if __name__ == "__main__":
    main()
