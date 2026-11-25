"""表定义参数化回归测试(标准库 unittest,零依赖)。

P2「每店自己的表数量与倍率」的后端地基。这一层要同时保证两件互相拉扯的事:

1. **默认 4 表的数字一个字节都不能变** —— 2026-06 的 71226.1 度是用户拿 Excel
   核对过的值,参数化改造不管怎么动 `report.py` 都不许动它。
2. **非默认表的门店能正确算出来** —— 2 块表的门店如果某处仍在读全局 `TABLES`
   或硬编码 `hall`,表现为「少一块表」或「整月 0 度」,而且**不会抛异常**。

第 2 点最阴的地方是 `report.py` 里 `r.get("hall") is not None` 这个过滤条件 ——
它被用来判断「这行有没有电表读数」。门店没有 hall 表时,所有抄表行都被当成
「只录了水电的行」跳过 → 月报 0 度、不报错、界面看起来「这个月没用电」。

覆盖:
- 默认 4 表:71226.1 度口径不变;显式传 DEFAULT_TABLES 结果逐键相同
- 2 表门店:by_meter 只有这 2 个键、total 等于手算值、days 的键跟着表集合走
- row_values 读取器:顶层字段与 meters 字典都能读;同 key 时 meters 优先(D2)
- 缓存:同店同月、不同表集合不许互相命中(否则串数字)

运行:
    python3 -m unittest tests.test_meter_tables -v
"""
# ruff: noqa: E402  —— 必须先 sys.path 注入 MeterStats/ 才能 import,故在文件中部 import
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "MeterStats"))
sys.path.insert(0, str(TESTS_DIR))

import test_monthly_report as monthly_fixture
from constants import DEFAULT_TABLES
from modules.stores.meters import (
    LEGACY_KEYS,
    is_valid_meter_key,
    normalize_tables,
    row_has_any_value,
    row_values,
)

import report

# 复用月度报表的 2026-06 真实夹具(用户 Excel 核对过 71226.1 度)。
# 复制一份到本文件会让「核对值变了」这件事在两处各改一次 —— 直接 import 同源。
JUNE_READINGS = monthly_fixture.READINGS
JUNE_CHARGES = monthly_fixture.CHARGES

# 2 块表的门店:表值放 meters 字典(自定义表),倍率 2 / 3。
# 09-01 → 09-11 共 10 天:m1 用 10 表字、m2 用 10 表字
#   m1: 10 × 2 = 20 度   m2: 10 × 3 = 30 度   合计 50 度
CUSTOM_TABLES = [
    {"key": "m1", "label": "吧台", "mult": 2},
    {"key": "m2", "label": "后厨", "mult": 3},
]
CUSTOM_READINGS = [
    {"date": "2026-09-01", "meters": {"m1": 100.0, "m2": 50.0}},
    {"date": "2026-09-11", "meters": {"m1": 90.0, "m2": 40.0}},
]


class TestDefaultTablesCaliber(unittest.TestCase):
    """默认 4 表:口径红线。"""

    def setUp(self) -> None:
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)

    def test_june_total_is_71226_1(self) -> None:
        """不传 tables → 用默认 4 表,2026-06 必须是 71226.1 度。"""
        r = report.calculate_monthly_report(JUNE_READINGS, JUNE_CHARGES, "2026-06")
        self.assertEqual(r["summary"]["total_kwh"], 71226.1)

    def test_explicit_default_tables_are_identical(self) -> None:
        """显式传 DEFAULT_TABLES 与不传,结果必须逐键相同。

        这条防止「参数化只对显式传参生效、默认路径悄悄走了别的分支」。
        """
        implicit = report.calculate_monthly_report(JUNE_READINGS, JUNE_CHARGES, "2026-06")
        report.invalidate_report_cache()
        explicit = report.calculate_monthly_report(
            JUNE_READINGS, JUNE_CHARGES, "2026-06", tables=DEFAULT_TABLES,
        )
        self.assertEqual(implicit["summary"], explicit["summary"])
        self.assertEqual(implicit["days"], explicit["days"])
        self.assertEqual(implicit["summary"]["total_kwh"], 71226.1)

    def test_default_tables_are_four_and_keyed_as_before(self) -> None:
        """DEFAULT_TABLES 就是原来那 4 块表,key 与顺序都不许变。"""
        self.assertEqual([t["key"] for t in DEFAULT_TABLES],
                         ["hall", "fire", "private_room", "ac"])
        self.assertEqual([t["mult"] for t in DEFAULT_TABLES], [160, 1, 160, 160])

    def test_price_parameter_does_not_change_default(self) -> None:
        """价格可传,不传时仍用常量 0.9。"""
        r = report.calculate_monthly_report(JUNE_READINGS, JUNE_CHARGES, "2026-06")
        self.assertEqual(r["summary"]["price"], 0.9)
        report.invalidate_report_cache()
        r2 = report.calculate_monthly_report(
            JUNE_READINGS, JUNE_CHARGES, "2026-06", price=1.5,
        )
        self.assertEqual(r2["summary"]["price"], 1.5)
        # 度数不受单价影响
        self.assertEqual(r2["summary"]["total_kwh"], 71226.1)


