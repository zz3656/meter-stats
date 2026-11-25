r"""门店切换前端行为验证(标准库 unittest,零依赖)。

用 node 的 vm 沙箱跑真实的 js/core/storeContext.js,验证:
- 切店后 State / 裸全局 / 离线缓存 / 报表缓存 / 充值归属缓存全被清空
- **在真实实现上验证**(真实 state.js + meterConfig.js 一起进沙箱),不只测替身
- 门店失效(被删 / 权限被收回)恢复时,旧店的数据同样要清干净
- 登出(reset)清干净缓存 —— 换人登录不能看到上一位用户的数据
- 门店 ID 校验与后端 \A[A-Za-z0-9_-]{1,32}\Z 等价(尾随换行必须被拒)
- 引导端点不带 store 参数(锁死链路),这条直接验真实 js/core/api.js

运行:
    python3 -m unittest tests.test_store_switch_frontend -v
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
STORE_CONTEXT_JS = METERSTATS / "js" / "core" / "storeContext.js"
API_JS = METERSTATS / "js" / "core" / "api.js"

# 替身沙箱:验证 StoreContext 自身的行为(调不调 State.reset()、带不带参数)。
# 真实实现的验证在 _PROD_HARNESS 里 —— 替身只能证明「替身被调用了」。
_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

const sandbox = {
  console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
  Promise, RegExp, Error, isNaN, parseInt, parseFloat,
  localStorage: (function () {
    const map = {};
    return {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
      setItem: (k, v) => { map[k] = String(v); },
      removeItem: (k) => { delete map[k]; },
      __dump: () => map,
    };
  })(),
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// ---- 替身:State / 裸全局 / 报表缓存 / 充值归属缓存 ----
const StateData = {
  readings: [{ date: '2026-01-01', hall: 1 }],
  charges: [{ id: 1 }],
  water: [{ date: '2026-01-01' }],
  items: [{ id: 1 }],
  purchases: [{ id: 1 }],
  duty: [{ id: 1 }],
};
sandbox.State = {
  get: (k) => StateData[k],
  set: (k, v) => { StateData[k] = v; },
  reset: () => { for (const k of Object.keys(StateData)) StateData[k] = []; },
};
sandbox.CURRENT_READINGS = [{ date: '2026-01-01', hall: 1 }];
sandbox.CURRENT_CHARGES = [{ id: 1 }];
sandbox.CURRENT_WATER_READINGS = [];
sandbox.CURRENT_ITEMS = [];
sandbox.CURRENT_PURCHASES = [];
sandbox.CURRENT_DUTY = [];
sandbox._currentReport = { month: '2026-01' };
sandbox._currentYearly = { year: 2026 };
sandbox._currentUtilities = { month: '2026-01' };
sandbox.__chargeAttrCache = { sig: 'x', map: [] };
sandbox.resetChargeAttrCache = function () { sandbox.__chargeAttrCache = null; };

// ---- 替身:Api(记录实参,用来证明引导请求没带门店参数) ----
const calls = [];
sandbox.__calls = calls;
sandbox.Api = {
  stores: {
    list: async (...args) => {
      calls.push({ path: '/api/stores', args: args.map((a) => String(a)) });
      return { ok: true, stores: [
        { id: 'main', name: '总店' }, { id: 's002', name: '国贸店' },
      ], all_stores: true };
    },
    current: async (...args) => {
      calls.push({ path: '/api/stores/current', args: args.map((a) => String(a)) });
      return { ok: true, store_id: 'main', all_stores: true };
    },
  },
};

vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/storeContext.js'), 'utf8'),
                sandbox, { filename: 'storeContext.js' });

(async () => {
  const out = {};
  await sandbox.StoreContext.init();
  out.storeIdAfterInit = sandbox.StoreContext.getStoreId();

  // 切店 → 缓存必须被清空
  const ok = await sandbox.StoreContext.switchTo('s002');
  out.switched = ok;
  out.storeIdAfterSwitch = sandbox.StoreContext.getStoreId();
  out.stateAfter = JSON.parse(JSON.stringify(StateData));
  out.globalsAfter = {
    readings: sandbox.CURRENT_READINGS.length,
    charges: sandbox.CURRENT_CHARGES.length,
    items: sandbox.CURRENT_ITEMS.length,
    purchases: sandbox.CURRENT_PURCHASES.length,
    duty: sandbox.CURRENT_DUTY.length,
  };
  out.chargeAttrCache = sandbox.__chargeAttrCache;
  out.offlineCache = {
    readings: sandbox.localStorage.getItem('meter_readings_v1'),
    charges: sandbox.localStorage.getItem('meter_charges_v1'),
  };

  // ID 校验:后端 \A..\Z 不接受尾随换行,JS 的 $ 会 —— 必须等价
  out.idValid = sandbox.StoreContext.isValidStoreId('s002');
  out.idNewline = sandbox.StoreContext.isValidStoreId('s002\n');
  out.idSlash = sandbox.StoreContext.isValidStoreId('../etc');
  out.idTooLong = sandbox.StoreContext.isValidStoreId('a'.repeat(33));
  // switchTo 的口径必须与 isValidStoreId 一致(不能先 trim 再判)
  out.switchNewline = await sandbox.StoreContext.switchTo('s002\n');

  // 引导请求不得带 store(由 api.js 负责,这里只验证 StoreContext 不自己塞)
  out.calls = calls.slice();
  console.log(JSON.stringify(out));
})();
"""


