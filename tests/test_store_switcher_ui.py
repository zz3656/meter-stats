"""门店切换器接线回归测试(标准库 unittest,零依赖)。

静态接线检查(与 tests/test_stores_frontend.py 同风格):
- index.html 有切换器 DOM,并引入了两个新脚本
- storeSwitcher.js 订阅了 StoreContext 变化、调用了 switchTo、切换后重拉数据
- admin.js 先引导门店上下文再 loadAppData(顺序反了 → 第一个请求落到后端默认店)

外加行为验证(node vm 沙箱,跑真实的 js/modules/storeSwitcher.js 与 admin.js 里
抠出来的 setLoggedIn):静态断言只能证明「字符串出现过」,证明不了「真按那个顺序跑」。
上一轮复核就是靠纯静态断言漏掉了两个坑:
- switchTo 失败时不提示(字符串还在,静态断言照样绿)
- onChange 订阅被塞进「DOM 只绑一次」的守卫里(登出后再登录就没有订阅者了,
  切店不刷数据 —— 字符串也还在,静态断言同样绿)

运行:
    python3 -m unittest tests.test_store_switcher_ui -v
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
STORE_SWITCHER_JS = METERSTATS / "js" / "modules" / "storeSwitcher.js"
ADMIN_JS = METERSTATS / "admin.js"


# ===== 真实 storeSwitcher.js 的行为沙箱 =====
#
# 替身只提供 DOM 与 StoreContext,被测代码是仓库里真实的那份 js/modules/storeSwitcher.js。
_SWITCHER_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeEl() {
  const handlers = {};
  return {
    style: {},
    dataset: {},
    innerHTML: '',
    value: '',
    addEventListener: function (type, fn) {
      (handlers[type] = handlers[type] || []).push(fn);
    },
    fire: function (type) {
      (handlers[type] || []).forEach(function (fn) { fn(); });
    },
    handlerCount: function (type) { return (handlers[type] || []).length; },
  };
}

function tick() {
  return new Promise(function (r) { setTimeout(r, 5); });
}

function makeSandbox(opts) {
  opts = opts || {};
  const wrap = makeEl();
  const sel = makeEl();
  const alerts = [];
  const calls = [];
  const listeners = [];          // StoreContext.onChange 的订阅者
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, Date, Number, String,
    Array, Object, RegExp, Error, Boolean,
    document: {
      getElementById: function (id) {
        if (id === 'store-switcher') return wrap;
        if (id === 'store-select') return sel;
        return null;
      },
    },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  // ⚠️ escapeHtml / escapeAttr 必须给**不同的实现**:
  //    生产里全局 escapeHtml 是 admin.js 的弱版本(只转义 & < >,不转义引号),
  //    escapeAttr 才是 js/helpers/utils.js 的强版本(引号也转义)。
  //    沙箱里若两者同源,「门店 ID 误用弱 escapeHtml」这条变异就抓不住 ——
  //    弱版不转义 '"' → value="a"b" → 属性被打断。
  sandbox.escapeHtml = function (s) {
    // 弱版本(与 admin.js:1082 一致):只转义 & < >
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  };
  sandbox.escapeAttr = function (s) {
    // 强版本(与 js/helpers/utils.js 一致):连引号一起转义
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  };
  sandbox.showAlert = function (msg, type) {
    alerts.push({ msg: String(msg), type: String(type) });
  };
  sandbox.loadAppData = function () { calls.push('loadAppData'); };

  let storeId = opts.storeId || 'main';
  sandbox.StoreContext = {
    getStoreId: function () { return storeId; },
    getStores: function () {
      return opts.stores || [
        { id: 'main', name: '总店' }, { id: 's002', name: '国贸店' },
      ];
    },
    getAllStores: function () { return !!opts.allStores; },
    onChange: function (cb) {
      listeners.push(cb);
      return function () {
        const i = listeners.indexOf(cb);
        if (i >= 0) listeners.splice(i, 1);
      };
    },
    switchTo: async function (id) {
      calls.push('switchTo:' + String(id));
      if (opts.switchFails) return false;
      storeId = String(id);
      return true;
    },
    // 真实 StoreContext.reset() 会清空 listeners —— 登出后必须重新订阅
    reset: function () { listeners.length = 0; },
  };

  vm.runInContext(
    fs.readFileSync(path.join(ROOT, 'js/modules/storeSwitcher.js'), 'utf8'),
    sandbox, { filename: 'storeSwitcher.js' },
  );
  return { sandbox, wrap, sel, alerts, calls, listeners };
}

function notify(sandbox, listeners, state, reason) {
  listeners.forEach(function (cb) { cb(state, reason); });
}

(async () => {
  const out = {};

  // ① 引导:订阅门店上下文 + 渲染下拉
  const a = makeSandbox({ allStores: true });
  a.sandbox.initStoreSwitcher();
  out.init = {
    listeners: a.listeners.length,
    changeHandlers: a.sel.handlerCount('change'),
    display: a.wrap.style.display,
    options: a.sel.innerHTML,
    value: a.sel.value,
  };

  // ② 切店:change → switchTo → 提示
  a.sel.value = 's002';
  a.sel.fire('change');
  await tick();
  out.switch = { calls: a.calls.slice(), alerts: a.alerts.slice() };

  // ③ 切店失败:必须提示(不能静默)
  const b = makeSandbox({ allStores: true, switchFails: true });
  b.sandbox.initStoreSwitcher();
  b.sel.value = 's002';
  b.sel.fire('change');
  await tick();
  out.switchFailed = { calls: b.calls.slice(), alerts: b.alerts.slice() };

  // ④ 门店上下文广播 'switch' → 必须重拉数据;广播 'no-store' → 必须提示
  const c = makeSandbox({ allStores: true });
  c.sandbox.initStoreSwitcher();
  notify(c.sandbox, c.listeners, { stores: [], allStores: true }, 'switch');
  notify(c.sandbox, c.listeners, { stores: [], allStores: true }, 'no-store');
  out.notify = { calls: c.calls.slice(), alerts: c.alerts.slice() };

  // ⑤ 登出(reset 清空订阅)→ 再登录必须重新订阅,且 DOM 事件不能重复绑
  const d = makeSandbox({ allStores: true });
  d.sandbox.initStoreSwitcher();
  d.sandbox.StoreContext.reset();          // 登出
  d.sandbox.initStoreSwitcher();            // 再登录
  out.resubscribe = {
    listeners: d.listeners.length,
    changeHandlers: d.sel.handlerCount('change'),
  };

  // ⑥ 可见性:单店用户不显示;总部账号即使只有 1 家店也要显示
  const e = makeSandbox({ stores: [{ id: 'main', name: '总店' }], allStores: false });
  e.sandbox.initStoreSwitcher();
  const e2 = makeSandbox({ stores: [{ id: 'main', name: '总店' }], allStores: true });
  e2.sandbox.initStoreSwitcher();
  out.visibility = {
    single: e.wrap.style.display,
    headquarters: e2.wrap.style.display,
    singleOptions: e.sel.innerHTML,
  };

  // ⑥b 先渲染出门店(总部账号),再变成不可见 → 下拉内容必须清空
  //    (隐藏时残留上一位用户的门店名 = 跨用户信息泄露)
  const e3 = makeSandbox({ allStores: true });
  e3.sandbox.initStoreSwitcher();
  const beforeHidden = e3.sel.innerHTML;
  e3.sandbox.renderStoreSwitcher({ stores: [{ id: 'main', name: '总店' }], allStores: false });
  out.hiddenClears = { before: beforeHidden, after: e3.sel.innerHTML };

  // ⑦ 自由文本必须转义:门店 ID 进属性值(escapeAttr)、门店名进元素内容(escapeHtml)
  const f = makeSandbox({
    allStores: true,
    stores: [{ id: 'a"b', name: '<b>A&B</b>' }, { id: 's002', name: '国贸店' }],
  });
  f.sandbox.initStoreSwitcher();
  out.escaping = { options: f.sel.innerHTML };

  console.log(JSON.stringify(out));
})();
"""


