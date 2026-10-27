# -*- coding: utf-8 -*-
"""DSNP / DSNY / -ZeroTV 等发布标记不能留在标题里。"""
import sys
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name


def main():
    en = parse_name(
        "What.If.S02.2023.2160p.DSNP.WEB-DL.H265.HDR.DDP5.1.Atmos-ZeroTV",
        is_dir=True)
    assert en.title == "What If", en.title
    assert en.queries == ["What If"], en.queries

    cn = parse_name(
        "假如...? What.If.S02.2160p.DSNP.WEB-DL.H265.HDR.DDP5.1.Atmos-ZeroTV",
        is_dir=True)
    assert cn.title == "假如...?", cn.title

    ep = parse_name(
        "What.If.S02E01.2023.2160p.DSNP.WEB-DL.H265.HDR.DDP5.1.Atmos-ZeroTV.mkv")
    assert ep.title == "What If", ep.title
    assert ep.season == 2 and ep.episode == 1

    chd = parse_name(
        "假如...? What.If.S03.2160p.Disney+ WEB-DL.DDP5.1.Atmos.HDR10-CHDWEB",
        is_dir=True)
    assert chd.title == "假如...?", chd.title
    print("RELEASE TAGS OK")


if __name__ == "__main__":
    main()
