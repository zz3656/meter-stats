"""报表 / 图表 / 告警的表集合动态化测试(标准库 unittest,零依赖)。

P2 Task 5 —— 报表、图表、周趋势、告警全部按**当前门店**的表集合渲染。

改造前盘面:`reports.js` 14 处、`render_pie_charts.js` 6 处、`render_charts.js` 5 处、
`alerts.js` 5 处、`render_weekly*.js` 各 2 处,外加 `index.html` 里月报表头的 4 个 `<th>`。

最阴的一处不是列数,而是 `r.hall != null` 这个过滤条件 —— 全项目用它判断
「这行是不是只录了水电、要跳过」。2 表门店没有 hall 表,这个判断会把**整月读数
全部跳过** → 报表 0 度、图表空白,而且不报错。已统一换成 `rowHasMeterValues()`
(对应后端的 `row_has_any_value`)。

覆盖:
- 静态:各文件都从 METER_KEYS 取表集合;不许再有 `r.hall != null`;月报表头是空 tr
- node 行为:2 表门店的月报表格列数/表头列数/合计行都跟着变;默认 4 表不变;
  `rowHasMeterValues` 认可自定义表、也认可 0(表底真到 0 了)

运行:
    python3 -m unittest tests.test_dynamic_render -v
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
INDEX_HTML = METERSTATS / "index.html"

MODULES = [
    "reports.js", "render_charts.js", "render_pie_charts.js",
    "render_weekly.js", "alerts.js",
]


class TestRenderStaticGuards(unittest.TestCase):
    """静态护栏 —— 不需要 node。"""

    def test_every_file_reads_meter_keys(self) -> None:
        """每个文件都必须从 METER_KEYS / rowHasMeterValues 取表集合。"""
        for name in MODULES:
            src = (METERSTATS / "js" / "modules" / name).read_text(encoding="utf-8")
            self.assertTrue(
                ("METER_KEYS" in src) or ("_reportMeterKeys" in src)
                or ("rowHasMeterValues" in src),
                "%s 里没有引用 METER_KEYS —— 仍按写死的 4 表渲染" % name,
            )

    def test_no_hall_null_filter_left(self) -> None:
        """`r.hall != null` / `r.hall == null` 一个都不许留。

        门店没有 hall 表时它会把整月读数全部跳过(报表 0 度、图表空白),
        而且不报错 —— 这是本期最难排查的一处。
        """
        offenders = []
        for name in MODULES:
            f = METERSTATS / "js" / "modules" / name
            for no, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
                if ".hall != null" in line or ".hall == null" in line:
                    offenders.append("%s:%d: %s" % (name, no, line.strip()[:80]))
        self.assertEqual(offenders, [],
                         "还能按写死的 hall 过滤读数(2 表门店会整月 0 度):\n  "
                         + "\n  ".join(offenders))

    def test_meter_config_loads_before_consumers(self) -> None:
        """`meterConfig.js` 必须排在所有用到表集合的模块之前。

        那些模块是**裸标识符**调用 `rowHasMeterValues()` / `MULTIPLIER()` 的,
        顺序错了就是整页 ReferenceError。改造中确实踩到过(测试沙箱里没桩 →
        `rowHasMeterValues is not defined`),所以把顺序也锁住。
        """
        html = INDEX_HTML.read_text(encoding="utf-8")
        pos_config = html.find("js/core/meterConfig.js")
        self.assertGreater(pos_config, 0, "index.html 没有引入 meterConfig.js")
        for name in MODULES:
            pos = html.find("js/modules/" + name)
            self.assertGreater(pos, 0, "index.html 没有引入 %s" % name)
            self.assertGreater(pos, pos_config,
                               "%s 排在 meterConfig.js 之前 —— 会 ReferenceError" % name)

    def test_report_table_head_is_dynamic(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="report-thead-row"', html)
        src = (METERSTATS / "js" / "modules" / "reports.js").read_text(encoding="utf-8")
        self.assertIn("report-thead-row", src, "reports.js 没有填充月报表头")


_NODE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox(keys, meta) {
  const els = {};
  function mk(id) { return { id: id, innerHTML: '', style: {}, textContent: '' }; }
  ['monthly-report-table', 'report-body', 'report-empty', 'monthly-stat-grid',
   'report-thead-row', 'btn-copy-report'].forEach(id => { els[id] = mk(id); });

  const sandbox = {
    console, JSON, Object, Array, String, Number, Math, Date, isNaN, parseInt, parseFloat,
    document: {
      getElementById: id => (id in els ? els[id] : null),
      querySelectorAll: () => [],
      querySelector: () => null,
    },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  sandbox.ELECTRICITY_PRICE = 0.9;
  sandbox.WATER_PRICE = 4.5;
  sandbox.escapeHtml = s => String(s == null ? '' : s)
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ⚠️ 先加载 meterConfig.js:它在加载时会执行 resetMeterConfig(),
  // 把 METER_KEYS/METER_CONFIG 重置成默认 4 表。必须**加载之后**再喂测试数据,
  // 否则写在前面的 METER_KEYS 会被它覆盖掉(表现为"改了没生效")。
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/meterConfig.js'), 'utf8'),
                  sandbox, { filename: 'meterConfig.js' });

  sandbox.METER_KEYS = keys;
  sandbox.METER_CONFIG = meta;
  sandbox.METER_META = k => meta[k] || { label: k, multiplier: 1, color: '#888' };
  sandbox.LABELS = k => (meta[k] || { label: k }).label;
  sandbox.COLORS = k => (meta[k] || {}).color || '#888';
  sandbox.MULTIPLIER = k => (meta[k] || {}).multiplier || 1;

  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/modules/reports.js'), 'utf8'),
                  sandbox, { filename: 'reports.js' });
  return sandbox;
}

function report2() {
  return {
    month: '2026-09',
    days: [
      { date: '2026-09-01', m1: 2.0, m2: 3.0, total: 5.0 },
      { date: '2026-09-02', m1: 4.0, m2: 6.0, total: 10.0 },
    ],
    summary: { total_kwh: 15.0, by_meter: { m1: 6.0, m2: 9.0 }, price: 0.9 },
    conflicts: [],
  };
}

function countTag(html, tag) {
  return (html.match(new RegExp('<' + tag + '[ >]', 'g')) || []).length;
}

const out = {};

// ① 2 表门店:每日行 = 日期 + 2 表 + 合计 = 4 个 td;表头 = 4 个 th
{
  const meta = { m1: { label: '吧台', multiplier: 80 }, m2: { label: '后厨', multiplier: 1 } };
  const s = makeSandbox(['m1', 'm2'], meta);
  s.renderMonthlyReportTable(report2());
  const body = s.document.getElementById('report-body').innerHTML;
  const head = s.document.getElementById('report-thead-row').innerHTML;
  const firstRow = body.split('</tr>')[0];
  out.twoMeter = {
    headCols: countTag(head, 'th'),
    headHtml: head,
    firstRowCells: countTag(firstRow, 'td'),
    firstRowHtml: firstRow,
    totalRowCells: countTag(body.split('</tr>').slice(-2)[0], 'td'),
    hasHall: body.indexOf('hall') >= 0,
  };
}

// ② 默认 4 表:列数与改造前一致(日期 + 4 + 合计 = 6)
{
  const meta = {
    hall: { label: '大厅', multiplier: 160 }, fire: { label: '消防', multiplier: 1 },
    private_room: { label: '包厢', multiplier: 160 }, ac: { label: '空调', multiplier: 160 },
  };
  const s = makeSandbox(['hall', 'fire', 'private_room', 'ac'], meta);
  s.renderMonthlyReportTable({
    month: '2026-09',
    days: [{ date: '2026-09-01', hall: 1, fire: 2, private_room: 3, ac: 4, total: 10 }],
    summary: { total_kwh: 10, by_meter: {}, price: 0.9 },
    conflicts: [],
  });
  const body = s.document.getElementById('report-body').innerHTML;
  const head = s.document.getElementById('report-thead-row').innerHTML;
  out.fourMeter = {
    headCols: countTag(head, 'th'),
    firstRowCells: countTag(body.split('</tr>')[0], 'td'),
    headHtml: head,
  };
}

// ③ rowHasMeterValues:认自定义表、认 0、不认"只有 date"
{
  const meta = { m1: { label: '吧台', multiplier: 1 }, m2: { label: '后厨', multiplier: 1 } };
  const s = makeSandbox(['m1', 'm2'], meta);
  // 旧 4 表的门店要单独建沙箱:同一家店不可能既有 m1 又有 hall
  const legacyMeta = {
    hall: { label: '大厅', multiplier: 160 }, fire: { label: '消防', multiplier: 1 },
    private_room: { label: '包厢', multiplier: 160 }, ac: { label: '空调', multiplier: 160 },
  };
  const sLegacy = makeSandbox(['hall', 'fire', 'private_room', 'ac'], legacyMeta);
  out.rowHas = {
    custom: s.rowHasMeterValues({ meters: { m1: 5 } }),
    zero: s.rowHasMeterValues({ meters: { m1: 0 } }),
    onlyDate: s.rowHasMeterValues({ date: '2026-09-01' }),
    legacy: sLegacy.rowHasMeterValues({ hall: 3 }),
    legacyTop: sLegacy.rowHasMeterValues({ hall: 3, fire: null, private_room: null, ac: null }),
    nullVal: s.rowHasMeterValues({ meters: { m1: null, m2: null } }),
    // 2 表门店里"只有 hall"的行 → 不该算有读数(那块表这个店根本没有)
    hallInTwoMeterStore: s.rowHasMeterValues({ hall: 3 }),
  };
}

console.log(JSON.stringify(out));
"""


