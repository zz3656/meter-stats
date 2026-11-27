"""空态与加载态测试(标准库 unittest,零依赖)。

**背景**(2026-11-27):此前空态就是一行灰字(「还没有物品」「暂无抄表记录」),加载时
**什么提示都没有** —— 用户看着空白表格,既分不清"是空的"还是"没加载出来",也不知道下一步
该做什么。现在:
  - 空态 = 图标 + 一句说明 + 一句「下一步做什么」
  - 加载态 = 骨架行占位(不是居中转圈),数据到达后原地替换,布局不跳
  - 骨架呼吸动画在 `prefers-reduced-motion` 下关闭

这条测试守:
1. `emptyStateHtml` / `emptyRowHtml` / `skeletonRowsHtml` 的契约(转义、colspan、行列数)
2. 渲染函数里**不许再出现裸的空态句子**(必须走 emptyStateHtml/emptyRowHtml)
3. 首屏骨架确实挂在 renderAll 上,并且有兜底清理(否则会一直停在骨架上)
4. CSS 里空态/骨架样式存在,且骨架动画尊重 reduced-motion

运行:
    python3 -m unittest tests.test_states -v
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MS = REPO / "MeterStats"
STATES_JS = MS / "js" / "shared" / "states.js"
READINGS_JS = MS / "js" / "modules" / "readings.js"
STYLE_CSS = MS / "style.css"
INDEX = MS / "index.html"

_NODE = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
const sandbox = { console, JSON, Object, Array, String, Number, Math,
  // 假 sprite:让 icons.js 的 known() 认得出这几个名字(真实页面里来自 index.html)
  document: { readyState: 'complete', addEventListener: () => {},
              querySelectorAll: (sel) => (String(sel).indexOf('symbol') >= 0
                ? ['package', 'clipboard', 'notebook', 'droplet', 'coins', 'cart',
                   'zap', 'chart-bar'].map(n => ({ id: 'i-' + n, getAttribute: () => null,
                                                   removeAttribute: () => {} }))
                : []),
              querySelector: () => null, getElementById: () => null } };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/shared/icons.js'), 'utf8'), sandbox, { filename: 'icons.js' });
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/shared/states.js'), 'utf8'), sandbox, { filename: 'states.js' });
process.stdout.write(JSON.stringify({
  empty: sandbox.emptyStateHtml({ icon: 'package', title: '还没有物品记录', hint: '在上方表单登记工具' }),
  withAction: sandbox.emptyStateHtml({ title: '空', action: { label: '去添加', onclick: 'openModal()' } }),
  escaped: sandbox.emptyStateHtml({ title: '<img src=x onerror=alert(1)>', hint: '"><script>' }),
  row: sandbox.emptyRowHtml(7, { title: '空' }),
  skel: sandbox.skeletonRowsHtml(3, 5),
  skelDefault: sandbox.skeletonRowsHtml(0, 0),
}));
"""


class TestStateHelpers(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        proc = subprocess.run(["node", "-e", _NODE], capture_output=True, text=True,
                              env=dict(os.environ, MS_ROOT=str(MS)), timeout=60)
        assert proc.returncode == 0, "node 执行失败:\n%s" % proc.stderr
        cls.out = json.loads(proc.stdout)

    def test_empty_state_structure(self) -> None:
        html = self.out["empty"]
        self.assertIn("empty-state", html)
        self.assertIn("empty-title", html)
        self.assertIn("empty-hint", html)
        self.assertIn("还没有物品记录", html)
        self.assertIn("<svg", html, "空态缺少图标(emptyStateHtml 应调用 icon())")

    def test_empty_state_escapes_free_text(self) -> None:
        html = self.out["escaped"]
        self.assertNotIn("<img", html, "标题里的 HTML 被当成标签了")
        self.assertNotIn("<script", html, "提示里的 HTML 被当成标签了")
        self.assertIn("&lt;img", html)

    def test_empty_state_optional_action(self) -> None:
        html = self.out["withAction"]
        self.assertIn("empty-action", html)
        self.assertIn("去添加", html)
        self.assertNotIn("empty-action", self.out["empty"], "没传 action 却渲染了按钮")

    def test_empty_row_has_colspan(self) -> None:
        self.assertIn('colspan="7"', self.out["row"])
        self.assertIn("empty-state", self.out["row"])

    def test_skeleton_shape(self) -> None:
        skel = self.out["skel"]
        self.assertEqual(skel.count("<tr"), 3, "骨架行数不对")
        self.assertEqual(skel.count('class="skeleton"'), 15, "3×5 应有 15 个占位块")
        # 传 0 也要给出可用的最小骨架,不能渲染空串
        self.assertGreater(self.out["skelDefault"].count("<tr"), 0)


class TestRenderersUseHelper(unittest.TestCase):
    """渲染函数里不许再写裸的空态句子。"""

    BARE = re.compile(r"""(textContent\s*=\s*['"][^'"]*(暂无|还没有))""")

    def test_no_bare_empty_text_in_renderers(self) -> None:
        offenders = []
        for f in sorted((MS / "js").rglob("*.js")) + [MS / "admin.js"]:
            for no, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
                if self.BARE.search(line):
                    offenders.append(f"{f.relative_to(MS)}:{no}: {line.strip()[:90]}")
        self.assertEqual(offenders, [],
                         "这些地方还在用裸文本当空态(应改用 emptyStateHtml/emptyRowHtml):\n"
                         + "\n".join(offenders))

    def test_main_tables_use_row_helper(self) -> None:
        for rel in ("js/modules/items.js", "js/modules/purchases.js"):
            src = (MS / rel).read_text(encoding="utf-8")
            self.assertIn("emptyRowHtml(", src, f"{rel} 的空态没走 emptyRowHtml")


class TestSkeletonWiring(unittest.TestCase):

    def test_render_all_shows_and_clears(self) -> None:
        src = READINGS_JS.read_text(encoding="utf-8")
        self.assertIn("showBootSkeletons()", src, "renderAll 没铺骨架")
        self.assertIn("clearSkeletons()", src, "缺少兜底清理 —— 没被覆盖的骨架会一直停在页面上")
        # 铺骨架必须在第一次 await 之前
        show_at = src.index("showBootSkeletons()")
        first_await = src.index("await Api.reports.snapshot")
        self.assertLess(show_at, first_await, "骨架要铺在发起请求之前,否则等于没有加载态")

    def test_states_js_loaded_before_consumers(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        at = html.find("js/shared/states.js")
        self.assertGreater(at, 0, "index.html 没引入 states.js")
        for consumer in ("js/modules/readings.js", "js/modules/items.js", "js/modules/alerts.js"):
            self.assertGreater(html.find(consumer), at, f"{consumer} 在 states.js 之前加载")

    def test_css_has_states_and_respects_reduced_motion(self) -> None:
        css = STYLE_CSS.read_text(encoding="utf-8")
        for cls in (".empty-state", ".empty-title", ".empty-hint", ".skeleton", ".skeleton-row"):
            self.assertIn(cls, css, f"CSS 缺少 {cls}")
        blocks = re.findall(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
        self.assertTrue(blocks, "缺少 prefers-reduced-motion 兜底")
        covered = any(
            ".skeleton" in b
            or ("*" in b and "animation-duration" in b)   # 全局 * 规则同样能让骨架停下
            for b in blocks)
        self.assertTrue(covered, "骨架动画没有在 reduced-motion 下关闭")


if __name__ == "__main__":
    unittest.main()
