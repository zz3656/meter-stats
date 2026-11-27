"""切门店后报表区必须清空/重载(标准库 unittest,零依赖)。

用户报告:在分店页面点开报表,里面显示的是**总店**的数据。

根因(不是后端串店):切门店后 `loadAppData()` 会按**新门店**的抄表数据重建
「月份」下拉。刚建的分店一条抄表都没有 → 下拉被清空 → `loadMonthlyReport()`
读到空月份就 early return(**不重拉**)→ 屏幕上还留着上一家店的表格与概况。
于是「分店页面显示总店数据」。

修法:**没有数据也要显式渲染成空态**,不能什么都不做。
`resetReportView()` 负责把月度表格/概况卡/水电区/年报区一起清干净,
连"复制"用的缓存也清掉(否则复制出来的还是上一家店的数字)。

覆盖:
- 静态:reports.js 定义 resetReportView;init.js 在月份为空的分支里调用它
- node 行为:调用后表格隐藏、空态显示、概况卡清空、水电/年报复位、缓存被清

运行:
    python3 -m unittest tests.test_report_store_switch -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
INIT_JS = METERSTATS / "js" / "core" / "init.js"
REPORTS_JS = METERSTATS / "js" / "modules" / "reports.js"


class TestReportResetStatic(unittest.TestCase):
    def test_reports_js_defines_reset(self) -> None:
        src = REPORTS_JS.read_text(encoding="utf-8")
        self.assertRegex(src, r"(?m)^function resetReportView\(\)")

    def test_init_calls_reset_when_no_months(self) -> None:
        """月份为空(NEW 门店没数据)时必须调用 resetReportView。

        只做字符串包含不够 —— 把调用注释掉也得能被抓住,所以匹配未注释的实际调用。
        """
        src = INIT_JS.read_text(encoding="utf-8")
        body = src[src.index("window.loadAppData"):]
        body = body[:body.index("// 抄表提醒")]

        # 必须**无条件**清(切到"有数据"的门店时年报区也需要清),
        # 且要在重建月份下拉之前 —— 否则下拉一填就又渲染成旧数据了。
        self.assertRegex(
            body,
            r"(?m)^\s*(?:try \{ )?if \(typeof resetReportView === 'function'\) resetReportView\(\);",
            "loadAppData 没有调用 resetReportView —— 会留着上一家店的报表",
        )
        self.assertLess(body.index("resetReportView()"), body.index("const months ="),
                        "resetReportView 要在重建月份下拉之前调用")
        self.assertIn("reportMonth.value = ''", body,
                      "月份为空时没有把下拉清空")


_NODE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

const els = {};
function mk(id) { return { id: id, innerHTML: '', textContent: '', style: {} }; }
['monthly-report-table', 'report-body', 'report-empty', 'monthly-stat-grid',
 'report-thead-row', 'btn-copy-report', 'utilities-result', 'btn-copy-utilities',
 'yearly-result', 'btn-copy-yearly', 'report-month', 'yearly-year']
  .forEach(id => { els[id] = mk(id); });

let resetCalls = 0;

const sandbox = {
  // 空态/骨架助手:被加载的模块会调它们;这里给最小实现(断言不关心外观)
  emptyStateHtml: (o) => '<div class="empty-state">' + String((o && o.title) || '') + '</div>',
  emptyRowHtml: (n, o) => '<tr class="empty-row"><td colspan="' + n + '">' +
    String((o && o.title) || '') + '</td></tr>',
  skeletonRowsHtml: (r, c) => '<tr class="skeleton-row"><td>' + r + 'x' + c + '</td></tr>',
  skeletonCardsHtml: (n) => '<div class="skeleton-card"></div>',
  showBootSkeletons: () => {},
  clearSkeletons: () => {},
  console, JSON, Object, Array, String, Number, Math, Date, isNaN, parseInt, parseFloat,
  document: { getElementById: id => (els[id] || null), querySelectorAll: () => [], querySelector: () => null },
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

sandbox.METER_KEYS = ['hall', 'fire', 'private_room', 'ac'];
sandbox.METER_META = k => ({ label: k, multiplier: 1, color: '#888' });
sandbox.LABELS = k => k;
sandbox.COLORS = k => '#888';
sandbox.ELECTRICITY_PRICE = 0.9;
sandbox.WATER_PRICE = 4.5;
sandbox.escapeHtml = s => String(s == null ? '' : s);
sandbox.escapeAttr = sandbox.escapeHtml;
sandbox.resetReportCaches = function () { resetCalls += 1; };
sandbox.CURRENT_READINGS = [];

vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/modules/reports.js'), 'utf8'),
                sandbox, { filename: 'reports.js' });

// 先摆成"上一家店的报表还留在屏幕上"的状态
els['monthly-report-table'].style.display = 'block';
els['report-empty'].style.display = 'none';
els['monthly-stat-grid'].innerHTML = '<div>总店的概况卡</div>';
els['monthly-stat-grid'].style.display = '';
els['report-body'].innerHTML = '<tr><td>总店的一行</td></tr>';
els['utilities-result'].innerHTML = '<div>总店的水电</div>';
els['btn-copy-utilities'].style.display = '';
els['yearly-result'].innerHTML = '<div>总店的年报</div>';
els['btn-copy-yearly'].style.display = '';

sandbox.resetReportView();

console.log(JSON.stringify({
  tableDisplay: els['monthly-report-table'].style.display,
  emptyDisplay: els['report-empty'].style.display,
  statGridHtml: els['monthly-stat-grid'].innerHTML,
  statGridDisplay: els['monthly-stat-grid'].style.display,
  utilHtml: els['utilities-result'].innerHTML,
  utilCopy: els['btn-copy-utilities'].style.display,
  yearlyHtml: els['yearly-result'].innerHTML,
  yearlyCopy: els['btn-copy-yearly'].style.display,
  resetCalls: resetCalls,
  bodyHtml: els['report-body'].innerHTML,
}));
"""


class TestReportResetBehaviour(unittest.TestCase):
    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "reset_harness.js"
        hp.write_text(_NODE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_table_hidden_and_empty_shown(self) -> None:
        o = self.out
        self.assertEqual(o["tableDisplay"], "none", "月度表格没隐藏 —— 还留着上一家店的表")
        self.assertEqual(o["emptyDisplay"], "block", "没有显示空态提示")

    def test_stat_cards_cleared(self) -> None:
        o = self.out
        self.assertEqual(o["statGridHtml"], "", "概况卡没清空 —— 还显示上一家店的数字")
        self.assertEqual(o["statGridDisplay"], "none")

    def test_utilities_and_yearly_reset(self) -> None:
        o = self.out
        self.assertNotIn("总店", o["utilHtml"], "水电区还留着上一家店的内容")
        self.assertNotIn("总店", o["yearlyHtml"], "年报区还留着上一家店的内容")
        self.assertEqual(o["utilCopy"], "none")
        self.assertEqual(o["yearlyCopy"], "none")

    def test_copy_caches_reset(self) -> None:
        """复制用的缓存必须清 —— 否则「复制月报」复制出来还是上一家店的数字。"""
        self.assertGreaterEqual(self.out["resetCalls"], 1, "没有清报表缓存")


if __name__ == "__main__":
    unittest.main()
