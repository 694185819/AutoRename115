# -*- coding: utf-8 -*-
"""重命名撤销记录。只记录成功的重命名，撤销时先核对当前名字。"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from .models import RenameOp
from .p115 import RenameResult


class UndoManager:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "undo.json")
        self.batches: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("batches"), list):
                    self.batches = data["batches"]
        except Exception:
            self.batches = []

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"batches": self.batches[-20:]}, f,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def record(self, ops: list[RenameOp], results: list[RenameResult],
               scope: str = "cloud") -> int:
        ok_ids = {r.fid for r in results if r.ok}
        done = [o for o in ops if o.fid in ok_ids]
        if not done:
            return -1
        self.batches.append({
            "time": int(time.time()),
            "undone": False,
            "scope": scope or "cloud",
            "ops": [{
                "fid": o.fid, "old_name": o.old_name, "new_name": o.new_name,
                "is_dir": o.is_dir, "parent_id": o.parent_id, "role": o.role,
            } for o in done],
        })
        self._save()
        return len(self.batches) - 1

    def last_undoable(self, scope: Optional[str] = None
                      ) -> Optional[tuple[int, dict]]:
        for i in range(len(self.batches) - 1, -1, -1):
            b = self.batches[i]
            if b.get("undone") or not b.get("ops"):
                continue
            # 旧记录没有 scope，按 115 网盘处理；本地/演示记录互不串用。
            if scope is not None and str(b.get("scope") or "cloud") != scope:
                continue
            return i, b
        return None

    def mark_undone(self, index: int) -> None:
        if 0 <= index < len(self.batches):
            self.batches[index]["undone"] = True
            self._save()

    def undo_last(self, client, log=None,
                  scope: Optional[str] = None) -> list[RenameResult]:
        log = log or (lambda s: None)
        found = self.last_undoable(scope)
        if not found:
            log("没有可以撤销的重命名记录。")
            return []
        index, batch = found
        # 按父目录缓存当前列表，核对名字后再改回
        cache: dict[str, dict[str, str]] = {}

        def name_of(parent_id: str, fid: str) -> Optional[str]:
            if parent_id not in cache:
                try:
                    cache[parent_id] = {i.fid: i.name
                                        for i in client.list_dir(parent_id)}
                except Exception as e:
                    log(f"读取目录失败，无法撤销部分项目：{e}")
                    cache[parent_id] = {}
            return cache[parent_id].get(fid)

        back: list[RenameOp] = []
        skipped = 0
        for o in reversed(batch["ops"]):
            current = name_of(str(o.get("parent_id", "")), str(o["fid"]))
            if current != o["new_name"]:
                if current is None:
                    log(f"找不到文件 {o['fid']}，已跳过。")
                else:
                    log(f"当前名字已变化（{o['old_name']} → {current}），已跳过。")
                skipped += 1
                continue
            back.append(RenameOp(fid=o["fid"], old_name=o["new_name"],
                                 new_name=o["old_name"],
                                 is_dir=bool(o.get("is_dir")),
                                 role=o.get("role", ""),
                                 parent_id=str(o.get("parent_id", ""))))
        if not back:
            log("没有项目需要撤销。")
            return []
        results = client.rename_many(back)
        ok = sum(1 for r in results if r.ok)
        log(f"撤销完成：成功 {ok} 个" + (f"，跳过 {skipped} 个" if skipped else ""))
        # 只有全部改回成功才标记整批完成；部分失败时保留记录，方便再次撤销
        if results and all(r.ok for r in results):
            self.mark_undone(index)
        return results
