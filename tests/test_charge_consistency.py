"""充值与抄表一致性回归测试(标准库 unittest,零依赖)。

问题 —— 用户在「每日趋势」页复制单天用电,拿到的是:
    🎤 大厅: 33456.0 度,¥30110.40 较昨日↑5708.3%
    — 合计: 89588.8 度,¥80629.92
而真实用电是 1130.3 度 / ¥1017.27。

根因 —— charges.json 里多了一条充值记录:
    {"id": "2026-11-11-1794369685771", "date": "2026-11-11",
     "hall": 205.7, "fire": 1706.5, "private_room": 197.6, "ac": 138.9}
四个数**和 2026-11-11 的抄表读数一模一样** —— 有人把当天抄的表底填进了充值栏。
系统照单全收,按「预付费表表底下降=用电、上升=刚到账」的口径把这笔「充值」算进了
11-11 → 11-12 区间的用电量,于是大厅凭空多出 205.7 × 160 = 32912 度。

物理上这笔钱不可能到账:如果 205.7 表字在 11-11 进表,11-12 的表底应该是
205.7 + 205.7 - 3.4 ≈ 408,实际抄到的是 202.3 —— 表底不升反降,钱根本没进表。

本文件固化三条防线:
  1. 后端 find_charge_conflicts() 能认出这种「把抄表读数当充值」的记录;
  2. 月报/每日趋势的归属口径自动跳过它(数字不再被顶飞);
  3. 录入充值时后端直接拒绝,并给出「是不是把抄表读数填错了」的提示。

运行:
    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "MeterStats"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from report import (  # noqa: E402
    calculate_monthly_report, find_charge_conflicts, find_pasted_reading_charges,
)

REPO = Path(__file__).resolve().parent.parent

# ---- fixture: 2026 年 11 月真实抄表数据(节选 11-01 ~ 11-12) ----
NOV_READINGS = [
    {"date": "2026-11-01", "hall": 31.2, "fire": 646.4, "private_room": 60.9, "ac": 149.3},
    {"date": "2026-11-02", "hall": 27.1, "fire": 600.1, "private_room": 57.1, "ac": 147.2},
    {"date": "2026-11-03", "hall": 233.6, "fire": 2055.5, "private_room": 223.8, "ac": 146.0},
    {"date": "2026-11-04", "hall": 230.4, "fire": 2010.8, "private_room": 220.7, "ac": 144.7},
    {"date": "2026-11-05", "hall": 227.2, "fire": 1967.1, "private_room": 217.4, "ac": 143.1},
    {"date": "2026-11-06", "hall": 223.5, "fire": 1923.4, "private_room": 214.3, "ac": 142.9},
    {"date": "2026-11-07", "hall": 220.0, "fire": 1880.2, "private_room": 211.0, "ac": 142.2},
    {"date": "2026-11-08", "hall": 216.0, "fire": 1836.7, "private_room": 207.4, "ac": 140.4},
    {"date": "2026-11-09", "hall": 212.5, "fire": 1793.2, "private_room": 203.9, "ac": 139.2},
    {"date": "2026-11-10", "hall": 209.3, "fire": 1750.3, "private_room": 200.7, "ac": 139.1},
    {"date": "2026-11-11", "hall": 205.7, "fire": 1706.5, "private_room": 197.6, "ac": 138.9},
    {"date": "2026-11-12", "hall": 202.3, "fire": 1664.2, "private_room": 194.3, "ac": 138.8},
]

# 真实充值:11-02 提申请 / 11-03 到账,金额是表字
LEGIT_CHARGE = {
    "id": "2026-11-02-1793602086282", "date": "2026-11-02",
    "hall": 210.0, "fire": 1500.0, "private_room": 170.0, "ac": 0.0,
    "note": "充值申请(充值计算器)", "status": "confirmed",
    "created_at": "2026-11-02T14:48:06.282603",
    "confirmed_at": "2026-11-03T12:09:42.538541",
}

# 事故记录:四个数 = 11-11 的抄表读数
BOGUS_CHARGE = {
    "id": "2026-11-11-1794369685771", "date": "2026-11-11",
    "hall": 205.7, "fire": 1706.5, "private_room": 197.6, "ac": 138.9,
    "note": "", "status": "confirmed",
    "created_at": "2026-11-11T12:01:25.771865",
}


class TestChargeConflictDetection(unittest.TestCase):
    """find_charge_conflicts():认出与抄表对不上的充值。"""

    def test_pasted_reading_charge_is_detected(self):
        conflicts = find_charge_conflicts(NOV_READINGS, [LEGIT_CHARGE, BOGUS_CHARGE])
        by_meter = {c["meter"]: c for c in conflicts}
        self.assertEqual(
            sorted(by_meter), ["ac", "fire", "hall", "private_room"],
            "四块表都应被判为矛盾(每块的金额都等于当天抄表读数)",
        )
        hall = by_meter["hall"]
        self.assertEqual(hall["charge_id"], BOGUS_CHARGE["id"])
        self.assertEqual(hall["date"], "2026-11-11")
        self.assertAlmostEqual(hall["amount"], 205.7, places=3)
        # 205.7 表字 × 160 倍率 = 32912 度凭空进了 11-11 → 11-12 这一天
        self.assertAlmostEqual(hall["implied_kwh"], 33456.0, places=1)

    def test_legit_charge_is_not_flagged(self):
        conflicts = find_charge_conflicts(NOV_READINGS, [LEGIT_CHARGE])
        self.assertEqual(conflicts, [], "真实充值(11-03 到账、表底跳升)不能被判为矛盾")

    def test_pending_charge_never_flagged(self):
        pending = dict(LEGIT_CHARGE, id="p1", status="pending")
        pending.pop("confirmed_at", None)
        conflicts = find_charge_conflicts(NOV_READINGS, [pending, BOGUS_CHARGE])
        self.assertNotIn("p1", [c["charge_id"] for c in conflicts])

    def test_charge_without_following_reading_is_not_flagged(self):
        """到账日之后还没抄表 → 无法证伪,必须放行(充值通常就是先到账、后抄表)。"""
        charges = [dict(LEGIT_CHARGE, id="future", date="2026-11-12", confirmed_at=None)]
        charges[0].pop("confirmed_at", None)
        conflicts = find_charge_conflicts(NOV_READINGS, charges)
        self.assertEqual(conflicts, [])

    def test_conflict_reason_mentions_reading(self):
        conflicts = find_charge_conflicts(NOV_READINGS, [LEGIT_CHARGE, BOGUS_CHARGE])
        self.assertTrue(conflicts)
        for c in conflicts:
            self.assertTrue(c.get("reason"), "每条矛盾都要有可展示的原因")


class TestMonthlyReportSkipsConflicts(unittest.TestCase):
    """月报归属口径:矛盾的充值不计入用电量。"""

    def setUp(self):
        # 月报按 month 键缓存,即使参数不同也命中同一个 key —— 换数据必须先清缓存
        from report import invalidate_report_cache
        invalidate_report_cache()

    def test_bogus_charge_does_not_inflate_month_total(self):
        with_bogus = calculate_monthly_report(NOV_READINGS, [LEGIT_CHARGE, BOGUS_CHARGE], "2026-11")
        without = calculate_monthly_report(NOV_READINGS, [LEGIT_CHARGE], "2026-11")
        self.assertAlmostEqual(
            with_bogus["summary"]["total_kwh"], without["summary"]["total_kwh"], places=1,
            msg="与抄表矛盾的充值不得改变月报用电量",
        )
        # 真实用量:11-01 ~ 11-12 共 12 次抄表,合计 14242.2 度
        self.assertAlmostEqual(without["summary"]["total_kwh"], 14242.2, places=1)

    def test_report_exposes_conflicts_for_ui_warning(self):
        r = calculate_monthly_report(NOV_READINGS, [LEGIT_CHARGE, BOGUS_CHARGE], "2026-11")
        conflicts = r.get("conflicts") or []
        self.assertEqual(len(conflicts), 4, "月报要把矛盾记录带出来给界面提示")

    def test_clean_month_has_no_conflicts(self):
        r = calculate_monthly_report(NOV_READINGS, [LEGIT_CHARGE], "2026-11")
        self.assertEqual(r.get("conflicts") or [], [])


class TestJuneRegressionUnchanged(unittest.TestCase):
    """2026 年 6 月 Excel 核对值 71226.1 度 —— 口径改动绝不能动它。"""

    def setUp(self):
        from report import invalidate_report_cache
        invalidate_report_cache()

    def test_june_total_still_matches_excel(self):
        from test_monthly_report import READINGS, CHARGES  # 同目录 fixture
        r = calculate_monthly_report(READINGS, CHARGES, "2026-06")
        self.assertAlmostEqual(r["summary"]["total_kwh"], 71226.1, places=1)
        self.assertEqual(r.get("conflicts") or [], [], "6 月数据不该被判出矛盾")


class FakeHandler:
    """模拟 BaseHTTPRequestHandler 的最小实现,捕获响应。"""

    def __init__(self, path: str, body: Optional[dict] = None, method: str = "POST"):
        self.path = path
        self.command = method
        self.response_status = None
        self.response_headers = {}
        self.response_body = b""
        self.wfile = io.BytesIO()
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        self.rfile = io.BytesIO(raw)
        self.headers = {"Content-Length": str(len(raw))}

    def send_response(self, status):
        self.response_status = status

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass

    @property
    def parsed(self):
        body = self.wfile.getvalue()
        return json.loads(body) if body else None


class TestChargeEntryValidation(unittest.TestCase):
    """录入充值时就要拦住「把抄表读数填进充值栏」。"""

    def setUp(self):
        import routing
        self._prev_enforce = routing.ENFORCE_AUTH
        routing.ENFORCE_AUTH = False

        import app_handler
        self.app_handler = app_handler
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)
        paths = {
            "readings": data_dir / "readings.json",
            "readings_water": data_dir / "readings_water.json",
            "charges": data_dir / "charges.json",
            "items": data_dir / "items.json",
            "purchases": data_dir / "purchases.json",
            "duty": data_dir / "duty.json",
        }
        app_handler.DATA_PATHS = paths
        for p in paths.values():
            p.write_text("[]", encoding="utf-8")
        (data_dir / "readings.json").write_text(
            json.dumps(NOV_READINGS), encoding="utf-8")

    def tearDown(self):
        import routing
        routing.ENFORCE_AUTH = self._prev_enforce
        self.tmp.cleanup()

    def call(self, method: str, path: str, body: Optional[dict] = None) -> FakeHandler:
        h = FakeHandler(path, body, method)
        self.app_handler._do_api(method, h, path)
        return h

    def test_post_pasted_reading_is_rejected(self):
        h = self.call("POST", "/api/charges", dict(BOGUS_CHARGE, id=None))
        self.assertEqual(h.response_status, 400)
        err = (h.parsed or {}).get("error", "")
        self.assertTrue(err, "必须给出错误提示")
        self.assertIn("抄表", err, "提示要指向「把抄表读数填进充值栏」这个具体错误")

    def test_rejected_charge_is_not_saved(self):
        self.call("POST", "/api/charges", dict(BOGUS_CHARGE, id=None))
        saved = json.loads(
            (Path(self.tmp.name) / "charges.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, [], "被拒绝的充值不能落库")

    def test_legit_charge_is_accepted(self):
        h = self.call("POST", "/api/charges", {
            "date": "2026-11-02", "hall": 210.0, "fire": 1500.0,
            "private_room": 170.0, "ac": 0.0,
        })
        self.assertEqual(h.response_status, 200, (h.parsed or {}).get("error"))
        saved = json.loads(
            (Path(self.tmp.name) / "charges.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)

    def test_charge_for_today_is_accepted(self):
        """今天刚充值、还没抄表 → 无法证伪,必须放行。"""
        h = self.call("POST", "/api/charges", {
            "date": "2026-11-13", "hall": 50.0, "fire": 0, "private_room": 0, "ac": 0,
        })
        self.assertEqual(h.response_status, 200, (h.parsed or {}).get("error"))


class TestFrontendChargeConflicts(unittest.TestCase):
    """前端(js/core/meterConfig.js)必须和后端用同一套规则。

    后端已经挡住"把抄表读数填进充值栏"的记录,但「每日趋势」页的单天复制是**前端**
    自己算的(js/modules/render_charts.js::copyDayUsage),前端不算一遍的话,复制出去的
    文本仍然是 89588.8 度。这里用 node 跑真实前端代码验证。
    """

    def _run_node(self, script: str, readings=None, charges=None):
        node = shutil.which("node")
        if not node:
            self.skipTest("需要 node 才能验证前端行为")
        env = dict(os.environ, MS_ROOT=str(REPO),
                   MS_READINGS=json.dumps(readings if readings is not None else NOV_READINGS),
                   MS_CHARGES=json.dumps(charges if charges is not None
                                         else [LEGIT_CHARGE, BOGUS_CHARGE]))
        proc = subprocess.run([node, "-e", script], capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_frontend_copy_text_shows_real_usage_not_inflated(self):
        script = r"""
