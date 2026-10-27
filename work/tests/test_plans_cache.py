# -*- coding: utf-8 -*-
"""预览缓存：重启后恢复上次等待列表，并严格核对文件是否仍在原处。"""
import os
import sys
import tempfile

sys.path.insert(0, r"I:\实验\AutoRename115")

from app.gui import App
from app.local import LocalClient
from app.models import ParsedName, P115Item, PlanItem, RenameOp


class DirClient:
    """带可配置目录内容的假客户端。"""

    def __init__(self, root, tree):
        self.root = root
        self.tree = tree

    def list_dir(self, cid, page_size=500):
        return list(self.tree.get(cid, []))

    def risk_cooldown_remaining(self):
        return 0


def make_plan():
    folder = P115Item(fid="root", parent_id="0", name="A 某剧", is_dir=True,
                      ancestors=["动画"])
    videos = [P115Item(fid=f"v{i}", parent_id="root",
                       name=f"A 某剧 S01E{i:02d}.mkv", is_dir=False, size=100)
              for i in (1, 2)]
    p = PlanItem(item=folder, media_type="series",
                 parsed=ParsedName(raw=folder.name, title="某剧"))
    p.ops = [RenameOp(fid=v.fid, old_name=v.name,
                      new_name=f"某剧 S01E{i:02d}.mkv", is_dir=False)
             for i, v in enumerate(videos, 1)]
    return p, videos


def main():
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = os.path.join(tmp, "app")
        local_root = os.path.join(tmp, "media")
        os.makedirs(local_root)

        app = App(app_dir)
        app.withdraw()
        p, videos = make_plan()
        client = DirClient(local_root, {"root": videos})
        app.client = client
        app.local_client = LocalClient(
            local_root, index_path=os.path.join(tmp, "idx.json"))
        app.local_root = local_root
        app.is_local = True
        app.is_demo = False
        app.plans = [p]
        app._render_plans()
        app._save_plans_cache()
        assert os.path.exists(app._plans_cache_path()), "缓存文件没有写出"

        # 同一账号/根目录启动：能恢复
        app2 = App(app_dir)
        app2.withdraw()
        app2.is_local = True
        app2.local_client = app.local_client
        app2.local_root = local_root
        app2.client = DirClient(local_root, {"root": videos})
        assert app2._restore_plans(), "同一根目录应能恢复预览缓存"
        assert len(app2.plans) == 1, app2.plans
        assert app2.plans[0].item.name == "A 某剧", app2.plans[0].item.name

        # 文件已被改名/删除：核对失败，缓存整批作废
        ok, reason = app2._verify_plans(
            DirClient(local_root, {"root": videos[:1]}))
        assert not ok and "不在原文件夹" in reason, (ok, reason)

        # 换了根目录：不能把 A 目录的预览恢复到 B 目录
        app3 = App(app_dir)
        app3.withdraw()
        app3.is_local = True
        app3.local_root = os.path.join(tmp, "other")
        app3.local_client = type("L", (), {"root": os.path.join(tmp, "other")})()
        app3.client = DirClient(os.path.join(tmp, "other"), {})
        assert not app3._restore_plans(), "根目录不同时不能恢复"

        # 关闭“记住上次分析结果”后不再写盘
        app2.settings["remember_plans"] = False
        app2._save_plans_cache()
        assert not os.path.exists(app2._plans_cache_path()), "关闭后不应保留缓存"

        # 手动清空任务时同步作废缓存
        app.settings["remember_plans"] = True
        app._save_plans_cache()
        assert os.path.exists(app._plans_cache_path())
        app._discard_plans_cache()
        assert not os.path.exists(app._plans_cache_path())

        for a in (app, app2, app3):
            try:
                a.destroy()
            except Exception:
                pass
    print("PLANS CACHE OK")


if __name__ == "__main__":
    main()
