# -*- coding: utf-8 -*-
"""设置里的敏感字段不能被空值/模板覆盖。

事故背景：豆瓣 Cookie 输入框预置了拼接模板（含「这里填dbcl2的值」），
用户打开设置直接保存时，模板被当成真值写进 settings.json，
把原先填好的真实 Cookie 覆盖掉；同时空值也会覆盖已有的 TMDB Key。
"""
import sys

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import (DOUBAN_COOKIE_TEMPLATE, clean_douban_cookie,
                     merge_settings_safely)


def test_template_not_saved():
    """模板占位符不能被当成真 Cookie 保存。"""
    assert clean_douban_cookie(DOUBAN_COOKIE_TEMPLATE) == ""


def test_real_cookie_kept():
    """真实 Cookie 原样保留。"""
    real = "dbcl2=12345:abc; bid=xyz789; ck=Qk3f"
    assert clean_douban_cookie(real) == real


def test_empty_stays_empty():
    assert clean_douban_cookie("") == ""
    assert clean_douban_cookie("   ") == ""


def test_empty_does_not_overwrite():
    """空值不能覆盖已有的非空值（Cookie / TMDB Key）。"""
    old = {"douban_cookie": "dbcl2=REAL; bid=x", "tmdb_key": "abc123",
           "use_bangumi": True}
    new = {"douban_cookie": "", "tmdb_key": "", "use_bangumi": False}
    merged = merge_settings_safely(old, new)
    assert merged["douban_cookie"] == "dbcl2=REAL; bid=x", merged
    assert merged["tmdb_key"] == "abc123", merged
    # 非空的新值正常覆盖
    assert merged["use_bangumi"] is False, merged


def test_new_values_applied():
    """用户真的填了新值时正常生效。"""
    old = {"tmdb_key": "old"}
    new = {"tmdb_key": "newkey"}
    assert merge_settings_safely(old, new)["tmdb_key"] == "newkey"


def test_new_key_added():
    """原来没有的键要能加上。"""
    merged = merge_settings_safely({}, {"tmdb_key": "k1"})
    assert merged["tmdb_key"] == "k1"


def main():
    test_template_not_saved()
    test_real_cookie_kept()
    test_empty_stays_empty()
    test_empty_does_not_overwrite()
    test_new_values_applied()
    test_new_key_added()
    print("SETTINGS SAFETY OK")


if __name__ == "__main__":
    main()
