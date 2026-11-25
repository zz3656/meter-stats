"""分店前端接线回归测试(标准库 unittest,零依赖)。

只做静态接线检查(与 tests/test_frontend_refresh.py 同风格):
- index.html 引入了 stores.js,侧栏有「门店管理」入口
- api.js 有 Api.stores 封装
- stores.js 渲染门店列表并调用 Api.stores.create / update / remove
- admin.js 的用户表单带门店多选

外加两条「别把前端的坑再挖一遍」的护栏:
- stores.js 不得自己再定义一份 escapeHtml(全局那份已经够用,重复定义会互相覆盖)
- 门店 ID 进属性值必须走 escapeAttr —— 全局 escapeHtml 被 admin.js 的弱版本覆盖,
  那份只转义 & < >,不转义 " 和 ' ,自由文本进属性值就能打断属性
"""
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
API_JS = METERSTATS / "js" / "core" / "api.js"
STORES_JS = METERSTATS / "js" / "modules" / "stores.js"
NAV_JS = METERSTATS / "js" / "core" / "navigation.js"
ADMIN_JS = METERSTATS / "admin.js"


class TestStoresFrontendWiring(unittest.TestCase):

    def test_stores_js_is_loaded_by_index(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("js/modules/stores.js", html)

    def test_sidebar_has_stores_entry(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn("switchSettingsPage('stores')", html)
        self.assertIn("门店管理", html)

    def test_index_has_stores_section(self) -> None:
        """switchSettingsPage 靠 section-settings-<page> 找容器,id 必须对。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="section-settings-stores"', html)

    def test_api_exposes_stores_endpoints(self) -> None:
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("var stores = {", src)
        for call in ("/api/stores", "create:", "update:", "remove:"):
            self.assertIn(call, src)

    def test_api_returns_stores_in_public_surface(self) -> None:
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("stores: stores", src)

    def test_stores_js_renders_list_and_calls_api(self) -> None:
        src = STORES_JS.read_text(encoding="utf-8")
        self.assertIn("function renderStoresPage", src)
        self.assertIn("Api.stores.list()", src)
        self.assertIn("Api.stores.create", src)
        self.assertIn("Api.stores.update", src)
        self.assertIn("Api.stores.remove", src)

    def test_admin_js_has_store_multi_select(self) -> None:
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("store_ids", src)
        self.assertIn("all_stores", src)

    def test_user_form_renders_store_checkboxes(self) -> None:
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertRegex(src, r"store_ids")

    def test_navigation_switch_settings_page_supports_stores(self) -> None:
        src = NAV_JS.read_text(encoding="utf-8")
        self.assertIn("page === 'stores'", src)
        self.assertIn("loadStores", src)

    def test_stores_js_does_not_define_its_own_escape_html(self) -> None:
        """全局 escapeHtml 已经够用 —— 再定义一份只会互相覆盖。"""
        src = STORES_JS.read_text(encoding="utf-8")
        self.assertNotRegex(src, r"function\s+escapeHtml")
        self.assertNotIn("window.escapeHtml", src)

    def test_store_values_in_attributes_use_attribute_escaping(self) -> None:
        """门店 ID 进属性值必须走 escapeAttr(全局 escapeHtml 是弱版,不转义引号)。"""
        stores = STORES_JS.read_text(encoding="utf-8")
        admin = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("escapeAttr", stores)
        for frag in re.findall(r'value="([^"]*)"', stores):
            if "+" in frag or "${" in frag:
                self.assertIn("escapeAttr(", frag, f"stores.js 属性值未转义: {frag}")
        for box_name in ("new-store-ids", "edit-store-ids"):
            self.assertIn(f'name="{box_name}"', admin)
            markup = [ln for ln in admin.splitlines()
                      if f'name="{box_name}"' in ln and 'type="checkbox"' in ln]
            self.assertTrue(markup, f"没找到 {box_name} 的勾选框")
            for line in markup:
                self.assertIn("escapeAttr(", line, f"{box_name} 的 value 未转义")

    def test_delete_confirm_mentions_data_dir_is_kept(self) -> None:
        """删门店只删登记信息,数据目录保留 —— 确认文案必须写明。"""
        src = STORES_JS.read_text(encoding="utf-8")
        self.assertIn("数据目录", src)

    def test_admin_update_user_sends_id_as_query_param(self) -> None:
        """后端 PUT /api/admin/users 从 query 取 id(?id=)—— 路径形式会被判「无效的用户ID」。"""
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("/api/admin/users?id=", src)


# ============ 行为验证(需要 node) ============

# 用真实的 stores.js 跑一遍:先装上 admin.js 的那份弱 escapeHtml(页面运行时它会覆盖
# utils.js 的强版本),再喂恶意门店数据,看渲染出来的 HTML 到底长什么样。
_STORES_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeEl(id, tag) {
  return {
    id: id || null, tagName: tag || 'div', style: {}, dataset: {}, value: '',
    textContent: '', _html: '', children: [],
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    addEventListener() {}, removeEventListener() {}, setAttribute() {},
    querySelectorAll() { return []; }, querySelector() { return null; },
    closest() { return null; }, focus() {}, contains() { return false; },
    appendChild(c) { this.children.push(c); return c; },
  };
}

// 模拟浏览器:textContent → innerHTML 只转义 & < >,不转义引号
function textDiv() {
  let t = '';
  return {
    set textContent(v) { t = (v == null) ? '' : String(v); },
    get textContent() { return t; },
    get innerHTML() {
      return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  };
}

const reg = {};
const host = makeEl('stores-page');
reg['stores-page'] = host;

const sandbox = {
  document: {
    getElementById: (id) => reg[id] || null,
    querySelector: () => null, querySelectorAll: () => [],
    createElement: () => textDiv(),
  },
  console, setTimeout, clearTimeout, Math, JSON, Date, Number, String, Array, Object, Map, Set,
  showAlert: () => {},
  confirm: (msg) => { sandbox.__confirmMsg = String(msg); return true; },
  Api: {
    stores: {
      list: async () => ({ ok: true, stores: [] }),
      create: async () => ({ ok: true }),
      update: async () => ({ ok: true }),
      remove: async (id) => { sandbox.__removed = id; return { ok: true }; },
    },
  },
  ADMIN_USER: { role: 'admin' },
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// ① 真实运行时生效的是 admin.js 那份弱 escapeHtml(顶层函数声明会覆盖 utils.js 的)
const adminSrc = fs.readFileSync(path.join(ROOT, 'admin.js'), 'utf8');
const m = adminSrc.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/);
if (!m) { console.log(JSON.stringify({ error: 'admin.js 里找不到 escapeHtml' })); process.exit(0); }
vm.runInContext(m[0], sandbox, { filename: 'admin-escapeHtml.js' });

// ② 再加载 stores.js
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/modules/stores.js'), 'utf8'),
                sandbox, { filename: 'stores.js' });

// ③ 恶意门店数据:名称/编号是自由文本,ID 也故意带上引号(后端其实禁止,但前端不能靠后端兜底)
const hostile = {
  id: 's" onmouseover="alert(1)',
  name: '<img src=x onerror=alert(1)>"\'&',
  code: '<b>c</b>',
  address: "addr'\"x",
  active: true,
  created_at: '2026-11-25T10:00:00',
};
sandbox.STORE_LIST = [hostile];
sandbox.renderStoresPage();
const html = host.innerHTML;

(async () => {
  await sandbox.removeStore(hostile.id);
  console.log(JSON.stringify({
    html: html,
    confirmMsg: sandbox.__confirmMsg || '',
    removed: sandbox.__removed || '',
  }));
})();
"""


class TestStoresBehavior(unittest.TestCase):
    """用真实的 js/modules/stores.js 跑一遍渲染(需要 node,缺失则跳过)。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, harness: str) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(harness, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def test_store_name_cannot_inject_markup(self) -> None:
        """门店名称是自由文本 —— 弱 escapeHtml 下也不能拼出标签。"""
        out = self._run(_STORES_HARNESS)
        html = out["html"]
        self.assertNotIn("<img", html, "门店名称被拼成了真标签(弱 escapeHtml 不够用)")
        self.assertNotIn("<b>", html, "门店编号被拼成了真标签")
        self.assertIn("&lt;img", html, "门店名称应被转义成文本")

    def test_store_id_in_attribute_is_escaped(self) -> None:
        """门店 ID 进属性值必须走 escapeAttr —— 弱 escapeHtml 不转义引号。"""
        out = self._run(_STORES_HARNESS)
        html = out["html"]
        self.assertIn(
            'data-store-id="s&quot; onmouseover=&quot;alert(1)"', html,
            "data-store-id 的值没有被属性转义",
        )
        self.assertNotIn(
            'data-store-id="s" onmouseover="alert(1)"', html,
            "data-store-id 的值被引号打断了",
        )

    def test_delete_confirm_text_says_data_dir_is_kept(self) -> None:
        """删门店的确认文案必须写明「只删登记信息,数据目录保留」。"""
        out = self._run(_STORES_HARNESS)
        msg = out["confirmMsg"]
        self.assertIn("数据目录", msg, "删除确认文案没提数据目录")
        self.assertIn("保留", msg, "删除确认文案没说数据目录会保留")
        self.assertEqual(out["removed"], 's" onmouseover="alert(1)', "删错门店了")


if __name__ == "__main__":
    unittest.main()
