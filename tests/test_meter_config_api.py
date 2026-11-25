"""表计配置 HTTP API 测试(标准库 unittest,零依赖)。

P2 Task 2 —— 配置接口从**全局** settings 改到**每店** store.json。

单独成文件(不追加到 `tests/test_stores.py`):那边的 `TestStoreConfig` /
`TestStoreConfigIsolation` 已经覆盖了 `store.json` 的存储层与缓存隔离,
这里**只测 HTTP 层** —— 路由、当前店、校验、越权、缓存失效。

为什么这层必须单独测:P2 之前三个端点读写的是全局 `settings["meter"]`,
多店下「A 店改表名 → B 店跟着变」。改造最容易出的错是**只改了其中一两个**,
表现为「保存成功但刷新变回去」或「设置页显示总店、别的页面显示本店」。

覆盖:
- GET /api/meters 与 GET /api/admin/meter 都按**当前店**返回,且两者一致
- PUT /api/admin/meter 只改当前店,另一店不受影响
- 增表 / 删表(数量跟着变)
- 拒绝:0 块表 / 倍率 0、负数、非数字 / key 与旧 4 表重名 / key 非法 / key 重复
- 越权:员工 PUT → 403
- 改倍率后立刻取月报,数字必须跟着变(报表缓存要被失效)
- POST /api/readings 能写自定义表(`meters` 字典)并读回
- 充值一致性校验用当前店的表

运行:
    python3 -m unittest tests.test_meter_config_api -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "MeterStats"))
sys.path.insert(0, str(TESTS_DIR))

import report  # noqa: E402
from modules.stores import config  # noqa: E402
from storage import save_json  # noqa: E402
from test_store_api import StoreApiTestBase  # noqa: E402


def _meters_dict(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """表定义列表 → 接口用的有序字典(与 GET /api/meters 的 meters 同形)。"""
    return {m["key"]: m for m in items}


class MeterConfigApiBase(StoreApiTestBase):
    """在 StoreApiTestBase 之上补:两店目录 + 按店配置写入 + 读表辅助。"""

    def setUp(self) -> None:
        super().setUp()
        self._multi_store_layout()
        (self.data_dir / "stores" / "s002").mkdir(parents=True, exist_ok=True)
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)

    # ---- 辅助 ----

    def _set_meters(self, store_id: str, meters: List[Dict[str, Any]],
                    cfg: Dict[str, Any] | None = None) -> None:
        """直接写某店的 store.json(绕过接口,用于铺前置状态)。"""
        payload: Dict[str, Any] = {
            "id": store_id,
            "name": store_id,
            "meters": meters,
            "config": cfg if cfg is not None else dict(config.DEFAULT_CONFIG),
        }
        config.write_store_config(store_id, payload)

    def _get_meters(self, token: str, store_id: str, path: str = "/api/meters") -> Dict[str, Any]:
        h = self._call("GET", "%s?store=%s" % (path, store_id), token=token)
        self.assertEqual(h.response_status, 200, h.parsed)
        return h.parsed  # type: ignore[no-any-return]

    def _seed_readings(self, store_id: str, rows: List[Dict[str, Any]]) -> None:
        path = self.data_dir / "stores" / store_id / "readings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, rows)
        report.invalidate_report_cache()

    def _admin_token(self) -> str:
        return self._session(self._users()[0])

    def _emp_token(self) -> str:
        return self._session(self._users()[1])


class TestMetersReadPerStore(MeterConfigApiBase):
    """两个读端点都必须返回**当前店**的配置,而且彼此一致。"""

    def test_public_meters_endpoint_is_per_store(self) -> None:
        self._set_meters("s002", [{"key": "m1", "label": "吧台", "multiplier": 2}])
        tok = self._admin_token()

        main = self._get_meters(tok, "main")
        self.assertEqual(list(main["meters"].keys()),
                         ["hall", "fire", "private_room", "ac"],
                         "总店应该拿到默认 4 表")

        s002 = self._get_meters(tok, "s002")
        self.assertEqual(list(s002["meters"].keys()), ["m1"])
        self.assertEqual(s002["meters"]["m1"]["label"], "吧台")

    def test_both_read_endpoints_agree(self) -> None:
        """`/api/meters` 与 `/api/admin/meter` 必须读同一个源。

        只改一个的后果:电表设置页(读 admin 那个)显示总店的表,
        而抄表表单(读 public 那个)显示本店的表 —— 用户改了设置看不到效果。
        """
        self._set_meters("s002", [{"key": "m1", "label": "吧台", "multiplier": 2}])
        tok = self._admin_token()
        public = self._get_meters(tok, "s002", "/api/meters")
        admin = self._get_meters(tok, "s002", "/api/admin/meter")
        self.assertEqual(public["meters"], admin["meters"])
        self.assertEqual(public["config"], admin["config"])

    def test_config_is_per_store(self) -> None:
        self._set_meters(
            "s002", [{"key": "m1", "label": "吧台", "multiplier": 2}],
            cfg={"electricity_price": 2.5, "water_price": 9.0,
                 "main_mult": 11, "sub_mult": 12},
        )
        tok = self._admin_token()
        self.assertEqual(self._get_meters(tok, "s002")["config"]["electricity_price"], 2.5)
        self.assertEqual(self._get_meters(tok, "main")["config"]["electricity_price"], 0.9)


class TestMetersWrite(MeterConfigApiBase):
    """PUT /api/admin/meter —— 按店写 + 增删 + 校验。"""

    def test_write_only_affects_current_store(self) -> None:
        tok = self._admin_token()
        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"meters": [{"key": "m1", "label": "吧台", "multiplier": 2}]},
                       token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertEqual(list(self._get_meters(tok, "s002")["meters"].keys()), ["m1"])
        self.assertEqual(list(self._get_meters(tok, "main")["meters"].keys()),
                         ["hall", "fire", "private_room", "ac"],
                         "改分店把总店也改了")

    def test_add_and_remove_meters(self) -> None:
        tok = self._admin_token()
        three = [
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "m2", "label": "后厨", "multiplier": 3},
            {"key": "m3", "label": "露台", "multiplier": 4},
        ]
        self._call("PUT", "/api/admin/meter?store=s002", {"meters": three}, token=tok)
        self.assertEqual(list(self._get_meters(tok, "s002")["meters"].keys()),
                         ["m1", "m2", "m3"])

        self._call("PUT", "/api/admin/meter?store=s002", {"meters": three[:1]}, token=tok)
        self.assertEqual(list(self._get_meters(tok, "s002")["meters"].keys()), ["m1"])

    def test_accepts_legacy_meter_field_name(self) -> None:
        """旧前端发的是 `{meter: {...}}`(字典)—— 必须继续能存。"""
        tok = self._admin_token()
        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"meter": {"m1": {"label": "吧台", "multiplier": 2}}},
                       token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertEqual(list(self._get_meters(tok, "s002")["meters"].keys()), ["m1"])

    def test_rejects_empty_meter_list(self) -> None:
        tok = self._admin_token()
        h = self._call("PUT", "/api/admin/meter?store=s002", {"meters": []}, token=tok)
        self.assertEqual(h.response_status, 400, h.parsed)
        self.assertIn("至少", h.parsed["error"])

    def test_rejects_bad_multiplier(self) -> None:
        tok = self._admin_token()
        for bad in (0, -1, "abc", None, True):
            h = self._call("PUT", "/api/admin/meter?store=s002",
                           {"meters": [{"key": "m1", "label": "x", "multiplier": bad}]},
                           token=tok)
            self.assertEqual(h.response_status, 400, "倍率 %r 应被拒: %s" % (bad, h.parsed))

    def test_rejects_legacy_key_collision(self) -> None:
        """新表不许用旧 4 表的 key(D3:会造成顶层/meters 两份数据的隐藏口径)。"""
        tok = self._admin_token()
        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"meters": [{"key": "hall", "label": "大厅", "multiplier": 2}]},
                       token=tok)
        self.assertEqual(h.response_status, 400, h.parsed)
        self.assertIn("保留", h.parsed["error"])

    def test_rejects_invalid_and_duplicate_keys(self) -> None:
        tok = self._admin_token()
        for bad_key in ("M1", "1abc", "m-1", "", "表1"):
            h = self._call("PUT", "/api/admin/meter?store=s002",
                           {"meters": [{"key": bad_key, "label": "x", "multiplier": 2}]},
                           token=tok)
            self.assertEqual(h.response_status, 400, "key %r 应被拒: %s" % (bad_key, h.parsed))

        dup = [{"key": "m1", "label": "a", "multiplier": 2},
               {"key": "m1", "label": "b", "multiplier": 2}]
        h = self._call("PUT", "/api/admin/meter?store=s002", {"meters": dup}, token=tok)
        self.assertEqual(h.response_status, 400, h.parsed)
        self.assertIn("重复", h.parsed["error"])

    def test_employee_cannot_write(self) -> None:
        tok = self._emp_token()
        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"meters": [{"key": "m1", "label": "x", "multiplier": 2}]},
                       token=tok)
        self.assertEqual(h.response_status, 403, h.parsed)


class TestMeterChangeInvalidatesReport(MeterConfigApiBase):
    """改倍率之后月报必须立刻反映新倍率(D8:缓存要失效)。"""

    def test_multiplier_change_takes_effect_immediately(self) -> None:
        self._set_meters("s002", [{"key": "m1", "label": "吧台", "multiplier": 1}])
        self._seed_readings("s002", [
            {"date": "2026-09-01", "meters": {"m1": 100.0}},
            {"date": "2026-09-11", "meters": {"m1": 90.0}},
        ])
        tok = self._admin_token()

        first = self._call("GET", "/api/monthly-report?store=s002&month=2026-09", token=tok)
        self.assertEqual(first.response_status, 200, first.parsed)
        self.assertEqual(first.parsed["summary"]["total_kwh"], 10.0)   # 10 表字 × 1

        # 倍率 1 → 3
        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"meters": [{"key": "m1", "label": "吧台", "multiplier": 3}]},
                       token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)

        second = self._call("GET", "/api/monthly-report?store=s002&month=2026-09", token=tok)
        self.assertEqual(
            second.parsed["summary"]["total_kwh"], 30.0,
            "改完倍率月报还是旧值(%s)—— 报表缓存没失效" % second.parsed["summary"]["total_kwh"],
        )

    def test_price_change_takes_effect_immediately(self) -> None:
        self._set_meters(
            "s002", [{"key": "m1", "label": "吧台", "multiplier": 1}],
            cfg={"electricity_price": 1.0, "water_price": 4.5,
                 "main_mult": 50, "sub_mult": 40},
        )
        self._seed_readings("s002", [
            {"date": "2026-09-01", "meters": {"m1": 100.0}},
            {"date": "2026-09-11", "meters": {"m1": 90.0}},
        ])
        tok = self._admin_token()
        r = self._call("GET", "/api/monthly-report?store=s002&month=2026-09", token=tok)
        self.assertEqual(r.parsed["summary"]["price"], 1.0)
        self.assertEqual(r.parsed["summary"]["total_cost"], 10.0)

        h = self._call("PUT", "/api/admin/meter?store=s002",
                       {"config": {"electricity_price": 2.0, "water_price": 4.5,
                                   "main_mult": 50, "sub_mult": 40}},
                       token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)

        r2 = self._call("GET", "/api/monthly-report?store=s002&month=2026-09", token=tok)
        self.assertEqual(r2.parsed["summary"]["price"], 2.0)
        self.assertEqual(r2.parsed["summary"]["total_cost"], 20.0)


class TestReadingsAcceptCustomMeters(MeterConfigApiBase):
    """抄表/充值接口要能收自定义表(值进 meters 字典)。"""

    def test_post_reading_with_custom_meter(self) -> None:
        self._set_meters("s002", [{"key": "m1", "label": "吧台", "multiplier": 2}])
        tok = self._admin_token()
        h = self._call("POST", "/api/readings?store=s002",
                       {"date": "2026-09-01", "m1": 12.5}, token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)

        got = self._call("GET", "/api/readings?store=s002", token=tok)
        self.assertEqual(got.response_status, 200)
        self.assertEqual(len(got.parsed), 1)
        row = got.parsed[0]
        self.assertEqual(row["date"], "2026-09-01")
        self.assertEqual(row.get("meters", {}).get("m1"), 12.5)

    def test_legacy_meter_still_writes_top_level_field(self) -> None:
        """总店的 hall 仍写顶层字段 —— 历史数据零迁移(D1)。"""
        tok = self._admin_token()
        h = self._call("POST", "/api/readings?store=main",
                       {"date": "2026-09-02", "hall": 5.0}, token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)
        got = self._call("GET", "/api/readings?store=main", token=tok)
        self.assertEqual(got.parsed[0]["hall"], 5.0)
        self.assertNotIn("meters", {k: v for k, v in got.parsed[0].items() if v})

    def test_meter_not_in_store_is_rejected(self) -> None:
        """该店没有的表 key 不许写进来(否则悄悄存一份没人看的数据)。"""
        self._set_meters("s002", [{"key": "m1", "label": "吧台", "multiplier": 2}])
        tok = self._admin_token()
        h = self._call("POST", "/api/readings?store=s002",
                       {"date": "2026-09-03", "zzz": 9.0}, token=tok)
        self.assertEqual(h.response_status, 400, h.parsed)


class TestChargeApiWithCustomMeters(MeterConfigApiBase):
    """充值与抄表走同一套表集合语义。"""

    def test_post_charge_with_custom_meter(self) -> None:
        self._set_meters("s002", [{"key": "m1", "label": "吧台", "multiplier": 2}])
        tok = self._admin_token()
        h = self._call("POST", "/api/charges?store=s002",
                       {"date": "2026-09-05", "m1": 7.0}, token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)
        self.assertEqual(h.parsed["row"].get("meters", {}).get("m1"), 7.0)

    def test_put_charge_empty_value_clears_field(self) -> None:
        """PUT 传空串 = 清空该表,不是「没传所以保留」—— 历史语义,别合并掉。"""
        tok = self._admin_token()
        h = self._call("POST", "/api/charges?store=main",
                       {"date": "2026-09-06", "hall": 10.0, "fire": 5.0}, token=tok)
        self.assertEqual(h.response_status, 200, h.parsed)
        cid = h.parsed["row"]["id"]

        h2 = self._call("PUT", "/api/charges/" + cid + "?store=main",
                        {"fire": ""}, token=tok)
        self.assertEqual(h2.response_status, 200, h2.parsed)
        self.assertIsNone(h2.parsed["row"]["fire"])
        self.assertEqual(h2.parsed["row"]["hall"], 10.0)


class TestChargeConflictsUseStoreTables(MeterConfigApiBase):
    """充值一致性校验要看当前店的表,而不是写死的 4 表。"""

    def test_no_false_conflict_when_store_has_no_hall(self) -> None:
        """2 表门店没有 hall —— 不能因此把合法充值判成冲突。"""
        from report import find_charge_conflicts

        readings = [
            {"date": "2026-09-01", "meters": {"m1": 100.0}},
            {"date": "2026-09-11", "meters": {"m1": 90.0}},
        ]
        charges = [{"id": "c1", "date": "2026-09-11", "meters": {"m1": 5.0}}]
        conflicts = find_charge_conflicts(
            readings, charges, tables=[{"key": "m1", "label": "吧台", "mult": 1}],
        )
        self.assertEqual(conflicts, [])


if __name__ == "__main__":
    unittest.main()
