"""前端实时刷新回归测试(标准库 unittest,零依赖)。

本文件覆盖用户报告的两个前端问题:

问题 A ——「每日趋势」页的「每日用电」卡片显示「录入抄表数据后查看每日用电」,
          上方四张概况卡全空,录入今日抄表后也不刷新。

  根因:renderTrendChart() 的空态分支用
        `ctx.canvas.parentElement.innerHTML = '<div class="empty">…</div>'`
        渲染空态 —— 那会把整个 <canvas id="chart-trend"> 从 DOM 里永久删掉。
        之后每次调用都在下一行 `document.getElementById('chart-trend').getContext()`
        处抛 TypeError(null.getContext),而调用方(readings.js renderAll /
        navigation.js _afterSectionShown)都用 try/catch 静默吞掉异常。
        触发条件:页面加载时 snapshot 还没鉴权通过(401),renderAll() 带着
        空数组调用 renderTrendChart → canvas 当场被删,登录后再也回不来。

问题 B —— 抄表列表的月份下拉显示 2026-11,表格却渲染出所有月份的记录。

  根因:renderAll() 的顺序是「先渲染表格(第 2 步)→ 后刷新月份选择器(第 6 步)」。
        三张表的过滤读的是 #record-month 的当前值,而那时下拉还是空的
        (value === '')→ 不过滤 → 渲染全部月份;下拉随后被填成 2026-11,
        表格却没有跟着重绘。

本文件覆盖:
- 静态接线:renderTrendChart 不得再用 innerHTML 覆盖 canvas 容器
- 静态接线:refreshMonthSelectors 填完 #record-month 后必须重绘三张表
- 静态接线:renderAll 不得把整个 readings 数组传给饼图函数
- 行为验证(需要 node):空数据渲染后 canvas 仍在,后续有数据能正常出图
- 行为验证(需要 node):月份下拉填好后,表格必须只剩该月份的记录
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
INDEX_HTML = METERSTATS / "index.html"
CHARTS_JS = METERSTATS / "js" / "modules" / "render_charts.js"
REPORTS_JS = METERSTATS / "js" / "modules" / "reports.js"
READINGS_JS = METERSTATS / "js" / "modules" / "readings.js"


def _function_body(src: str, signature: str) -> str:
    """截出某个函数的函数体(顶层 `}` 结束)。"""
    m = re.search(signature + r"\s*\{[\s\S]*?\n\}", src)
    assert m, "读不到函数: %s" % signature
    return m.group(0)


def _strip_js_comments(src: str) -> str:
    """去掉 // 与 /* */ 注释 —— 注释里提到旧写法不算违规。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"//[^\n]*", "", src)
    return src


class TestStaticWiring(unittest.TestCase):
    """静态接线检查 —— 这几处一旦回退,用户马上能看出来。"""

    def test_trend_chart_never_overwrites_canvas_container(self):
        """renderTrendChart 不得再用 innerHTML 覆盖 canvas 的父容器。"""
        src = CHARTS_JS.read_text(encoding="utf-8")
        body = _strip_js_comments(_function_body(src, r"function renderTrendChart\(readings, charges\)"))
        self.assertNotIn(
            "parentElement.innerHTML",
            body,
            "renderTrendChart 不得用 parentElement.innerHTML 渲染空态 —— "
            "那会把 <canvas id=\"chart-trend\"> 永久删掉,之后每次调用都抛 TypeError "
            "并被 try/catch 静默吞掉,表现为「每日趋势」永远显示空态、概况卡全空",
        )

    def test_trend_chart_dom_has_canvas_and_empty_state(self):
        """index.html 里 canvas 与空态节点必须并存(只切换显隐)。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="trend-chart-wrap"', html, "缺少 #trend-chart-wrap 容器")
        self.assertIn('<canvas id="chart-trend">', html, "缺少趋势图 canvas")
        self.assertIn('id="trend-empty"', html, "缺少趋势图空态节点 #trend-empty")

    def test_month_selector_refresh_rerenders_record_tables(self):
        """refreshMonthSelectors 填完 #record-month 后必须重绘三张表。"""
        src = REPORTS_JS.read_text(encoding="utf-8")
        body = _function_body(src, r"function refreshMonthSelectors\(\)")
        for fn in ("renderReadingTable", "renderChargeTable", "renderWaterTable"):
            self.assertIn(
                fn,
                body,
                "refreshMonthSelectors 必须调用 %s —— "
                "否则下拉显示的月份与表格实际渲染的月份对不上" % fn,
            )
        # 顺序:先填下拉,再重绘
        fill_at = body.find("fillSelect('record-month'")
        redraw_at = body.find("renderReadingTable")
        self.assertNotEqual(fill_at, -1, "找不到 fillSelect('record-month', …)")
        self.assertNotEqual(redraw_at, -1, "找不到 renderReadingTable 调用")
        self.assertLess(
            fill_at, redraw_at,
            "必须先填 #record-month 再重绘表格,否则重绘时读到的还是空值(不过滤)",
        )

    def test_render_all_passes_selected_value_to_pie_charts(self):
        """renderAll 不得把整个 readings 数组传给饼图函数。"""
        src = READINGS_JS.read_text(encoding="utf-8")
        body = _function_body(src, r"async function renderAll\(\)")
        for fn in ("renderMonthlyPie", "renderDailyPie"):
            bad = "%s(State.get(" % fn
            self.assertNotIn(
                bad,
                body,
                "%s 必须传「选中的月份 / 日期」,不能传整个 readings 数组 —— "
                "数组会被 toString 成逗号串,过滤不到任何数据,反而把饼图藏起来" % fn,
            )

    def test_refresh_and_render_tables_rerenders_monthly_stats(self):
        """录入抄表后「每月用电」页的统计卡也要重绘(与余量预警卡同源)。"""
        src = READINGS_JS.read_text(encoding="utf-8")
        body = _function_body(src, r"function refreshAndRenderTables\(\)")
        self.assertIn(
            "renderStats",
            body,
            "refreshAndRenderTables 必须调用 renderStats —— "
            "否则录入抄表后「每月用电」页停留在旧数字",
        )


