# -*- coding: utf-8 -*-
"""目录名里的发布组与罗马数字季号。

用户截图：目录「将夜II.Ever.Night.S02.2160p.WEB-DL.H264.AAC-FLTTH」
被解析成片名「将夜II Ever Night -FLTTH」，于是：
  - 搜索词带上发布组，搜不到东西
  - 主标题变成「将夜II」，中文名和季号都没剥离
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name


def test_release_group_stripped():
    """规格后面的 -FLTTH 是发布组，不能留在片名里。"""
    p = parse_name("将夜II.Ever.Night.S02.2160p.WEB-DL.H264.AAC-FLTTH",
                   is_dir=True)
    print("title:", repr(p.title))
    assert "FLTTH" not in p.title, p.title
    assert "2160p" not in p.title, p.title
    assert "WEB" not in p.title.upper() or "WEB" not in p.title, p.title


def test_roman_season_stripped():
    """中文片名后的罗马数字是季号，要从片名里去掉。"""
    for name, want_season in (
            ("将夜II.Ever.Night.S02.2160p.WEB-DL.H264.AAC-FLTTH", 2),
            ("将夜II Ever Night", 2),
            ("将夜II.Ever.Night", 2),
            ("将夜III", 3)):
        p = parse_name(name, is_dir=True)
        print(f"{name!r} → title={p.title!r} season={p.season}")
        assert p.title == "将夜", f"{name}: {p.title!r}"
        assert p.season == want_season, f"{name}: {p.season}"


def test_normal_names_unaffected():
    """普通目录名不受影响。"""
    for name, want in (("将夜", "将夜"), ("灵笼", "灵笼"),
                       ("葬送的芙莉莲", "葬送的芙莉莲")):
        p = parse_name(name, is_dir=True)
        assert p.title == want, f"{name}: {p.title!r}"


def test_english_roman_not_eaten():
    """英文片名里的罗马数字不能被当成季号吃掉。"""
    p = parse_name("Rocky II", is_dir=True)
    print("Rocky II →", repr(p.title))
    assert "II" in p.title or p.title == "Rocky II", p.title


def main():
    test_release_group_stripped()
    test_roman_season_stripped()
    test_normal_names_unaffected()
    test_english_roman_not_eaten()
    print("DIR NAME CLEANUP OK")


if __name__ == "__main__":
    main()