class TestCustomTables(unittest.TestCase):
    """2 表门店 —— 表值走 meters 字典(自定义表)。"""

    def setUp(self) -> None:
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)

    def test_two_meter_store_computes_total_and_by_meter(self) -> None:
        r = report.calculate_monthly_report(
            CUSTOM_READINGS, [], "2026-09", tables=CUSTOM_TABLES,
        )
        self.assertEqual(
            r["summary"]["by_meter"], {"m1": 20.0, "m2": 30.0},
            "2 表门店的 by_meter 不对 —— 多半是某处仍在读全局 TABLES",
        )
        self.assertEqual(
            r["summary"]["total_kwh"], 50.0,
            "2 表门店整月 %s 度,手算应为 50 —— 若为 0,说明抄表行被 "
            "`r.get('hall') is not None` 当成「只录水电的行」全跳过了"
            % r["summary"]["total_kwh"],
        )

    def test_days_keys_follow_table_set(self) -> None:
        """days 的每条记录只带这 2 个表键(外加 date/total/is_reading_day)。"""
        r = report.calculate_monthly_report(
            CUSTOM_READINGS, [], "2026-09", tables=CUSTOM_TABLES,
        )
        self.assertTrue(r["days"])
        for d in r["days"]:
            self.assertEqual(
                set(d.keys()),
                {"date", "m1", "m2", "total", "is_reading_day"},
                "days 记录里出现了不属于本店表集合的键: %s" % sorted(d.keys()),
            )
        # 09-01..09-10 是分摊出来的日均日
        self.assertEqual(r["days"][0]["m1"], 2.0)   # 20 度 / 10 天
        self.assertEqual(r["days"][0]["m2"], 3.0)   # 30 度 / 10 天
        self.assertEqual(r["days"][0]["total"], 5.0)

    def test_custom_store_ignores_legacy_hall_field(self) -> None:
        """该店没有 hall 表时,行里的 hall 字段不参与计算。

        反向护栏:防止有人为了让老测试过而把 hall 也算进去。
        """
        readings = [
            {"date": "2026-09-01", "hall": 999.0, "meters": {"m1": 100.0}},
            {"date": "2026-09-11", "hall": 1.0, "meters": {"m1": 90.0}},
        ]
        r = report.calculate_monthly_report(
            readings, [], "2026-09", tables=[{"key": "m1", "label": "吧台", "mult": 2}],
        )
        self.assertEqual(r["summary"]["by_meter"], {"m1": 20.0})
        self.assertEqual(r["summary"]["total_kwh"], 20.0)

    def test_charge_attribution_works_for_custom_meter(self) -> None:
        """自定义表的充值也能被归属(充值字段同时支持顶层与 meters)。"""
        readings = [
            {"date": "2026-09-01", "meters": {"m1": 100.0}},
            {"date": "2026-09-05", "meters": {"m1": 150.0}},   # 当天到账 → 表底上升
            {"date": "2026-09-11", "meters": {"m1": 140.0}},
        ]
        charges = [{"id": "c1", "date": "2026-09-05", "meters": {"m1": 50.0}}]
        r = report.calculate_monthly_report(
            readings, charges, "2026-09", tables=[{"key": "m1", "label": "吧台", "mult": 1}],
        )
        # 09-01→09-05:表底 100→150 上升,钱进表,不算用电(0)
        # 09-05→09-11:150→140 用 10 度
        self.assertEqual(r["summary"]["by_meter"], {"m1": 10.0})
        self.assertEqual(r["conflicts"], [], "自定义表的合法充值被误判成冲突")


