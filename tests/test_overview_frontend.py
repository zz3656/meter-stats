"""门店总览页(前端)测试(标准库 unittest,零依赖)。

P3 Task 2 —— 总部在一个页面上横向对比各店当月用电与费用。

关键设计:这张表**不能**按 `METER_KEYS` 出列 —— 每家店的表集合不一样
(`m1`/`m2` vs `hall`/`fire`/…)。横向能比的是「总用电 / 电费 / 抄表天数 / 水电」
这类**跨店同构**指标。前端若照抄抄表表单那套会直接渲染出某一家店的表名。

覆盖:
- 静态:侧栏有门店总览入口(默认隐藏)、有页面骨架、引入 overview.js、
  api.js 有 overview 封装、navigation.js 打开页面时加载
- node 行为:2 店 + 1 错误店 → 3 行数据 + 1 行合计;错误行显示原因;
  合计 = 各行之和;表头是跨店指标而不是某家店的表名;
  空数据显示空态;入口可见性按 all_stores / 门店数

运行:
    python3 -m unittest tests.test_overview_frontend -v
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
API_JS = METERSTATS / "js" / "core" / "api.js"
NAV_JS = METERSTATS / "js" / "core" / "navigation.js"
OVERVIEW_JS = METERSTATS / "js" / "modules" / "overview.js"


class TestOverviewWiring(unittest.TestCase):
    """静态接线护栏。"""

    def setUp(self) -> None:
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_sidebar_entry_defaults_hidden(self) -> None:
        """单店用户看不到入口 —— 默认 display:none,由 StoreContext 决定显示。"""
        self.assertIn('id="nav-overview"', self.html)
        seg = self.html[self.html.index('id="nav-overview"'):]
        seg = seg[:seg.index(">")]
        self.assertIn("display:none", seg, "入口默认没隐藏 —— 单店用户会看到只有一行的总览")

    def test_has_page_section(self) -> None:
        self.assertIn('id="section-settings-overview"', self.html)
        self.assertIn('id="overview-body"', self.html)
        self.assertIn('id="overview-month"', self.html)

    def test_loads_overview_js(self) -> None:
        self.assertIn("js/modules/overview.js", self.html)

    def test_api_exposes_overview(self) -> None:
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("/api/stores/overview", src)

    def test_navigation_loads_on_open(self) -> None:
        src = NAV_JS.read_text(encoding="utf-8")
        self.assertIn("page === 'overview'", src)
        self.assertIn("loadStoresOverview", src)

    def test_table_columns_are_cross_store_metrics(self) -> None:
        """表头必须是跨店同构指标,不能是某一家店的表名。"""
        self.assertIn("<th>门店</th>", self.html)
        self.assertIn("<th>用电(度)</th>", self.html)
        self.assertIn("<th>电费(元)</th>", self.html)
        for legacy in ("1#大厅", "2#消防", "private_room"):
            self.assertNotIn(legacy, self.html[self.html.index('id="section-settings-overview"'):
                                               self.html.index('id="section-settings-stores"')],
                             "总览表里出现了具体表名 %s —— 各家店的表不一样" % legacy)


_NODE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox() {
  const els = {};
  function mk(id) { return { id: id, innerHTML: '', textContent: '', style: {} }; }
  ['overview-body', 'overview-table-wrap', 'overview-empty',
   'overview-chart-wrap', 'overview-chart', 'overview-month', 'nav-overview']
    .forEach(id => { els[id] = mk(id); });
  els['overview-chart'].getContext = () => ({});

  const sandbox = {
    console, JSON, Object, Array, String, Number, Math, Date, isNaN, parseInt, parseFloat,
    document: { getElementById: id => (els[id] || null), querySelectorAll: () => [] },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  sandbox.escapeHtml = s => String(s == null ? '' : s)
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  sandbox.showAlert = () => {};
  // 不提供 Chart:让 _drawChart 走「没有图表库就隐藏图表区」分支,断言更稳
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/modules/overview.js'), 'utf8'),
                  sandbox, { filename: 'overview.js' });
  return sandbox;
}

function countAll(html, needle) {
  let n = 0, i = 0;
  while ((i = html.indexOf(needle, i)) >= 0) { n++; i += needle.length; }
  return n;
}

const out = {};
const s = makeSandbox();

// ① 两家成功 + 一家失败
{
  s.renderStoresOverview({
    month: '2026-11',
    stores: [
      { id: 'main', name: '总店', total_kwh: 14242.2, total_cost: 12817.98,
        reading_days: 18, by_meter: { hall: 8100.1 }, utilities: { main_kwh: 3200.0, water_usage: 18.5 } },
      { id: 's002', name: '国贸店', total_kwh: 500.0, total_cost: 750.0,
        reading_days: 12, by_meter: { m1: 200 }, utilities: { main_kwh: 100.0, water_usage: 3.2 } },
      { id: 's003', name: '坏店', error: '模拟读取失败' },
    ],
    total: { total_kwh: 14742.2, total_cost: 13567.98 },
  });
  const body = s.document.getElementById('overview-body').innerHTML;
  out.render = {
    html: body,
    rows: countAll(body, '<tr'),
    hasError: body.indexOf('模拟读取失败') >= 0,
    hasTotalRow: body.indexOf('yearly-total-row') >= 0,
    showsMeterDetail: body.indexOf('hall') >= 0 || body.indexOf('m1') >= 0,
    emptyHidden: s.document.getElementById('overview-empty').style.display,
    tableShown: s.document.getElementById('overview-table-wrap').style.display,
  };
}

// ② 空数据 → 空态,表格隐藏
{
  s.renderStoresOverview({ month: '2026-11', stores: [], total: { total_kwh: 0, total_cost: 0 } });
  out.empty = {
    body: s.document.getElementById('overview-body').innerHTML,
    emptyShown: s.document.getElementById('overview-empty').style.display,
    emptyText: s.document.getElementById('overview-empty').textContent,
    tableHidden: s.document.getElementById('overview-table-wrap').style.display,
  };
}

// ③ 入口可见性
{
  const s2 = makeSandbox();
  const setCtx = (allStores, n) => {
    s2.StoreContext = {
      getAllStores: () => allStores,
      getStores: () => new Array(n).fill({ id: 'x' }),
      onChange: () => {},
    };
    s2.applyOverviewVisibility();
    return s2.document.getElementById('nav-overview').style.display;
  };
  out.visibility = {
    singleStoreEmployee: setCtx(false, 1),
    twoStores: setCtx(false, 2),
    adminOneStore: setCtx(true, 1),
  };
}

console.log(JSON.stringify(out));
"""


