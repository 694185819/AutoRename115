# -*- coding: utf-8 -*-
"""naming_rule 单测：固定顺序、各段取舍、长度预算。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.naming_rule import (NAME_SOURCE_LABELS, build_episode_filename,
                             build_movie_filename, episode_tag,
                             sanitize_segment)


def main():
    # 1) 图片里的顺序：中文主名称 . 来源名 . S01E01 . 副标题 [规格]
    name = build_episode_filename(
        "灵笼", 1, 1, ext=".mp4", name_segment="Ling Cage",
        subtitle="灯塔和光影会", specs="1080p WEB-DL")
    print("完整:", name)
    assert name == "灵笼.Ling.Cage.S01E01.灯塔和光影会 [1080p WEB-DL].mp4", name

    # 2) 来源名选“不显示”
    name = build_episode_filename("灵笼", 1, 2, ext=".mp4",
                                  name_segment="", subtitle="回忆")
    print("无来源名:", name)
    assert name == "灵笼.S01E02.回忆.mp4", name

    # 3) 副标题没有就省略这一段
    name = build_episode_filename("灵笼", 1, 3, ext=".mp4",
                                  name_segment="Ling Cage")
    print("无副标题:", name)
    assert name == "灵笼.Ling.Cage.S01E03.mp4", name

    # 4) 规格开关为否
    name = build_episode_filename("某剧", 2, 5, ext=".mkv",
                                  name_segment="Some Show",
                                  subtitle="标题", specs="")
    print("无规格:", name)
    assert name == "某剧.Some.Show.S02E05.标题.mkv", name

    # 5) 来源名与中文名相同则不重复
    name = build_episode_filename("Hyouka", 1, 1, ext=".mkv",
                                  name_segment="Hyouka")
    print("去重:", name)
    assert name == "Hyouka.S01E01.mkv", name

    # 6) 季集固定格式
    assert episode_tag(1, 2) == "S01E02"
    assert episode_tag(1, 2, 3) == "S01E02-E03"
    assert episode_tag(2, 7, version="v2") == "S02E07v2"

    # 7) 超长时先让出副标题，SxxExx 必须保留
    long_sub = "很长的副标题" * 40
    name = build_episode_filename("中文标题" * 10, 1, 1, ext=".mkv",
                                  name_segment="Very Long English Name",
                                  subtitle=long_sub, specs="1080p")
    print("长名尾巴:", name[-40:])
    assert "S01E01" in name and name.endswith(".mkv")
    assert len(name.encode("utf-8")) <= 235, len(name.encode("utf-8"))

    # 8) 清洗非法字符（直接删除，不留下点号连缀）
    cleaned = sanitize_segment('A/B:C*?"<>|')
    print("清洗:", cleaned)
    assert cleaned == "ABC", cleaned
    assert sanitize_segment("灵笼：第一季") == "灵笼.第一季", \
        sanitize_segment("灵笼：第一季")

    # 9) 电影
    assert build_movie_filename("朝花夕拾", 2018, ".mkv") == \
        "朝花夕拾 (2018).mkv"

    # 10) 选项表包含图片要求的来源
    for key in ("imdb", "tmdb", "douban", "bangumi", "none"):
        assert key in NAME_SOURCE_LABELS
    print("NAMING RULE OK")


if __name__ == "__main__":
    main()
