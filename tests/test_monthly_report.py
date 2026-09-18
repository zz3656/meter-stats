"""月度报告 V4 算法回归测试(标准库 unittest,零依赖)。

用 2026 年 6 月真实数据(用户 Excel 验证过的数据集:71,226.1 度 / ¥64,103.49)
固化核心算法,防止未来改动引入 regression。

运行:
    cd ~/Documents/electricity-stats-app && python3 -m unittest discover -s tests -v
    或直接: python3 tests/test_monthly_report.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))

from report import calculate_monthly_report, calculate_yearly_report  # noqa: E402

# ---- fixture: 2026 年 6-8 月真实抄表数据(源自 ~/Library/Application Support/com.meter.stats/readings.json) ----
READINGS = [
    {"date": "2026-06-01", "hall": 101.1, "fire": 2332.0, "private_room": 173.8, "ac": 157.2},
    {"date": "2026-06-05", "hall": 84.6, "fire": 2135.2, "private_room": 156.0, "ac": 138.7},
    {"date": "2026-06-08", "hall": 73.2, "fire": 1996.5, "private_room": 143.3, "ac": 127.2},
    {"date": "2026-06-11", "hall": 55.9, "fire": 1851.0, "private_room": 129.5, "ac": 114.1},
    {"date": "2026-06-13", "hall": 120.4, "fire": 1746.2, "private_room": 120.3, "ac": 102.7},
    {"date": "2026-06-16", "hall": 99.4, "fire": 1600.0, "private_room": 106.9, "ac": 86.2},
    {"date": "2026-06-20", "hall": 71.5, "fire": 1393.7, "private_room": 87.6, "ac": 60.6},
    {"date": "2026-06-22", "hall": 63.2, "fire": 1297.6, "private_room": 77.4, "ac": 49.4},
    {"date": "2026-06-25", "hall": 102.4, "fire": 1125.6, "private_room": 83.4, "ac": 86.3},
    {"date": "2026-06-27", "hall": 93.0, "fire": 1022.0, "private_room": 75.8, "ac": 78.2},
    {"date": "2026-06-29", "hall": 84.3, "fire": 912.0, "private_room": 67.3, "ac": 69.0},
    {"date": "2026-07-01", "hall": 77.0, "fire": 817.9, "private_room": 59.0, "ac": 60.4},
    {"date": "2026-07-03", "hall": 70.3, "fire": 710.0, "private_room": 50.7, "ac": 52.3},
    {"date": "2026-07-07", "hall": 54.9, "fire": 492.6, "private_room": 32.9, "ac": 31.4},
    {"date": "2026-07-10", "hall": 110.4, "fire": 1815.4, "private_room": 119.3, "ac": 131.0},
    {"date": "2026-07-13", "hall": 98.5, "fire": 1636.9, "private_room": 106.2, "ac": 110.4},
    {"date": "2026-07-16", "hall": 88.2, "fire": 1455.0, "private_room": 92.9, "ac": 90.1},
    {"date": "2026-07-18", "hall": 80.7, "fire": 1328.4, "private_room": 83.7, "ac": 76.7},
    {"date": "2026-07-21", "hall": 71.0, "fire": 1158.1, "private_room": 70.1, "ac": 57.0},
    {"date": "2026-07-23", "hall": 61.0, "fire": 1048.3, "private_room": 61.4, "ac": 43.0},
    {"date": "2026-07-28", "hall": 39.1, "fire": 736.1, "private_room": 77.7, "ac": 75.9},
    {"date": "2026-07-30", "hall": 32.1, "fire": 632.3, "private_room": 69.0, "ac": 63.3},
    {"date": "2026-08-01", "hall": 125.3, "fire": 2035.0, "private_room": 135.2, "ac": 199.9},
]

# ---- fixture: 充值记录(源自 charges.json) ----
CHARGES = [
    {"id": "2026-06-13-013024663725", "date": "2026-06-13", "hall": 80.0, "fire": 0.0, "private_room": 0.0, "ac": 0.0},
    {"id": "2026-06-25-1782359232517", "date": "2026-06-25", "hall": 50.0, "fire": 0.0, "private_room": 20.0, "ac": 50.0},
    {"id": "2026-07-08-1783499377649", "date": "2026-07-08", "hall": 70.0, "fire": 1500.0, "private_room": 100.0, "ac": 120.0},
    {"id": "2026-07-24-1785300624423", "date": "2026-07-24", "hall": 0.0, "fire": 0.0, "private_room": 40.0, "ac": 70.0},
    {"id": "2026-07-31-1785570349281", "date": "2026-07-31", "hall": 100.0, "fire": 1500.0, "private_room": 75.0, "ac": 150.0},
]


class TestMonthlyReport(unittest.TestCase):
    @staticmethod
    def _report(month: str):
        r = calculate_monthly_report(READINGS, CHARGES, month)
        return r, {d["date"]: d for d in r["days"]}

    def setUp(self):
        # 清缓存,防止上一个测试的 6 月缓存污染本测试的真实 fixture。
        # calculate_monthly_report 按 month 键缓存,即使参数不同也命中相同 key。
        from report import invalidate_report_cache
        invalidate_report_cache()

    def test_charge_on_reading_day_left_open_right_closed(self):
        """充值日期 == 抄表日 Y 时,应划入下一段(X.date < c.date <= Y.date)。
        例如 6/13 抄表且 6/13 充值 100 度,应算入 6/13→6/16 段。
        """
        # 构造最小场景: 6/1 抄表[hall=100], 6/5 抄表[hall=80], 6/5 充值[hall=10]
        # (6/1, 6/5] = (100 - 80 + 10) × 160 = 4800,4 天均摊=1200
        readings = [
            {"date": "2026-06-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-06-05", "hall": 80.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        # setUp 已清缓存,这里不需重复。
        charges = [
            {"date": "2026-06-05", "hall": 10.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        r = calculate_monthly_report(readings, charges, "2026-06")
        days = {d["date"]: d for d in r["days"]}
        # 6/1 hall 应为 1200(总费用 4800/4 天的首天),验证半开半闭: 6/5 充值
        # 属于 (6/1, 6/5] 段,被均摊到 6/1-6/4 这 4 天。
        self.assertEqual(days["2026-06-01"]["hall"], 1200.0)

    def test_multi_meter_different_multipliers(self):
        """4 块表倍率不同(hall=160, fire=1, private_room=160, ac=160):
        同一充值记录中的不同字段应各自 × 各自倍率,不能串。
        """
        # 6/1 抄表: hall=100, fire=100, pr=100, ac=100
        # 6/8 抄表: hall= 50, fire= 90, pr= 80, ac= 60
        # 期间(6/1, 6/8]充值: hall=5, fire=50, pr=10, ac=20
        # 期望:
        #   hall       = (100-50+5)×160  / 7 = 8800/7 = 1257.1
        #   fire       = (100-90+50)×1   / 7 = 60/7   = 8.6
        #   private_rm = (100-80+10)×160 / 7 = 4800/7 = 685.7
        #   ac         = (100-60+20)×160 / 7 = 9600/7 = 1371.4
        readings = [
            {"date": "2026-06-01", "hall": 100.0, "fire": 100.0, "private_room": 100.0, "ac": 100.0},
            {"date": "2026-06-08", "hall": 50.0, "fire": 90.0, "private_room": 80.0, "ac": 60.0},
        ]
        # setUp 已清缓存。
        charges = [
            {"date": "2026-06-05", "hall": 5.0, "fire": 50.0, "private_room": 10.0, "ac": 20.0},
        ]
        r = calculate_monthly_report(readings, charges, "2026-06")
        days = {d["date"]: d for d in r["days"]}
        d1 = days["2026-06-01"]
        self.assertEqual(d1["hall"], 1257.1)
        self.assertEqual(d1["fire"], 8.6)
        self.assertEqual(d1["private_room"], 685.7)
        self.assertEqual(d1["ac"], 1371.4)

    def test_charge_outside_range_excluded(self):
        """不在任何抄表对之间的充值不应影响用电计算。
        场景: 6/1 和 6/5 抄表, 6/10 充值(在 6/5 之后,不在任何区间)。
        """
        readings = [
            {"date": "2026-06-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-06-05", "hall": 80.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        # setUp 已清缓存。
        charges = [
            {"date": "2026-06-10", "hall": 1000.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        r = calculate_monthly_report(readings, charges, "2026-06")
        days = {d["date"]: d for d in r["days"]}
        # 不计入任何段: hall = (100-80)×160/4 = 3200/4 = 800
        self.assertEqual(days["2026-06-01"]["hall"], 800.0)
        # total_kwh 也不应包含额外充值(800×4 = 3200,不含 6/10 的 1000)
        self.assertEqual(r["summary"]["total_kwh"], 3200.0)

    def test_june_total_matches_user_excel(self):
        """6 月汇总必须精确等于用户 Excel 的'本月共计'列。"""
        r, _ = self._report("2026-06")
        self.assertEqual(r["summary"]["total_kwh"], 71226.1)
        self.assertEqual(r["summary"]["total_cost"], 64103.49)

    def test_june_charge_segment_hall_1240(self):
        """充值参与计算:6/11→6/13 大厅充 80 度 → (55.9+80-120.4)×160/2 = 1240/天。"""
        _, days = self._report("2026-06")
        self.assertEqual(days["2026-06-11"]["hall"], 1240.0)
        self.assertEqual(days["2026-06-12"]["hall"], 1240.0)

    def test_june_cross_month_segment_hall_584(self):
        """跨月段:6/29→7/1 → (84.3-77.0)×160/2 = 584/天,填在 6/29、6/30。"""
        _, days = self._report("2026-06")
        self.assertEqual(days["2026-06-29"]["hall"], 584.0)
        self.assertEqual(days["2026-06-30"]["hall"], 584.0)

    def test_reading_direction_prev_minus_curr(self):
        """读数方向:预付费表递减,用电 = 前次 - 本次。6/1→6/5 无充值 → (101.1-84.6)×160/4 = 660。"""
        _, days = self._report("2026-06")
        self.assertEqual(days["2026-06-01"]["hall"], 660.0)

    def test_multi_meter_charge_segment(self):
        """6/22→6/25 期间 6/25 充值:hall 50, private_room 20, ac 50(半开半闭含 Y 不含 X)。"""
        _, days = self._report("2026-06")
        # hall = (63.2 + 50 - 102.4) × 160 / 3 = 576
        self.assertEqual(days["2026-06-22"]["hall"], 576.0)
        # private_room = (77.4 + 20 - 83.4) × 160 / 3 = 2240 / 3 = 746.7
        self.assertEqual(days["2026-06-22"]["private_room"], 746.7)

    def test_no_negative_usage(self):
        """任何天的任何表用电都不得为负。"""
        for month in ("2026-06", "2026-07"):
            r, _ = self._report(month)
            for d in r["days"]:
                self.assertGreaterEqual(d["hall"], 0)
                self.assertGreaterEqual(d["fire"], 0)
                self.assertGreaterEqual(d["private_room"], 0)
                self.assertGreaterEqual(d["ac"], 0)

    def test_all_days_present(self):
        """6 月报告必须覆盖全部 30 天。"""
        r, _ = self._report("2026-06")
        self.assertEqual(len(r["days"]), 30)
        self.assertEqual(r["days"][0]["date"], "2026-06-01")
        self.assertEqual(r["days"][-1]["date"], "2026-06-30")

    def test_reading_days_marked(self):
        """抄表日要标记 is_reading_day=True。"""
        r, _ = self._report("2026-06")
        reading_dates = {d["date"] for d in r["days"] if d["is_reading_day"]}
        self.assertEqual(reading_dates, {
            "2026-06-01", "2026-06-05", "2026-06-08", "2026-06-11", "2026-06-13",
            "2026-06-16", "2026-06-20", "2026-06-22", "2026-06-25", "2026-06-27", "2026-06-29",
        })
        self.assertEqual(r["summary"]["reading_days"], 11)

    def test_yearly_report_contains_june(self):
        """年度汇总必须包含 6 月,且 6 月数值与月度报告一致。"""
        y = calculate_yearly_report(READINGS, CHARGES, "2026")
        months = {m["month"]: m for m in y["months"]}
        self.assertIn("2026-06", months)
        self.assertEqual(months["2026-06"]["total_kwh"], 71226.1)
        self.assertEqual(months["2026-06"]["total_cost"], 64103.49)
        # 年度合计 >= 6 月单月(还有 7 月/8 月数据)
        self.assertGreaterEqual(y["year_total_kwh"], 71226.1)
        self.assertGreaterEqual(len(y["months"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
