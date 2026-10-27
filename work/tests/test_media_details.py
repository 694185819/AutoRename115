# -*- coding: utf-8 -*-
"""影片资料：评分/封面/简介/演员的字段解析。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient


class FakeMeta(MetadataClient):
    def __init__(self, responses):
        super().__init__("", tmdb_key="test", use_bangumi=True)
        self.responses = responses

    def _get_json(self, url, source, params=None, referer="", headers=None):
        for part, data in self.responses.items():
            if part in url:
                return data
        raise RuntimeError("no mock for " + url)


def main():
    tmdb = FakeMeta({
        "/tv/123": {
            "id": 123, "name": "测试剧", "first_air_date": "2024-01-02",
            "vote_average": 8.62, "overview": "简介文本",
            "poster_path": "/p.jpg",
            "credits": {"cast": [{"name": "演员甲", "character": "角色甲"},
                                 {"name": "演员乙", "character": ""}]},
        }})
    info = tmdb.media_details("tmdb", "123", "tv")
    assert info["title"] == "测试剧", info
    assert info["year"] == 2024
    assert info["rating"] == 8.6
    assert info["overview"] == "简介文本"
    assert info["poster"].endswith("/p.jpg")
    assert info["cast"] == ["演员甲（角色甲）", "演员乙"], info

    douban = FakeMeta({
        "/rexxar/api/v2/tv/456": {
            "id": 456, "title": "豆瓣剧", "year": "2023",
            "rating": {"value": 8.0}, "intro": "豆瓣简介",
            "cover_url": "https://img.example/p.jpg",
            "actors": [{"name": "甲"}, {"name": "乙"}],
        }})
    info = douban.media_details("douban", "456", "tv")
    assert info["title"] == "豆瓣剧", info
    assert info["year"] == 2023
    assert info["rating"] == 8.0
    assert info["overview"] == "豆瓣简介"
    assert info["cast"] == ["甲", "乙"], info

    bangumi = FakeMeta({
        "/subjects/789/characters": [
            {"name": "角色甲", "actors": [{"name": "声优甲"}]}],
        "/subjects/789": {
            "id": 789, "name": "Bangumi 剧", "name_cn": "番剧",
            "date": "2022-04-01", "rating": {"score": 7.8},
            "summary": "番剧简介",
            "images": {"large": "https://img.example/b.jpg"},
            "infobox": [],
        },
    })
    info = bangumi.media_details("bangumi", "789", "tv")
    assert info["title"] == "番剧", info
    assert info["year"] == 2022
    assert info["rating"] == 7.8
    assert info["poster"].endswith("b.jpg")
    assert info["cast"] == ["角色甲（声优甲）"], info

    print("MEDIA DETAILS OK")


if __name__ == "__main__":
    main()
