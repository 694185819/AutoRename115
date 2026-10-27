# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")
from app.parser import parse_name

CASES = [
    ("[喵萌奶茶屋&LoliHouse] 葬送的芙莉莲 - 01 [WebRip 1080p HEVC-10bit AAC][简繁日内封字幕]",
     True, "葬送的芙莉莲", None, 1),
    ("[VCB-Studio] Sousou no Frieren [01][Ma10p_1080p][x265_flac]",
     True, "Sousou no Frieren", None, 1),
    ("Frieren.S01E03.1080p.WEB-DL.mkv", False, "Frieren", 1, 3),
    ("葬送的芙莉莲 第2季 第05集.mkv", False, "葬送的芙莉莲", 2, 5),
    ("【幻樱字幕组】★黑街 第一季【01】【BIG5】【1280X720】【MP4】",
     True, "黑街", 1, 1),
    ("Gangsta.S01E01.2015.1080p.BluRay.x264.mkv", False, "Gangsta", 1, 1),
    ("[Group] Show Title - 12v2 [1080p].mkv", False, "Show Title", None, 12),
    ("Show Title (2019) S02E03 1080p.mkv", False, "Show Title", 2, 3),
    ("Movie.Title.2019.2160p.UHD.BluRay.x265.mkv", False, "Movie Title", None, None),
    ("[Movie Title (2019)] [1080p].mkv", False, "Movie Title", None, None),
    ("朝花夕誓.2018.1080p.mkv", False, "朝花夕誓", None, None),
    ("某科学的超电磁炮T 第01话.mkv", False, "某科学的超电磁炮T", None, 1),
    ("[ReinForce] Title (BD 1920x1080 x264 FLAC)", True, "Title", None, None),
    ("Title - 01-02 [1080p].mkv", False, "Title", None, 1),
    ("S01E01.mkv", False, "", 1, 1),
    ("Season 2", True, "", 2, None),
    ("[Group] Mob Psycho 100", True, "Mob Psycho 100", None, None),
    ("[Group] Show 12", True, "Show", None, 12),
    ("[Group] 进击的巨人 最终季 Part.2 - 01 [1080p]", False,
     "进击的巨人 最终季 Part.2", None, 1),
    ("Show.Name.S02E10-E11.REPACK.1080p.mkv", False, "Show Name", 2, 10),
    ("[VCB-Studio] 86 - Eighty Six [01][Ma10p_1080p][x265_flac].mkv",
     False, "86 - Eighty Six", None, 1),
    ("SPY×FAMILY S02E01 1080p.mkv", False, "SPY×FAMILY", 2, 1),
    ("【喵萌奶茶屋】★10月新番★[葬送的芙莉莲][01][1080p][简繁日双语].mkv",
     False, "葬送的芙莉莲", None, 1),
    ("[LoliHouse] 葬送的芙莉莲 / Sousou no Frieren - 01 [WebRip 1080p].mkv",
     False, "葬送的芙莉莲", None, 1),
    # 中文名后面的英文/数字是标题的一部分，不能切掉
    ("攻壳机动队 SAC 2045", True, "攻壳机动队 SAC 2045", None, None),
    ("攻壳机动队 SAC_2045", True, "攻壳机动队 SAC 2045", None, None),
    ("攻殻機動隊 SAC_2045", True, "攻殻機動隊 SAC 2045", None, None),
    ("希德尼娅的骑士 Knights of Sidonia", True,
     "希德尼娅的骑士", None, None),
]

fail = 0
for raw, is_dir, title, season, ep in CASES:
    p = parse_name(raw, is_dir=is_dir)
    ok = (p.title == title and p.season == season and p.episode == ep)
    # 年份单独打印
    print(("OK " if ok else "FAIL") + f" | {raw!r}")
    print(f"     title={p.title!r} season={p.season} ep={p.episode} "
          f"end={p.episode_end} year={p.year} queries={p.queries[:4]}")
    if not ok:
        fail += 1

# 完整的中英混排名要保留在搜索词里，不能只剩中文部分
p = parse_name("希德尼娅的骑士 Knights of Sidonia", is_dir=True)
assert "希德尼娅的骑士 Knights of Sidonia" in p.queries, p.queries
p = parse_name("攻壳机动队 SAC_2045", is_dir=True)
assert p.queries[0] == "攻壳机动队 SAC 2045", p.queries
print("FAILED", fail)
sys.exit(1 if fail else 0)
