# -*- coding: utf-8 -*-
"""季号重复：中文季号已取出后，英文的 Sxx 还留在片名里。

用户截图：目录「庆余年 第2季[…][全36集]Joy.of.Life.2.S02.1080p」
输出 庆余年.Joy.of.Life2.Joy.of.Life.2.S02E01 —— 英文名出现两次。
根因：RE_SEASON_CN 先匹配到「第2季」并把 season 定下来，
之后就不再匹配 S02，于是 S02 留在 title 里，
来源名（Joy of Life）与残留的片名（Joy.of.Life.2.S02）叠加。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name


def test_english_season_stripped():
    """中文季号 + 英文季号同时出现时，英文那个也要从片名去掉。"""
    p = parse_name(
        "庆余年 第2季[迪士尼无广告版][全36集][国语音轨+繁体字幕]"
        "Joy.of.Life.2.S02.1080p", is_dir=True)
    print("title:", repr(p.title), "| season:", p.season)
    assert "S02" not in p.title, p.title
    assert p.season == 2, p.season


def test_season_word_stripped():
    """Season 2 与第2季同时出现时同理。"""
    p = parse_name("庆余年 第2季 Season 2 1080p", is_dir=True)
    print("title:", repr(p.title))
    assert "Season" not in p.title, p.title
    assert p.season == 2, p.season


def test_different_season_kept():
    """季号不同的英文标记不能被误删。"""
    p = parse_name("庆余年 第2季 Joy.of.Life.S03", is_dir=True)
    print("title:", repr(p.title))
    assert p.season == 2, p.season


def test_single_marker_unaffected():
    """只有一种季号写法时行为不变。"""
    for name in ("庆余年 S02", "庆余年 第2季",
                 "庆余年.Joy.of.Life.2.S02.1080p"):
        p = parse_name(name, is_dir=True)
        assert p.season == 2, (name, p.season)
        assert "S02" not in p.title or "第2季" not in p.title, (name, p.title)


def main():
    test_english_season_stripped()
    test_season_word_stripped()
    test_different_season_kept()
    test_single_marker_unaffected()
    print("SEASON MARKER DEDUP OK")


if __name__ == "__main__":
    main()
