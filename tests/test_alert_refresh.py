"""余量预警卡刷新回归测试(标准库 unittest,零依赖)。

背景:v0.4.1 起余量 = 最新抄表读数 + 已到账但还没反映进读数的充值,
卡片上会出现绿色提示「含 N 度已到账未抄表(YYYY-MM-DD 抄表 X 表字)」。
录入今日抄表后,这笔充值应该已经被抄进读数,提示必须消失。

曾经的 bug:renderChargeAlert() 全仓只在 renderAll() 里被调用,
而录入/删除抄表、确认充值走的都是 refreshAndRender() —— 数据更新了但卡片
没重绘,于是「已录入今日抄表,绿色提示却不消失」。

本文件覆盖:
- refreshAndRenderTables() 必须调用 renderChargeAlert(静态接线,永远执行)
- 真实前端文件 + 真实算法:录入今日抄表后提示确实消失(需要 node,缺失则跳过)

运行:
    python3 -m unittest tests.test_alert_refresh -v
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
READINGS_JS = METERSTATS / "js" / "modules" / "readings.js"


class TestAlertRefreshWiring(unittest.TestCase):
    """静态接线检查:数据刷新路径必须重绘余量预警卡。"""

    def test_refresh_and_render_tables_rerenders_alert_card(self):
        src = READINGS_JS.read_text(encoding="utf-8")
        m = re.search(r"function refreshAndRenderTables\(\)\s*\{[\s\S]*?\n\}", src)
        self.assertIsNotNone(m, "读不到 refreshAndRenderTables()")
        self.assertIn(
            "renderChargeAlert", m.group(0),
            "refreshAndRenderTables() 必须调用 renderChargeAlert —— "
            "否则录入/删除抄表、确认充值后余量预警卡不重绘,"
            "「含 N 度已到账未抄表」的绿色提示不会消失",
        )

    def test_render_charge_alert_is_reachable_from_data_refresh(self):
        """renderChargeAlert 不应只挂在 renderAll() 上(登录/NAS 同步才会触发)。"""
        src = READINGS_JS.read_text(encoding="utf-8")
        occurrences = src.count("renderChargeAlert(")
        # 至少两处:renderAll() 一处 + refreshAndRenderTables() 一处
        self.assertGreaterEqual(
            occurrences, 2,
            "renderChargeAlert 只被调用了 %d 次 —— 日常录入抄表走的路径必须能重绘预警卡" % occurrences,
        )


# ============ 行为验证(需要 node) ============

_HARNESS = r"""
// 用真实前端文件 + 构造数据,验证余量预警卡的提示随抄表录入而消失
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
const sandbox = {
  document: {
    getElementById: (id) => (sandbox.__c[id] || (sandbox.__c[id] = { innerHTML: '', style: {} })),
    querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ style: {}, dataset: {}, appendChild(){}, setAttribute(){} }),
  },
  console, setTimeout, clearTimeout, Math, JSON, Date, Number, String, Array, Object, Map, Set,
  fetch: () => Promise.reject(new Error('offline')),
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  showModal: () => Promise.resolve(false), showAlert: () => {},
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
sandbox.__c = {};
vm.createContext(sandbox);
for (const f of ['js/core/meterConfig.js', 'js/modules/alerts.js']) {
  vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), sandbox, { filename: f });
}
const readings = JSON.parse(fs.readFileSync(process.env.MS_READINGS, 'utf8'));
const charges  = JSON.parse(fs.readFileSync(process.env.MS_CHARGES, 'utf8'));
const HINT = /含\s*([\d]+)\s*度已到账未抄表/;
function render(rows) {
  sandbox.__c = {};
  sandbox.CURRENT_READINGS = rows;
  sandbox.CURRENT_CHARGES = charges;
  sandbox.renderChargeAlert(rows, charges);
  return sandbox.__c['reading-alerts-container'].innerHTML;
}
const sorted = readings.slice().sort((a, b) => a.date.localeCompare(b.date));
const lastDate = sorted[sorted.length - 1].date;
const before = sorted.filter(r => r.date !== lastDate);   // 今日抄表未录入
const mBefore = render(before).match(HINT);
const mAfter  = render(sorted).match(HINT);                 // 今日抄表已录入
console.log(JSON.stringify({
  hadHintBefore: !!mBefore,
  kwhBefore: mBefore ? mBefore[1] : null,
  hadHintAfter: !!mAfter,
}));
"""


class TestAlertBehaviorWithNode(unittest.TestCase):
    """用真实前端文件跑一遍:录入今日抄表后提示必须消失。"""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, readings, charges):
        rp = Path(self.tmp.name) / "readings.json"
        cp = Path(self.tmp.name) / "charges.json"
        rp.write_text(json.dumps(readings, ensure_ascii=False), encoding="utf-8")
        cp.write_text(json.dumps(charges, ensure_ascii=False), encoding="utf-8")
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_HARNESS, encoding="utf-8")

        env = dict(**__import__("os").environ)
        env.update(MS_ROOT=str(METERSTATS), MS_READINGS=str(rp), MS_CHARGES=str(cp))
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg=f"node 执行失败:\n{proc.stderr}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_hint_disappears_after_reading_entered(self):
        """构造场景:已确认到账的充值 + 今日抄表。

        - 今日抄表未录入 → 卡片应出现「含 N 度已到账未抄表」
        - 今日抄表录入后 → 提示必须消失(该充值已被抄进读数)
        """
        readings = [
            {"date": "2026-11-01", "hall": 31.2, "fire": 646.4, "private_room": 60.9, "ac": 149.3},
            {"date": "2026-11-02", "hall": 27.1, "fire": 600.1, "private_room": 57.1, "ac": 147.2},
        ]
        charges = [{
            "id": "c1", "date": "2026-11-02", "status": "confirmed",
            "confirmed_at": "2026-11-03T12:09:42", "hall": 210.0,
        }]

        out = self._run(readings, charges)
        self.assertTrue(out["hadHintBefore"], "今日抄表未录入时,提示应存在")
        self.assertEqual(out["kwhBefore"], "33600", "提示数值应为 210 表字 × 160 倍率 = 33600 度")

        # 录入今日抄表:表底跳升(27.1 → 233.6),该充值已被抄进读数
        readings.append({
            "date": "2026-11-03", "hall": 233.6, "fire": 2055.5,
            "private_room": 223.8, "ac": 146.0,
        })
        out2 = self._run(readings, charges)
        self.assertFalse(
            out2["hadHintAfter"],
            "录入今日抄表后,「含 N 度已到账未抄表」的绿色提示必须消失 —— "
            "实际仍在,说明余量预警卡没有随数据刷新重绘",
        )


if __name__ == "__main__":
    unittest.main()