const fs=require('fs'), vm=require('vm');
const ROOT=process.env.MS_ROOT;
const sandbox={console};
sandbox.window=sandbox;
sandbox.document={ getElementById:(id)=> (id==='day-copy-date'?{value:'2026-11-11'}:null) };
sandbox.navigator={};
vm.createContext(sandbox);
for (const f of ['js/helpers/utils.js','js/core/meterConfig.js','js/modules/render_charts.js']) {
  vm.runInContext(fs.readFileSync(ROOT+'/MeterStats/'+f,'utf8'), sandbox, {filename:f});
}
sandbox.CURRENT_READINGS=JSON.parse(process.env.MS_READINGS);
sandbox.CURRENT_CHARGES=JSON.parse(process.env.MS_CHARGES);
sandbox.showAlert=()=>{};
sandbox.__captured='';
sandbox.copyTextWithFallback=(t)=>{ sandbox.__captured=t; };
sandbox.copyDayUsage();
process.stdout.write(sandbox.__captured);
"""
        text = self._run_node(script)
        self.assertNotIn("89588.8", text, "复制出去的合计不能是被顶飞的 89588.8 度")
        self.assertNotIn("33456.0", text, "大厅不能是被顶飞的 33456 度")
        self.assertIn("1130.3", text, "合计应是真实用电 1130.3 度")
        self.assertIn("544.0", text, "大厅应是 544.0 度")

    def test_frontend_copy_text_warns_about_conflict(self):
        script = r"""