class TestRowValues(unittest.TestCase):
    """统一读取器 row_values —— 两种存法一个读法。"""

    def test_reads_legacy_top_level_field(self) -> None:
        row = {"date": "2026-09-01", "hall": 5.0}
        self.assertEqual(row_values(row, "hall"), 5.0)

    def test_reads_custom_meter_from_dict(self) -> None:
        row = {"date": "2026-09-01", "meters": {"m1": 7.5}}
        self.assertEqual(row_values(row, "m1"), 7.5)

    def test_missing_key_is_none(self) -> None:
        self.assertIsNone(row_values({"date": "x"}, "nope"))
        self.assertIsNone(row_values({"date": "x", "meters": {}}, "nope"))

    def test_meters_wins_when_both_present(self) -> None:
        """同一个 key 两处都有 → meters 优先(D2 的口径,必须锁死)。"""
        row = {"hall": 1.0, "meters": {"hall": 9.0}}
        self.assertEqual(row_values(row, "hall"), 9.0)

    def test_tolerates_broken_meters_field(self) -> None:
        """meters 被人手改成非字典时不许抛异常,退回顶层字段。"""
        row = {"hall": 3.0, "meters": "坏数据"}
        self.assertEqual(row_values(row, "hall"), 3.0)


class TestRowHasAnyValue(unittest.TestCase):
    """替代 report.py 里硬编码的 `r.get('hall') is not None`。"""

    def test_true_when_any_table_has_value(self) -> None:
        self.assertTrue(row_has_any_value({"meters": {"m1": 0.0}}, CUSTOM_TABLES))
        self.assertTrue(row_has_any_value({"hall": 1.0}, DEFAULT_TABLES))

    def test_false_when_all_null(self) -> None:
        self.assertFalse(row_has_any_value({"date": "x"}, CUSTOM_TABLES))
        self.assertFalse(
            row_has_any_value({"hall": None, "meters": {"m1": None}}, CUSTOM_TABLES),
        )

    def test_zero_counts_as_present(self) -> None:
        """抄到 0 也是抄了(表底真的到 0),不能当「没录」。"""
        self.assertTrue(row_has_any_value({"hall": 0}, DEFAULT_TABLES))


class TestMeterKeyRules(unittest.TestCase):
    """表 key 规则(D3:新表不得与旧 4 表重名)。"""

    def test_legacy_keys_are_the_four(self) -> None:
        self.assertEqual(LEGACY_KEYS, ("hall", "fire", "private_room", "ac"))

    def test_valid_keys(self) -> None:
        for k in ("m1", "bar_2", "abc"):
            self.assertTrue(is_valid_meter_key(k), k)

    def test_invalid_keys(self) -> None:
        for k in ("", "1abc", "M1", "m-1", "a" * 40, "表1", None, 5):
            self.assertFalse(is_valid_meter_key(k), k)

    def test_normalize_drops_bad_entries(self) -> None:
        out = normalize_tables([
            {"key": "m1", "label": "吧台", "multiplier": 2},
            {"key": "M2", "label": "非法key"},          # 大写 → 丢
            {"label": "没有key"},                        # 无 key → 丢
            "垃圾",                                      # 非 dict → 丢
            {"key": "m3", "multiplier": "abc"},          # 倍率非数字 → 丢
        ])
        self.assertEqual([m["key"] for m in out], ["m1"])
        self.assertEqual(out[0]["multiplier"], 2)


class TestCacheTableSignature(unittest.TestCase):
    """同店同月、不同表集合不许互相命中。"""

    def setUp(self) -> None:
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)

    def test_different_table_sets_do_not_collide(self) -> None:
        """参数化之后 tables 成了调用参数 —— 缓存键必须带上它。

        不带的后果:同一门店同一个月,先用 4 表算一次、再用 2 表算一次,
        第二次直接拿到第一次的结果(键相同)→ 2 表门店看到 4 表的数字。
        这里两次都用 2026-09,第一次喂 6 月的数据(9 月 0 度),第二次喂 9 月的
        2 表数据(50 度)—— 若缓存撞了,第二次会拿到 0 度。
        """
        first = report.calculate_monthly_report(JUNE_READINGS, [], "2026-09")
        second = report.calculate_monthly_report(
            CUSTOM_READINGS, [], "2026-09", tables=CUSTOM_TABLES,
        )
        self.assertEqual(list(first["summary"]["by_meter"].keys()),
                         ["hall", "fire", "private_room", "ac"])
        self.assertEqual(
            second["summary"]["total_kwh"], 50.0,
            "2 表门店拿到了 %.1f 度 —— 命中了 4 表那次调用的缓存,键里没带 tables"
            % second["summary"]["total_kwh"],
        )
        self.assertEqual(list(second["summary"]["by_meter"].keys()), ["m1", "m2"])

    def test_cache_stats_still_parse_store_and_month(self) -> None:
        """缓存统计的 store / month 字段保持原样(加了签名之后也不能变)。"""
        report.calculate_monthly_report(JUNE_READINGS, JUNE_CHARGES, "2026-06")
        stats = report.get_report_cache_stats()
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["entries"][0]["month"], "2026-06")
        self.assertIn("store", stats["entries"][0])


if __name__ == "__main__":
    unittest.main()
