"""门店总览(P3)后端测试(标准库 unittest,零依赖)。

`GET /api/stores/overview?month=YYYY-MM` —— 总部在一个页面上看各店当月用电与费用。

这里最需要守住的一条不是"数字对不对",而是**逐店算月报时必须切换门店上下文**:
`report._report_cache_key()` 用的是当前门店,不切上下文时两家「表集合相同」的店
会命中同一份缓存 → 总览上两家数字一模一样,而且不报错。
(与 P2 那个「同店同月不同表集合」的缓存坑是同一类。)

覆盖:
- 各店按自己的表集合与电价算(4 表 0.9 元 vs 2 表 1.5 元)
- 缓存不串:表集合完全相同的两家店,数据不同 → 数字必须不同
- 合计 = 各行之和
- 权限:s002 员工只看到自己那家;总部账号看到全部
- 单店失败不影响整体(该行带 error,其余照常,接口仍 200)
- 月份校验(2026-13 / 2026-1 / 空 → 400)
- 调用结束后门店上下文必须恢复原值

运行:
    python3 -m unittest tests.test_store_overview -v
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Dict, List

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "MeterStats"))
sys.path.insert(0, str(TESTS_DIR))

from modules.stores import config, context  # noqa: E402
from test_store_api import StoreApiTestBase  # noqa: E402

import report  # noqa: E402
from storage import save_json  # noqa: E402


class OverviewTestBase(StoreApiTestBase):
    """两店 + 各自的 store.json + 各自的抄表数据。"""

    def setUp(self) -> None:
        super().setUp()
        self._multi_store_layout()
        (self.data_dir / "stores" / "s002").mkdir(parents=True, exist_ok=True)
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)

    # ---- 辅助 ----

    def _set_meters(self, store_id: str, meters: List[Dict[str, Any]],
                    price: float = 0.9) -> None:
        config.write_store_config(store_id, {
            "id": store_id, "name": store_id,
            "meters": meters,
            "config": {
                "electricity_price": price, "water_price": 4.5,
                "main_mult": 50, "sub_mult": 40,
            },
        })

    def _seed(self, store_id: str, rows: List[Dict[str, Any]],
              model: str = "readings") -> None:
        path = self.data_dir / "stores" / store_id / (model + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, rows)
        report.invalidate_report_cache()

    def _overview(self, token: str, month: str = "2026-09") -> Dict[str, Any]:
        h = self._call("GET", "/api/stores/overview?month=" + month, token=token)
        self.assertEqual(h.response_status, 200, h.parsed)
        return h.parsed  # type: ignore[no-any-return]

    @staticmethod
    def _by_id(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {row["id"]: row for row in payload["stores"]}


class TestPerStoreCaliber(OverviewTestBase):
    def test_each_store_uses_its_own_tables_and_price(self) -> None:
        """main 4 表 ×0.9, s002 2 表 ×1.5 —— 各算各的。"""
        # main:默认 4 表(hall 倍率 160),电价默认 0.9
        self._seed("main", [
            {"date": "2026-09-01", "hall": 100.0},
            {"date": "2026-09-11", "hall": 90.0},
        ])
        # s002:2 表(m1 倍率 2 / m2 倍率 3),电价 1.5
        self._set_meters("s002", [
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "m2", "label": "后厨", "multiplier": 3},
        ], price=1.5)
        self._seed("s002", [
            {"date": "2026-09-01", "meters": {"m1": 100.0, "m2": 50.0}},
            {"date": "2026-09-11", "meters": {"m1": 90.0, "m2": 40.0}},
        ])

        data = self._overview(self._session(self._users()[0]))
        rows = self._by_id(data)

        # main: (100-90) × 160 = 1600 度; ×0.9 = 1440 元
        self.assertEqual(rows["main"]["total_kwh"], 1600.0)
        self.assertEqual(rows["main"]["total_cost"], 1440.0)
        self.assertEqual(list(rows["main"]["by_meter"].keys()),
                         ["hall", "fire", "private_room", "ac"])

        # s002: m1 (100-90)×2=20 + m2 (50-40)×3=30 = 50 度; ×1.5 = 75 元
        self.assertEqual(rows["s002"]["total_kwh"], 50.0)
        self.assertEqual(rows["s002"]["total_cost"], 75.0)
        self.assertEqual(list(rows["s002"]["by_meter"].keys()), ["m1", "m2"])

    def test_total_is_sum_of_rows(self) -> None:
        self._seed("main", [
            {"date": "2026-09-01", "hall": 100.0},
            {"date": "2026-09-11", "hall": 90.0},
        ])
        self._seed("s002", [
            {"date": "2026-09-01", "hall": 200.0},
            {"date": "2026-09-11", "hall": 40.0},
        ])
        data = self._overview(self._session(self._users()[0]))
        rows = self._by_id(data)
        kwh = sum(r.get("total_kwh", 0) for r in rows.values())
        cost = sum(r.get("total_cost", 0) for r in rows.values())
        self.assertAlmostEqual(data["total"]["total_kwh"], round(kwh, 1))
        self.assertAlmostEqual(data["total"]["total_cost"], round(cost, 2))


class TestCacheDoesNotMixStores(OverviewTestBase):
    def test_identical_table_sets_do_not_share_cache(self) -> None:
        """两家店表集合完全相同(都走默认 4 表),但数据不同 → 数字必须不同。

        这条专抓「逐店算月报时忘了切换门店上下文」:
        不切的话 `_report_cache_key()` 会是同一个键,第二家店直接拿到第一家的结果。
        """
        # 两家都不写 store.json → 都回落默认 4 表、默认电价
        self._seed("main", [
            {"date": "2026-09-01", "hall": 100.0},
            {"date": "2026-09-11", "hall": 90.0},
        ])
        self._seed("s002", [
            {"date": "2026-09-01", "hall": 200.0},
            {"date": "2026-09-11", "hall": 40.0},
        ])
        rows = self._by_id(self._overview(self._session(self._users()[0])))
        self.assertEqual(rows["main"]["total_kwh"], 1600.0)    # 10 × 160
        self.assertEqual(rows["s002"]["total_kwh"], 25600.0)   # 160 × 160
        self.assertNotEqual(rows["main"]["total_kwh"], rows["s002"]["total_kwh"],
                            "两家店拿到了同一个数字 —— 月报缓存串店了(没切门店上下文)")


class TestPermissions(OverviewTestBase):
    def test_employee_sees_only_own_store(self) -> None:
        self._seed("main", [{"date": "2026-09-01", "hall": 100.0},
                            {"date": "2026-09-11", "hall": 90.0}])
        self._seed("s002", [{"date": "2026-09-01", "hall": 200.0},
                            {"date": "2026-09-11", "hall": 40.0}])
        emp = self._session(self._users()[1])   # store_ids = ["s002"]
        rows = self._by_id(self._overview(emp))
        self.assertEqual(list(rows.keys()), ["s002"])

    def test_admin_sees_all_stores(self) -> None:
        rows = self._by_id(self._overview(self._session(self._users()[0])))
        self.assertEqual(sorted(rows.keys()), ["main", "s002"])


class TestResilience(OverviewTestBase):
    def test_one_store_failure_does_not_break_overview(self) -> None:
        """一家店算挂了 → 那行带 error,其余照常,接口仍 200。"""
        self._seed("main", [{"date": "2026-09-01", "hall": 100.0},
                            {"date": "2026-09-11", "hall": 90.0}])
        real = report.calculate_monthly_report
        calls = {"n": 0}

        def flaky(*a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("模拟某店数据损坏")
            return real(*a, **k)

        with unittest.mock.patch.object(report, "calculate_monthly_report", flaky):
            h = self._call("GET", "/api/stores/overview?month=2026-09",
                           token=self._session(self._users()[0]))
        self.assertEqual(h.response_status, 200, h.parsed)
        rows = self._by_id(h.parsed)
        self.assertEqual(rows["main"]["total_kwh"], 1600.0, "坏的那家把好的也带崩了")
        self.assertIn("error", rows["s002"])
        self.assertIn("模拟某店数据损坏", rows["s002"]["error"])


class TestValidation(OverviewTestBase):
    def test_bad_month_rejected(self) -> None:
        tok = self._session(self._users()[0])
        for bad in ("2026-13", "2026-1", "2026-00", "", "abc"):
            h = self._call("GET", "/api/stores/overview?month=" + bad, token=tok)
            self.assertEqual(h.response_status, 400, "month=%r 应被拒: %s" % (bad, h.parsed))


class TestContextRestored(OverviewTestBase):
    def test_overview_does_not_leave_store_on_last_iterated(self) -> None:
        """总览逐店切上下文,退出后不能停在**最后遍历**的那家店上。

        门店闸在请求开始时会按调用方的可见范围设好当前门店(admin → 第一家 main)。
        总览内部再逐店切换,如果忘了恢复,请求结束时上下文会留在 s002(最后一家)——
        同一线程上后续的读就会落到别家店的数据上。
        """
        context.clear_current_store()
        self.addCleanup(context.clear_current_store)
        # 先走一遍门店闸,拿到它设置的基准值
        tok = self._session(self._users()[0])
        self._call("GET", "/api/stores", token=tok)
        before = context.get_current_store()

        self._overview(tok)
        self.assertEqual(context.get_current_store(), before,
                         "总览算完后门店上下文留在了别的店 —— 后续请求会读到别家店的数据")

    def test_store_scope_restores_previous_value(self) -> None:
        """store_scope 退出后必须回到**进入前**的值。"""
        context.set_current_store("s002")
        self.addCleanup(context.clear_current_store)
        with context.store_scope("main"):
            self.assertEqual(context.get_current_store(), "main")
        self.assertEqual(context.get_current_store(), "s002")

    def test_store_scope_restores_unset_state(self) -> None:
        """原本「从未设置」时,退出后也要回到未设置,而不是 main。"""
        context.clear_current_store()
        with context.store_scope("s002"):
            self.assertEqual(context.get_current_store(), "s002")
        # clear 之后 get_current_store() 会回落 main,但内部状态应仍是「未设置」
        self.assertIsNone(getattr(context._ctx, "store_id", None),
                          "store_scope 把「未设置」恢复成了某个具体门店")


if __name__ == "__main__":
    unittest.main()
