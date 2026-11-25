"""表元数据前端动态化测试(标准库 unittest,零依赖)。

P2 Task 3 —— `METER_CONFIG` / `METER_KEYS` / `CHARGE_METERS` 由**当前门店**的
表集合重建,而不是写死 4 表。

为什么必须动态:前端约 70 处引用这 3 个全局,任何一处还用写死的 4 表,
2 表门店就会显示/提交一块不存在的表 —— 而且**不会报错**,只是数字悄悄错掉。

本文件分两部分:
1. 静态护栏(不依赖 node):`meterConfig.js` 里读表值必须走 `meterValue()`,
   不许再出现 `row[key]` 形式的直读;必须导出 `resetMeterConfig`。
2. node 行为验证:喂 2 表的响应,断言 METER_KEYS / CHARGE_METERS / 倍率跟着变;
   自定义表(值在 meters 字典)的充值归属与冲突判定能正常工作。

运行:
    python3 -m unittest tests.test_meter_config_frontend -v
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
METER_CONFIG_JS = METERSTATS / "js" / "core" / "meterConfig.js"
STORE_CONTEXT_JS = METERSTATS / "js" / "core" / "storeContext.js"


class TestMeterConfigStaticGuards(unittest.TestCase):
    """静态护栏 —— 不需要 node。"""

    def setUp(self) -> None:
        self.src = METER_CONFIG_JS.read_text(encoding="utf-8")

    def test_exports_reset_meter_config(self) -> None:
        """切门店时要能回到默认 4 表,必须导出 resetMeterConfig。"""
        self.assertIn("resetMeterConfig", self.src)
        self.assertIn("window.resetMeterConfig", self.src)

    def test_exports_meter_value_reader(self) -> None:
        """读表值必须有一个统一入口(对应后端 row_values)。"""
        self.assertIn("window.meterValue", self.src)

    def test_no_direct_meter_key_reads_left(self) -> None:
        """`row[key]` 形式的直读必须全部换成 meterValue()。

        自定义表的值在 `meters` 字典里,`row[key]` 读到的是 undefined ——
        表现为「这块表没抄过表」,充值归属整段失效,而且不报错。
        `METER_CONFIG[key]` 是元数据查表,不在禁止范围内。
        """
        # meterValue() 自己是那个唯一入口,函数体里的 m[key] / row[key] 是正常的
        src = self.src
        head = src.index("window.meterValue = function")
        tail = src.index("};", src.index("return row[key]", head))
        scan = src[:head] + src[tail + 2:]

        # ⚠️ 必须先剥掉注释再扫:注释里会写「不要用 row[key]」之类的说明,
        # 源码扫描误命中注释是本项目踩过的坑(PanelCraft 的 codeOnly 教训)。
        scan = re.sub(r"/\*[\s\S]*?\*/", "", scan)
        scan = re.sub(r"//[^\n]*", "", scan)

        offenders = []
        for no, line in enumerate(scan.split("\n"), 1):
            if "[key]" not in line:
                continue
            if "METER_CONFIG" in line:
                continue
            offenders.append("%d: %s" % (no, line.strip()))
        self.assertEqual(
            offenders, [],
            "meterConfig.js 里还有直读 row[key] 的地方(自定义表会读到 undefined):\n  "
            + "\n  ".join(offenders),
        )

    def test_load_meter_config_rebuilds_all_three_globals(self) -> None:
        """三个全局必须一起重建 —— 只改 METER_CONFIG 会让 METER_KEYS 还是 4 表。"""
        body = self.src[self.src.index("async function loadMeterConfig"):
                        self.src.index("// ===== 充值计算辅助函数")]
        for name in ("METER_CONFIG", "METER_KEYS", "CHARGE_METERS"):
            self.assertIn(name, body, "loadMeterConfig 没有重建 %s" % name)


_NODE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox(payload) {
  const sandbox = {
    console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
    Promise, RegExp, Error, isNaN, parseInt, parseFloat, Math,
    localStorage: (function () {
      const m = {};
      return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: k => { delete m[k]; } };
    })(),
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  sandbox.Api = { admin: { metersPublic: async () => payload } };
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/meterConfig.js'), 'utf8'),
                  sandbox, { filename: 'meterConfig.js' });
  return sandbox;
}

const TWO_METERS = {
  meters: {
    m1: { key: 'm1', label: '吧台', icon: '🍸', multiplier: 80, color: '#111111' },
    m2: { key: 'm2', label: '后厨', icon: '🔥', multiplier: 3,  color: '#222222' },
  },
  meter: null, // 同一个值,这里不重要
  config: { electricity_price: 1.25, water_price: 6.0 },
};
TWO_METERS.meter = TWO_METERS.meters;

(async () => {
  const out = {};

  // ① 2 表门店 → 三个全局都跟着变
  const s = makeSandbox(TWO_METERS);
  const beforeKeys = s.METER_KEYS.slice();
  await s.loadMeterConfig();
  out.afterLoad = {
    keys: s.METER_KEYS.slice(),
    beforeKeys: beforeKeys,
    chargeMeters: s.CHARGE_METERS.map(m => ({ key: m.key, label: m.label, meterNo: m.meterNo })),
    m1mult: s.MULTIPLIER('m1'),
    m1label: s.LABELS('m1'),
    m1color: s.COLORS('m1'),
    price: s.ELECTRICITY_PRICE,
    water: s.WATER_PRICE,
  };

  // ② resetMeterConfig 回到默认 4 表
  s.resetMeterConfig();
  out.afterReset = {
    keys: s.METER_KEYS.slice(),
    chargeKeys: s.CHARGE_METERS.map(m => m.key),
    hallMult: s.MULTIPLIER('hall'),
  };

  // ③ meterValue:meters 字典 / 顶层字段 / 缺失
  const s2 = makeSandbox(TWO_METERS);
  out.meterValue = {
    fromDict: s2.meterValue({ meters: { m1: 7.5 } }, 'm1'),
    fromTop: s2.meterValue({ hall: 3 }, 'hall'),
    missing: s2.meterValue({ date: 'x' }, 'm1') === undefined ? 'undefined' : 'other',
    nullVal: s2.meterValue({ meters: { m1: null } }, 'm1') === null ? 'null' : 'other',
    undefinedarith: String(s2.meterValue({ date: 'x' }, 'm1') - 5),
  };

  // ④ 自定义表的充值归属(值在 meters 字典里)
  const s3 = makeSandbox(TWO_METERS);
  await s3.loadMeterConfig();
  s3.CURRENT_READINGS = [
    { date: '2026-09-01', meters: { m1: 100 } },
    { date: '2026-09-05', meters: { m1: 150 } },
    { date: '2026-09-11', meters: { m1: 140 } },
  ];
  const attr = s3.chargeAttribution([{ id: 'c1', date: '2026-09-05', meters: { m1: 50 } }], 'm1');
  out.attribution = { attr: attr };

  // ⑤ 自定义表的「把抄表读数填进充值栏」也要能认出来
  s3.CURRENT_READINGS = [
    { date: '2026-09-01', meters: { m1: 100 } },
    { date: '2026-09-11', meters: { m1: 90 } },
  ];
  const pasted = s3.findPastedReadingCharges([{ id: 'c2', date: '2026-09-11', meters: { m1: 90 } }]);
  out.pasted = { count: pasted.length, meter: pasted.length ? pasted[0].meter : null };

  // ⑥ 默认 4 表的行为不因动态化而改变(顶层字段照旧)
  const s4 = makeSandbox({ meters: {
    hall:   { key: 'hall', label: '大厅', icon: '🎤', multiplier: 160, color: '#2563eb' },
    fire:   { key: 'fire', label: '消防', icon: '🧯', multiplier: 1, color: '#dc2626' },
    private_room: { key: 'private_room', label: '包厢', icon: '🛋️', multiplier: 160, color: '#059669' },
    ac:     { key: 'ac', label: '空调', icon: '❄️', multiplier: 160, color: '#d97706' },
  }, config: {} });
  await s4.loadMeterConfig();
  out.legacy = {
    keys: s4.METER_KEYS.slice(),
    chargeNos: s4.CHARGE_METERS.map(m => m.meterNo),
    hallMult: s4.MULTIPLIER('hall'),
  };

  console.log(JSON.stringify(out));
})();
"""


