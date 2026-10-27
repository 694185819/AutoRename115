# -*- coding: utf-8 -*-
"""罗马数字季/部：Your Highness Ⅱ、Season II、第Ⅱ季、Part II。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name, roman_to_int
from app.planner import (is_part_dir, is_season_dir, season_from_dir,
                         season_from_text)


def main():
    assert roman_to_int("Ⅱ") == 2
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9
    assert roman_to_int("XII") == 12
    assert roman_to_int("Rocky") is None

    # 截图里的写法：中文标题带 2，英文后面用 Ⅱ
    p = parse_name(
        "拜见宫主大人2.Your Highness Ⅱ.2019.EP01-22.WEB-DL."
        "1080p.H264.AAC-OurTV", is_dir=True)
    assert p.title == "拜见宫主大人", p.title
    assert p.season == 2, p.season
    assert p.episode == 1 and p.episode_end == 22, (p.episode, p.episode_end)
    assert p.year == 2019, p.year

    p = parse_name("Show.Your Highness II.2019.EP01-22.WEB-DL",
                   is_dir=True)
    assert p.season == 2, p.season
    assert p.episode == 1 and p.episode_end == 22

    # 电影名里的 II 不能当季
    p = parse_name("Rocky II.1979.1080p.BluRay")
    assert p.season is None, p.season
    assert p.title == "Rocky II", p.title

    # 显式 S01E01 优先，不被标题里的 II 覆盖
    p = parse_name("Show.Your Highness Ⅱ 2019 S01E01")
    assert p.season == 1, p.season

    # 季目录 / 季文本 / Part II
    assert is_season_dir("Season II")
    assert season_from_dir("Season II") == 2
    assert season_from_dir("第Ⅱ季") == 2
    assert season_from_text("Show II") == 2
    assert is_part_dir("Part II")

    p = parse_name("Show.Part.II.2019.EP01", is_dir=True)
    assert p.season == 2, p.season
    assert p.episode == 1, p.episode

    # Highness 末尾的 s 不能被当成 Sxx 简写而吞掉 EP01-21
    p = parse_name("拜见宫主大人.Your.Highness.EP01-21.2017."
                   "1080p.WEB-DL", is_dir=True)
    assert p.episode == 1 and p.episode_end == 21, (p.episode, p.episode_end)

    print("ROMAN SEASON OK")


if __name__ == "__main__":
    main()
