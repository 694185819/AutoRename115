# -*- coding: utf-8 -*-
"""豆瓣分集页解析：从真实页面结构取“本集中文名”，拿不到就明确失败。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import MetadataClient

# 截图里豆瓣分集页的关键结构（真实页面的片段）
PAGE_OK = """
<html><head><title>灵笼 第一季 第1集 灯塔和光影会(豆瓣)</title></head>
<body><div class="subject">
<h1><span>灵笼 第一季</span> 第1集 灯塔和光影会</h1>
<ul>
  <li>本集中文名：灯塔和光影会</li>
  <li>本集原名：灯塔和光影会</li>
  <li>播放时间：2019-03-04</li>
</ul>
</div></body></html>
"""

PAGE_TITLE_ONLY = """
<html><head><title>灵笼 第一季 第2集 第二集名(豆瓣)</title></head>
<body><h1>灵笼 第一季</h1></body></html>
"""

PAGE_BLOCKED = """
<html><body><p class="loading">载入中 ...</p>
<form name="sec" id="sec"><input name="cha" value="x"></form></body></html>
"""


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.url = ""
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        self.url = url

        class R:
            status_code = 200

            def __init__(self, text):
                self.text = text

        return R(self.pages.get(url, ""))


def make_client(pages):
    m = MetadataClient("", use_bangumi=False)
    m.douban_cookie = "bid=fake; dbcl2=x"
    m.session = FakeSession(pages)
    m.delays["douban"] = 0.0
    return m


def main():
    base = "https://movie.douban.com/subject/27121260/episode/{}/"
    pages = {base.format(1): PAGE_OK, base.format(2): PAGE_TITLE_ONLY,
             base.format(3): PAGE_BLOCKED}
    m = make_client(pages)
    titles = m._douban_episode_titles("27121260", 1)
    print("titles:", titles)
    assert titles.get(1) == "灯塔和光影会", titles
    # 只有页面标题时也能取出集名
    assert titles.get(2) == "第二集名", titles
    # 第 3 集是验证页 -> 到此为止，不继续
    assert 3 not in titles, titles
    assert m.session.url.endswith("/episode/3/"), m.session.url

    # 没有 Cookie：不联网，直接空
    m2 = MetadataClient("", use_bangumi=False)
    m2.session = FakeSession({})
    assert m2._douban_episode_titles("27121260", 1) == {}
    assert m2.session.calls == 0, "没有 Cookie 时不应发请求"

    # 第 1 集就被拦截：整次放弃，避免无效连抓
    m3 = make_client({base.format(1): PAGE_BLOCKED})
    assert m3._douban_episode_titles("27121260", 1) == {}
    assert m3.session.calls == 1, m3.session.calls

    print("DOUBAN EPISODES OK")


if __name__ == "__main__":
    main()