class TestMeterConfigBehaviour(unittest.TestCase):
    """node 沙箱行为验证(需要 node,缺失则跳过)。"""

    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "meter_config_harness.js"
        hp.write_text(_NODE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_two_meter_store_rebuilds_keys_and_charge_meters(self) -> None:
        """2 表门店:METER_KEYS 恰好 2 个,CHARGE_METERS 序号跟着重排。"""
        out = self.out["afterLoad"]
        self.assertEqual(out["beforeKeys"],
                         ["hall", "fire", "private_room", "ac"],
                         "前置:加载前应是默认 4 表")
        self.assertEqual(out["keys"], ["m1", "m2"],
                         "METER_KEYS 没跟着当前店变 —— 还写死 4 表")
        self.assertEqual([m["key"] for m in out["chargeMeters"]], ["m1", "m2"])
        self.assertEqual([m["meterNo"] for m in out["chargeMeters"]], ["1#", "2#"])

    def test_metadata_comes_from_server(self) -> None:
        out = self.out["afterLoad"]
        self.assertEqual(out["m1mult"], 80)
        self.assertEqual(out["m1label"], "吧台")
        self.assertEqual(out["m1color"], "#111111")
        self.assertEqual(out["price"], 1.25)
        self.assertEqual(out["water"], 6.0)

    def test_reset_restores_default_four(self) -> None:
        out = self.out["afterReset"]
        self.assertEqual(out["keys"], ["hall", "fire", "private_room", "ac"])
        self.assertEqual(out["chargeKeys"], ["hall", "fire", "private_room", "ac"])
        self.assertEqual(out["hallMult"], 160)

    def test_meter_value_reads_both_shapes(self) -> None:
        out = self.out["meterValue"]
        self.assertEqual(out["fromDict"], 7.5)
        self.assertEqual(out["fromTop"], 3)
        # 缺失必须是 undefined:下面多处裸算术依赖 `undefined - x = NaN`
        # 来跳过「这块表没抄」的区间。返回 null 会让 `null - 5 = -5`
        # 配上充值额算出正数,把没抄表的区间当成有效用电。
        self.assertEqual(out["missing"], "undefined")
        self.assertEqual(out["undefinedarith"], "NaN")
        self.assertEqual(out["nullVal"], "null")

    def test_charge_attribution_works_for_custom_meter(self) -> None:
        """自定义表的充值归属必须能算出来(值在 meters 字典里)。"""
        attr = self.out["attribution"]["attr"]
        self.assertIsNotNone(attr, "自定义表的充值归属整段失效(行里读不到表值)")
        # 09-05 当天表底 150 相对 100 上升 → 钱进表,归属 09-01→09-05
        self.assertTrue(attr, "归属结果为空")

    def test_pasted_reading_charge_detected_for_custom_meter(self) -> None:
        """「充值额 = 当天抄表读数」在自定义表上也要能认出来。"""
        out = self.out["pasted"]
        self.assertEqual(out["count"], 1, "自定义表的抄表读数误填没被认出来")
        self.assertEqual(out["meter"], "m1")

    def test_default_four_tables_unchanged(self) -> None:
        """默认 4 表:key 顺序、序号、倍率都与改造前一致。"""
        out = self.out["legacy"]
        self.assertEqual(out["keys"], ["hall", "fire", "private_room", "ac"])
        self.assertEqual(out["chargeNos"], ["1#", "2#", "3#", "4#"])
        self.assertEqual(out["hallMult"], 160)


_CONTEXT_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

const sandbox = {
  console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
  Promise, RegExp, Error, isNaN, parseInt, parseFloat,
  localStorage: (function () {
    const m = {};
    return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: k => { delete m[k]; } };
  })(),
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 打桩:记录 resetMeterConfig 有没有被调用
let resetCalls = 0;
sandbox.resetMeterConfig = function () { resetCalls += 1; };
sandbox.State = { reset: () => {} };
sandbox.Api = { stores: { list: async () => ({ ok: true, stores: [], all_stores: false }),
                          current: async () => ({ ok: false }) } };

vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/storeContext.js'), 'utf8'),
                sandbox, { filename: 'storeContext.js' });

(async () => {
  await sandbox.StoreContext.init();
  const before = resetCalls;
  sandbox.StoreContext.reset();          // 登出
  console.log(JSON.stringify({ before: before, afterReset: resetCalls }));
})();
"""


class TestSwitchShopReloadsMeterConfig(unittest.TestCase):
    """切/登出门店必须重置表元数据 —— 否则切到 B 店还显示 A 店的表。"""

    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "ctx_harness.js"
        hp.write_text(_CONTEXT_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_reset_clears_meter_config(self) -> None:
        self.assertGreater(
            self.out["afterReset"], self.out["before"],
            "StoreContext.reset() 没有调用 resetMeterConfig —— "
            "换人登录/切店后会继续用上一家店的表集合",
        )


if __name__ == "__main__":
    unittest.main()
