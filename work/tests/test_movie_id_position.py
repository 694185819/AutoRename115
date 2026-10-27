# -*- coding: utf-8 -*-
"""电影：IMDb 号插到中文名/带括号中文名之后，其他规格不变。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
sys.path.insert(0, r"I:\实验\AutoRename115\work\tests")

from app.models import Candidate, MatchResult
from app.planner import NamingOptions, Planner
from test_ancestor_context import FakeClient, item, GB


class Meta:
    def match(self, parsed, media_type, category_hint=""):
        return MatchResult(
            title_zh="朝花夕拾", title_original="朝花夕誓",
            year=2018, imdb_id="tt1234567", tmdb_id="",
            country="jp", confidence=0.95,
            imdb=Candidate(source="imdb", title="Maquia",
                           original_title="Maquia", year=2018,
                           sid="tt1234567", kind="movie"))

    def save_cache(self):
        pass


def main():
    p = Planner(None, NamingOptions(imdb_id_style="jellyfin"))
    suffix = "[imdbid-tt1234567]"
    cases = [
        ("朝花夕拾", True, "朝花夕拾" + suffix),
        ("[朝花夕拾]", True, "[朝花夕拾]" + suffix),
        ("[朝花夕拾 2018]", True, "[朝花夕拾 2018]" + suffix),
        ("朝花夕拾.2018.1080p.BluRay.mkv", False,
         "朝花夕拾" + suffix + ".2018.1080p.BluRay.mkv"),
        ("[BD-REMUX]朝花夕拾 [1080p].mkv", False,
         "[BD-REMUX]朝花夕拾" + suffix + " [1080p].mkv"),
        # 原 ID 在末尾：删掉，改放到中文名后
        ("朝花夕拾.2018.[imdbid-tt9999999].1080p.mkv", False,
         "朝花夕拾" + suffix + ".2018.1080p.mkv"),
        ("[朝花夕拾][imdbid-tt9999999]", True,
         "[朝花夕拾]" + suffix),
        # 语言标签不是标题
        ("[简繁][朝花夕拾][1080p].mkv", False,
         "[简繁][朝花夕拾]" + suffix + "[1080p].mkv"),
    ]
    for name, is_dir, want in cases:
        got = p._insert_id_after_title(name, suffix, is_dir)
        print(name, "->", got)
        assert got == want, (name, got, want)

    # 英文名没有中文标题：不强行插，走原来的英文命名
    assert p._insert_id_after_title("The.Movie.2018.mkv", suffix, False) == ""

    # 整部电影的文件夹和视频文件都插入
    folder = item("m", "1", "朝花夕拾", True, ancestors=["电影"])
    video = item("mv", "m", "朝花夕拾.2018.1080p.BluRay.mkv",
                 False, 8 * GB, ["电影", "朝花夕拾"])
    plan = Planner(Meta(), NamingOptions(imdb_id_style="jellyfin")).analyze(
        FakeClient({"m": [video]}), [folder])[0]
    names = {(o.role, o.old_name): o.new_name for o in plan.ops}
    print(names)
    assert names.get(("movie", "朝花夕拾")) == "朝花夕拾" + suffix
    assert names.get(("movie", "朝花夕拾.2018.1080p.BluRay.mkv")) == \
        "朝花夕拾" + suffix + ".2018.1080p.BluRay.mkv"
    print("MOVIE ID POSITION OK")


if __name__ == "__main__":
    main()
