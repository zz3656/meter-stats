"""电表设置页(P2:增删表 / 按店保存)测试(标准库 unittest,零依赖)。

改造前:设置页写死 4 块表,只能改名和倍率,而且提交的是 `{meter: 字典}` 给**全局**
settings —— 一家店改表名,全部门店跟着变。

现在:按当前门店读写 store.json,支持增删表,提交 `{meters: 数组, config}`。

覆盖:
- 静态:设置页有「当前门店」与「新增一块表」;admin.js 提交的是 meters 数组、
  不再写死 meterKeys;渲染/收集委托给 MeterForm(与抄表表单同一处实现)
- node 行为:2 块表 → 2 个单元格与 2 个删除按钮;1 块表 → 不给删除按钮(至少保留 1 块);
  自由文本进属性值必须转义;倍率非法值不被静默改成 1;
  新增表的 key 自动避让(m1/m2/…);载荷是数组且字段齐全

运行:
    python3 -m unittest tests.test_meter_settings_ui -v
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
ADMIN_JS = METERSTATS / "admin.js"
METER_FORM_JS = METERSTATS / "js" / "core" / "meterForm.js"


class TestSettingsStaticGuards(unittest.TestCase):
    """静态护栏 —— 不需要 node。"""

    def setUp(self) -> None:
        self.html = INDEX_HTML.read_text(encoding="utf-8")
        self.admin = ADMIN_JS.read_text(encoding="utf-8")

    def test_has_store_name_placeholder(self) -> None:
        """总部账号容易改错店 —— 标题上必须写清楚正在编辑哪家。"""
        self.assertIn('id="meter-settings-store"', self.html)
        self.assertIn("meter-settings-store", self.admin)

    def test_has_add_meter_button(self) -> None:
        self.assertIn("addMeterRow()", self.html)
        self.assertIn("function addMeterRow", self.admin)

    def test_description_not_hardcoded_to_four(self) -> None:
        self.assertNotIn("4 块表的显示名称", self.html)

    def test_saves_meters_as_payload(self) -> None:
        """提交的是 meters 数组(不是旧的 meter 字典),否则后端按旧形状处理。"""
        self.assertIn("meters:", self.admin)
        self.assertIn("saveMeterSettings({ meters:", self.admin)

    def test_no_hardcoded_meter_keys_in_settings(self) -> None:
        """设置页不许再写死那 4 个 key。"""
        self.assertNotIn("const meterKeys = ['hall', 'fire', 'private_room', 'ac']", self.admin)

    def test_delegates_to_meter_form(self) -> None:
        """渲染/收集必须复用 MeterForm(与抄表表单同一处实现,别再造一份 4 表逻辑)。"""
        self.assertIn("MeterForm.renderSettings", self.admin)
        self.assertIn("MeterForm.readSettings", self.admin)
        self.assertIn("MeterForm.settingsPayload", self.admin)

    def test_switch_reloads_settings_page(self) -> None:
        """切门店时必须重载电表设置页。

        不重载 → 表单还留着上一家店的数值、「当前门店」标签也不变,
        用户会以为改动串到别家店了;而此时按保存会把 A 店的值写进 B 店
        (保存的 ?store= 取的是实时门店)。
        """
        src = (METERSTATS / "js" / "modules" / "storeSwitcher.js").read_text(encoding="utf-8")
        block = src[src.index("async function onStoreContextChanged"):]
        block = block[:block.index("showAlert('账号未分配门店")]
        # 必须是**未被注释**的实际调用 —— 只做字符串包含的话,
        # 把调用注释掉(/* loadMeterSettings(); */)也能通过,护栏就空了。
        self.assertRegex(block, r"(?m)^\s*loadMeterSettings\(\);\s*$",
                         "切店后没有真正调用 loadMeterSettings() —— 会显示上一家店的数值")

    def test_save_guards_against_store_switch(self) -> None:
        """保存前必须校验「表单加载时的门店」与「实时门店」是否一致。"""
        self.assertIn("_meterSettingsStoreId", self.admin)
        self.assertIn("sameStore", self.admin,
                      "saveMeterSettings 没有门店一致性校验 —— 切店后保存会串写")

    def test_surfaces_backend_error(self) -> None:
        """后端 400(0 块表 / 倍率非法 / key 非法)要把原因显示出来。"""
        self.assertIn("res.error", self.admin)


_NODE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox() {
  const els = {};
  function mk(id) { return { id: id, innerHTML: '', value: '' }; }
  els['meter-settings-form'] = mk('meter-settings-form');

  const sandbox = {
  // 图标助手:被加载的文件会调 meterIconHtml()/icon();这里给桩,
  // 断言只关心"这里本该有个图标",不关心 SVG 长什么样。
  icon: (name) => '<svg class="icon" data-icon="' + name + '"></svg>',
  // 与真实 meterIconHtml 的契约一致:未知值走「转义后的纯文本」,绝不原样插入 HTML
  meterIconHtml: (value) => '<svg class="icon" data-meter-icon="' +
    String(value == null ? '' : value).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]) + '"></svg>',
  meterIconName: (value) => String(value || ''),
  meterIconPickerHtml: (cur) => '<div class="meter-icon-picker" data-field="icon">' +
    '<button class="meter-icon-choice" data-icon-value="mic"></button></div>',
    console, JSON, Object, Array, String, Number, Math, isNaN, parseInt,
    document: { getElementById: id => (els[id] || null) },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  sandbox.METER_KEYS = ['hall', 'fire', 'private_room', 'ac'];
  sandbox.METER_META = k => ({ label: k, multiplier: 1 });
  sandbox.escapeHtml = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  };
  sandbox.escapeAttr = sandbox.escapeHtml;

  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/meterForm.js'), 'utf8'),
                  sandbox, { filename: 'meterForm.js' });
  return sandbox;
}

function countAll(html, needle) {
  let n = 0, i = 0;
  while ((i = html.indexOf(needle, i)) >= 0) { n++; i += needle.length; }
  return n;
}

const out = {};
const s = makeSandbox();
const form = s.document.getElementById('meter-settings-form');

// ① 2 块表 → 2 个单元格 + 2 个删除按钮
{
  const list = [
    { key: 'm1', label: '吧台', icon: '🍸', multiplier: 80 },
    { key: 'm2', label: '后厨', icon: '🔥', multiplier: 3 },
  ];
  s.MeterForm.renderSettings(form, list, function () {});
  out.two = {
    cells: countAll(form.innerHTML, 'class="meter-cell"'),
    dels: countAll(form.innerHTML, 'meter-del-btn'),
    html: form.innerHTML,
  };
}

// ② 只剩 1 块表 → 不许给删除按钮(至少保留 1 块)
{
  s.MeterForm.renderSettings(form, [{ key: 'm1', label: '唯一', icon: '⚡', multiplier: 1 }], function () {});
  out.one = {
    cells: countAll(form.innerHTML, 'class="meter-cell"'),
    dels: countAll(form.innerHTML, 'meter-del-btn'),
  };
}

// ③ 自由文本进属性值必须转义(门店名/表名是用户输入)
{
  const evil = 'a" onmouseover="alert(1)';
  s.MeterForm.renderSettings(form, [
    { key: 'm1', label: evil, icon: '<img>', multiplier: 1 },
  ], function () {});
  out.escape = {
    html: form.innerHTML,
    hasRawQuote: form.innerHTML.indexOf('onmouseover="alert(1)"') >= 0,
    hasRawImg: form.innerHTML.indexOf('<img>') >= 0,
  };
}

// ④ 倍率非法值不许被静默改成 1
{
  s.MeterForm.renderSettings(form, [{ key: 'm1', label: 'x', icon: '⚡', multiplier: 0 }], function () {});
  const hasZero = form.innerHTML.indexOf('value="0"') >= 0;
  out.zeroMult = { renderedZero: hasZero };
}

// ⑤ 新增表的 key 自动避让
{
  out.nextKey = {
    empty: s.MeterForm.nextMeterKey([]),
    usedOne: s.MeterForm.nextMeterKey(['m1']),
    usedGap: s.MeterForm.nextMeterKey(['m1', 'm3']),
    usedMany: s.MeterForm.nextMeterKey(['m1', 'm2', 'm3']),
  };
}

// ⑥b 保存前的门店一致性判定
{
  out.sameStore = {
    same: s.MeterForm.sameStore('S002', 'S002'),
    diff: s.MeterForm.sameStore('S002', 'main'),
    noLoaded: s.MeterForm.sameStore('', 'main'),
    noLive: s.MeterForm.sameStore('S002', ''),
  };
}

// ⑥ 载荷是数组且字段齐全
{
  out.payload = s.MeterForm.settingsPayload([
    { key: 'm1', label: '吧台', icon: '🍸', multiplier: 80 },
    { key: 'm2', label: '后厨', icon: '🔥', multiplier: 3 },
  ]);
}

console.log(JSON.stringify(out));
"""


