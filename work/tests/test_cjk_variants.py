# -*- coding: utf-8 -*-
"""中文一字之差导致某站搜不到时，用异体字变体补搜。

实例：目录名「东离剑游记」，TMDB 收录的是「东离剑游纪」（记/纪 不同），
按原词搜索返回 0 条 → TMDB 条目匹配不上 → 英文名段为空 →
用户以为「英文名段不显示」把英文名关掉了。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.metadata import _cjk_variants


def test_variants_generated():
    """记→纪 这类替换要能生成出来。"""
    got = _cjk_variants("东离剑游记")
    print("东离剑游记 →", got)
    assert "东离剑游纪" in got, got


def test_variants_contain_original_free_set():
    """生成的变体不应包含原词本身。"""
    got = _cjk_variants("东离剑游记")
    assert "东离剑游记" not in got, got


def test_variants_limit():
    """变体数量要有上限，避免疯狂请求。"""
    got = _cjk_variants("東離劍遊紀傳說戰役")
    print(f"长串变体 {len(got)} 个")
    assert len(got) <= 6, len(got)


def test_empty_input():
    assert _cjk_variants("") == []
    assert _cjk_variants("   ") == []


def test_no_swap_chars():
    """没有可替换字时返回空（不该乱造词）。"""
    got = _cjk_variants("青云志")
    print("青云志 →", got)
    assert got == [], got


def main():
    test_variants_generated()
    test_variants_contain_original_free_set()
    test_variants_limit()
    test_empty_input()
    test_no_swap_chars()
    print("\nCJK VARIANTS OK")


if __name__ == "__main__":
    main()