# ===== 真实 admin.js 的 setLoggedIn 行为沙箱 =====
#
# 把 admin.js 里 setLoggedIn 的函数源码抠出来单独跑(整个 admin.js 依赖太多 DOM,
# 整体灌进沙箱不现实)。要验的是**顺序**与**空态分支**:
# - 先 await 门店引导,再拉数据
# - 账号未分配门店 → 提示 + 不拉数据
# - 门店列表拿到了但没选出店 → 另一种提示 + 不拉数据
_ADMIN_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
const SRC = fs.readFileSync(path.join(ROOT, 'admin.js'), 'utf8');

// 花括号配平,抠出 setLoggedIn 的完整源码
function extractFunction(text, marker) {
  const i = text.indexOf(marker);
  if (i < 0) throw new Error('admin.js 里找不到 ' + marker);
  const start = text.indexOf('{', i);
  let depth = 0;
  for (let k = start; k < text.length; k++) {
    if (text[k] === '{') depth++;
    else if (text[k] === '}') {
      depth--;
      if (depth === 0) return text.slice(i, k + 1);
    }
  }
  throw new Error('setLoggedIn 花括号不配平');
}

const FN = extractFunction(SRC, 'async function setLoggedIn(');

function tick() {
  return new Promise(function (r) { setTimeout(r, 5); });
}

