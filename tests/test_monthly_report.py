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

    def test_charge_on_reading_day_belongs_to_next_segment(self):
        """充值日期 == 抄表日 Y 时,先看 Y 相对上一次是否**上升**。

        预付费表表底上升才是"钱到账了"。6/5 抄表 80 比 6/1 的 100 更低,说明这笔
        充值在 6/5 抄表之后才到账,所以它不属于 6/1→6/5 段;等 6/9 抄表看到表底从
        80 跳到 275,才把它归属到 6/5→6/9 段。
        旧口径 (X, Y] 无条件把 Y 当天的充值算进 X→Y 段,等于把刚充进去的余额当成
        已经用掉的电,日均被顶高几十倍(实际事故:大厅 656 度/天被算成 34256 度/天)。
        """
        readings = [
            {"date": "2026-06-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-06-05", "hall": 80.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-06-09", "hall": 275.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        charges = [
            {"date": "2026-06-05", "hall": 200.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        r = calculate_monthly_report(readings, charges, "2026-06")
        days = {d["date"]: d for d in r["days"]}
        # 6/1→6/5 段不含充值:(100-80)×160 = 3200,4 天 → 800/天
        self.assertEqual(days["2026-06-01"]["hall"], 800.0)
        # 6/5→6/9 段含充值:(80-275+200)×160 = 800,4 天 → 200/天
        self.assertEqual(days["2026-06-05"]["hall"], 200.0)

    def test_charge_not_yet_credited_is_not_counted_as_usage(self):
        """钱还没充进表(表底一直没跳升)时,不能被算成"本月已用电"。"""
        readings = [
            {"date": "2026-06-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-06-05", "hall": 80.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        charges = [
            {"date": "2026-06-05", "hall": 200.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        r = calculate_monthly_report(readings, charges, "2026-06")
        # 只有 (100-80)×160 = 3200 度真实用电,充进去还没用的 200 表字不该混进来
        self.assertEqual(r["summary"]["total_kwh"], 3200.0)

    def test_charge_strictly_between_readings_always_counted(self):
        """充值日期落在两条读数正中间(当天没抄表)→ 必然在该区间到账,照常计入。"""
        readings = [
            {"date": "2026-06-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-06-08", "hall": 50.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        charges = [
            {"date": "2026-06-05", "hall": 5.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        r = calculate_monthly_report(readings, charges, "2026-06")
        # (100-50+5)×160 = 8800,7 天 → 1257.1/天
        days = {d["date"]: d for d in r["days"]}
        self.assertEqual(days["2026-06-01"]["hall"], 1257.1)

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


class TestLandingDateAttribution(unittest.TestCase):
    """充值归属以 confirmed_at(实际到账日)为准,不是申请日。

    真实场景:11-02 提申请、11-03 财务打款到账。若按申请日 11-02 归区间,会把还没
    进表的钱算成 11-01→11-02 的用电(实际事故:日均 656 被顶成 34256)。
    """

    def setUp(self):
        from report import invalidate_report_cache
        invalidate_report_cache()

    @staticmethod
    def _days(r):
        return {d["date"]: d for d in r["days"]}

    def test_confirmed_at_moves_credit_to_landing_interval(self):
        """申请 11-02、到账 11-03;11-03 抄表表底跳升 → 归 11-02→11-03 段。"""
        readings = [
            {"date": "2026-11-01", "hall": 31.2, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-11-02", "hall": 27.1, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-11-03", "hall": 236.5, "fire": 0, "private_room": 0, "ac": 0},
        ]
        charges = [{
            "date": "2026-11-02", "hall": 210.0, "fire": 0, "private_room": 0, "ac": 0,
            "status": "confirmed", "confirmed_at": "2026-11-03T12:09:42.538541",
        }]
        days = self._days(calculate_monthly_report(readings, charges, "2026-11"))
        # 11-01→11-02 段不该含充值:(31.2-27.1)×160 = 656
        self.assertEqual(days["2026-11-01"]["hall"], 656.0)
        # 11-02→11-03 段含充值:(27.1-236.5+210)×160 = 96
        self.assertEqual(days["2026-11-02"]["hall"], 96.0)

    def test_credit_consumed_same_day_still_counted(self):
        """到账当天抄表但表底没上升(钱当天就被用光)→ 归下一个区间,不能整笔漏掉。"""
        readings = [
            {"date": "2026-11-01", "hall": 100.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-11-02", "hall": 95.0, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-11-05", "hall": 80.0, "fire": 0, "private_room": 0, "ac": 0},
        ]
        charges = [{
            "date": "2026-11-01", "hall": 10.0, "fire": 0, "private_room": 0, "ac": 0,
            "status": "confirmed", "confirmed_at": "2026-11-02T09:00:00",
        }]
        r = calculate_monthly_report(readings, charges, "2026-11")
        # 11-02 抄到 95(比 100 低)说明这笔没体现在 11-02 读数里 → 归 11-02→11-05 段
        #   11-01→11-02 段: (100-95)×160        = 800
        #   11-02→11-05 段: (95-80+10)×160      = 4000
        #   合计 = 4800
        self.assertEqual(r["summary"]["total_kwh"], 4800.0)

    def test_credit_after_last_reading_not_counted_yet(self):
        """到账日之后还没抄表 → 钱还没进表底,不该算成任何一段的用电。"""
        readings = [
            {"date": "2026-11-01", "hall": 31.2, "fire": 0, "private_room": 0, "ac": 0},
            {"date": "2026-11-02", "hall": 27.1, "fire": 0, "private_room": 0, "ac": 0},
        ]
        charges = [{
            "date": "2026-11-02", "hall": 210.0, "fire": 0, "private_room": 0, "ac": 0,
            "status": "confirmed", "confirmed_at": "2026-11-03T12:09:42",
        }]
        r = calculate_monthly_report(readings, charges, "2026-11")
        self.assertEqual(r["summary"]["total_kwh"], 656.0)

    def test_legacy_charge_without_confirmed_at_uses_record_date(self):
        """历史记录 status/confirmed_at 为 null → 退回记录日期,保持 6 月 Excel 口径。"""
        from report import _landing_date
        self.assertEqual(_landing_date({"date": "2026-06-13"}), "2026-06-13")
        self.assertEqual(_landing_date({"date": "2026-06-13", "status": None}), "2026-06-13")
        self.assertEqual(
            _landing_date({"date": "2026-11-02", "status": "confirmed",
                           "confirmed_at": "2026-11-03T12:09:42"}),
            "2026-11-03",
        )
        self.assertEqual(
            _landing_date({"date": "2026-11-02", "status": "pending", "confirmed_at": None}),
            "2026-11-02",
        )
        r = calculate_monthly_report(READINGS, CHARGES, "2026-06")
        self.assertEqual(r["summary"]["total_kwh"], 71226.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