# ============ 行为验证(需要 node) ============

_MINI_DOM = r"""
// 极简 DOM,够跑 renderReadingTable / refreshMonthSelectors / renderTrendChart
// ⚠ innerHTML 赋值必须真的把子节点从文档里摘掉 —— 旧版 renderTrendChart 就是
//   用 innerHTML 覆盖父容器来删 canvas 的,harness 必须能重现这一点。
function makeRegistry() {
  const reg = {};
  function mk(id, tag) {
    return {
      id: id || null, tagName: tag || 'div', style: {}, _html: '', textContent: '',
      value: '', className: '', children: [], dataset: {}, parentElement: null,
      get innerHTML() { return this._html; },
      set innerHTML(v) {
        (this.children || []).forEach((c) => { if (c.id && reg[c.id] === c) delete reg[c.id]; });
        this.children = [];
        this._html = v;
      },
      getContext() { return { canvas: this }; },
      appendChild(c) {
        this.children.push(c);
        c.parentElement = this;
        if (c.id) reg[c.id] = c;
        return c;
      },
      setAttribute() {}, addEventListener() {}, removeEventListener() {},
      querySelectorAll() { return []; }, querySelector() { return null; },
      closest() { return null; }, focus() {},
    };
  }
  function table(id) {
    const t = mk(id, 'table');
    t.tbody = mk(id + '-tbody', 'tbody');
    reg[id] = t;
    return t;
  }
  const histTable = table('history-table');
  const chargeTable = table('charge-table');
  const waterTable = table('water-history-table');
  const sel = (id) => { reg[id] = mk(id, 'select'); return reg[id]; };
  const div = (id) => { reg[id] = mk(id, 'div'); return reg[id]; };
  sel('record-month'); sel('stats-month'); sel('report-month'); sel('yearly-year');
  div('history-empty'); div('charge-list-empty'); div('charge-summary');
  div('water-history-empty'); div('meter-reminder'); div('meter-reminder-text');
  return { reg, mk, table, sel, div, histTable, chargeTable, waterTable };
}
"""

