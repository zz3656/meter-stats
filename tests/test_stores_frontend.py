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
STORE_CONTEXT_JS = METERSTATS / "js" / "core" / "storeContext.js"
ACCESSIBILITY_JS = METERSTATS / "js" / "shared" / "accessibility.js"
STORES_JS = METERSTATS / "js" / "modules" / "stores.js"
UTILS_JS = METERSTATS / "js" / "helpers" / "utils.js"
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

    def test_escape_attr_is_defined_only_in_utils_js(self) -> None:
        """escapeAttr 只能有一份,且必须住在 js/helpers/utils.js。

        为什么:admin.js(用户管理页)也在调用 escapeAttr,
        如果它定义在 stores.js(门店管理页)里,就是「用户管理页依赖门店管理页」的隐式耦合 ——
        哪��天单独加载 admin.js,用户表单的门店勾选框会直接抛 ReferenceError。
        工具函数按项目既有约定统一放 js/helpers/utils.js(与 escapeHtml 同居)。
        """
        utils = UTILS_JS.read_text(encoding="utf-8")
        self.assertIn("window.escapeAttr", utils, "escapeAttr 应定义在 js/helpers/utils.js")
        for name, path in (("stores.js", STORES_JS), ("admin.js", ADMIN_JS)):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("window.escapeAttr", src, f"{name} 不该再定义 escapeAttr")
            self.assertNotRegex(src, r"function\s+escapeAttr")

    def test_delete_confirm_mentions_data_dir_is_kept(self) -> None:
        """删门店只删登记信息,数据目录保留 —— 确认文案必须写明。"""
        src = STORES_JS.read_text(encoding="utf-8")
        self.assertIn("数据目录", src)

    def test_admin_update_user_sends_id_as_query_param(self) -> None:
        """后端 PUT /api/admin/users 从 query 取 id(?id=)—— 路径形式会被判「无效的用户ID」。"""
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("/api/admin/users?id=", src)

    def test_admin_delete_user_sends_id_as_query_param(self) -> None:
        """删除用户也必须走 query —— 后端 handle_delete_users 同样只从 query 取 id。

        回归背景:原来前端是路径形式 DELETE /api/admin/users/<name>,
        而后端只认 ?id=<uid> → **删除用户功能整个是坏的**,永远返回「无效的用户ID」。
        """
        src = API_JS.read_text(encoding="utf-8")
        line = next(
            (ln for ln in src.splitlines() if "deleteUser:" in ln and "function" in ln),
            "",
        )
        self.assertTrue(line, "api.js 里找不到 deleteUser 的定义")
        self.assertIn("/api/admin/users?id=", line)
        # 旧的路径形式不能再出现
        self.assertNotIn("/api/admin/users/' +", line)
        self.assertNotIn("/api/admin/users/\" +", line)

    def test_api_js_appends_store_parameter(self) -> None:
        """api.js 必须给请求拼上当前门店,且引导端点除外。"""
        src = API_JS.read_text(encoding="utf-8")
        self.assertIn("_appendStore", src)
        self.assertIn("StoreContext.getStoreId()", src)
        # store-free 白名单:这三类端点不能带 store(否则会锁死 / 误踢登录)
        self.assertIn("/api/stores", src)
        self.assertIn("/api/auth/", src)

    def test_store_free_endpoints_are_not_given_store(self) -> None:
        """引导端点带 store 会锁死用户 —— 白名单必须真的生效。

        规则的唯一真相源是 js/core/storeContext.js::isStoreFreePath,
        api.js / accessibility.js 都调它 —— 谁再抄一份规则,谁就是下一个走样的地方。
        (这条断言不能删:它是「引导端点不带 store」这层保护的一部分。)
        """
        src = STORE_CONTEXT_JS.read_text(encoding="utf-8")
        fn = re.search(r"function isStoreFreePath\(path\)\s*\{[\s\S]*?\n  \}", src)
        self.assertIsNotNone(fn, "storeContext.js 里找不到 isStoreFreePath")
        body = fn.group(0) if fn else ""
        for guard in ("/api/health", "/api/version", "/api/auth/", "/api/stores"):
            self.assertIn(guard, body, f"isStoreFreePath 少了 {guard}")
        # 调用方必须真的调它,而不是各自留一份规则
        self.assertIn(
            "StoreContext.isStoreFreePath", API_JS.read_text(encoding="utf-8"),
            "api.js 没调 StoreContext.isStoreFreePath",
        )
        self.assertIn(
            "StoreContext.isStoreFreePath", ACCESSIBILITY_JS.read_text(encoding="utf-8"),
            "accessibility.js 没调 StoreContext.isStoreFreePath",
        )

    def test_duty_image_url_carries_store(self) -> None:
        """图片按门店分目录 —— <img src> 必须带 store,否则串店。"""
        src = UTILS_JS.read_text(encoding="utf-8")
        fn = re.search(r"window\.getDutyImageUrl[\s\S]*?\n\};", src)
        self.assertIsNotNone(fn)
        # mypy strict:assertIsNotNone 不做类型收窄 → 取值处显式兜底
        self.assertIn("store=", fn.group(0) if fn else "")


