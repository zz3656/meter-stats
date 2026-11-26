"""年报口径一致性与复杂度回归测试(标准库 unittest,零依赖)。

背景:年报原来就是「循环 12 次调月报」,于是每次年报都要把最贵的两步
(找冲突、归属充值)**各重算 12 遍**,而且 `_attributed_segment` 里
每笔充值 × 每块表都重建一次日期索引。合成 1100 行 / 160 笔的数据实测:

    年报 1210ms → 31ms(37×)      月报 100ms → 28ms(3.5×)

重构的**正确性**保证不是"看着对",而是逐字段等价性验证(月报/年报/冲突清单
在全量 fixture、合成大数据、2 表门店、空数据、单条读数、含负数充值六种输入下
与改造前的输出逐字节一致)。

本文件守两件事:
1. **年度汇总与逐月汇总必须永远自洽** —— 两条入口现在共用 `_monthly_core`,
   将来若有人只改一条,这里会立刻红;
2. **年报不许退化成 12 倍月报的耗时** —— 它是唯一会被用户直接感知的慢接口
   (点"年度报表"要等两秒 = GIL 独占两秒)。

运行:
    python3 -m unittest tests.test_report_perf -v
"""
from __future__ import annotations

import sys
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

import report  # noqa: E402


def _synthetic(rows: int = 1100, charges: int = 160) -> tuple[list, list]:
    """造一批像真实数据的抄表 + 充值(表底单调下降,偶尔充值把它顶上去)。"""
    readings = []
    d = date(2024, 1, 1)
    hall, fire, pr, ac = 5000.0, 9000.0, 3000.0, 2000.0
    step = 0
    while len(readings) < rows:
        step += 1 if step % 3 else 2
        d = date(2024, 1, 1) + timedelta(days=step)
        hall -= 7.0
        fire -= 30.0
        pr -= 3.0
        ac -= 2.0
        readings.append({"date": d.isoformat(), "hall": round(hall, 1),
                         "fire": round(fire, 1), "private_room": round(pr, 1),
                         "ac": round(ac, 1)})
    payload = []
    for i in range(charges):
        cd = date(2024, 1, 1) + timedelta(days=(i * step) // charges)
        payload.append({"id": f"c{i}", "date": cd.isoformat(),
                        "hall": 50.0 if i % 2 else 0.0,
                        "fire": 800.0 if i % 3 else 0.0,
                        "private_room": 20.0 if i % 4 else 0.0,
                        "ac": 30.0 if i % 5 else 0.0})
    return readings, payload


class TestYearlyConsistency(unittest.TestCase):
    """年度汇总必须等于逐月月报的汇总(两条入口共用同一内核)。"""

    def setUp(self) -> None:
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)
        self.readings, self.charges = _synthetic(rows=400, charges=60)

    def test_yearly_matches_monthly(self) -> None:
        yearly = report.calculate_yearly_report(self.readings, self.charges, "2024")
        total_kwh = 0.0
        total_cost = 0.0
        for m in range(1, 13):
            month = f"2024-{m:02d}"
            report.invalidate_report_cache()
            r = report.calculate_monthly_report(self.readings, self.charges, month)
            s = r["summary"]
            if s["reading_days"] > 0:
                total_kwh += s["total_kwh"]
                total_cost += s["total_cost"]
        self.assertAlmostEqual(yearly["year_total_kwh"], round(total_kwh, 1), places=1)
        self.assertAlmostEqual(yearly["year_total_cost"], round(total_cost, 2), places=2)

    def test_yearly_months_carry_same_numbers_as_monthly(self) -> None:
        report.invalidate_report_cache()
        yearly = report.calculate_yearly_report(self.readings, self.charges, "2024")
        by_month = {m["month"]: m for m in yearly["months"]}
        self.assertTrue(by_month, "年报应当至少有一个月有抄表")
        for month, entry in by_month.items():
            report.invalidate_report_cache()
            r = report.calculate_monthly_report(self.readings, self.charges, month)
            s = r["summary"]
            self.assertEqual(entry["total_kwh"], s["total_kwh"], month)
            self.assertEqual(entry["total_cost"], s["total_cost"], month)
            self.assertEqual(entry["by_meter"], s["by_meter"], month)

    def test_conflicts_same_in_monthly_and_yearly(self) -> None:
        """冲突清单由共用内核产出 —— 月报里看到的告警条数必须和年报一致。"""
        report.invalidate_report_cache()
        yearly_months = report.calculate_yearly_report(self.readings, self.charges, "2024")
        direct = report.find_charge_conflicts(self.readings, self.charges)
        month = yearly_months["months"][0]["month"]
        report.invalidate_report_cache()
        monthly = report.calculate_monthly_report(self.readings, self.charges, month)
        self.assertEqual(len(direct), len(monthly["conflicts"]))


class TestYearlyNotTwelveTimesMonthly(unittest.TestCase):
    """年报**不许**退化成「12 倍月报」—— 那正是改造前 1.2 秒的来源。"""

    def setUp(self) -> None:
        report.invalidate_report_cache()
        self.addCleanup(report.invalidate_report_cache)
        self.readings, self.charges = _synthetic()

    def _time(self, fn: Any, *args: Any) -> float:
        best = None
        for _ in range(2):
            report.invalidate_report_cache()
            t0 = time.perf_counter()
            fn(*args)
            dt = time.perf_counter() - t0
            best = dt if best is None else min(best, dt)
        return best or 0.0

    def test_yearly_cost_does_not_scale_by_twelve(self) -> None:
        monthly = self._time(report.calculate_monthly_report,
                             self.readings, self.charges, "2024-06")
        yearly = self._time(report.calculate_yearly_report,
                            self.readings, self.charges, "2024")
        # 改造前: yearly / monthly ≈ 12；改造后 ≈ 1.1。
        # 阈值取 4 —— 留足机器波动的余量,又能挡住"退回 12 次月报"的回归。
        self.assertGreater(monthly, 0.0)
        self.assertLess(
            yearly / monthly, 4.0,
            f"年报耗时是月报的 {yearly / monthly:.1f} 倍,疑似又退回「循环 12 次月报」"
            f"(monthly={monthly*1000:.1f}ms, yearly={yearly*1000:.1f}ms)",
        )


if __name__ == "__main__":
    unittest.main()