function makeSandbox(opts) {
  opts = opts || {};
  const alerts = [];
  const calls = [];
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, Date, Number, String,
    Array, Object, RegExp, Error, Boolean,
    document: { getElementById: function () { return { style: {} }; } },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  sandbox.ADMIN_USER = null;
  sandbox.applyRoleVisibility = function () {};
  sandbox.initStoreSwitcher = function () { calls.push('initStoreSwitcher'); };
  sandbox.showAlert = function (msg, type) {
    alerts.push({ msg: String(msg), type: String(type) });
  };
  // 记录拉数据那一刻的当前门店 —— 用来证明「先引导、后拉数据」
  sandbox.loadAppData = function () {
    calls.push('loadAppData:' + String(sandbox.StoreContext.getStoreId()));
  };

  // 引导完成前 getStoreId()/hasNoStore() 都返回空 —— 顺序反了就会露出来
  let ready = false;
  let storeId = '';
  sandbox.StoreContext = {
    init: async function () {
      await tick();
      storeId = opts.storeId || '';
      ready = true;
      return storeId;
    },
    getStoreId: function () { return ready ? storeId : ''; },
    hasNoStore: function () { return ready ? !!opts.noStore : false; },
  };

  vm.runInContext(FN, sandbox, { filename: 'setLoggedIn.js' });
  return { sandbox, alerts, calls };
}

