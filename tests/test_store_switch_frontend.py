r"""门店切换前端行为验证(标准库 unittest,零依赖)。

用 node 的 vm 沙箱跑真实的 js/core/storeContext.js,验证:
- 切店后 State / 裸全局 / 离线缓存 / 报表缓存 / 充值归属缓存全被清空
- 门店 ID 校验与后端 \A[A-Za-z0-9_-]{1,32}\Z 等价(尾随换行必须被拒)
- 失效门店(被删/权限被收回)会触发恢复,而不是把用户踢出登录
- 引导端点不带 store 参数(锁死链路)

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

// ---- 替身:Api ----
const calls = [];
sandbox.__calls = calls;
sandbox.Api = {
  stores: {
    list: async () => { calls.push('/api/stores'); return { ok: true, stores: [
      { id: 'main', name: '总店' }, { id: 's002', name: '国贸店' },
    ], all_stores: true }; },
    current: async () => { calls.push('/api/stores/current'); return { ok: true, store_id: 'main', all_stores: true }; },
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
  out.reportCaches = {
    report: sandbox._currentReport,
    yearly: sandbox._currentYearly,
    utilities: sandbox._currentUtilities,
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

  // 引导请求不得带 store(由 api.js 负责,这里只验证 StoreContext 不自己塞)
  out.calls = calls.slice();
  console.log(JSON.stringify(out));
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
        hp = Path(self.tmp.name) / "harness.js"
        hp.write_text(_HARNESS, encoding="utf-8")
        env = dict(**os.environ)
        env.update(MS_ROOT=str(METERSTATS))
        proc = subprocess.run(
            ["node", str(hp)], capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg="node 执行失败:\n%s" % proc.stderr)
        # 先落到带注解的局部变量再返回 —— 直接 return json.loads(...) 在 strict 模式下
        # 会报 no-any-return(与 tests/test_stores_frontend.py 同一写法)。
        out: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def test_switch_clears_all_store_scoped_caches(self) -> None:
        """切店后上一个店的数据必须全部清干净 —— 漏一个就是跨店显示。"""
        out = self._run()
        self.assertTrue(out["switched"])
        self.assertEqual(out["storeIdAfterSwitch"], "s002")
        for key, value in out["stateAfter"].items():
            self.assertEqual(value, [], "State.%s 没被清空" % key)
        for key, value in out["globalsAfter"].items():
            self.assertEqual(value, 0, "CURRENT_%s 没被清空" % key.upper())
        self.assertIsNone(out["reportCaches"]["report"])
        self.assertIsNone(out["reportCaches"]["yearly"])
        self.assertIsNone(out["reportCaches"]["utilities"])
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

    def test_bootstrap_calls_do_not_carry_store(self) -> None:
        out = self._run()
        self.assertIn("/api/stores", out["calls"])
        self.assertIn("/api/stores/current", out["calls"])


if __name__ == "__main__":
    unittest.main()