_TREND_HARNESS = _MINI_DOM + r"""
// 用真实 render_charts.js 验证:空态渲染不会毁掉 canvas,后续有数据能出图
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
const D = makeRegistry();
const wrap = D.mk('trend-chart-wrap');
const canvas = D.mk('chart-trend', 'canvas');
const emptyEl = D.mk('trend-empty', 'div');
emptyEl.style.display = 'none';
wrap.appendChild(canvas); wrap.appendChild(emptyEl);
const statGrid = D.mk('trend-stat-grid');
D.reg['trend-chart-wrap'] = wrap;
D.reg['chart-trend'] = canvas;
D.reg['trend-empty'] = emptyEl;
D.reg['trend-stat-grid'] = statGrid;

const charts = [];
function FakeChart(ctx, cfg) { charts.push(cfg); this.destroy = () => {}; }

const sandbox = {
  document: {
    getElementById: (id) => D.reg[id] || null,
    querySelector: () => null, querySelectorAll: () => [],
    createElement: (t) => D.mk(null, t),
  },
  console, setTimeout, clearTimeout, Math, JSON, Date, Number, String, Array, Object, Map, Set,
  Chart: FakeChart, navigator: {},
  CHARGE_METERS: [
    { key: 'hall', label: '1#大厅', icon: '⚡' },
    { key: 'fire', label: '2#消防', icon: '🔥' },
    { key: 'private_room', label: '3#包厢', icon: '📦' },
    { key: 'ac', label: '4#空调', icon: '❄' },
  ],
  ELECTRICITY_PRICE: 1,
  realKwh: (v) => v,
  sumChargesBetween: () => 0,
  formatDate: (d) => d.toISOString().slice(0, 10),
  COLORS: () => '#123456',
  LABELS: (k) => k,
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/modules/render_charts.js'), 'utf8'),
                sandbox, { filename: 'render_charts.js' });

const rows = [
  { date: '2026-10-01', hall: 30, fire: 640, private_room: 60, ac: 150 },
  { date: '2026-11-01', hall: 31, fire: 646, private_room: 61, ac: 149 },
  { date: '2026-11-03', hall: 233.6, fire: 2055.5, private_room: 223.8, ac: 146 },
];

function callRender(list) {
  // 调用方(readings.js / navigation.js)都用 try/catch 吞异常,
  // 这里把异常记下来,断言才能看清「静默失败」到底在哪一步炸的。
  try { sandbox.renderTrendChart(list, []); return null; }
  catch (e) { return String((e && e.message) || e); }
}

// 1) 未登录 / 无数据:renderAll 带着空数组调用
const errEmpty = callRender([]);
const afterEmpty = {
  canvasExists: !!sandbox.document.getElementById('chart-trend'),
  canvasDisplay: canvas.style.display,
  emptyDisplay: emptyEl.style.display,
  statHtmlLen: statGrid.innerHTML.length,
  chartCount: charts.length,
  error: errEmpty,
};

// 2) 登录后 / 有数据:必须能正常出图并填上概况卡
const errData = callRender(rows);
const afterData = {
  canvasExists: !!sandbox.document.getElementById('chart-trend'),
  canvasDisplay: canvas.style.display,
  emptyDisplay: emptyEl.style.display,
  statHtmlLen: statGrid.innerHTML.length,
  chartCount: charts.length,
  error: errData,
};

// 3) canvas 被外部删掉后必须能自愈
delete D.reg['chart-trend'];
const errHeal = callRender(rows);
const afterHeal = {
  canvasExists: !!sandbox.document.getElementById('chart-trend'),
  chartCount: charts.length,
  error: errHeal,
};

console.log(JSON.stringify({ afterEmpty, afterData, afterHeal }));
"""

_MONTH_HARNESS = _MINI_DOM + r"""
// 用真实 readings.js + reports.js 复现 renderAll() 的真实顺序:
//   ① renderReadingTable(此时 #record-month 还是空的)
//   ② refreshMonthSelectors(填下拉)
// 断言 ② 之后表格只剩选中月份的记录。
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
const D = makeRegistry();

const state = { readings: [], charges: [], water: [] };
const sandbox = {
  document: {
    getElementById: (id) => D.reg[id] || null,
    querySelector: (sel) => {
      if (sel === '#history-table tbody') return D.histTable.tbody;
      if (sel === '#charge-table tbody') return D.chargeTable.tbody;
      if (sel === '#water-history-table tbody') return D.waterTable.tbody;
      return null;
    },
    querySelectorAll: () => [],
    createElement: (t) => D.mk(null, t),
  },
  console, setTimeout, clearTimeout, Math, JSON, Date, Number, String, Array, Object, Map, Set,
  navigator: {},
  State: { get: (k) => state[k], set: (k, v) => { state[k] = v; } },
  CHARGE_METERS: [
    { key: 'hall', label: '1#大厅', icon: '⚡' },
    { key: 'fire', label: '2#消防', icon: '🔥' },
    { key: 'private_room', label: '3#包厢', icon: '📦' },
    { key: 'ac', label: '4#空调', icon: '❄' },
  ],
  ELECTRICITY_PRICE: 1,
  realKwh: (v) => v,
  escapeHtml: (s) => String(s),
  chargeEffectiveDate: (c) => (c.confirmed_at ? c.confirmed_at.slice(0, 10) : c.date),
  daysBetween: () => 1,
  todayStr: () => '2026-11-03',
  formatDate: (d) => d.toISOString().slice(0, 10),
  showAlert: () => {}, showModal: () => Promise.resolve(false),
  Api: {}, navigator: {},
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const f of ['js/modules/readings.js', 'js/modules/reports.js']) {
  vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), sandbox, { filename: f });
}
// reports.js 会调用 loadYearlyReport —— 用空实现替换,避免拉后端
sandbox.loadYearlyReport = () => {};

const readings = [
  { date: '2026-10-01', hall: 30, fire: 640, private_room: 60, ac: 150 },
  { date: '2026-11-01', hall: 31, fire: 646, private_room: 61, ac: 149 },
  { date: '2026-11-03', hall: 233.6, fire: 2055.5, private_room: 223.8, ac: 146 },
];
state.readings = readings;
state.charges = [];
state.water = [];

// ① renderAll() 第 2 步:先渲染表格(此刻 #record-month 还没有 option)
sandbox.renderReadingTable(state.readings);
const rowDates = () => (D.histTable.tbody.innerHTML.match(/<tr data-date="([^"]+)"/g) || [])
  .map((s) => s.replace(/^<tr data-date="|"$/g, ''));
const datesAfterFirstRender = rowDates();

// ② renderAll() 第 6 步:刷新月份选择器
sandbox.refreshMonthSelectors();
const selectedMonth = D.reg['record-month'].value;
const datesAfterSelectorRefresh = rowDates();

console.log(JSON.stringify({
  datesAfterFirstRender,
  datesAfterSelectorRefresh,
  selectedMonth,
}));
"""