# 空态:账号没有可用门店。后端 routing.py::_store_gate 有两条不同的 403 文案 ——
# 「账号未分配门店」(一个店都没分到)与「账号未分配有效门店」(分到的店全被删了)。
# 两条都是空态,不是致命错误 —— 前端必须都认出来,置 noStore,而不是让用户看一屏空白。
_NO_STORE_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeSandbox(listImpl) {
  const sandbox = {
    console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
    Promise, RegExp, Error, isNaN, parseInt, parseFloat,
    localStorage: (function () {
      const map = {};
      return {
        getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
        setItem: (k, v) => { map[k] = String(v); },
        removeItem: (k) => { delete map[k]; },
      };
    })(),
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  sandbox.State = { reset: () => {} };
  sandbox.Api = {
    stores: {
      list: listImpl,
      current: async () => ({ ok: false, error: '账号未分配门店,请联系管理员' }),
    },
  };
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/storeContext.js'), 'utf8'),
                  sandbox, { filename: 'storeContext.js' });
  return sandbox;
}

async function probe(listImpl) {
  const sandbox = makeSandbox(listImpl);
  const reasons = [];
  sandbox.StoreContext.onChange((_state, reason) => { reasons.push(reason); });
  await sandbox.StoreContext.init();
  return {
    noStore: sandbox.StoreContext.hasNoStore(),
    storeId: sandbox.StoreContext.getStoreId(),
    ready: sandbox.StoreContext.isReady(),
    stores: sandbox.StoreContext.getStores().length,
    reasons: reasons,
  };
}

