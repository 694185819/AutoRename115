# -*- coding: utf-8 -*-
"""统一命名模板：所有媒体类型走同一套拼装。

目标：命名规则是唯一入口，媒体信息只负责填字段。
本测试确保模板引擎与旧的 naming_rule 行为完全一致（不改变既有输出）。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app import naming_rule, naming_template


def test_equivalent_to_legacy():
    """模板引擎的输出必须与旧实现逐字相同。"""
    cases = [
        ("将夜", "Ever Night", "渭城有雨，少年有侍", "2160p WEB-DL H264 AAC", 2, 1),
        ("将夜", "", "", "", 2, 1),
        ("将夜", "Ever Night", "", "", 2, 1),
        ("将夜", "", "渭城有雨", "1080p", 2, 1),
        ("灵笼", "Ling Cage", "灯塔和光影会", "1080p WEB-DL", 1, 1),
        ("葬送的芙莉莲", "Frieren", "冒险的结束", "", 1, 1),
        ("庆余年", "Joy of Life", "初入京都", "2160p WEB-DL", 2, 1),
    ]
    for title, seg, sub, specs, season, ep in cases:
        a = naming_template.build_episode_filename(
            title, season, ep, ext=".mkv", name_segment=seg,
            subtitle=sub, specs=specs)
        b = _legacy_build(title, season, ep, seg, sub, specs)
        assert a == b, f"不一致：\n  新 {a}\n  旧 {b}"


def _legacy_build(title, season, ep, seg, sub, specs):
    """旧实现的独立复刻，用于对照。"""
    tag = f"S{season:02d}E{ep:02d}"
    cn = naming_rule.sanitize_segment(title, 235, colon_to_dot=False)
    s = naming_rule.sanitize_segment(seg, 235) if seg else ""
    if s and naming_rule.norm_title(s) == naming_rule.norm_title(cn):
        s = ""
    u = naming_rule.sanitize_segment(sub, 235) if sub else ""
    spec = f" [{specs.strip()}]" if (specs or "").strip() else ""
    head = ".".join(p for p in (cn, s) if p)
    out = head
    for piece in (tag, u):
        if piece:
            out += "." + piece
    return out + spec + ".mkv"


def test_missing_fields_collapse():
    """空字段不能留下多余的点或空括号。"""
    tpl = naming_template.DEFAULT_EPISODE_TEMPLATE
    out = naming_template.render(
        tpl, {"title": "将夜", "season_ep": "S02E01"})
    print("缺字段:", repr(out))
    assert out == "将夜.S02E01", out
    assert ".." not in out
    assert "[]" not in out
    assert not out.endswith(".")


def test_movie_format():
    """电影：标题 (年份) [规格] [id]。"""
    out = naming_template.build_movie_filename(
        "朝花夕拾", 2018, ext=".mkv", specs="1080p",
        id_suffix=" [imdbid-tt9691596]")
    print("电影:", out)
    assert out == "朝花夕拾 (2018) [1080p] [imdbid-tt9691596].mkv", out
    assert "((" not in out


def test_title_with_year_not_doubled():
    """标题里已带年份时不能出现 ((2018))。"""
    out = naming_template.build_movie_filename("朝花夕拾 (2018)", 2018,
                                               ext=".mkv")
    print("带年份标题:", out)
    assert "((2018))" not in out, out
    assert out.count("2018") == 1, out


def test_episode_tag():
    """季集标记。"""
    assert naming_template.episode_tag(1, 2) == "S01E02"
    assert naming_template.episode_tag(1, 2, 3) == "S01E02-E03"
    assert naming_template.episode_tag(1, 2, version="v2") == "S01E02v2"


def main():
    test_equivalent_to_legacy()
    test_missing_fields_collapse()
    test_movie_format()
    test_title_with_year_not_doubled()
    test_episode_tag()
    print("NAMING TEMPLATE OK")


if __name__ == "__main__":
    main()