class TestNodeBehavior(unittest.TestCase):
    """用真实前端文件跑一遍行为(需要 node,缺失则跳过)。"""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, harness: str) -> dict:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(harness, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_empty_render_keeps_canvas_and_later_data_renders_chart(self):
        """空数据不得删掉 canvas;后续有数据必须能出图并填概况卡。"""
        out = self._run(_TREND_HARNESS)

        empty = out["afterEmpty"]
        self.assertIsNone(
            empty["error"],
            "空数据渲染不应抛异常,实际: %s" % empty["error"],
        )
        self.assertTrue(
            empty["canvasExists"],
            "空数据渲染后 <canvas id=\"chart-trend\"> 必须仍然存在 —— "
            "被删掉之后每次调用都会抛 TypeError 并被 try/catch 吞掉",
        )
        self.assertEqual(empty["canvasDisplay"], "none", "空数据时应隐藏 canvas")
        self.assertEqual(empty["emptyDisplay"], "block", "空数据时应显示空态文案")
        self.assertEqual(empty["statHtmlLen"], 0, "空数据时概况卡必须清空,不能留上一轮的数字")
        self.assertEqual(empty["chartCount"], 0, "空数据时不应创建图表")

        data = out["afterData"]
        self.assertIsNone(
            data["error"],
            "有数据时不得抛异常,实际: %s —— "
            "这正是旧版 bug 的形态:canvas 被删后每次调用都在 getContext 处炸掉,"
            "再被调用方的 try/catch 静默吞掉" % data["error"],
        )
        self.assertTrue(data["canvasExists"], "有数据时 canvas 必须还在")
        self.assertEqual(data["canvasDisplay"], "block", "有数据时必须显示 canvas")
        self.assertEqual(data["emptyDisplay"], "none", "有数据时必须隐藏空态文案")
        self.assertGreater(
            data["statHtmlLen"], 0,
            "有数据时概况卡(近 N 天用电 / 日均 / 最高 / 最低)必须被填上",
        )
        self.assertEqual(data["chartCount"], 1, "有数据时必须真正创建图表")

        self.assertTrue(out["afterHeal"]["canvasExists"], "canvas 丢失后应能自愈重建")
        self.assertIsNone(out["afterHeal"]["error"], "自愈过程不应抛异常")

    def test_record_table_matches_selected_month_after_first_load(self):
        """月份下拉填好后,抄表表格必须只剩该月份的记录。"""
        out = self._run(_MONTH_HARNESS)

        self.assertEqual(
            out["selectedMonth"], "2026-11",
            "月份下拉应默认选最新月份",
        )
        months = sorted(set(d[:7] for d in out["datesAfterSelectorRefresh"]))
        self.assertEqual(
            months, ["2026-11"],
            "刷新月份选择器后,表格里只剩 %s 的记录 —— 实际是 %s。"
            "下拉显示的月份与表格实际内容必须一致" % (out["selectedMonth"], months),
        )
        self.assertEqual(
            len(out["datesAfterSelectorRefresh"]), 2,
            "2026-11 应只有 11-01 与 11-03 两条记录,实际 %d 条"
            % len(out["datesAfterSelectorRefresh"]),
        )
        # 回归点:修复前第 ① 步渲染的是「全部月份」,第 ② 步之后依然是全部月份
        first_months = sorted(set(d[:7] for d in out["datesAfterFirstRender"]))
        self.assertEqual(
            first_months, ["2026-10", "2026-11"],
            "第 ① 步(下拉还没填)确实渲染了所有月份 —— "
            "这正是 bug 的触发前提,若这里变了说明前提失效,测试失去意义",
        )


if __name__ == "__main__":
    unittest.main()