(async () => {
  const out = {};
  out.throwNoStore = await probe(async () => {
    throw new Error('账号未分配门店,请联系管理员');
  });
  out.throwNoValidStore = await probe(async () => {
    throw new Error('账号未分配有效门店,请联系管理员');
  });
  out.badEnvelope = await probe(async () => ({
    ok: false, error: '账号未分配门店,请联系管理员',
  }));
  console.log(JSON.stringify(out));
})();
"""


# 生产路径沙箱:把**真实**的 utils.js / meterConfig.js / state.js / storeContext.js
# 一起灌进同一个 vm,断言落在真实实现上。
#
# 为什么必须这样:替身只能证明「替身被调用了」,证明不了生产代码真的清了东西。
# 上轮就漏在这里 —— 报表缓存的断言一直走在 clearCaches() 的兜底分支上,
# 而 resetReportCaches() 在整个仓库里根本不存在。
#
# 注意:顶层 const State / let _chargeAttrCache 在 vm 里位于 global lexical scope,
# sandbox.State 是 undefined,只能靠 vm.runInContext 取值。
_PROD_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;

function makeStorage() {
  const map = {};
  return {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null),
    setItem: (k, v) => { map[k] = String(v); },
    removeItem: (k) => { delete map[k]; },
  };
}

function makeSandbox(opts) {
  opts = opts || {};
  const sandbox = {
    console, setTimeout, clearTimeout, JSON, Date, Number, String, Array, Object,
    Promise, RegExp, Error, isNaN, parseInt, parseFloat,
    localStorage: makeStorage(),
    document: { getElementById: () => null },
    window: null,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  // Api 替身(只给 storeContext 用):门店列表 + 后端默认店
  const stores = opts.stores || [
    { id: 'main', name: '总店' }, { id: 's002', name: '国贸店' },
  ];
  const apiCalls = { list: 0, current: 0 };
  sandbox.__apiCalls = apiCalls;
  sandbox.Api = {
    stores: {
      list: async () => { apiCalls.list++; return { ok: true, stores, all_stores: true }; },
      current: async () => {
        apiCalls.current++;
        if (opts.currentThrows) throw new Error('引导接口挂了');
        return { ok: true, store_id: opts.currentStoreId || 'main', all_stores: true };
      },
    },
  };

  // 真实加载顺序:utils.js → meterConfig.js → state.js → storeContext.js
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/helpers/utils.js'), 'utf8'),
                  sandbox, { filename: 'utils.js' });
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/meterConfig.js'), 'utf8'),
                  sandbox, { filename: 'meterConfig.js' });
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/state.js'), 'utf8'),
                  sandbox, { filename: 'state.js' });
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/core/storeContext.js'), 'utf8'),
                  sandbox, { filename: 'storeContext.js' });

  // 探针:证明清报表缓存走的是 state.js 导出的 resetReportCaches()(主路径),
  // 而不是 clearCaches() 里的兜底分支。
  vm.runInContext(`
    window.__reportCacheResetCalls = 0;
    var __origResetReportCaches = resetReportCaches;
    resetReportCaches = function () {
      window.__reportCacheResetCalls++;
      return __origResetReportCaches();
    };
  `, sandbox);
  return sandbox;
}

// 把「上一家店」的脏数据铺满 5 类缓存
function seedDirty(sandbox) {
  vm.runInContext(`
    State.set('readings', [{date:'2026-01-01', hall:1}]);
    State.set('charges', [{id:1}]);
    State.set('water', [{date:'2026-01-01'}]);
    State.set('items', [{id:1}]);
    State.set('purchases', [{id:1}]);
    State.set('duty', [{id:1}]);
    window.CURRENT_READINGS = [{date:'2026-01-01', hall:1}];
    window.CURRENT_CHARGES = [{id:1}];
    window.CURRENT_WATER_READINGS = [{date:'2026-01-01'}];
    window.CURRENT_ITEMS = [{id:1}];
    window.CURRENT_PURCHASES = [{id:1}];
    window.CURRENT_DUTY = [{id:1}];
    _currentReport = {month:'2026-01'};
    _currentYearly = {year:2026};
    _currentUtilities = {month:'2026-01'};
    _chargeAttrCache = {sig:'x', map:[]};
    localStorage.setItem('meter_readings_v1', JSON.stringify([{date:'2026-01-01'}]));
    localStorage.setItem('meter_charges_v1', JSON.stringify([{id:1}]));
  `, sandbox);
}

function probe(sandbox) {
  return JSON.parse(vm.runInContext(`JSON.stringify({
    readings: State.get('readings'),
    charges: State.get('charges'),
    water: State.get('water'),
    items: State.get('items'),
    purchases: State.get('purchases'),
    duty: State.get('duty'),
    currReadings: window.CURRENT_READINGS,
    currCharges: window.CURRENT_CHARGES,
    currWater: window.CURRENT_WATER_READINGS,
    currItems: window.CURRENT_ITEMS,
    currPurchases: window.CURRENT_PURCHASES,
    currDuty: window.CURRENT_DUTY,
    report: _currentReport,
    yearly: _currentYearly,
    utilities: _currentUtilities,
    chargeAttr: _chargeAttrCache,
    offlineReadings: localStorage.getItem('meter_readings_v1'),
    offlineCharges: localStorage.getItem('meter_charges_v1'),
    reportCacheResetCalls: window.__reportCacheResetCalls,
    storeId: StoreContext.getStoreId(),
    noStore: StoreContext.hasNoStore(),
    ready: StoreContext.isReady(),
  })`, sandbox));
}

function waitForReason(sandbox, reason, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('等待 ' + reason + ' 超时')), ms || 5000);
    sandbox.StoreContext.onChange((_state, r) => {
      if (r === reason) { clearTimeout(timer); resolve(true); }
    });
  });
}

(async () => {
  const out = {};

  // ① 切店
  const s1 = makeSandbox();
  seedDirty(s1);
  await s1.StoreContext.init();
  out.switch = {
    switched: await s1.StoreContext.switchTo('s002'),
    probe: probe(s1),
  };

  // ② 门店失效恢复(管理员删掉了当前店)
  const s2 = makeSandbox();
  seedDirty(s2);
  await s2.StoreContext.init();
  await s2.StoreContext.switchTo('s002');
  seedDirty(s2);                       // 恢复前页面上还挂着旧店的数据
  const recovered = waitForReason(s2, 'recovered');
  s2.StoreContext.handleStoreError(404, '门店不存在: s002');
  out.recover = { ok: await recovered, probe: probe(s2) };

  // ③ 登出(reset)
  const s3 = makeSandbox();
  seedDirty(s3);
  await s3.StoreContext.init();
  let notified = 0;
  s3.StoreContext.onChange(() => { notified++; });
  s3.StoreContext.reset();
  const afterReset = notified;
  const probeAfterReset = probe(s3);      // ← 登出后的状态(要在重新登录之前取)
  await s3.StoreContext.init();           // 重新登录 → UI 会重新订阅
  out.logout = {
    afterReset: afterReset,
    afterReInit: notified,
    probe: probeAfterReset,
  };

  // ④ 后端给的默认店不在可见列表里 → 不能选它(口径与「记住的店」一致)
  const s4 = makeSandbox({ stores: [{ id: 'main', name: '总店' }], currentStoreId: 's002' });
  await s4.StoreContext.init();
  out.unknownDefault = { storeId: s4.StoreContext.getStoreId() };

  // ⑤ 后端默认店拿不到(current() 失败)→ 兜底到可见列表第一家
  const s5 = makeSandbox({ currentThrows: true });
  await s5.StoreContext.init();
  out.currentFailed = { storeId: s5.StoreContext.getStoreId() };

  // ⑥ 并发 init() → 只打一次后端(重入保护)
  const s6 = makeSandbox();
  await Promise.all([s6.StoreContext.init(), s6.StoreContext.init()]);
  out.concurrentInit = { listCalls: s6.__apiCalls.list, currentCalls: s6.__apiCalls.current };

  console.log(JSON.stringify(out));
})();
"""