const fs=require('fs'), vm=require('vm');
const ROOT=process.env.MS_ROOT;
const sandbox={console};
sandbox.window=sandbox;
sandbox.document={ getElementById:(id)=> (id==='day-copy-date'?{value:'2026-11-11'}:null) };
sandbox.navigator={};
vm.createContext(sandbox);
for (const f of ['js/helpers/utils.js','js/core/meterConfig.js','js/modules/render_charts.js']) {
  vm.runInContext(fs.readFileSync(ROOT+'/MeterStats/'+f,'utf8'), sandbox, {filename:f});
}
sandbox.CURRENT_READINGS=JSON.parse(process.env.MS_READINGS);
sandbox.CURRENT_CHARGES=JSON.parse(process.env.MS_CHARGES);
sandbox.showAlert=()=>{};
sandbox.__captured='';
sandbox.copyTextWithFallback=(t)=>{ sandbox.__captured=t; };
sandbox.copyDayUsage();
process.stdout.write(sandbox.__captured);
"""
        text = self._run_node(script)
        self.assertIn("充值", text, "复制出去的文本要提醒用户去处理那条充值记录")
        self.assertIn("2026-11-11", text)

    def test_frontend_and_backend_agree_on_conflicts(self):
        """前后端判出的矛盾记录必须完全一致(两套规则不许分叉)。"""
        script = r"""
