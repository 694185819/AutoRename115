# -*- coding: utf-8 -*-
"""本地文件模式：稳定 ID、改名、索引恢复、NFO 写入与撤销。"""
import os
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.local import LocalClient, LocalFileError, is_valid_local_name
from app.models import RenameOp
from app.undo import UndoManager


def main():
    assert is_valid_local_name("中文名 S01E01.mkv")
    assert not is_valid_local_name("bad:name.mkv")
    assert not is_valid_local_name("bad.")
    assert not is_valid_local_name("CON.txt")

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "媒体库")
        season = os.path.join(root, "Show", "Season 01")
        os.makedirs(season)
        video = os.path.join(season, "01.mkv")
        sub = os.path.join(season, "01.ass")
        with open(video, "wb") as f:
            f.write(b"video")
        with open(sub, "wb") as f:
            f.write(b"sub")
        data = os.path.join(tmp, "data")
        os.makedirs(data)
        index = os.path.join(data, "local_index.json")

        c = LocalClient(root, index_path=index)
        roots = c.list_dir(c.root_id)
        show = next(x for x in roots if x.name == "Show")
        show_id = show.fid
        seasons = c.list_dir(show_id)
        s1 = next(x for x in seasons if x.name == "Season 01")
        files = c.list_dir(s1.fid)
        one = next(x for x in files if x.name == "01.mkv")
        one_id = one.fid
        assert c.download_bytes(one.pickcode) == b"video"

        # 改名后 ID 不变，路径同步
        result = c.rename_many([
            RenameOp(fid=one_id, old_name=one.name,
                     new_name="中文名.S01E01.mkv", is_dir=False,
                     parent_id=s1.fid)])[0]
        assert result.ok, result
        assert os.path.exists(os.path.join(season, "中文名.S01E01.mkv"))
        names = {x.name: x for x in c.list_dir(s1.fid)}
        assert "中文名.S01E01.mkv" in names
        assert names["中文名.S01E01.mkv"].fid == one_id
        assert not os.path.exists(video)

        # 目录改名后，缓存中的子项路径要能继续使用
        result = c.rename_many([
            RenameOp(fid=show_id, old_name="Show", new_name="新剧名",
                     is_dir=True, parent_id=c.root_id)])[0]
        assert result.ok, result
        moved = os.path.join(root, "新剧名", "Season 01")
        assert os.path.exists(os.path.join(moved, "中文名.S01E01.mkv"))
        result = c.rename_many([
            RenameOp(fid=one_id, old_name="中文名.S01E01.mkv",
                     new_name="第二版.S01E01.mkv", is_dir=False,
                     parent_id=s1.fid)])[0]
        assert result.ok, result
        assert os.path.exists(os.path.join(moved, "第二版.S01E01.mkv"))

        # 扩展名保护和同名冲突
        bad = c.rename_many([
            RenameOp(fid=one_id, old_name="第二版.S01E01.mkv",
                     new_name="第二版.S01E01.avi", is_dir=False,
                     parent_id=s1.fid)])[0]
        assert not bad.ok and "扩展名" in bad.message, bad
        c.upload_bytes(s1.fid, "extra.nfo", b"<nfo/>")
        with open(os.path.join(moved, "目标.mkv"), "wb") as f:
            f.write(b"other")
        dup = c.rename_many([
            RenameOp(fid=one_id, old_name="第二版.S01E01.mkv",
                     new_name="目标.mkv", is_dir=False, parent_id=s1.fid)])[0]
        assert not dup.ok and "同名" in dup.message, dup
        with open(os.path.join(moved, "01.ass"), "rb") as f:
            assert f.read() == b"sub"

        # 索引重新加载后，旧 ID 仍指向改名后的路径
        c2 = LocalClient(root, index_path=index)
        assert c2.path_of(one_id).endswith("第二版.S01E01.mkv")
        assert c2.path_of(show_id).endswith("新剧名")
        extra = next(x for x in c2.list_dir(s1.fid) if x.name == "extra.nfo")
        assert c2.download_bytes(extra.pickcode) == b"<nfo/>"

        # NFO 写入、重名保护
        c2.upload_bytes(s1.fid, "poster.jpg", b"jpg")
        with open(os.path.join(moved, "poster.jpg"), "rb") as f:
            assert f.read() == b"jpg"
        try:
            c2.upload_bytes(s1.fid, "poster.jpg", b"new")
        except LocalFileError as e:
            assert "已存在" in str(e)
        else:
            raise AssertionError("重复 NFO 应被拒绝")
        try:
            c2.delete_to_recycle([one_id])
        except LocalFileError:
            pass
        else:
            raise AssertionError("本地模式不能删除")

        # 本地撤销按 scope 隔离
        undo = UndoManager(data)
        op = RenameOp(fid=one_id, old_name="第二版.S01E01.mkv",
                      new_name="第三版.S01E01.mkv", is_dir=False,
                      parent_id=s1.fid)
        res = c2.rename_many([op])
        assert undo.record([op], res, scope="local:" + os.path.normcase(root)) >= 0
        assert undo.last_undoable("cloud") is None
        assert undo.last_undoable("local:" + os.path.normcase(root)) is not None
        undo.undo_last(c2, scope="local:" + os.path.normcase(root))
        assert os.path.exists(os.path.join(moved, "第二版.S01E01.mkv"))

        # list_tree 深度正常
        tree = c2.list_tree(c2.root_id, max_depth=3)
        assert any(x.name == "Season 01" for x in tree)
        assert any(x.name == "第二版.S01E01.mkv" for x in tree)

    print("LOCAL MODE OK")


if __name__ == "__main__":
    main()