# 真实 api.js:引导端点必须不带 store 参数。
#
# 为什么这条必须锁死:管理员删掉当前门店后,前端还留着那个 ID →
# 列表请求带着它 → 后端 404 → 连门店列表都拿不到 → 无从切店 → 用户永久卡死。
#
# 沙箱里故意把当前门店设成一个真实门店 ID:只要 api.js 给引导请求拼上了
# store= 参数,这里就会露出来。
_API_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
// api.js 的路径可被 MS_API_JS 覆盖 —— 变异验证时用副本,绝不碰仓库里的真文件
const API_FILE = process.env.MS_API_JS || path.join(ROOT, 'js/core/api.js');

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
  document: { getElementById: () => null },
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
// 当前门店故意设成一个真实门店 ID —— Task 3 若把 store= 自动拼上去,这里就会露馅
sandbox.StoreContext = { getStoreId: () => 's002' };
sandbox.fetch = function (url, opts) {
  fetched.push({ url: String(url), method: (opts && opts.method) || 'GET' });
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ ok: true, store_id: 'main', all_stores: true, stores: [] }),
  });
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(API_FILE, 'utf8'),
                sandbox, { filename: 'api.js' });

function hasStoreParam(url) {
  const query = String(url).split('?')[1] || '';
  return query.split('&').some((kv) => kv.split('=')[0] === 'store');
}