const fs=require('fs'), vm=require('vm');
const ROOT=process.env.MS_ROOT;
const sandbox={console};
sandbox.window=sandbox;
sandbox.document={ getElementById:()=>null };
sandbox.navigator={};
vm.createContext(sandbox);
for (const f of ['js/helpers/utils.js','js/core/meterConfig.js']) {
  vm.runInContext(fs.readFileSync(ROOT+'/MeterStats/'+f,'utf8'), sandbox, {filename:f});
}
sandbox.CURRENT_READINGS=JSON.parse(process.env.MS_READINGS);
sandbox.CURRENT_CHARGES=JSON.parse(process.env.MS_CHARGES);
process.stdout.write(JSON.stringify(sandbox.findChargeConflicts(sandbox.CURRENT_CHARGES)));
"""
        out = self._run_node(script)
        js_conflicts = {(c["charge_id"], c["meter"]) for c in json.loads(out)}
        py_conflicts = {(c["charge_id"], c["meter"])
                        for c in find_charge_conflicts(NOV_READINGS, [LEGIT_CHARGE, BOGUS_CHARGE])}
        self.assertEqual(js_conflicts, py_conflicts, "前端与后端的矛盾判定必须一致")
        self.assertEqual(len(py_conflicts), 4)

    def test_frontend_and_backend_agree_on_late_landing(self):
        """钱晚点才进表的充值:前后端都必须改归属到表底跳升的那一段。"""
        script = r"""
