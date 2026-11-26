"""前端整包加载冒烟测试(需要 node;没有就跳过)。

这个测试解决一个 Python 静态断言永远覆盖不了的空白:**33 个脚本按
index.html 的顺序在同一作用域里执行,到底会不会炸。**

它会抓到这几类真实事故:
- **删了还在被用的函数**(删完 Python 那边的字面量断言照样绿,浏览器里是
  ReferenceError,而且往往在某个弹窗/某次点击时才炸);
- **顶层代码直接炸**(例如某个模块顶层就调 `Chart.defaults`、`matchMedia`,
  依赖尚未加载的对象 → 整个文件后续函数全部不定义,症状是"这页什么按钮都没反应");
- **加载顺序被改坏**(storeContext 必须在 api.js 之前、图表实例名的声明晚于使用等)。

做法:用 node 起一个最小 DOM 沙箱,按 index.html 里 `<script src>` 的**真实顺序**
逐个 `vm.runInContext`,收集异常;最后断言一批关键全局函数确实被定义了。

运行:
    python3 -m unittest tests.test_frontend_load -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"

_NODE_SCRIPT = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.METERSTATS_ROOT;  // 用 -e 传参时 argv 不可靠

function el(tag) {
  return {
    tagName: tag, style: {}, dataset: {}, children: [], value: '', textContent: '',
    innerHTML: '', checked: false, disabled: false,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { return c; }, remove() {}, cloneNode() { return el(tag); },
    addEventListener() {}, removeEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    focus() {}, select() {}, insertAdjacentHTML() {}, insertBefore(c) { return c; },
    getContext() { return {}; }, closest() { return null; }, contains() { return false; },
  };
}

const sandbox = {
  console, setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
  navigator: { clipboard: null, userAgent: 'node' },
  localStorage: { _d: {}, getItem(k){ return this._d[k] ?? null; }, setItem(k,v){ this._d[k]=String(v); },
                  removeItem(k){ delete this._d[k]; }, clear(){ this._d = {}; } },
  location: { href: 'http://127.0.0.1:1/', origin: 'http://127.0.0.1:1', pathname: '/', search: '' },
  document: {
    getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
    createElement: (t) => el(t), addEventListener: () => {}, removeEventListener: () => {},
    body: el('body'), documentElement: el('html'), head: el('head'),
    cookie: '', readyState: 'complete', execCommand: () => true,
  },
  fetch: () => Promise.resolve({ ok: true, status: 200,
                                 json: () => Promise.resolve({}), text: () => Promise.resolve('') }),
  alert: () => {}, confirm: () => true,
  btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  matchMedia: () => ({ matches: false, addEventListener(){}, removeEventListener(){},
                       addListener(){}, removeListener(){} }),
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true,
  // Chart 刻意留空:defer 加载的 CDN 脚本在首屏那一刻可能还没到,代码必须能扛住
  Chart: undefined,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  isNaN, parseInt, parseFloat,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
const ctx = vm.createContext(sandbox);

const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const srcs = [...html.matchAll(/<script\s+src="([^"]+)"/g)]
  .map((m) => m[1])
  .filter((s) => !/^https?:|^\/\//.test(s))
  .map((s) => s.split('?')[0]);

const failures = [];
for (const rel of srcs) {
  const file = path.join(ROOT, rel);
  if (!fs.existsSync(file)) { failures.push('missing ' + rel); continue; }
  try {
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: rel });
  } catch (e) {
    failures.push(rel + ': ' + e.name + ': ' + e.message);
  }
}

const need = ['showToast', 'showAlert', 'escapeHtml', 'escapeAttr', 'renderAll',
              'renderUsersTable', 'currentAuthToken', 'initAuth', 'copyTextWithFallback',
              'renderCharts', 'meterValue', 'rowHasMeterValues', 'loadMeterConfig',
              'renderTrendChart', 'calcMonthPie'];
const missing = need.filter((n) => typeof sandbox[n] !== 'function');

process.stdout.write(JSON.stringify({ scripts: srcs.length, failures, missing }));
"""


class TestFrontendBundleLoads(unittest.TestCase):
    """按 index.html 的真实顺序在 node 里跑一遍全部前端脚本。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")

    def test_all_scripts_load_without_error(self) -> None:
        if not self.node:
            self.skipTest("没有 node,跳过整包加载冒烟")
        env = dict(os.environ, METERSTATS_ROOT=str(METERSTATS))
        proc = subprocess.run(
            [self.node, "-e", _NODE_SCRIPT],
            capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertEqual(proc.returncode, 0, f"node 执行失败: {proc.stderr[:800]}")
        data = json.loads(proc.stdout)

        self.assertGreaterEqual(data["scripts"], 30, "index.html 引入的脚本数量异常")
        self.assertEqual(data["failures"], [],
                         "按 index.html 顺序加载时有脚本抛异常(通常是删了还在被用的函数,"
                         "或顶层代码依赖尚未加载的对象)")
        self.assertEqual(data["missing"], [], "这些关键全局函数没有被定义")


if __name__ == "__main__":
    unittest.main()
