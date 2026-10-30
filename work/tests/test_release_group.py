# -*- coding: utf-8 -*-
"""压制组不能进入文件名。

用户截图：目录尾部 -BlackTV（与正式英文名隔着 1080p DSNP WEB-DL AAC
2.0 H.265 一堆规格词），却被解析进片名，输出成
庆余年.Joy.of.Life.2.BlackTV.S02E01。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name

FOLDER = ("庆余年 第2季[迪士尼无广告版][全36集][国语音轨+繁体字幕]"
          "Joy.of.Life.2.S02.1080p.DSNP.WEB-DL.AAC.2.0.H.265-BlackTV")


def test_group_not_in_title():
    p = parse_name(FOLDER, is_dir=True)
    print("title:", repr(p.title))
    assert "BlackTV" not in p.title, p.title
    assert p.season == 2, p.season


def test_no_dangling_dots():
    """规格词剥掉后不能留下「. . . . 」这种空点号。"""
    p = parse_name(FOLDER, is_dir=True)
    assert " . " not in p.title, p.title
    assert not p.title.endswith("-"), p.title


def test_common_groups():
    """常见发布组后缀都要能剥掉。"""
    cases = [
        ("Show.Name.S01.1080p.WEB-DL.H264.AAC-FLTTH", "FLTTH"),
        ("Show.Name.S01.2160p.WEB-DL.AAC.2.0.H.265-BlackTV", "BlackTV"),
        ("Show.2024.S01.1080p.BluRay.x264-GROUP", "GROUP"),
        ("Show.S01.720p.HDTV.x264@HDsky", "HDsky"),
    ]
    for name, group in cases:
        p = parse_name(name, is_dir=True)
        print(f"{name} → {p.title!r}")
        assert group not in p.title, (name, p.title)


def test_title_without_specs_kept():
    """没有规格词时，普通片名不受影响。"""
    for name in ("庆余年", "将夜", "Joy of Life"):
        p = parse_name(name, is_dir=True)
        assert p.title, (name, p.title)


def main():
    test_group_not_in_title()
    test_no_dangling_dots()
    test_common_groups()
    test_title_without_specs_kept()
    print("RELEASE GROUP STRIPPED OK")


if __name__ == "__main__":
    main()