(async () => {
  const out = {};

  // ① 正常:引导成功 → 拉数据,且拉数据时门店已经定下来了
  const a = makeSandbox({ storeId: 'main' });
  await a.sandbox.setLoggedIn({ role: 'admin' });
  out.ok = { calls: a.calls, alerts: a.alerts };

  // ② 账号未分配门店 → 提示「未分配门店」,且不拉数据
  const b = makeSandbox({ noStore: true });
  await b.sandbox.setLoggedIn({ role: 'employee' });
  out.noStore = { calls: b.calls, alerts: b.alerts };

  // ③ 门店列表拿到了但没选出店 → 另一种提示,同样不拉数据
  const c = makeSandbox({ storeId: '' });
  await c.sandbox.setLoggedIn({ role: 'employee' });
  out.emptyStore = { calls: c.calls, alerts: c.alerts };

  console.log(JSON.stringify(out));
})();
"""


# ===== 真实 storeContext.js:引导代次(登出后旧引导必须作废) =====
#
# 缺陷:reset() 清了 state / listeners,但没清在途的 init()。
# 引导期间点登出 → 在途引导回来后把**旧用户**的门店写回 state,
# 下一个登录继承上一个用户的门店(第一个数据请求带 ?store=<旧用户的店> → 403)。
#
# 修法:代次计数器 —— reset() 让代次 +1,在途引导发现自己不是最新代次就丢弃结果。
_GEN_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox(opts) {
  opts = opts || {};
  const map = {};
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, Date, Number, String,
    Array, Object, RegExp, Error, Boolean,
    localStorage: {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
      setItem: (k, v) => { map[k] = String(v); },
      removeItem: (k) => { delete map[k]; },
    },
    document: { getElementById: () => null },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  const apiCalls = { list: 0, current: 0 };
  sandbox.__apiCalls = apiCalls;
  const storesByToken = opts.storesByToken || {};
  sandbox.Api = {
    stores: {
      list: async () => {
        apiCalls.list++;
        // 请求发出那一刻的 token —— 之后换 token 不会改写已在途的请求
        const token = sandbox.localStorage.getItem('token') || '';
        if (opts.listDelay) await new Promise(function (r) { setTimeout(r, opts.listDelay); });
        const stores = storesByToken[token] || opts.stores || [{ id: 'main', name: '总店' }];
        return { ok: true, stores: stores, all_stores: true };
      },
      current: async () => {
        apiCalls.current++;
        const token = sandbox.localStorage.getItem('token') || '';
        if (opts.listDelay) await new Promise(function (r) { setTimeout(r, opts.listDelay); });
        const stores = storesByToken[token] || opts.stores || [{ id: 'main', name: '总店' }];
        return { ok: true, store_id: stores[0].id, all_stores: true };
      },
    },
  };

  vm.runInContext(
    fs.readFileSync(path.join(ROOT, 'js/core/storeContext.js'), 'utf8'),
    sandbox, { filename: 'storeContext.js' },
  );
  return sandbox;
}

(async () => {
  const out = {};
  const storesByToken = {
    userA: [{ id: 'main', name: '总店' }],
    userB: [{ id: 's002', name: '国贸店' }],
  };

  // ① 引导在途 → reset()(登出)→ 旧引导的结果必须丢弃
  const a = makeSandbox({ listDelay: 40, storesByToken: storesByToken });
  a.localStorage.setItem('token', 'userA');
  const reasonsA = [];
  a.StoreContext.onChange(function (_s, r) { reasonsA.push(r); });
  const p1 = a.StoreContext.init();     // userA 的引导在途
  a.StoreContext.reset();               // 登出
  await p1;
  out.stale = {
    storeId: a.StoreContext.getStoreId(),
    stores: a.StoreContext.getStores().length,
    ready: a.StoreContext.isReady(),
    reasons: reasonsA,
  };

  // ② 引导在途 → reset()(登出)→ 另一个用户登录 → 必须重新引导,
  //    且当前门店是新用户的店,不是旧用户的
  const b = makeSandbox({ listDelay: 40, storesByToken: storesByToken });
  b.localStorage.setItem('token', 'userA');
  const pb1 = b.StoreContext.init();    // userA 的引导在途
  b.StoreContext.reset();               // 登出
  b.localStorage.setItem('token', 'userB');
  const pb2 = b.StoreContext.init();    // userB 登录后的引导
  await Promise.all([pb1, pb2]);
  out.switchUser = {
    storeId: b.StoreContext.getStoreId(),
    stores: b.StoreContext.getStores().map(function (s) { return s.id; }),
    listCalls: b.__apiCalls.list,
  };

  // ③ 重入保护不能退化:并发 init() 只打一次后端
  const c = makeSandbox({ storesByToken: storesByToken });
  c.localStorage.setItem('token', 'userA');
  await Promise.all([c.StoreContext.init(), c.StoreContext.init()]);
  out.concurrent = { listCalls: c.__apiCalls.list, currentCalls: c.__apiCalls.current };

  console.log(JSON.stringify(out));
})();
"""