class TestOverviewBehaviour(unittest.TestCase):
    """node 沙箱行为验证(需要 node,缺失则跳过)。"""

    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "overview_harness.js"
        hp.write_text(_NODE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_renders_one_row_per_store_plus_total(self) -> None:
        r = self.out["render"]
        self.assertEqual(r["rows"], 4, "2 家店 + 1 家失败店 + 合计行 = 4 行")
        self.assertTrue(r["hasTotalRow"], "缺少合计行")
        self.assertEqual(r["tableShown"], "", "有数据时表格应显示")
        self.assertEqual(r["emptyHidden"], "none")

    def test_error_store_shows_reason_but_others_render(self) -> None:
        r = self.out["render"]
        self.assertTrue(r["hasError"], "失败的门店没有显示原因")
        self.assertIn("总店", r["html"], "失败店把其它行带崩了")
        self.assertIn("国贸店", r["html"])

    def test_total_numbers_present(self) -> None:
        # 14,742.2 度 / 13,567.98 元(千分位由 toLocaleString 生成)
        html = self.out["render"]["html"]
        self.assertIn("14,742.2", html)
        self.assertIn("13,567.98", html)

    def test_no_per_meter_detail_in_overview(self) -> None:
        """总览不展示某一家店的分表明细 —— 各家店的表 key 不通用。"""
        self.assertFalse(self.out["render"]["showsMeterDetail"],
                         "总览表里出现了某家店的表 key —— 跨店比较不该按表出列")

    def test_empty_data_shows_empty_state(self) -> None:
        e = self.out["empty"]
        self.assertEqual(e["body"], "")
        self.assertEqual(e["emptyShown"], "block")
        self.assertIn("没有可汇总的门店", e["emptyText"])
        self.assertEqual(e["tableHidden"], "none")

    def test_entry_visibility(self) -> None:
        v = self.out["visibility"]
        self.assertEqual(v["singleStoreEmployee"], "none",
                         "单店员工不该看到门店总览入口")
        self.assertEqual(v["twoStores"], "")
        self.assertEqual(v["adminOneStore"], "",
                         "总部账号即使只有 1 家店也要能进总览")


if __name__ == "__main__":
    unittest.main()
