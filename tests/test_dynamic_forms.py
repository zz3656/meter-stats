"""表输入表单动态化测试(标准库 unittest,零依赖)。

P2 Task 4 —— 抄表/充值的 6 组表单(`录入 / 新增 / 编辑` × `抄表 / 充值`)
与两个记录表的表头,全部按**当前门店**的表集合渲染。

改造前的盘面:`index.html` 里 6 组 × 4 表 = **24 个写死的 `<input>`**,
`<label>` 里的倍率提示(「读数 × 160」)也写死了 **25 处**。
门店改成 2 块表、或把某块表倍率改成 80,页面就跟着错 ——
而倍率提示不是装饰文案,用户会**照着它手算**。

两部分:
1. 静态护栏(不依赖 node):index.html 不许再有写死的表输入/倍率提示,
   必须有 6 个容器与两个动态表头。
2. node 行为验证:渲染 2 表门店 → 6 组各 2 个输入、id 前缀不变、提示按倍率生成;
   收集时旧 4 表走顶层、自定义表走 meters 字典;表头列数跟着表集合变。

运行:
    python3 -m unittest tests.test_dynamic_forms -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
INDEX_HTML = METERSTATS / "index.html"
METER_FORM_JS = METERSTATS / "js" / "core" / "meterForm.js"

# 改造前那些写死的 input id —— 一个都不许留(否则就是「表单还是 4 表」)
LEGACY_INPUT_IDS = [
    'hall', 'fire', 'private_room', 'ac',
    'charge-hall', 'charge-fire', 'charge-private_room', 'charge-ac',
    'reading-add-hall', 'reading-add-fire', 'reading-add-private_room', 'reading-add-ac',
    'charge-add-hall', 'charge-add-fire', 'charge-add-private_room', 'charge-add-ac',
    'reading-edit-hall', 'reading-edit-fire', 'reading-edit-private_room', 'reading-edit-ac',
    'charge-edit-hall', 'charge-edit-fire', 'charge-edit-private_room', 'charge-edit-ac',
]

CONTAINERS = [
    'mf-reading-entry', 'mf-charge-entry',
    'mf-reading-add', 'mf-charge-add',
    'mf-reading-edit', 'mf-charge-edit',
]


class TestIndexHtmlGuards(unittest.TestCase):
    """静态护栏 —— index.html 的形态。"""

    def setUp(self) -> None:
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_loads_meter_form_js(self) -> None:
        self.assertIn("js/core/meterForm.js", self.html)

    def test_has_six_containers(self) -> None:
        for cid in CONTAINERS:
            self.assertIn('id="%s"' % cid, self.html,
                          "缺少表输入容器 %s" % cid)

    def test_has_dynamic_table_headers(self) -> None:
        self.assertIn('id="reading-thead-row"', self.html)
        self.assertIn('id="charge-thead-row"', self.html)

    def test_no_hardcoded_meter_inputs_left(self) -> None:
        """24 个写死的表输入必须全部消失(换成容器)。"""
        left = [i for i in LEGACY_INPUT_IDS if ('id="%s"' % i) in self.html]
        self.assertEqual(left, [], "index.html 里还有写死的表输入: %s" % left)

    def test_no_hardcoded_multiplier_hints_left(self) -> None:
        """电表的倍率提示必须全部消失 —— 它们要由 MeterForm 按 multiplier 生成。

        只盯**电表**那几个值:`读数 × 160` / `表读数 ×160` / `读数即实际电量`。
        水电表(总表 ×50 / 分表 ×40)是另一套,倍率来自门店配置的
        `main_mult` / `sub_mult`,不由表集合驱动(P2 计划 D9),不在此列。
        """
        patterns = [
            "读数 × 160", "读数 ×160", "表读数 × 160", "表读数 ×160",
            "读数即实际电量",
        ]
        leftovers = []
        for no, line in enumerate(self.html.split("\n"), 1):
            for pat in patterns:
                if pat in line:
                    leftovers.append("%d: %s" % (no, line.strip()[:90]))
                    break
        self.assertEqual(
            leftovers, [],
            "index.html 里还有写死的电表倍率提示(应改由 MeterForm 按 multiplier 生成):\n  "
            + "\n  ".join(leftovers),
        )


_NODE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox(keys, meta) {
  const els = {};
  function mk(id) { return { id: id, innerHTML: '', value: '' }; }
  ['mf-reading-entry', 'mf-charge-entry', 'mf-reading-add', 'mf-charge-add',
   'mf-reading-edit', 'mf-charge-edit',
   'reading-thead-row', 'charge-thead-row'].forEach(id => { els[id] = mk(id); });

  const sandbox = {
    console, JSON, Object, Array, String, Number, Math, undefined,
    document: { getElementById: id => (id in els ? els[id] : null) },
    window: null,
    els: els,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  // renderAll 只往容器里塞 innerHTML 字符串,假 DOM 不解析它 ——
  // 需要按 id 取值的用例自己 ensure() 一下
  sandbox.ensure = function (ids) {
    ids.forEach(function (id) { if (!(id in els)) els[id] = mk(id); });
    return els;
  };
  vm.createContext(sandbox);

  sandbox.METER_KEYS = keys;
  sandbox.METER_META = k => meta[k] || { label: k, multiplier: 1 };
  sandbox.meterValue = function (row, key) {
    if (!row || typeof row !== 'object') return undefined;
    var m = row.meters;
    if (m && typeof m === 'object' && Object.prototype.hasOwnProperty.call(m, key)) return m[key];
    return row[key];
  };
  sandbox.escapeHtml = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  };

  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/meterForm.js'), 'utf8'),
                  sandbox, { filename: 'meterForm.js' });
  return sandbox;
}

const TWO = {
  m1: { label: '吧台', multiplier: 80 },
  m2: { label: '后厨', multiplier: 1 },
};

const out = {};

// ① 2 表门店:6 组各渲染 2 个输入,id 前缀不变
{
  const s = makeSandbox(['m1', 'm2'], TWO);
  s.MeterForm.renderAll();
  out.render = {};
  s.MeterForm.GROUPS.forEach(g => {
    const html = s.els[g.id].innerHTML;
    out.render[g.id] = {
      prefix: g.prefix,
      hasM1: html.indexOf('id="' + g.prefix + 'm1"') >= 0,
      hasM2: html.indexOf('id="' + g.prefix + 'm2"') >= 0,
      hasHall: html.indexOf('hall') >= 0,
      inputs: (html.match(/<input /g) || []).length,
      html: html,
    };
  });
}

// ② 倍率提示必须跟着倍率走(m1=80 → × 80;m2=1 → 即实际电量 / 表读数)
{
  const s = makeSandbox(['m1', 'm2'], TWO);
  s.MeterForm.renderAll();
  out.hints = {
    readingEntry: s.els['mf-reading-entry'].innerHTML,
    chargeEntry: s.els['mf-charge-entry'].innerHTML,
  };
}

// ③ 收集:旧 4 表走顶层,自定义表走 meters 字典
{
  const s = makeSandbox(['hall', 'm1'], { hall: { label: '大厅', multiplier: 160 }, m1: { label: '吧台', multiplier: 2 } });
  s.MeterForm.renderAll();
  s.ensure(['reading-add-hall', 'reading-add-m1']);
  s.els['reading-add-hall'].value = '12.5';
  s.els['reading-add-m1'].value = '7';
  const c = s.MeterForm.collect('reading-add-');
  out.collect = { all: c.all, legacy: c.legacy, meters: c.meters, hasNaN: c.hasNaN };
  out.payload = s.MeterForm.toPayload(c, { keepNullLegacy: true });
}

// ④ 空输入 = null(SQL 意义上的"没填"),且不混进 meters
{
  const s = makeSandbox(['hall', 'm1'], { hall: { label: '大厅', multiplier: 160 }, m1: { label: '吧台', multiplier: 2 } });
  s.MeterForm.renderAll();
  s.ensure(['reading-add-hall', 'reading-add-m1']);
  s.els['reading-add-hall'].value = '';
  s.els['reading-add-m1'].value = '';
  const c = s.MeterForm.collect('reading-add-');
  out.empty = { all: c.all, legacy: c.legacy, meters: c.meters, hasNaN: c.hasNaN };
}

// ⑤ 非数字要被识别出来(交给调用方报错,而不是静默变成 0)
{
  const s = makeSandbox(['hall'], { hall: { label: '大厅', multiplier: 160 } });
  s.MeterForm.renderAll();
  s.ensure(['reading-add-hall']);
  s.els['reading-add-hall'].value = 'abc';
  out.badNumber = { hasNaN: s.MeterForm.collect('reading-add-').hasNaN };
}

// ⑥ 表头列数跟着表集合走
{
  const s = makeSandbox(['m1', 'm2'], TWO);
  s.MeterForm.renderHead('reading-thead-row', ['日期'], ['备注', '']);
  s.MeterForm.renderHead('charge-thead-row', ['日期'], ['金额', '备注', '']);
  out.head = {
    reading: s.els['reading-thead-row'].innerHTML,
    charge: s.els['charge-thead-row'].innerHTML,
    readingCols: (s.els['reading-thead-row'].innerHTML.match(/<th>/g) || []).length,
    chargeCols: (s.els['charge-thead-row'].innerHTML.match(/<th>/g) || []).length,
  };
}

// ⑦ 回填:自定义表的值在 meters 字典里也能填进去
{
  const s = makeSandbox(['hall', 'm1'], { hall: { label: '大厅', multiplier: 160 }, m1: { label: '吧台', multiplier: 2 } });
  s.MeterForm.renderAll();
  s.ensure(['reading-edit-hall', 'reading-edit-m1']);
  s.MeterForm.fill({ date: '2026-09-01', hall: 3.5, meters: { m1: 9.25 } }, 'reading-edit-');
  out.fill = {
    hall: s.els['reading-edit-hall'].value,
    m1: s.els['reading-edit-m1'].value,
  };
}

console.log(JSON.stringify(out));
"""