class TestStoreSwitcherWiring(unittest.TestCase):

    def test_index_has_store_switcher(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="store-switcher"', html)
        self.assertIn('id="store-select"', html)
        self.assertIn("js/core/storeContext.js", html)
        self.assertIn("js/modules/storeSwitcher.js", html)

    def test_store_switcher_js_is_wired(self) -> None:
        src = STORE_SWITCHER_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.onChange", src)
        self.assertIn("StoreContext.switchTo", src)
        self.assertIn("loadAppData", src)

    def test_admin_js_awaits_store_context_before_loading_data(self) -> None:
        """必须先引导门店上下文再拉数据 —— 否则第一个请求落到后端默认店。"""
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.init()", src)
        idx_init = src.find("StoreContext.init()")
        idx_load = src.find("loadAppData", idx_init)
        self.assertTrue(idx_init >= 0 and idx_load > idx_init,
                        "loadAppData 必须排在 StoreContext.init() 之后")

    def test_logout_resets_store_context(self) -> None:
        """登出要清门店上下文 —— 换人登录不该继承上一个人选的门店。"""
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.reset()", src)

    # ---------- 静态护栏 ----------

    def test_index_loads_scripts_in_dependency_order(self) -> None:
        """加载顺序:storeContext.js 在 api.js 之前,storeSwitcher.js 在 admin.js 之前。

        api.js 读 StoreContext.getStoreId() 拼 ?store=;
        admin.js 调 initStoreSwitcher() —— 顺序反了就静默失效。
        """
        html = INDEX_HTML.read_text(encoding="utf-8")
        idx_ctx = html.find("js/core/storeContext.js")
        idx_api = html.find("js/core/api.js")
        idx_switch = html.find("js/modules/storeSwitcher.js")
        idx_admin = html.find("admin.js?v=")
        self.assertTrue(idx_ctx >= 0 and idx_api >= 0, "缺少 storeContext.js / api.js")
        self.assertTrue(idx_switch >= 0 and idx_admin >= 0, "缺少 storeSwitcher.js / admin.js")
        self.assertLess(idx_ctx, idx_api, "storeContext.js 必须排在 api.js 之前")
        self.assertLess(idx_switch, idx_admin, "storeSwitcher.js 必须排在 admin.js 之前")

    def test_store_switcher_escapes_store_id_in_attribute(self) -> None:
        """门店 ID 进 value="..." 必须走 escapeAttr(全局 escapeHtml 被弱版本覆盖)。

        断言要**带参数**:只断言文件里出现过 "escapeAttr(" 的话,
        「ID 改用 escapeHtml、名字改用 escapeAttr」这条变异照样绿。
        """
        src = STORE_SWITCHER_JS.read_text(encoding="utf-8")
        self.assertRegex(src, r"escapeAttr\(\s*sid\s*\)",
                         "门店 ID 进属性值必须用 escapeAttr(sid)")
        self.assertRegex(src, r"escapeHtml\(\s*name\s*\)",
                         "门店名进元素内容必须用 escapeHtml(name)")
        self.assertNotIn("function escapeHtml", src, "不要在切换器里重定义 escapeHtml")

    def test_index_has_no_duplicate_initial_render(self) -> None:
        """index.html 里那段 DOMContentLoaded 的 renderAll() 必须删掉。

        它跑在 StoreContext.init() 之前(脚本求值期的 initAuth() 里那次
        Api.system.me() 是网络请求)→ 第一个数据请求不带 ?store= →
        多店用户每次刷新先看到默认店的数据;慢响应时那批数据还会留在页面上,
        而切换器显示的是另一家店。
        """
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertNotIn("DOMContentLoaded", html,
                         "index.html 里的 DOMContentLoaded 初始渲染必须删掉")
        self.assertNotIn("renderAll()", html,
                         "index.html 里不该再有独立的 renderAll() 调用")

    def test_admin_js_distinguishes_empty_store_states(self) -> None:
        """「当前店为空」有两种,提示文案必须不同,两种都不能去拉数据。"""
        src = ADMIN_JS.read_text(encoding="utf-8")
        self.assertIn("StoreContext.hasNoStore()", src,
                      "必须区分「账号未分配门店」与「门店列表没选出来」")
        self.assertIn("账号未分配门店", src)
        self.assertIn("加载门店列表失败", src)


class TestStoreSwitcherBehaviour(unittest.TestCase):
    """用真实的 js/modules/storeSwitcher.js 跑一遍(需要 node,缺失则跳过)。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, harness: str) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(harness, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def test_bootstrap_subscribes_and_renders(self) -> None:
        """引导后要订阅门店上下文,并把门店渲染进下拉。"""
        out = self._run(_SWITCHER_HARNESS)
        init = out["init"]
        self.assertEqual(init["listeners"], 1, "没有订阅 StoreContext 变化")
        self.assertEqual(init["changeHandlers"], 1, "change 事件没绑")
        self.assertEqual(init["display"], "block", "总部账号应显示切换器")
        self.assertIn("总店", init["options"])
        self.assertIn("国贸店", init["options"])

    def test_switching_store_switches_and_reloads(self) -> None:
        """切店 → switchTo → 提示。"""
        out = self._run(_SWITCHER_HARNESS)
        calls = out["switch"]["calls"]
        self.assertIn("switchTo:s002", calls, "change 事件没有调用 switchTo")
        alerts = out["switch"]["alerts"]
        self.assertTrue(alerts, "切店成功没有提示")
        self.assertIn("已切换到", alerts[-1]["msg"])

    def test_failed_switch_is_reported(self) -> None:
        """切店失败必须提示 —— 静默失败会让用户以为切成功了。"""
        out = self._run(_SWITCHER_HARNESS)
        alerts = out["switchFailed"]["alerts"]
        self.assertTrue(alerts, "切店失败没有提示")
        self.assertIn("切换门店失败", alerts[-1]["msg"])

    def test_store_context_change_reloads_data(self) -> None:
        """切店广播 'switch' → 必须重拉数据;'no-store' → 必须提示。"""
        out = self._run(_SWITCHER_HARNESS)
        self.assertIn("loadAppData", out["notify"]["calls"], "切店后没有重拉数据")
        alerts = out["notify"]["alerts"]
        self.assertTrue(alerts, "no-store 没有提示")
        self.assertIn("未分配门店", alerts[-1]["msg"])

    def test_resubscribe_after_logout(self) -> None:
        """登出(reset 清空订阅)→ 再登录必须重新订阅;DOM 事件不能重复绑。

        onChange 订阅若被塞进「DOM 只绑一次」的守卫里,这里就会是 0 个订阅者 ——
        切店不刷数据。
        """
        out = self._run(_SWITCHER_HARNESS)
        res = out["resubscribe"]
        self.assertEqual(res["listeners"], 1, "登出后再登录没有重新订阅门店上下文")
        self.assertEqual(res["changeHandlers"], 1, "change 事件被重复绑定了")

    def test_visibility_rules(self) -> None:
        """单店用户不显示切换器;总部账号即使只有 1 家店也显示。"""
        out = self._run(_SWITCHER_HARNESS)
        self.assertEqual(out["visibility"]["single"], "none", "单店用户不该显示切换器")
        self.assertEqual(out["visibility"]["headquarters"], "block", "总部账号应显示切换器")

    def test_store_text_is_escaped(self) -> None:
        """门店名是自由文本 → 元素内容转义;门店 ID 进属性值 → escapeAttr(强版本)。

        沙箱里 escapeHtml 是**弱版本**(不转义引号,与 admin.js 的弱实现一致),
        escapeAttr 是强版本 —— 所以「ID 误用 escapeHtml」这条变异会在这里露出来:
        弱版不转义 '"' → value="a"b" → 属性被打断。
        """
        out = self._run(_SWITCHER_HARNESS)
        options = out["escaping"]["options"]
        self.assertNotIn("<b>A&B</b>", options, "门店名没转义")
        self.assertIn("&lt;b&gt;A&amp;B&lt;/b&gt;", options)
        self.assertIn('value="a&quot;b"', options,
                      "门店 ID 进属性值没走 escapeAttr(引号没转义)")
        self.assertNotIn('value="a"b"', options,
                         "门店 ID 用了弱 escapeHtml —— 属性值被打断")

    def test_hidden_switcher_clears_options(self) -> None:
        """切换器隐藏时要把下拉内容清空 —— 残留的是上一位用户的门店名。"""
        out = self._run(_SWITCHER_HARNESS)
        self.assertTrue(out["hiddenClears"]["before"], "前置场景没渲染出门店")
        self.assertEqual(out["hiddenClears"]["after"], "",
                         "切换器隐藏后 <option> 内容没清空")
        self.assertEqual(out["visibility"]["singleOptions"], "",
                         "单店用户(切换器不可见)不该留下门店名")


class TestSetLoggedInOrder(unittest.TestCase):
    """用 admin.js 里真实的 setLoggedIn 跑一遍(需要 node,缺失则跳过)。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_ADMIN_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def test_data_loaded_after_store_context_ready(self) -> None:
        """先 await 门店引导,再拉数据 —— 拉数据那一刻门店必须已经定下来了。"""
        out = self._run()
        calls = out["ok"]["calls"]
        self.assertIn("loadAppData:main", calls,
                      "拉数据时门店还没定下来 —— 第一个请求会落到后端默认店")
        self.assertEqual(out["ok"]["alerts"], [], "正常路径不该弹提示")

    def test_account_without_store_does_not_load_data(self) -> None:
        """账号未分配门店 → 提示 + 不拉数据(拉了就是满屏 403)。"""
        out = self._run()
        res = out["noStore"]
        self.assertFalse([c for c in res["calls"] if c.startswith("loadAppData")],
                         "账号未分配门店时不该拉数据")
        self.assertTrue(res["alerts"], "账号未分配门店没有提示")
        self.assertIn("未分配门店", res["alerts"][-1]["msg"])

    def test_store_not_selected_does_not_load_data(self) -> None:
        """门店列表拿到了但没选出店 → 另一种提示 + 不拉数据。"""
        out = self._run()
        res = out["emptyStore"]
        self.assertFalse([c for c in res["calls"] if c.startswith("loadAppData")],
                         "当前店为空时不该拉数据")
        self.assertTrue(res["alerts"], "当前店为空没有提示")
        self.assertIn("加载门店列表失败", res["alerts"][-1]["msg"])


class TestStoreContextGeneration(unittest.TestCase):
    """真实 js/core/storeContext.js:登出后旧引导必须作废(需要 node)。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_GEN_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env["MS_ROOT"] = str(METERSTATS)
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def test_stale_bootstrap_is_discarded_after_reset(self) -> None:
        """引导在途时登出 → 旧引导的结果不许再写回 state。"""
        out = self._run()
        stale = out["stale"]
        self.assertEqual(stale["storeId"], "", "登出后旧引导把门店写回来了")
        self.assertEqual(stale["stores"], 0, "登出后旧引导把门店列表写回来了")
        self.assertFalse(stale["ready"], "登出后旧引导把引导状态写回来了")
        self.assertNotIn("init", stale["reasons"], "旧引导在登出后还广播了变更")

    def test_new_user_does_not_inherit_previous_users_store(self) -> None:
        """引导在途 → 登出 → 另一个账号登录 → 当前门店必须是新账号的店。"""
        out = self._run()
        res = out["switchUser"]
        self.assertEqual(res["storeId"], "s002", "新账号继承了上一个账号的门店")
        self.assertEqual(res["stores"], ["s002"], "门店列表还是上一个账号的")
        self.assertEqual(res["listCalls"], 2, "登出后的引导没有重新打后端(复用了陈旧 promise)")

    def test_concurrent_init_still_hits_backend_once(self) -> None:
        """代次计数器不许破坏重入保护 —— 并发 init() 仍然只打一次后端。"""
        out = self._run()
        self.assertEqual(out["concurrent"]["listCalls"], 1, "并发 init() 重复打了后端")
        self.assertEqual(out["concurrent"]["currentCalls"], 1, "并发 init() 重复打了后端")


if __name__ == "__main__":
    unittest.main()
