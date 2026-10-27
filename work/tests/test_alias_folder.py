# -*- coding: utf-8 -*-
"""目录中文名 / 文件日文别名不同时，剧集文件夹仍然要参与改名。"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.models import Candidate, MatchResult, P115Item, ParsedName
from app.planner import Planner


class Client:
    def __init__(self, root, files):
        self.items = {root.fid: root}
        self.children = {root.fid: []}
        for i, name in enumerate(files, 1):
            item = P115Item(fid=f"f{i}", parent_id=root.fid, name=name,
                            is_dir=False, size=100)
            self.items[item.fid] = item
            self.children[root.fid].append(item.fid)

    def list_dir(self, cid="0", page_size=500):
        return [self.items[x] for x in self.children.get(str(cid), [])]

    def list_tree(self, cid="0", max_depth=1, include_files=True):
        return []

    def download_bytes(self, *args, **kwargs):
        return b""


class Meta:
    def match(self, parsed, media_type, category_hint=""):
        title = "女子落语" if "女子" in parsed.title else parsed.title
        original = "じょしらく" if title == "女子落语" else parsed.title
        m = MatchResult(
            title_zh=title, title_original=original, year=2012,
            tmdb_id="999", imdb_id="tt999", confidence=1.0)
        m.series_title = title
        m.series_original_title = original
        m.series_year = 2012
        m.tmdb = Candidate(source="tmdb", title=title,
                           original_title=original, year=2012,
                           sid="999", kind="tv")
        return m

    def save_cache(self):
        pass


def plans_for(folder, files):
    root = P115Item(fid="root", parent_id="0", name=folder,
                    is_dir=True, ancestors=["动画"])
    return Planner(Meta()).analyze(Client(root, files), [root])


def main():
    episodes = [
        f"[Group] じょしらく S01E{i:02d}.第{i}话.m2ts"
        for i in range(1, 14)]
    ova = "[Group] じょしらく OVA.台無屋 / 三軒本屋 / びっくり集.m2ts"

    for folder in (
            "[BD-REMUX]女子落语 [じょしらく]",
            "[BD-REMUX]女子落语"):
        plans = plans_for(folder, episodes + [ova])
        series = [p for p in plans if p.media_type == "series"]
        movies = [p for p in plans if p.media_type == "movie"]
        assert len(series) == 1, (folder, [(p.item.name, p.media_type)
                                          for p in plans])
        p = series[0]
        assert p.item.is_dir, (folder, p.item.name)
        assert p.rename_root, (folder, p.rename_root)
        assert any(op.is_dir and op.old_name == folder for op in p.ops), p.ops
        assert sum(1 for op in p.ops if not op.is_dir) >= 13, p.ops
        assert len(movies) == 1 and movies[0].item.name == ova, movies

    # 真正的多剧合集（两个不同剧名）不能把合集目录改成其中一部
    folder = "[BD-REMUX]某合集"
    files = [f"A S01E{i:02d}.m2ts" for i in range(1, 3)] + \
            [f"B S01E{i:02d}.m2ts" for i in range(1, 3)]
    plans = plans_for(folder, files)
    assert len(plans) == 2, plans
    assert all(not p.rename_root for p in plans), [
        (p.item.name, p.rename_root) for p in plans]
    assert all(not p.item.is_dir for p in plans), [
        (p.item.name, p.item.is_dir) for p in plans]

    # 精确目录名不能被搜索返回的同名番外/季条目抢走
    match = MatchResult(
        title_zh="葬送的芙莉莲", series_title="葬送的芙莉莲", year=2023)
    match.bangumi = Candidate(
        source="bangumi", title="葬送的芙莉莲 ~●●的魔法~",
        original_title="葬送のフリーレン ~●●の魔法~", year=2023, sid="1")
    parsed = ParsedName(raw="葬送的芙莉莲", title="葬送的芙莉莲",
                        queries=["葬送的芙莉莲"])
    planner = Planner(None)
    assert planner._online_series_title(match, 2023, parsed) == "葬送的芙莉莲"
    parsed2 = ParsedName(raw="庆余年 第二季", title="庆余年 第二季",
                         queries=["庆余年 第二季"], season=2)
    match2 = MatchResult(title_zh="庆余年", series_title="庆余年", year=2019)
    assert planner._online_series_title(match2, 2019, parsed2) == "庆余年"

    print("ALIAS FOLDER OK")


if __name__ == "__main__":
    main()
