# -*- coding: utf-8 -*-
"""已有 NFO 作为元数据锚点：优先用 NFO 的 ID/标题，不再先搜标题。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import MatchResult, P115Item
from app.nfo import parse_nfo_bytes
from app.planner import NamingOptions, Planner


class FakeClient:
    def __init__(self, tree, nfo_map):
        self.tree = tree
        self.nfo_map = nfo_map
        self.download_calls = []

    def list_dir(self, cid):
        return list(self.tree.get(cid, []))

    def download_bytes(self, pickcode, max_size=2 * 1024 * 1024):
        self.download_calls.append((pickcode, max_size))
        return self.nfo_map.get(pickcode, b"")


class FakeMeta:
    def __init__(self):
        self.match_calls = 0
        self.id_calls = []

    def match(self, parsed, media_type, category_hint=""):
        self.match_calls += 1
        return MatchResult()

    def match_by_ids(self, imdb_id, tmdb_id, media_type,
                     fallback_title=""):
        self.id_calls.append((imdb_id, tmdb_id, media_type, fallback_title))
        if media_type == "movie":
            titles = {"900": "电影甲", "901": "电影乙"}
            title = titles.get(tmdb_id, fallback_title or "NFO 电影")
            return MatchResult(
                title_zh=title, title_original=title, year=2021,
                tmdb_id=tmdb_id, imdb_id=imdb_id,
                confidence=1.0)
        return MatchResult(
            title_zh="NFO 剧名", title_original="NFO Show",
            year=2020, series_title="NFO 剧名", series_year=2020,
            tmdb_id=tmdb_id or "999", imdb_id=imdb_id or "tt999999",
            series_imdb_id=imdb_id or "tt999999",
            country="jp", animation=True, confidence=1.0)

    def season_episode_titles(self, *args, **kwargs):
        return {}

    def save_cache(self):
        pass


def main():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <tvshow>
      <title>NFO 剧名</title>
      <originaltitle>NFO Show</originaltitle>
      <year>2020</year>
      <uniqueid type="tmdb" default="true">999</uniqueid>
      <uniqueid type="imdb">tt999999</uniqueid>
    </tvshow>""".encode("utf-8")
    parsed = parse_nfo_bytes(xml)
    assert parsed["title"] == "NFO 剧名", parsed
    assert parsed["year"] == 2020, parsed
    assert parsed["tmdb_id"] == "999", parsed
    assert parsed["imdb_id"] == "tt999999", parsed

    root = P115Item(fid="show", parent_id="jp",
                    name="乱码目录名", is_dir=True,
                    ancestors=["动画", "日番"])
    nfo = P115Item(fid="n1", parent_id="show", name="tvshow.nfo",
                   is_dir=False, pickcode="p1")
    video = P115Item(fid="v1", parent_id="show",
                     name="Show.S01E01.mkv", is_dir=False)
    client = FakeClient({"show": [nfo, video]}, {"p1": xml})
    meta = FakeMeta()
    plan = Planner(meta, NamingOptions()).analyze(client, [root])[0]
    assert client.download_calls, client.download_calls
    assert client.download_calls[0][0] == "p1"
    assert meta.id_calls and meta.id_calls[0][1] == "999", meta.id_calls
    assert meta.match_calls == 0, meta.match_calls
    assert plan.title == "NFO 剧名", plan.title
    assert plan.year == 2020, plan.year
    assert plan.match.tmdb_id == "999", plan.match.tmdb_id
    assert "NFO" in plan.note, plan.note

    # 电影库根目录里每部电影用自己的 NFO，不能拿错同目录别的 NFO
    lib = P115Item(fid="lib", parent_id="0", name="电影", is_dir=True)
    va = P115Item(fid="ma", parent_id="lib", name="Movie.A.2020.mkv",
                  is_dir=False)
    vb = P115Item(fid="mb", parent_id="lib", name="Movie.B.2021.mkv",
                  is_dir=False)
    na = P115Item(fid="na", parent_id="lib", name="Movie.A.2020.nfo",
                  is_dir=False, pickcode="pa")
    nb = P115Item(fid="nb", parent_id="lib", name="Movie.B.2021.nfo",
                  is_dir=False, pickcode="pb")
    xa = """<?xml version="1.0" encoding="UTF-8"?>
    <movie><title>电影 A</title><year>2020</year>
    <uniqueid type="tmdb">900</uniqueid></movie>""".encode("utf-8")
    xb = """<?xml version="1.0" encoding="UTF-8"?>
    <movie><title>电影 B</title><year>2021</year>
    <uniqueid type="tmdb">901</uniqueid></movie>""".encode("utf-8")
    client2 = FakeClient({"lib": [va, vb, na, nb]}, {"pa": xa, "pb": xb})
    meta2 = FakeMeta()
    plans = Planner(meta2, NamingOptions()).analyze(client2, [lib])
    got = {p.match.tmdb_id: p.title for p in plans if p.media_type == "movie"}
    assert got.get("900") == "电影甲", got
    assert got.get("901") == "电影乙", got
    assert meta2.match_calls == 0, meta2.match_calls
    print("NFO ANCHOR OK")


if __name__ == "__main__":
    main()