class TestNoHardcodedMeterIdLookups(unittest.TestCase):
    """JS 里不许再按**写死的表 id** 取元素。

    改造时最容易漏的不是渲染,而是散落各处的 `getElementById('reading-add-hall')`
    这种取值/聚焦/清空 —— 门店没有 hall 时它们静默返回 null,表现为
    「点新增没反应」「清空没清掉」,很难查到。
    """

    FILES = [
        METERSTATS / "admin.js",
        METERSTATS / "js" / "modules" / "readings.js",
        METERSTATS / "js" / "modules" / "charges.js",
    ]

    def test_no_literal_meter_ids_in_getelementbyid(self) -> None:
        pat = re.compile(
            r"getElementById\(\s*['\"][a-z_-]*(?:hall|fire|private_room|ac)['\"]\s*\)"
        )
        offenders = []
        for f in self.FILES:
            for no, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
                if pat.search(line):
                    offenders.append("%s:%d: %s" % (f.name, no, line.strip()[:80]))
        self.assertEqual(
            offenders, [],
            "这些地方还在按写死的表 id 取元素(门店没有那块表时静默返回 null):\n  "
            + "\n  ".join(offenders),
        )


class TestMeterFormBehaviour(unittest.TestCase):
    """node 沙箱行为验证(需要 node,缺失则跳过)。"""

    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "meter_form_harness.js"
        hp.write_text(_NODE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_all_six_groups_render_current_store_meters(self) -> None:
        """6 组都要跟着变 —— 只改一组就是「新增对了、编辑还是老的」。"""
        for cid, info in self.out["render"].items():
            self.assertTrue(info["hasM1"], "%s 没渲染出 m1" % cid)
            self.assertTrue(info["hasM2"], "%s 没渲染出 m2" % cid)
            self.assertFalse(info["hasHall"],
                             "%s 还出现了不存在的 hall —— 仍在按 4 表渲染" % cid)
            self.assertEqual(info["inputs"], 2, "%s 的输入框数量不是 2" % cid)

    def test_input_ids_keep_the_prefix_contract(self) -> None:
        """id = 前缀 + 表 key —— 下游按 id 取值/回填都靠这条约定。"""
        for cid, info in self.out["render"].items():
            self.assertIn('id="%sm1"' % info["prefix"], info["html"],
                          "%s 的 id 前缀不是约定值" % cid)

    def test_multiplier_hints_follow_the_store(self) -> None:
        """倍率 80 的表必须写「× 80」,不许出现「× 160」。"""
        reading = self.out["hints"]["readingEntry"]
        self.assertIn("读数 × 80", reading, "倍率提示没跟着表走")
        self.assertNotIn("× 160", reading, "页面还写着写死的 × 160")
        self.assertIn("读数即实际电量", reading, "倍率 1 的表提示不对")

        charge = self.out["hints"]["chargeEntry"]
        self.assertIn("表读数 ×80", charge)
        self.assertIn("表读数", charge)

    def test_collect_splits_legacy_and_custom(self) -> None:
        c = self.out["collect"]
        self.assertEqual(c["legacy"], {"hall": 12.5})
        self.assertEqual(c["meters"], {"m1": 7.0})
        self.assertFalse(c["hasNaN"])
        payload = self.out["payload"]
        self.assertEqual(payload["hall"], 12.5)
        self.assertEqual(payload["meters"], {"m1": 7.0})

    def test_empty_inputs_are_null_not_zero(self) -> None:
        """空输入 = null(没填),不能被当成 0 —— 否则「没抄」会变成「抄到 0」。"""
        e = self.out["empty"]
        self.assertIsNone(e["all"]["hall"])
        self.assertIsNone(e["all"]["m1"])
        self.assertEqual(e["meters"], {}, "空的自定义表不该进 meters 字典")

    def test_bad_number_is_flagged(self) -> None:
        self.assertTrue(self.out["badNumber"]["hasNaN"])

    def test_table_header_columns_follow_meter_count(self) -> None:
        """2 表门店:抄表表头 = 日期 + 2 + 备注 + 操作 = 5 列。"""
        head = self.out["head"]
        self.assertEqual(head["readingCols"], 5)
        self.assertIn("1#吧台", head["reading"])
        self.assertIn("2#后厨", head["reading"])
        self.assertEqual(head["chargeCols"], 6)   # 日期 + 2 + 金额 + 备注 + 操作

    def test_fill_reads_custom_meter_from_dict(self) -> None:
        # 假 DOM 的 value 不做字符串coercion(真 DOM 会),这里按数值比
        f = self.out["fill"]
        self.assertEqual(float(f["hall"]), 3.5)
        self.assertEqual(float(f["m1"]), 9.25,
                         "自定义表的值在 meters 字典里,fill 没读到 —— 编辑弹窗会是空的")


if __name__ == "__main__":
    unittest.main()