class TestSettingsBehaviour(unittest.TestCase):
    """node 沙箱行为验证(需要 node,缺失则跳过)。"""

    out: dict[str, Any]
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node,跳过前端行为验证")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        hp = Path(cls._tmp.name) / "settings_harness.js"
        hp.write_text(_NODE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(["node", str(hp)], capture_output=True, text=True,
                              env=env, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node 执行失败:\n%s" % proc.stderr)
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_two_meters_render_two_cells_with_delete(self) -> None:
        two = self.out["two"]
        self.assertEqual(two["cells"], 2)
        self.assertEqual(two["dels"], 2, "每块表都该有删除按钮")

    def test_single_meter_cannot_be_deleted(self) -> None:
        """至少保留 1 块表 —— 删到 1 块时不给删除按钮。"""
        one = self.out["one"]
        self.assertEqual(one["cells"], 1)
        self.assertEqual(one["dels"], 0,
                         "只剩 1 块表还给了删除按钮 —— 会导致 0 块表,后端直接 400")

    def test_free_text_in_attributes_is_escaped(self) -> None:
        esc = self.out["escape"]
        self.assertFalse(esc["hasRawQuote"], "表名里的引号没转义 —— 属性被截断(XSS)")
        self.assertFalse(esc["hasRawImg"], "图标里的 <img> 被当成真标签")

    def test_invalid_multiplier_is_not_silently_fixed(self) -> None:
        """倍率 0 原样显示,交给用户看到 + 后端拒绝,而不是悄悄改成 1。"""
        self.assertTrue(self.out["zeroMult"]["renderedZero"],
                        "倍率 0 被静默改掉了 —— 用户看不出自己填错了")

    def test_next_meter_key_avoids_used(self) -> None:
        k = self.out["nextKey"]
        self.assertEqual(k["empty"], "m1")
        self.assertEqual(k["usedOne"], "m2")
        self.assertEqual(k["usedGap"], "m2")
        self.assertEqual(k["usedMany"], "m4")

    def test_same_store_guard(self) -> None:
        """门店一致才允许保存;任一为空时不拦(单店布局不能误伤)。"""
        g = self.out["sameStore"]
        self.assertTrue(g["same"], "同一门店却判定为不一致")
        self.assertFalse(g["diff"], "门店不同却放行 —— 会把 A 店的表集合写进 B 店")
        self.assertTrue(g["noLoaded"], "加载时门店为空不应拦住保存(单店布局)")
        self.assertTrue(g["noLive"], "实时门店为空不应拦住保存")

    def test_payload_is_array_with_all_fields(self) -> None:
        p = self.out["payload"]
        self.assertIsInstance(p, list, "提交给后端的必须是数组(后端按数组校验)")
        self.assertEqual(len(p), 2)
        for item in p:
            for f in ("key", "label", "icon", "multiplier"):
                self.assertIn(f, item, "载荷缺字段 %s" % f)
        self.assertEqual(p[0]["multiplier"], 80)


if __name__ == "__main__":
    unittest.main()
