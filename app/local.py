# -*- coding: utf-8 -*-
"""本地文件夹模式：用和 115 相同的列表/改名接口浏览本机目录。

本地模式只做重命名和用户明确要求保存的 NFO/图片；不删除、不移动文件，
也不会改动 115 网盘。目录项使用文件系统 inode 作为稳定 ID，
这样改名后撤销记录仍然能找回同一项。
"""
from __future__ import annotations

import json
import os
import stat as stat_module
from typing import Callable, Optional

from .models import P115Item, RenameOp
from .p115 import RenameResult, _natural_key

_LOCAL_INDEX_VERSION = 1
_REPARSE_POINT = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class LocalFileError(Exception):
    pass


def is_valid_local_name(name: str) -> bool:
    """Windows 文件名检查；不含路径分隔符，也不允许保留设备名。"""
    name = str(name or "")
    if not name or name in (".", ".."):
        return False
    if any(ch in name for ch in '<>:"/\\|?*') or \
            any(ord(ch) < 32 for ch in name):
        return False
    if name.endswith((" ", ".")):
        return False
    if name.split(".", 1)[0].strip().upper() in _RESERVED_NAMES:
        return False
    return True


class LocalClient:
    """本地目录适配器，接口与 P115Client 的浏览/改名部分保持一致。"""

    def __init__(self, root: str, index_path: str = "",
                 log: Optional[Callable[[str], None]] = None):
        self.root = os.path.abspath(os.path.realpath(root))
        if not os.path.isdir(self.root):
            raise LocalFileError(f"本地文件夹不存在：{root}")
        self.index_path = index_path
        self.log = log or (lambda s: None)
        self._paths: dict[str, str] = {}
        self._ids: dict[str, str] = {}
        self._dirty = False
        self._index_auto_save = True
        self._load_index()
        self.root_id = self._register(self.root)
        if not self.root_id:
            raise LocalFileError(f"无法读取本地文件夹：{root}")

    # ------------------------------------------------------------ 路径/ID
    @staticmethod
    def _file_id(path: str) -> str:
        st = os.stat(path, follow_symlinks=False)
        return f"L{st.st_dev:x}-{st.st_ino:x}"

    def _within_root(self, path: str) -> bool:
        try:
            path = os.path.normcase(os.path.abspath(path))
            root = os.path.normcase(self.root)
            return os.path.commonpath([root, path]) == root
        except (ValueError, OSError):
            return False

    def _register(self, path: str) -> str:
        path = os.path.abspath(path)
        if not self._within_root(path):
            return ""
        try:
            fid = self._file_id(path)
        except OSError:
            return ""
        key = os.path.normcase(path)
        old = self._ids.get(key)
        old_path = self._paths.get(fid)
        if old and old != fid:
            self._paths.pop(old, None)
            self._dirty = True
        self._paths[fid] = path
        self._ids[key] = fid
        if old != fid or old_path != path:
            self._dirty = True
        return fid

    def _resolve(self, fid: str) -> str:
        path = self._paths.get(str(fid or ""))
        if path and os.path.exists(path):
            return path
        return ""

    def _register_child(self, entry: os.DirEntry, cid: str) -> Optional[P115Item]:
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        # 不跟随符号链接/目录联接，避免本地模式意外跳出选定目录。
        if entry.is_symlink() or (
                getattr(st, "st_file_attributes", 0) & _REPARSE_POINT):
            return None
        if not (entry.is_dir(follow_symlinks=False) or
                entry.is_file(follow_symlinks=False)):
            return None
        path = os.path.abspath(entry.path)
        fid = self._register(path)
        if not fid:
            return None
        return P115Item(
            fid=fid, parent_id=cid, name=entry.name,
            is_dir=entry.is_dir(follow_symlinks=False),
            size=int(st.st_size) if entry.is_file(follow_symlinks=False) else 0,
            pickcode=path,
            updated=str(int(st.st_mtime)),
        )

    def root_item(self) -> P115Item:
        name = os.path.basename(self.root.rstrip("\\/")) or self.root
        return P115Item(
            fid=self.root_id, parent_id="", name=name, is_dir=True,
            pickcode=self.root)

    def path_of(self, fid: str) -> str:
        return self._resolve(fid)

    # ------------------------------------------------------------ 索引
    def _load_index(self) -> None:
        if not self.index_path or not os.path.exists(self.index_path):
            return
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            if os.path.normcase(str(data.get("root") or "")) != \
                    os.path.normcase(self.root):
                return
            items = data.get("items")
            if not isinstance(items, dict):
                return
            for fid, rel in items.items():
                if not isinstance(fid, str) or not isinstance(rel, str):
                    continue
                path = os.path.abspath(os.path.join(self.root, rel))
                if not self._within_root(path) or not os.path.exists(path):
                    continue
                try:
                    actual = self._file_id(path)
                except OSError:
                    continue
                if actual != fid:
                    continue
                self._paths[fid] = path
                self._ids[os.path.normcase(path)] = fid
        except Exception as e:
            self.log(f"读取本地目录索引失败：{e}")

    def _save_index(self) -> None:
        if not self.index_path or not self._dirty:
            return
        items = {}
        for fid, path in self._paths.items():
            if path == self.root or not os.path.exists(path):
                continue
            if not self._within_root(path):
                continue
            try:
                items[fid] = os.path.relpath(path, self.root)
            except ValueError:
                continue
        data = {"version": _LOCAL_INDEX_VERSION,
                "root": self.root, "items": items}
        try:
            parent = os.path.dirname(self.index_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = self.index_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=0)
            os.replace(tmp, self.index_path)
            self._dirty = False
        except Exception as e:
            self.log(f"保存本地目录索引失败：{e}")

    # ------------------------------------------------------------ 浏览
    def list_dir(self, cid: str = "0", page_size: int = 500) -> list[P115Item]:
        path = self._resolve(cid)
        if not path:
            raise LocalFileError("本地文件夹已移动或不可访问，请重新选择文件夹。")
        if not os.path.isdir(path):
            raise LocalFileError(f"不是文件夹：{path}")
        items: list[P115Item] = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    item = self._register_child(entry, str(cid))
                    if item is not None:
                        items.append(item)
        except PermissionError as e:
            raise LocalFileError(f"没有权限读取：{path}") from e
        items.sort(key=lambda x: (not x.is_dir, _natural_key(x.name)))
        if self._index_auto_save:
            self._save_index()
        return items

    def list_tree(self, cid: str = "0", max_depth: int = 1,
                  include_files: bool = True) -> list[P115Item]:
        result: list[P115Item] = []
        old_auto = self._index_auto_save
        self._index_auto_save = False
        try:
            def walk(parent: str, depth: int) -> None:
                for it in self.list_dir(parent):
                    if it.is_dir:
                        result.append(it)
                        if depth < max_depth:
                            walk(it.fid, depth + 1)
                    elif include_files:
                        result.append(it)

            walk(str(cid), 1)
        finally:
            self._index_auto_save = old_auto
            self._save_index()
        return result

    def download_bytes(self, pickcode: str,
                       max_size: int = 2 * 1024 * 1024) -> bytes:
        path = str(pickcode or "")
        if not path or not self._within_root(path) or not os.path.isfile(path):
            return b""
        try:
            with open(path, "rb") as f:
                return f.read(max(0, int(max_size)))
        except OSError:
            return b""

    # ------------------------------------------------------------ 写入
    @staticmethod
    def _same_path(a: str, b: str) -> bool:
        return os.path.normcase(os.path.abspath(a)) == \
            os.path.normcase(os.path.abspath(b))

    def _rename_one(self, op: RenameOp) -> RenameResult:
        src = self._resolve(op.fid)
        if not src:
            return RenameResult(op.fid, op.old_name, op.new_name, False,
                                "本地项目已移动或不可访问")
        if not is_valid_local_name(op.new_name):
            return RenameResult(op.fid, op.old_name, op.new_name, False,
                                "文件名包含 Windows 不允许的字符")
        if not op.is_dir:
            old_ext = os.path.splitext(src)[1]
            new_ext = os.path.splitext(op.new_name)[1]
            if old_ext.casefold() != new_ext.casefold():
                return RenameResult(op.fid, op.old_name, op.new_name, False,
                                    "不允许修改扩展名")
        parent = os.path.dirname(src)
        dst = os.path.join(parent, op.new_name)
        if not self._within_root(dst):
            return RenameResult(op.fid, op.old_name, op.new_name, False,
                                "目标路径超出已选文件夹")
        if os.path.exists(dst) and not self._same_path(src, dst):
            return RenameResult(op.fid, op.old_name, op.new_name, False,
                                "同名文件已存在")
        if src == dst:
            return RenameResult(op.fid, op.old_name, op.new_name, True)
        old_path = src
        try:
            if self._same_path(src, dst):
                # Windows 大小写改名：先换到临时名，失败时尽量改回。
                tmp = os.path.join(
                    parent, f".autorstmp-{os.getpid()}-{op.fid}.tmp")
                os.rename(src, tmp)
                try:
                    os.rename(tmp, dst)
                except Exception:
                    try:
                        os.rename(tmp, src)
                    except OSError:
                        pass
                    raise
            else:
                os.rename(src, dst)
        except OSError as e:
            return RenameResult(op.fid, op.old_name, op.new_name, False,
                                str(e))
        self._replace_cached_path(op.fid, old_path, dst)
        return RenameResult(op.fid, op.old_name, op.new_name, True)

    def _replace_cached_path(self, fid: str, old_path: str, new_path: str) -> None:
        old_key = os.path.normcase(old_path)
        self._ids.pop(old_key, None)
        self._paths[fid] = new_path
        self._ids[os.path.normcase(new_path)] = fid
        # 目录改名后，缓存中所有子项路径也要跟着换前缀。
        old_prefix = old_path.rstrip("\\/") + os.sep
        new_prefix = new_path.rstrip("\\/") + os.sep
        old_norm = os.path.normcase(old_prefix)
        for other, path in list(self._paths.items()):
            if other == fid:
                continue
            if os.path.normcase(path).startswith(old_norm):
                moved = new_prefix + path[len(old_prefix):]
                self._paths[other] = moved
                self._ids.pop(os.path.normcase(path), None)
                self._ids[os.path.normcase(moved)] = other
        self._dirty = True

    def rename_many(self, ops: list[RenameOp], chunk_size: int = 20,
                    progress=None) -> list[RenameResult]:
        results: list[RenameResult] = []
        total = max(1, len(ops))
        for i, op in enumerate(ops, 1):
            result = self._rename_one(op)
            results.append(result)
            if result.ok:
                self.log(f"本地改名：{op.old_name} → {op.new_name}")
            else:
                self.log(f"本地改名失败：{op.old_name}：{result.message}")
            if progress:
                progress(i, total)
        self._save_index()
        return results

    def upload_bytes(self, cid: str, filename: str, data: bytes,
                     mime: str = "application/octet-stream") -> None:
        path = self._resolve(cid)
        if not path or not os.path.isdir(path):
            raise LocalFileError("目标文件夹已移动或不可访问")
        if not is_valid_local_name(filename) or filename != \
                os.path.basename(filename):
            raise LocalFileError(f"非法的文件名：{filename}")
        target = os.path.join(path, filename)
        if not self._within_root(target):
            raise LocalFileError("目标路径超出已选文件夹")
        if os.path.exists(target):
            raise LocalFileError(f"同名文件已存在：{filename}")
        try:
            with open(target, "xb") as f:
                f.write(data)
        except FileExistsError as e:
            raise LocalFileError(f"同名文件已存在：{filename}") from e
        except OSError as e:
            raise LocalFileError(f"写入失败：{filename}：{e}") from e
        self._register(target)
        self._save_index()

    def delete_to_recycle(self, fids: list[str]) -> int:
        # 本地模式不允许删除/移到回收站，清空 NFO 的入口在界面层禁用。
        raise LocalFileError("本地模式不会删除文件")

    # ---- 与 P115Client 相同的少量兼容接口
    def is_logged_in(self, force: bool = False) -> bool:
        return True

    def cookie_dict(self) -> dict:
        return {"LOCAL": self.root}

    def logout(self) -> None:
        pass

    def set_cookie_text(self, text: str) -> None:
        pass

    def risk_cooldown_remaining(self) -> int:
        return 0

    def find_item(self, fid: str, parent_id: str = "") -> Optional[P115Item]:
        path = self._resolve(fid)
        if not path:
            return None
        return P115Item(
            fid=fid, parent_id=parent_id,
            name=os.path.basename(path), is_dir=os.path.isdir(path),
            size=os.path.getsize(path) if os.path.isfile(path) else 0,
            pickcode=path)
