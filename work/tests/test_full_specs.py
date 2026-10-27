# -*- coding: utf-8 -*-
"""电视剧/欧美动画规格尽量保留 HDR/DV/声道等详细信息。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")
from app.parser import parse_name, quality_suffix


def check(name, must):
    p = parse_name(name)
    q = quality_suffix(p)
    print(name, "->", q)
    for token in must:
        assert token.lower() in q.lower(), (name, token, q)
    return q


q = check(
    "Show.S01E01.2160p.WEB-DL.HDR10.DV.x265.10bit.DDP5.1.Atmos.mkv",
    ["2160p", "WEB-DL", "HDR10", "DV", "x265", "10bit", "DDP5.1", "Atmos"])
assert "HDR" not in q.replace("HDR10", ""), q
assert "DDP5.1 Atmos" in q, q
assert "DDP Atmos 5.1" not in q, q

check("Show.S01E02.1080p.BluRay.REMUX.AVC.FLAC.2.0.mkv",
      ["1080p", "BluRay", "REMUX", "AVC", "FLAC", "2.0"])
check("Show.S01E03.2160p.Dolby.Vision.TrueHD.Atmos.7.1.mkv",
      ["2160p", "Dolby.Vision", "TrueHD", "Atmos", "7.1"])
check("Show.S01E04.1080p.BluRay.x264.DTS-HD.MA.5.1.mkv",
      ["1080p", "BluRay", "x264", "DTS-HD", "MA", "5.1"])
check("Show.S01E05.2160p.UHD.BluRay.HDR10+.DoVi.x265.12bit.mkv",
      ["2160p", "UHD", "BluRay", "HDR10+", "DoVi", "x265", "12bit"])
check("Show.S01E07.2160p.WEB-DL.TrueHD7.1.2.Atmos.mkv",
      ["2160p", "WEB-DL", "TrueHD7.1.2", "Atmos"])
check("Show.S01E08.2160p.WEB-DL.AAC2.0.mkv", ["2160p", "AAC2.0"])

# HDR/DV 不应该被当成标题的一部分
p = parse_name("Show.S01E06.2160p.HDR10.DV.WEB-DL.mkv")
assert p.title == "Show", p.title
assert p.episode == 6, p.episode

print("FULL SPECS OK")