# ============ 行为验证:api.js 的 store 贯通(需要 node) ============

# Task 3 的核心契约是「普通端点带 store、引导端点不带 store」——
# 而 tests/test_store_switch_frontend.py 的 api.js harness 只调了
# Api.stores.list() / Api.stores.current(),**两个都是 store-free 端点**。
# 也就是说:如果 _appendStore() 对普通端点是个彻底的 no-op,整个测试套件照样全绿。
# 这张网专门补上那个方向。
#
# 关键设计:
# 1) 沙箱里门店 ID 的**两个来源给不同的值** ——
#    StoreContext.getStoreId() → 's002'(正确来源)
#    localStorage['meter_current_store'] → 's999'(错误来源)
#    断言 store 参数等于 's002',就同时约束了「带 store」和「ID 从哪来」。
# 2) 加载**真实的** js/core/storeContext.js(不是替身)——
#    白名单规则 isStoreFreePath 就住在那里,用替身就测不到规则本身。
# 3) 引导完之后**再打一次**引导端点:那时 storeId 已经是 's002',
#    白名单要是失效,这两个请求就会带上 store=s002(→ 删店后用户永久锁死)。
_API_STORE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
// 路径可被环境变量覆盖 —— 变异验证时用副本,绝不碰仓库里的真文件
const API_FILE = process.env.MS_API_JS || path.join(ROOT, 'js/core/api.js');
const STORE_CONTEXT_FILE = process.env.MS_STORE_CONTEXT_JS || path.join(ROOT, 'js/core/storeContext.js');

const fetched = [];

// 假 FormData:记下 append 过的字段名 —— 字段名就是后端契约,写反了照样得绿
class FakeFormData {
  constructor() { this.fields = []; }
  append(name, value) { this.fields.push([name, value]); }
}

const sandbox = {
  console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
  Promise, RegExp, Error, isNaN, parseInt, parseFloat, URLSearchParams,
  Map, Set, FormData: FakeFormData,
  localStorage: (function () {
    const map = {};
    return {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
      setItem: (k, v) => { map[k] = String(v); },
      removeItem: (k) => { delete map[k]; },
    };
  })(),
  document: { getElementById: () => null },
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
// 门店 ID 的错误来源:localStorage 里放一个**不同**的值。
// 真正的门店上下文(下面加载)会把它当成「记住的店」校验 ——
// s999 不在可见门店列表里 → 被拒 → 改用后端给的 s002。
sandbox.localStorage.setItem('meter_current_store', 's999');
sandbox.fetch = function (url, opts) {
  fetched.push({
    url: String(url),
    path: String(url).split('?')[0],
    method: (opts && opts.method) || 'GET',
    hasBody: !!(opts && opts.body !== undefined && opts.body !== null),
    fields: (opts && opts.body && opts.body.fields) ? opts.body.fields.map((f) => f[0]) : [],
  });
  const p = String(url).split('?')[0];
  if (p === '/api/stores') {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({
      ok: true, stores: [{ id: 's002', name: '国贸店' }], all_stores: true }) });
  }
  if (p === '/api/stores/current') {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({
      ok: true, store_id: 's002', all_stores: true }) });
  }
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ ok: true, stores: [], items: [], charges: [], readings: [] }),
  });
};
vm.createContext(sandbox);
// 真实加载顺序:api.js → storeContext.js(两个都只定义,不执行请求)
vm.runInContext(fs.readFileSync(API_FILE, 'utf8'), sandbox, { filename: 'api.js' });
vm.runInContext(fs.readFileSync(STORE_CONTEXT_FILE, 'utf8'), sandbox, { filename: 'storeContext.js' });

