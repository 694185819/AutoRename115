# -*- coding: utf-8 -*-
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.metadata import MetadataClient
from app.p115 import MockP115Client
from app.planner import NamingOptions, Planner

CACHE = r"I:\实验\AutoRename115\work\metadata_cache.json"

meta = MetadataClient(CACHE, log=lambda s: print("  META:", s))
planner = Planner(meta, NamingOptions(include_imdb_id=True,
                                      imdb_id_style="jellyfin"),
                  log=lambda s: print("  PLAN:", s))
client = MockP115Client()

print("ROOT:", [(x.fid, x.name, x.is_dir) for x in client.list_dir("0")])
for root_name in ("日番", "电视剧", "电影"):
    root = next(x for x in client.list_dir("0") if x.name == root_name)
    print("\n" + "=" * 78)
    print("分析", root_name, root.fid)
    plans = planner.analyze(client, [root],
                            progress=lambda a, b, m: print(f"  [{a}/{b}] {m}"))
    for p in plans:
        print("-" * 70)
        print(f"类型={p.media_type} 分类={p.category} 状态={p.status} "
              f"置信度={p.confidence:.2f} 选中={p.selected}")
        print(f"当前: {p.current_name}")
        print(f"标题: {p.title!r} 年份={p.year} 季={p.season} "
              f"集={p.episodes} 季列表={p.seasons} 季确认={p.season_confirmed}")
        print(f"备注: {p.note}")
        print(f"  MATCH: series={p.match.series_title!r} "
              f"series_year={p.match.series_year} "
              f"series_imdb={p.match.series_imdb_id!r} "
              f"match_year={p.match.year} imdb={p.match.imdb_id!r} "
              f"country={p.match.country!r}")
        for op in p.ops:
            print(f"  [{op.role}] {op.old_name!r} -> {op.new_name!r}")
    if root_name == "日番":
        # 测试分类覆盖：把芙莉莲改成电视剧，应出现规格
        frieren = next((p for p in plans if "芙莉莲" in p.title), None)
        if frieren:
            print("\n--- 覆盖分类为 tv ---")
            frieren.category = "tv"
            planner.rebuild(frieren)
            for op in frieren.ops:
                print(f"  [{op.role}] {op.new_name!r}")
print("\ncache saved")
meta.save_cache()