class TestRenderBehaviour(unittest.TestCase):
    """node 沙箱行为验证(需要 node,缺失则跳过)。"""

    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "render_harness.js"
        hp.write_text(_NODE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_two_meter_report_columns(self) -> None:
        """2 表门店:每日行 = 日期 + 2 表 + 合计 = 4 个 td,不多不少。"""
        two = self.out["twoMeter"]
        self.assertEqual(two["firstRowCells"], 4,
                         "2 表门店的日报行有 %d 个 td(应为 4:日期+2表+合计)" % two["firstRowCells"])
        self.assertFalse(two["hasHall"], "报表里还出现 hall —— 仍按 4 表渲染")
        self.assertEqual(two["totalRowCells"], 4, "合计行的列数没跟着表集合走")

    def test_two_meter_head(self) -> None:
        two = self.out["twoMeter"]
        self.assertEqual(two["headCols"], 4)
        self.assertIn("1#吧台", two["headHtml"])
        self.assertIn("2#后厨", two["headHtml"])
        self.assertNotIn("大厅", two["headHtml"])

    def test_default_four_meter_report_unchanged(self) -> None:
        """默认 4 表:列数必须与改造前一致(日期 + 4 + 合计 = 6)。"""
        four = self.out["fourMeter"]
        self.assertEqual(four["headCols"], 6)
        self.assertEqual(four["firstRowCells"], 6)

    def test_row_has_meter_values(self) -> None:
        r = self.out["rowHas"]
        self.assertTrue(r["custom"], "自定义表有值却没被认出来")
        self.assertTrue(r["zero"], "0 也是抄表值(表底真到 0 了),不该被当成没录")
        self.assertFalse(r["onlyDate"], "只有日期没有表值的行应被跳过")
        self.assertTrue(r["legacy"], "旧 4 表的顶层字段也要能认出来")
        self.assertTrue(r["legacyTop"], "旧 4 表只要有一块有值就算有读数")
        self.assertFalse(r["hallInTwoMeterStore"],
                         "2 表门店里只有 hall 的行不算有读数(该店没有那块表)")
        self.assertFalse(r["nullVal"], "全 null 的行应被跳过")


if __name__ == "__main__":
    unittest.main()