function storeParam(url) {
  const query = String(url).split('?')[1] || '';
  for (const kv of query.split('&')) {
    const parts = kv.split('=');
    if (parts[0] === 'store') return decodeURIComponent(parts[1] || '');
  }
  return null;
}

(async () => {
  // ① 先引导真实的门店上下文(它自己会打 /api/stores 与 /api/stores/current)
  await sandbox.StoreContext.init();
  // ② 引导完之后**再打一次**引导端点 —— 此时 storeId 已经是 's002',
  //    白名单要是失效,这两个请求就会带上 store=s002(→ 用户永久锁死)。
  await sandbox.Api.stores.list();
  await sandbox.Api.stores.current();
  // ③ localStorage 里再塞一个**不同**的门店 ID:
  //    「门店 ID 只能问 StoreContext」这条规则靠它守住
  //    (真实 init() 刚把 localStorage 写成了 s002,这里改回 s999)
  sandbox.localStorage.setItem('meter_current_store', 's999');
  // ④ 普通端点(必须带 store)
  await sandbox.Api.readings.list();
  await sandbox.Api.charges.list();
  await sandbox.Api.items.list();
  // ⑤ 上传类端点(必须带 store **且** 真的把 FormData 挂到请求体上)
  await sandbox.Api.upload.doUpload({ name: 'b.zip' });
  await sandbox.Api.adminRestore.upload({ name: 'c.zip' });
  await sandbox.Api.dataimport.import('readings', { name: 'd.csv' });
  await sandbox.Api.adminImport.doImport('readings', { name: 'e.csv' });
  // 备份恢复(浏览器手里的 File 走 /api/admin/restore-upload)
  await sandbox.Api.backup.restore({ name: 'f.zip' });
  await sandbox.Api.backup.doRestore({ name: 'g.zip' });

  console.log(JSON.stringify({
    storeId: sandbox.StoreContext.getStoreId(),
    localStore: sandbox.localStorage.getItem('meter_current_store'),
    fetched: fetched.map((c) => ({
      url: c.url, path: c.path, method: c.method,
      hasBody: c.hasBody, store: storeParam(c.url), fields: c.fields,
    })),
  }));
})();
"""


class TestApiStoreWiring(unittest.TestCase):
    """用真实的 js/core/api.js 跑一遍,验证 store 参数贯通的两个方向。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_API_STORE_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        for var, value in (
            ("MS_API_JS", os.environ.get("MS_API_JS")),
            ("MS_STORE_CONTEXT_JS", os.environ.get("MS_STORE_CONTEXT_JS")),
        ):
            if value:
                env[var] = value
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def _calls(self, out: dict[str, Any], path: str) -> list[Any]:
        return [c for c in out["fetched"] if c["path"] == path]

    def test_normal_endpoints_carry_store_from_store_context(self) -> None:
        """普通端点必须带 store,且门店 ID 取自 StoreContext(不是 localStorage)。

        这条是 Task 3 的核心契约 —— 之前一条断言都没有:
        引导端点恰好是 store-free 的,全绿也证明不了「普通端点带了 store」。
        """
        out = self._run()
        # 前提:两个来源给的是**不同的**值 —— 否则断言区分不出实现取自哪边
        self.assertEqual(out["storeId"], "s002", "门店上下文没引导出 s002")
        self.assertEqual(out["localStore"], "s999", "localStorage 的门店 ID 没种上")
        for path in ("/api/readings", "/api/charges", "/api/items"):
            calls = self._calls(out, path)
            self.assertTrue(calls, "%s 没发请求" % path)
            for call in calls:
                self.assertEqual(
                    call["store"], "s002",
                    "%s 的 store 参数是 %r,期望 's002'(取自 StoreContext;"
                    "读 localStorage 的 s999 就是错的)" % (path, call["store"]),
                )

    def test_bootstrap_endpoints_do_not_carry_store(self) -> None:
        """引导端点不许带 store —— 否则删店后用户永久锁死。"""
        out = self._run()
        for path in ("/api/stores", "/api/stores/current"):
            calls = self._calls(out, path)
            self.assertTrue(calls, "%s 没发请求" % path)
            for call in calls:
                self.assertIsNone(
                    call["store"], "引导端点带了 store: %s" % call["url"],
                )

    def test_formdata_uploads_send_body_and_store(self) -> None:
        """上传类请求:带 store **且** 真的把 FormData 挂到请求体上,**且字段名对**。

        body 没挂 = 请求发出去不带任何数据 = 上传功能整个是坏的
        (历史上 6 处 FormData 全都只 new + append,没有一处 opts.body = formData)。
        字段名也是契约的一部分 —— 写反了后端照样认不出来:
          - /api/admin/restore-upload → zip_file(后端按 filename="*.zip" 提取)
          - /api/import              → model + file
          - /api/upload              → file
        """
        out = self._run()
        # 逐路径断言:每条上传路径各自断言「确实发过 + 带 store + body 有 + 字段名对」。
        # (不能用全局 seen 标志 —— 少一条路径也未必红。)
        expected = {
            "/api/upload": ["file"],
            "/api/admin/restore-upload": ["zip_file"],
            "/api/import": ["model", "file"],
        }
        for path, fields in expected.items():
            calls = self._calls(out, path)
            self.assertTrue(calls, "%s 没发请求(上传路径被删/改错了)" % path)
            for call in calls:
                self.assertEqual(
                    call["store"], "s002",
                    "%s 的 store 参数是 %r,期望 's002'" % (path, call["store"]),
                )
                self.assertTrue(
                    call["hasBody"],
                    "%s 没把 FormData 挂到请求体上(请求发出去不带任何数据): %s"
                    % (path, call["url"]),
                )
                self.assertEqual(
                    sorted(call["fields"]), sorted(fields),
                    "%s 的 multipart 字段名不对: %r(后端要 %r)" % (path, call["fields"], fields),
                )

    def test_backup_restore_uses_the_upload_endpoint(self) -> None:
        """浏览器手里的 File 只能走 /api/admin/restore-upload。

        POST /api/restore 要的是 JSON {zip_path: 服务器磁盘路径} ——
        浏览器手里只有 File,走不通那条路(后端 modules/backup/handler.py:551)。
        """
        out = self._run()
        paths = [c["path"] for c in out["fetched"]]
        self.assertIn("/api/admin/restore-upload", paths, "备份恢复没走上传端点")
        self.assertNotIn(
            "/api/restore", paths,
            "备份恢复还在打 /api/restore(JSON zip_path —— 浏览器走不通)",
        )