const fs=require('fs'), vm=require('vm');
const ROOT=process.env.MS_ROOT;
const sandbox={console};
sandbox.window=sandbox;
sandbox.document={ getElementById:()=>null };
sandbox.navigator={};
vm.createContext(sandbox);
for (const f of ['js/helpers/utils.js','js/core/meterConfig.js']) {
  vm.runInContext(fs.readFileSync(ROOT+'/MeterStats/'+f,'utf8'), sandbox, {filename:f});
}
sandbox.CURRENT_READINGS=JSON.parse(process.env.MS_READINGS);
sandbox.CURRENT_CHARGES=JSON.parse(process.env.MS_CHARGES);
const map=sandbox.chargeAttribution(sandbox.CURRENT_CHARGES,'hall');
process.stdout.write(JSON.stringify(map));
"""
        out = self._run_node(script,
                             readings=TestLateLandingChargeIsNotAConflict.READINGS,
                             charges=[TestLateLandingChargeIsNotAConflict.CHARGE])
        js_map = json.loads(out)
        self.assertEqual(
            [(m["start"], m["end"], m["meterVal"]) for m in js_map],
            [("2026-11-12", "2026-11-13", 210.0)],
            "前端也必须把这笔钱归到 11-12 → 11-13(表底真正跳升的那段)",
        )


class TestPastedReadingDetection(unittest.TestCase):
    """「充值额 = 当天抄表读数」—— 把抄表读数填进充值栏的直接指纹。"""

    def test_pasted_reading_is_detected(self):
        hits = find_pasted_reading_charges(NOV_READINGS, [LEGIT_CHARGE, BOGUS_CHARGE])
        self.assertEqual(len(hits), 4, "四块表的金额都等于当天抄表读数")
        self.assertEqual({h["meter"] for h in hits},
                         {"hall", "fire", "private_room", "ac"})
        for h in hits:
            self.assertIn("抄表", h["reason"])

    def test_legit_charge_not_flagged(self):
        """真实充值:表底当天跳升,读数里已经体现了 → 不是填错。"""
        self.assertEqual(find_pasted_reading_charges(NOV_READINGS, [LEGIT_CHARGE]), [])

    def test_pending_charge_not_flagged(self):
        pending = dict(LEGIT_CHARGE, id="p1", status="pending")
        pending.pop("confirmed_at", None)
        hits = find_pasted_reading_charges(NOV_READINGS, [pending, BOGUS_CHARGE])
        self.assertNotIn("p1", [h["charge_id"] for h in hits])


class TestLateLandingChargeIsNotAConflict(unittest.TestCase):
    """钱晚点才进表的充值不能被当成错记录排除。

    11-11 申请充值 210 表字,11-11 抄表时钱还没到(表底没上升),11-13 才进表。
    归属区间 [11-11, 11-12] 算出来的用电会离谱,但钱确实进表了 —— 后面 11-12 → 11-13
    表底跳升就是证据。这种记录必须保留,只是它没落在当前区间里。
    """

    READINGS = NOV_READINGS + [
        {"date": "2026-11-13", "hall": 409.0, "fire": 1662.0, "private_room": 391.3, "ac": 138.5},
    ]
    CHARGE = {
        "id": "late-2026-11-11", "date": "2026-11-11",
        "hall": 210.0, "fire": 0, "private_room": 0, "ac": 0,
        "status": "confirmed", "created_at": "2026-11-11T12:00:00",
    }

    def test_not_flagged_as_conflict(self):
        conflicts = find_charge_conflicts(self.READINGS, [self.CHARGE])
        self.assertEqual(conflicts, [], "钱在后面的区间进了表,不能判成错记录")

    def test_still_counted_in_usage(self):
        from report import invalidate_report_cache
        invalidate_report_cache()
        r = calculate_monthly_report(self.READINGS, [self.CHARGE], "2026-11")
        self.assertEqual(r.get("conflicts") or [], [])
        days = {d["date"]: d for d in r["days"]}
        # 11-11 → 11-12 这段钱还没进表,用电就是表底差 (205.7-202.3)×160 = 544
        self.assertAlmostEqual(days["2026-11-11"]["hall"], 544.0, places=1,
                               msg="钱没进表的那段不能被算成 34144 度")
        # 钱在 11-12 → 11-13 这段进的表 → (202.3 + 210 - 409.0)×160 = 528
        self.assertAlmostEqual(days["2026-11-12"]["hall"], 528.0, places=1,
                               msg="钱进表的那段用电必须算得出来(不能被算成 0)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