(async () => {
  await sandbox.Api.stores.list();
  await sandbox.Api.stores.current();
  console.log(JSON.stringify({
    fetched: fetched.map((c) => ({ url: c.url, method: c.method, hasStore: hasStoreParam(c.url) })),
  }));
})();
"""


class TestStoreContextBehaviour(unittest.TestCase):
    """用真实的 js/core/storeContext.js 跑一遍(需要 node,缺失则跳过)。"""

    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("未安装 node,跳过前端行为验证")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self) -> dict[str, Any]:
        return self._run_harness(_HARNESS)

    def _run_harness(self, harness: str, env_extra: dict[str, str] | None = None) -> dict[str, Any]:
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(harness, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        # 先落到带注解的局部变量再返回 —— 直接 return json.loads(...) 在 strict 模式下
        # 会报 no-any-return(与 tests/test_stores_frontend.py 同一写法)。
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def _assert_caches_cleared(self, probe: dict[str, Any]) -> None:
        """5 类缓存必须全清 —— 漏一类就是一次跨店串数据。"""
        for key in ("readings", "charges", "water", "items", "purchases", "duty"):
            self.assertEqual(probe[key], [], "State.%s 没被清空" % key)
        for key in ("currReadings", "currCharges", "currWater",
                    "currItems", "currPurchases", "currDuty"):
            self.assertEqual(probe[key], [], "CURRENT_* 没被清空: %s" % key)
        self.assertIsNone(probe["report"], "报表缓存(_currentReport)没被清空")
        self.assertIsNone(probe["yearly"], "报表缓存(_currentYearly)没被清空")
        self.assertIsNone(probe["utilities"], "报表缓存(_currentUtilities)没被清空")
        self.assertIsNone(probe["chargeAttr"], "充值归属缓存没被清空")
        self.assertIsNone(probe["offlineReadings"], "离线缓存 meter_readings_v1 没被清空")
        self.assertIsNone(probe["offlineCharges"], "离线缓存 meter_charges_v1 没被清空")

    # ---------- 替身沙箱:StoreContext 自身的行为 ----------

    def test_switch_clears_all_store_scoped_caches(self) -> None:
        """切店后上一个店的数据必须全部清干净 —— 漏一个就是跨店显示。"""
        out = self._run()
        self.assertTrue(out["switched"])
        self.assertEqual(out["storeIdAfterSwitch"], "s002")
        for key, value in out["stateAfter"].items():
            self.assertEqual(value, [], "State.%s 没被清空" % key)
        for key, value in out["globalsAfter"].items():
            self.assertEqual(value, 0, "CURRENT_%s 没被清空" % key.upper())
        self.assertIsNone(out["chargeAttrCache"])
        self.assertIsNone(out["offlineCache"]["readings"])
        self.assertIsNone(out["offlineCache"]["charges"])

    def test_store_id_validation_matches_backend(self) -> None:
        """前端校验必须与后端 \\A[A-Za-z0-9_-]{1,32}\\Z 等价。"""
        out = self._run()
        self.assertTrue(out["idValid"])
        self.assertFalse(out["idNewline"], "尾随换行必须被拒(JS 的 $ 会放行)")
        self.assertFalse(out["idSlash"])
        self.assertFalse(out["idTooLong"])

    def test_switch_to_rejects_trailing_newline(self) -> None:
        """switchTo 的口径必须与 isValidStoreId 一致 —— 不能先 trim 再判。

        trim 完 's002\\n' 是合法的 's002',但 isValidStoreId('s002\\n') 是 false:
        两处口径不一致 → 同一个字符串在两处一个合法一个非法。
        """
        out = self._run()
        self.assertFalse(out["switchNewline"], "switchTo 放行了带尾随换行的门店 ID")

    def test_bootstrap_calls_do_not_carry_store(self) -> None:
        """引导请求不许带门店参数 —— 断言的是**实参**,不是替身 push 的常量。"""
        out = self._run()
        paths = [call["path"] for call in out["calls"]]
        self.assertIn("/api/stores", paths)
        self.assertIn("/api/stores/current", paths)
        for call in out["calls"]:
            self.assertEqual(
                call["args"], [],
                "%s 引导请求带了参数 %r" % (call["path"], call["args"]),
            )

    def test_no_store_account_enters_empty_state(self) -> None:
        """账号没有可用门店 → 置空态,不是致命错误。

        后端 routing.py::_store_gate 有两条不同的 403 文案:
        「账号未分配门店」(一个店都没分到)与「账号未分配有效门店」(分到的店全被删了)。
        两条都要认出来 —— 只认一条的话,另一种用户看到的是一屏空白。
        """
        out = self._run_harness(_NO_STORE_HARNESS)
        for case in ("throwNoStore", "throwNoValidStore", "badEnvelope"):
            with self.subTest(case=case):
                res = out[case]
                self.assertTrue(res["noStore"], "%s 没置 noStore 空态" % case)
                self.assertEqual(res["storeId"], "", "%s 不该留下当前门店" % case)
                self.assertTrue(res["ready"], "%s bootstrap 应当结束" % case)
                self.assertEqual(res["stores"], 0, "%s 不该有门店列表" % case)
                self.assertIn("no-store", res["reasons"], "%s 没广播 no-store" % case)

    # ---------- 生产路径沙箱:真实 state.js / meterConfig.js ----------

    def test_production_switch_clears_real_caches(self) -> None:
        """真实实现上验证 5 类缓存被清空 —— 替身证明不了生产代码清了东西。"""
        out = self._run_harness(_PROD_HARNESS)
        probe = out["switch"]["probe"]
        self.assertTrue(out["switch"]["switched"])
        self.assertEqual(probe["storeId"], "s002")
        self._assert_caches_cleared(probe)
        self.assertGreaterEqual(
            probe["reportCacheResetCalls"], 1,
            "报表缓存没走 state.js 导出的 resetReportCaches() 主路径",
        )

    def test_production_recovery_clears_real_caches(self) -> None:
        """门店失效恢复时也必须清干净 —— 否则恢复后显示的还是已删除门店的数据。"""
        out = self._run_harness(_PROD_HARNESS)
        probe = out["recover"]["probe"]
        self.assertTrue(out["recover"]["ok"], "恢复流程没有完成")
        self.assertEqual(probe["storeId"], "main", "恢复后应退回后端默认店")
        self._assert_caches_cleared(probe)

    def test_production_logout_clears_real_caches(self) -> None:
        """登出必须清干净 —— 换人登录不能看到上一位用户的数据。

        admin.js 的 clearAuth() 不刷新页面,内存与 localStorage 里的数据都还在;
        accessibility.js 在后端不可用时会回退去读 meter_readings_v1 / meter_charges_v1。
        """
        out = self._run_harness(_PROD_HARNESS)
        probe = out["logout"]["probe"]
        self._assert_caches_cleared(probe)
        self.assertEqual(probe["storeId"], "", "登出后不该留着当前门店")
        self.assertEqual(
            out["logout"]["afterReInit"], out["logout"]["afterReset"],
            "reset() 之后订阅者没被清掉 —— 重新登录会重复注册 onChange",
        )

    def test_backend_default_store_must_be_in_visible_list(self) -> None:
        """后端给的默认店不在可见列表里 → 不能选它(口径与「记住的店」一致)。"""
        out = self._run_harness(_PROD_HARNESS)
        self.assertEqual(
            out["unknownDefault"]["storeId"], "main",
            "选了一个不在可见列表里的门店",
        )

    def test_backend_default_store_falls_back_to_first_visible(self) -> None:
        """后端默认店拿不到(current() 失败)→ 兜底到可见列表第一家。

        不兜底的话 storeId 为空而 noStore=false → 第三种状态,UI 无从显示。
        """
        out = self._run_harness(_PROD_HARNESS)
        self.assertEqual(
            out["currentFailed"]["storeId"], "main",
            "后端默认店拿不到时没兜底到可见列表第一家",
        )

    def test_concurrent_init_only_hits_backend_once(self) -> None:
        """并发 init() 只打一次后端 —— 重入保护。"""
        out = self._run_harness(_PROD_HARNESS)
        self.assertEqual(
            out["concurrentInit"]["listCalls"], 1,
            "并发 init() 重复打了 /api/stores",
        )
        self.assertEqual(
            out["concurrentInit"]["currentCalls"], 1,
            "并发 init() 重复打了 /api/stores/current",
        )

    # ---------- 真实 api.js:引导端点不带 store ----------

    def test_real_api_bootstrap_endpoints_do_not_carry_store(self) -> None:
        """真实 api.js 里,引导端点不许带 store= 参数。

        这是给 Task 3 兜底的网:只要给 /api/stores、/api/stores/current 拼上
        store=,这条就会红(管理员删店后 → 404 → 连门店列表都拿不到 → 永久卡死)。
        """
        extra: dict[str, str] = {}
        override = os.environ.get("MS_API_JS")
        if override:
            extra["MS_API_JS"] = override
        out = self._run_harness(_API_HARNESS, extra or None)
        urls = [call["url"] for call in out["fetched"]]
        self.assertTrue(urls, "没有捕获到任何请求")
        self.assertTrue(any("/api/stores/current" in u for u in urls), "没打到 /api/stores/current")
        for call in out["fetched"]:
            self.assertFalse(
                call["hasStore"], "引导请求带了 store 参数: %s" % call["url"],
            )


if __name__ == "__main__":
    unittest.main()
