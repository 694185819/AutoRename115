# -*- coding: utf-8 -*-
"""「片名 01 中文本集标题」这类写法的集号识别。

用户现象：名侦探柯南：给工藤新一的挑战书 01 成为柯南前的高中生侦探.mkv
         全部「没有识别到集数，已跳过」。

原因：集号后面还跟着中文副标题，不在文件名末尾，
      RE_EP_TRAIL（只认结尾数字）抓不到。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"I:\实验\AutoRename115")

from app.parser import parse_name


def test_mid_cn_episode():
    """集号在两段中文之间 → 必须识别。"""
    cases = [
        ("名侦探柯南：给工藤新一的挑战书 01 成为柯南前的高中生侦探.mkv", 1),
        ("名侦探柯南：给工藤新一的挑战书 13 小兰之死 真凶对天才侦探的最后挑战.mkv", 13),
        ("某剧 12 第十二集的中文标题.mkv", 12),
    ]
    for name, want in cases:
        p = parse_name(name, is_dir=False)
        print(f"{name[:40]} → ep={p.episode} title={p.title[:22]!r}")
        assert p.episode == want, (name, p.episode, want)
        # 片名要干净，不能把整行都当标题
        assert "成为柯南前" not in p.title, p.title


def test_no_false_positive():
    """年份、单数字片名、分辨率不能被误判成集号。"""
    cases = [
        ("流浪地球 2049 影史最伟大.mkv", None),
        ("琅琊榜2.mkv", None),
        ("高达00 剧场版.mkv", None),
        ("冰与火之歌 1080p 中文字幕.mkv", None),
    ]
    for name, want in cases:
        p = parse_name(name, is_dir=False)
        print(f"{name[:34]} → ep={p.episode}  (期望 {want})")
        assert p.episode == want, (name, p.episode, want)


def test_existing_forms_still_work():
    """已有写法不能被破坏。"""
    cases = [
        ("将夜01.mkv", 1),
        ("名字.E05.1080p.mkv", 5),
        ("名字 第3集 标题.mkv", 3),
    ]
    for name, want in cases:
        p = parse_name(name, is_dir=False)
        assert p.episode == want, (name, p.episode, want)


def test_dir_name_unaffected():
    """目录名不受新规则影响。"""
    p = parse_name("名侦探柯南：给工藤新一的挑战书 Detective Conan "
                   "Shinichi Kudo's", is_dir=True)
    print("目录 title:", p.title, "ep:", p.episode)
    assert p.episode is None, p.episode


def main():
    test_mid_cn_episode()
    test_no_false_positive()
    test_existing_forms_still_work()
    test_dir_name_unaffected()
    print("\nEPISODE BETWEEN CJK TITLES OK")


if __name__ == "__main__":
    main()