# accessibility.js 的 api() 是**活路径**(readings.js / toast.js / nas_sync.js 都在调),
# 门店失效时必须像 api.js::_request 一样把错误转交 StoreContext.handleStoreError ——
# 否则 state.storeId 不清、缓存不清、不重新引导 → UI 停在失效门店上。
_ACCESSIBILITY_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
// 可被 MS_ACCESSIBILITY_JS 覆盖 —— 变异验证时用副本,绝不碰仓库里的真文件
const ACCESSIBILITY_FILE = process.env.MS_ACCESSIBILITY_JS || path.join(ROOT, 'js/shared/accessibility.js');

const handled = [];
const fetched = [];

const sandbox = {
  console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
  Promise, RegExp, Error, isNaN, parseInt, parseFloat, URLSearchParams,
  localStorage: (function () {
    const map = {};
    return {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
      setItem: (k, v) => { map[k] = String(v); },
      removeItem: (k) => { delete map[k]; },
    };
  })(),
  document: {
    readyState: 'loading',                 // 跳过 applyAccessibility 的立即执行
    documentElement: { setAttribute() {} },
    addEventListener() {}, removeEventListener() {}, getElementById: () => null,
  },
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.matchMedia = () => ({ addEventListener() {} });
sandbox.StoreContext = {
  getStoreId: () => 's002',
  handleStoreError: (status, text) => { handled.push({ status: status, text: String(text) }); },
};
sandbox.fetch = function (url) {
  fetched.push({ url: String(url) });
  return Promise.resolve({
    ok: false,
    status: 404,
    text: () => Promise.resolve(JSON.stringify({ error: '门店不存在: s002' })),
  });
};
vm.createContext(sandbox);

// utils.js 先加载(它提供共享的 isValidStoreId),再加载 accessibility.js
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/helpers/utils.js'), 'utf8'),
                sandbox, { filename: 'utils.js' });
