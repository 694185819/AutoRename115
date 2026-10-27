# -*- coding: utf-8 -*-
"""分类：文件夹归属（动画/电视剧/剧）和 TMDB 类型共同参与判断。

回归：日本真人电视剧 country=jp 时曾被无条件归成日番。
"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient
from app.models import Candidate, MatchResult
from app.parser import parse_name
from app.planner import Planner


def cat(context="", country="", animation=False, title="某剧",
        original="", tmdb_animation=False, media_type="series"):
    matching = MatchResult(title_zh=title, title_original=original,
                           country=country, animation=animation)
    if tmdb_animation:
        matching.tmdb = Candidate(
            source="tmdb", title=title, original_title=original,
            sid="1", kind="tv", extra={"animation": True})
    parsed = parse_name(title)
    return Planner(None)._detect_category(media_type, matching, parsed, context)


def main():
    # 日本真人剧：文件夹和元数据都说明不是动画
    assert cat("日剧 我家的故事", country="jp") == "tv"
    assert cat("电视剧 重启人生", country="jp") == "tv"
    assert cat("剧 寄生兽", country="") == "tv"
    assert cat("", country="jp") == "tv"
    # 根目录“剧”是弱提示，里面明确是动画时仍按动画
    assert cat("剧 某动画", country="jp", animation=True) == "jp_anime"
    # 明确写“日剧/电视剧”时优先按电视剧处理
    assert cat("日剧 某剧", country="jp", animation=True) == "tv"

    # 日本动画：文件夹或 TMDB genre 16 / Bangumi tag 说明是动画
    assert cat("动画 冰菓", country="jp", title="冰菓", original="氷菓") == "jp_anime"
    assert cat("日番 葬送的芙莉莲", country="jp") == "jp_anime"
    assert cat("", country="jp", animation=True) == "jp_anime"
    assert cat("", country="jp", tmdb_animation=True) == "jp_anime"

    # 国产真人剧 / 国产动画
    assert cat("电视剧 庆余年", country="cn") == "tv"
    assert cat("动画 斗罗大陆", country="cn", animation=True) == "cn_anime"

    # 欧美电视剧 / 美漫 / 其他欧美动画
    assert cat("电视剧 怪奇物语", country="us") == "tv"
    assert cat("", country="us", animation=True) == "us_anime"
    assert cat("美漫 瑞克和莫蒂", title="瑞克和莫蒂",
               original="Rick and Morty") == "us_anime"
    assert cat("美国动画 瑞克和莫蒂", country="us") == "us_anime"
    assert cat("", country="uk", animation=True) == "west_anime"

    # 没有地区时，靠目录/标题语言兜底
    assert cat("动画 葬送的芙莉莲", title="葬送的芙莉莲",
               original="葬送のフリーレン") == "jp_anime"
    assert cat("动画 Rick and Morty", title="Rick and Morty",
               original="Rick and Morty") == "west_anime"

    # Bangumi 的地区/标签也参与美漫识别
    assert MetadataClient.normalize_country("美国") == "us"
    assert MetadataClient.normalize_country("日本 / 美国") == "jp"
    assert MetadataClient.normalize_country("United States") == "us"
    assert MetadataClient._country_from_tags(["美漫", "动画"]) == "us"
    assert MetadataClient._candidate_is_animation(Candidate(
        source="bangumi", title="瑞克和莫蒂", extra={"tags": ["美漫"]}))

    # 电影始终是 movie
    assert cat("动画 电影", country="jp", media_type="movie") == "movie"

    print("CATEGORY OK")


if __name__ == "__main__":
    main()
