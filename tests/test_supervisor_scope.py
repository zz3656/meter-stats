"""主管权限边界测试(标准库 unittest,零依赖)。

用户提出:分店主管应当只能看/改本店数据。核对后的事实是 ——
**业务数据的读写早就按店了**(routing._store_gate 统一拦),但"管理面"还有几处是全站的:

- 5 个**部署级全局配置**(备份目录 / NAS 凭据 / 自动备份开关 / 保留份数 / 图片目录)
  写的是顶层 settings.json,一家店的主管改了会波及全站 → 收归管理员
- 目录列举原来只校验"在 data_dir 之下",而 data_dir 里就有 stores/ →
  本店主管能把别家门店目录列出来
- 审计日志全站可见,且记录里没有门店字段 → 无法按店过滤
- 备份**下载**有门店闸,但**删除**没有 → 主管能删掉含别家数据的全量包

主管**保留**的能力:本店数据读写、本店电表配置、手动备份本店、恢复本店范围、
本店范围内的备份列表/下载/删除、数据文件列表。

运行:
    python3 -m unittest tests.test_supervisor_scope -v
"""
from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "MeterStats"))
sys.path.insert(0, str(TESTS_DIR))

from modules.stores import config, context  # noqa: E402
from test_store_api import StoreApiTestBase  # noqa: E402
from utils.audit import init_audit_log, log_audit  # noqa: E402

import storage  # noqa: E402


class SupervisorTestBase(StoreApiTestBase):
    """加一个「只管 s002 的主管」账号。"""

    def setUp(self) -> None:
        super().setUp()
        self._multi_store_layout()
        (self.data_dir / "stores" / "s002").mkdir(parents=True, exist_ok=True)
        config.write_store_config("s002", {
            "id": "s002", "name": "国贸店",
            "meters": [dict(m) for m in config.DEFAULT_METERS],
            "config": dict(config.DEFAULT_CONFIG),
        })
        init_audit_log(self.data_dir)

        # 目录列举/备份下载删除这几个 handler 用的是 storage.get_data_dir()
        # (不是 app_handler.DATA_PATHS),测试里必须把它指向临时目录,
        # 否则它们会去读真实用户数据目录 —— 那既不是被测行为,也可能碰到真数据。
        self._orig_get_data_dir = storage.get_data_dir
        storage.get_data_dir = lambda *a, **k: self.data_dir
        self.addCleanup(lambda: setattr(storage, "get_data_dir", self._orig_get_data_dir))

    def _users(self) -> List[Dict[str, Any]]:
        users = super()._users()
        users.append({
            "id": 3, "username": "sup", "password": "x", "role": "supervisor",
            "name": "国贸主管", "enabled": True,
            "all_stores": False, "store_ids": ["s002"],
        })
        return users

    def _sup(self) -> str:
        return self._session(self._users()[2])

    def _admin(self) -> str:
        return self._session(self._users()[0])


class TestDeployConfigIsAdminOnly(SupervisorTestBase):
    """部署级全局配置:主管一律 403,管理员不是 403。"""

    ENDPOINTS: List[tuple[str, str, Dict[str, Any]]] = [
        ("PUT", "/api/admin/backup-config", {"backup_dir": ""}),
        ("PUT", "/api/admin/nas-config", {"nas_user": "x", "nas_pass": "", "nas_url": ""}),
        ("PUT", "/api/admin/auto-backup", {"enabled": False}),
        ("PUT", "/api/admin/backup-retention", {"retention_count": 3}),
        ("PUT", "/api/admin/images", {"image_dir": ""}),
    ]

    def test_supervisor_forbidden(self) -> None:
        for method, path, body in self.ENDPOINTS:
            h = self._call(method, path, body, token=self._sup())
            self.assertEqual(h.response_status, 403,
                             "%s 主管应当被拒,实际 %s %s" % (path, h.response_status, h.parsed))

    def test_admin_not_forbidden(self) -> None:
        for method, path, body in self.ENDPOINTS:
            h = self._call(method, path, body, token=self._admin())
            self.assertNotEqual(h.response_status, 403,
                                "%s 管理员被误拦了: %s" % (path, h.parsed))