vm.runInContext(fs.readFileSync(ACCESSIBILITY_FILE, 'utf8'),
                sandbox, { filename: 'accessibility.js' });

(async () => {
  let err = '';
  try { await sandbox.api('GET', '/api/readings'); } catch (e) { err = String(e && e.message); }
  console.log(JSON.stringify({ handled: handled, err: err, fetched: fetched }));
})();
"""


class TestAccessibilityStoreError(unittest.TestCase):
    """accessibility.js::api() 失败时必须转交 StoreContext.handleStoreError。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_ACCESSIBILITY_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        override = os.environ.get("MS_ACCESSIBILITY_JS")
        if override:
            env["MS_ACCESSIBILITY_JS"] = override
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def test_failure_is_forwarded_to_store_context(self) -> None:
        """门店失效(404)必须转交 handleStoreError —— 否则 UI 停在失效门店上。"""
        out = self._run()
        self.assertTrue(
            out["handled"], "失败没转交 StoreContext.handleStoreError(门店失效无人恢复)",
        )
        self.assertEqual(out["handled"][0]["status"], 404)
        self.assertIn("门店不存在", out["handled"][0]["text"])
        # 原始错误仍要抛出去 —— 转交不能掩盖它
        self.assertIn("HTTP 404", out["err"])

    def test_accessibility_api_also_carries_store(self) -> None:
        """accessibility.js 的 api() 也要带 store —— 它同样是活路径。"""
        out = self._run()
        self.assertTrue(out["fetched"], "accessibility.js 的 api() 没发请求")
        self.assertIn("store=s002", out["fetched"][0]["url"])


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

// ① 先加载 utils.js(浏览器里它加载得最早)—— 提供 escapeHtml(强版)与 escapeAttr
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/helpers/utils.js'), 'utf8'),
                sandbox, { filename: 'utils.js' });

// ② 真实运行时生效的是 admin.js 那份弱 escapeHtml(顶层函数声明会覆盖 utils.js 的)
const adminSrc = fs.readFileSync(path.join(ROOT, 'admin.js'), 'utf8');
const m = adminSrc.match(/function escapeHtml\(str\) \{[\s\S]*?\n\}/);
if (!m) { console.log(JSON.stringify({ error: 'admin.js 里找不到 escapeHtml' })); process.exit(0); }
vm.runInContext(m[0], sandbox, { filename: 'admin-escapeHtml.js' });

// ③ 再加载 stores.js
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