class TestSupervisorKeepsOwnStore(SupervisorTestBase):
    def test_can_still_configure_own_store_meters(self) -> None:
        """电表设置是本店配置,主管必须还能改(否则收口收过头了)。"""
        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"meters": [{"key": "m1", "label": "吧台", "multiplier": 2}]},
                       token=self._sup())
        self.assertEqual(h.response_status, 200, h.parsed)

    def test_cannot_configure_other_store(self) -> None:
        h = self._call("PUT", "/api/admin/meter?store=main",
                       {"meters": [{"key": "m1", "label": "吧台", "multiplier": 2}]},
                       token=self._sup())
        self.assertEqual(h.response_status, 403, h.parsed)

    def test_data_files_only_own_store(self) -> None:
        h = self._call("GET", "/api/admin/data-files", token=self._sup())
        self.assertEqual(h.response_status, 200, h.parsed)
        files = h.parsed.get("files") or {}
        foreign = [k for k in files if k.startswith("stores/main/")]
        self.assertEqual(foreign, [], "主管拿到了别家门店的数据文件: %s" % foreign)


class TestDirListingScope(SupervisorTestBase):
    def test_cannot_browse_other_store_dir(self) -> None:
        target = self.data_dir / "stores" / "main"
        h = self._call("GET", "/api/admin/dir-listing?path=" + str(target), token=self._sup())
        self.assertEqual(h.response_status, 403,
                         "主管能浏览别家门店目录: %s" % h.parsed)

    def test_can_browse_own_store_dir(self) -> None:
        target = self.data_dir / "stores" / "s002"
        h = self._call("GET", "/api/admin/dir-listing?path=" + str(target), token=self._sup())
        self.assertEqual(h.response_status, 200, h.parsed)

    def test_admin_can_browse_data_root(self) -> None:
        h = self._call("GET", "/api/admin/dir-listing?path=" + str(self.data_dir),
                       token=self._admin())
        self.assertEqual(h.response_status, 200, h.parsed)


class TestAuditLogScope(SupervisorTestBase):
    def _write_logs(self) -> None:
        context.set_current_store("main")
        log_audit("WRITE", "readings", "总店的抄表", user="admin", role="admin")
        context.set_current_store("s002")
        log_audit("WRITE", "readings", "本店的抄表", user="sup", role="supervisor")
        context.clear_current_store()

    def test_supervisor_sees_only_own_store(self) -> None:
        self._write_logs()
        h = self._call("GET", "/api/admin/audit?count=50", token=self._sup())
        self.assertEqual(h.response_status, 200, h.parsed)
        details = [e.get("detail") for e in h.parsed.get("logs", [])]
        self.assertIn("本店的抄表", details)
        self.assertNotIn("总店的抄表", details, "主管看到了别家门店的审计记录")

    def test_admin_sees_all(self) -> None:
        self._write_logs()
        h = self._call("GET", "/api/admin/audit?count=50", token=self._admin())
        details = [e.get("detail") for e in h.parsed.get("logs", [])]
        self.assertIn("总店的抄表", details)
        self.assertIn("本店的抄表", details)

    def test_legacy_entries_without_store_hidden_from_supervisor(self) -> None:
        """历史记录没有 store 字段 → fail-closed:只给总部账号看。"""
        import json
        path = self.data_dir / "audit.json"
        path.write_text(json.dumps([
            {"ts": "2026-01-01T00:00:00", "user": "old", "role": "admin",
             "action": "WRITE", "resource": "readings", "detail": "改造前的记录", "ip": ""},
        ], ensure_ascii=False), encoding="utf-8")

        h = self._call("GET", "/api/admin/audit?count=50", token=self._sup())
        details = [e.get("detail") for e in h.parsed.get("logs", [])]
        self.assertNotIn("改造前的记录", details,
                         "无门店字段的历史审计被泄露给受限主管")

        h2 = self._call("GET", "/api/admin/audit?count=50", token=self._admin())
        details2 = [e.get("detail") for e in h2.parsed.get("logs", [])]
        self.assertIn("改造前的记录", details2, "总部账号也看不到历史记录了")


class TestBackupDeleteScope(SupervisorTestBase):
    def _make_full_backup(self) -> str:
        """造一个含总店数据的备份包(自动备份本来就是全量的)。"""
        bdir = self.data_dir / "backup"
        bdir.mkdir(parents=True, exist_ok=True)
        name = "auto-bak-20260101.zip"
        with zipfile.ZipFile(bdir / name, "w") as z:
            z.writestr("stores/main/readings.json", "[]")
            z.writestr("stores/s002/readings.json", "[]")
        return name

    def test_supervisor_cannot_delete_out_of_scope_backup(self) -> None:
        name = self._make_full_backup()
        h = self._call("POST", "/api/admin/backup-delete", {"zip_name": name},
                       token=self._sup())
        self.assertEqual(h.response_status, 403,
                         "主管能删掉含别家门店数据的备份包: %s" % h.parsed)
        self.assertTrue((self.data_dir / "backup" / name).exists(), "包被删掉了")

    def test_supervisor_cannot_download_out_of_scope_backup(self) -> None:
        name = self._make_full_backup()
        h = self._call("POST", "/api/admin/backup-download", {"zip_name": name},
                       token=self._sup())
        self.assertEqual(h.response_status, 403, h.parsed)


class TestFrontendHidesAdminOnly(unittest.TestCase):
    """前端必须跟后端一致:主管看不到、也不会去请求那些全局配置。"""

    def setUp(self) -> None:
        self.html = (REPO / "MeterStats" / "index.html").read_text(encoding="utf-8")
        self.admin = (REPO / "MeterStats" / "admin.js").read_text(encoding="utf-8")
        self.nav = (REPO / "MeterStats" / "js" / "core" / "navigation.js").read_text(encoding="utf-8")

    def test_panels_marked_admin_only(self) -> None:
        """备份目录 / 自动备份 / 图片目录 / NAS 这几块要标 data-admin-only。"""
        self.assertEqual(self.html.count("data-admin-only"), 6,
                         "全局配置面板没有全部标 data-admin-only(实际 %d 处)"
                         % self.html.count("data-admin-only"))

    def test_apply_role_visibility_handles_admin_only(self) -> None:
        self.assertIn("data-admin-only", self.admin,
                      "applyRoleVisibility 没有处理 data-admin-only —— 主管仍会看到这几块")

    def test_navigation_skips_admin_only_loaders(self) -> None:
        """主管打开数据管理页时不能去请求管理员专属接口(会吃 403)。"""
        idx = self.nav.index("page === 'data'")
        block = self.nav[idx:idx + 900]
        self.assertIn("if (isAdmin) {", block,
                      "没有按角色分流加载 —— 主管一进数据管理页就会吃 403")
        for fn in ("loadImageDirConfig", "loadBackupDirConfig", "loadNasConfig"):
            self.assertIn(fn, block)
        # 这三个调用必须在 isAdmin 分支内
        gate = block.index("if (isAdmin)")
        for fn in ("loadImageDirConfig", "loadBackupDirConfig", "loadNasConfig"):
            self.assertGreater(block.index(fn + "("), gate,
                               "%s 没有放到 isAdmin 分支里" % fn)

    def test_supervisor_still_has_backup_entries(self) -> None:
        """主管仍要能看到「备份 / 恢复 / 备份列表」—— 收口不能收过头。"""
        for fn in ("adminBackup()", "adminRestore()", "loadBackupList()"):
            self.assertIn(fn, self.html + self.nav,
                          "主管的本店备份入口被误删了: %s" % fn)


if __name__ == "__main__":
    unittest.main()
