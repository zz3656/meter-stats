"""表计图标库测试(标准库 unittest,零依赖)。

**背景**(2026-11-27):表计图标原来是一个自由文本输入框,用户在里面敲 emoji(🎤🧯🛋️❄️)。
问题有四个:①emoji 跨系统渲染不一致;②自带颜色、不受主题控制;③手输容易输错;
④canvas 图表图例里只能当文字显示,和 DOM 里的图标完全不是一回事。

改成「从固定图标库里选」,并且**不做数据迁移** —— `store.json` 里旧的 emoji 靠
`LEGACY_EMOJI_ICON` 映射照旧渲染,用户下次进设置页选一次就换成图标名。

这条测试守:
1. 图标库 / 兼容映射里的每个名字,在 index.html 的 sprite 里都存在
2. 设置页不再有「图标」文本输入框(否则用户又能敲进任意 emoji)
3. canvas 与纯文本渲染处不再拼图标(canvas 画不了 SVG,会退化成字面量)
4. 后端对 icon 字段仍然按字符串透传(不因这次改动把值吃掉)

运行:
    python3 -m unittest tests.test_meter_icons -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MS = REPO / "MeterStats"
sys.path.insert(0, str(MS))

INDEX = MS / "index.html"
ICONS_JS = MS / "js" / "shared" / "icons.js"
METER_FORM = MS / "js" / "core" / "meterForm.js"
CHARTS = MS / "js" / "modules" / "render_charts.js"
WEEKLY = MS / "js" / "modules" / "render_weekly.js"


def _sprite() -> set:
    return set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', INDEX.read_text(encoding="utf-8")))


def _lib_names() -> list:
    src = ICONS_JS.read_text(encoding="utf-8")
    block = re.search(r"var METER_ICON_LIB = \[(.*?)\];", src, re.S)
    assert block, "icons.js 里找不到 METER_ICON_LIB"
    return re.findall(r"name:\s*'([a-z0-9-]+)'", block.group(1))


def _legacy_targets() -> list:
    src = ICONS_JS.read_text(encoding="utf-8")
    block = re.search(r"var LEGACY_EMOJI_ICON = \{(.*?)\};", src, re.S)
    assert block, "icons.js 里找不到 LEGACY_EMOJI_ICON"
    return re.findall(r":\s*'([a-z0-9-]+)'", block.group(1))


class TestMeterIconLibrary(unittest.TestCase):

    def test_library_is_usable(self) -> None:
        names = _lib_names()
        self.assertGreaterEqual(len(names), 12, f"图标库太小({len(names)} 个),不够用")
        self.assertEqual(len(names), len(set(names)), "图标库里有重名")

    def test_every_library_name_has_a_symbol(self) -> None:
        sprite = _sprite()
        missing = [n for n in _lib_names() if n not in sprite]
        self.assertEqual(missing, [], f"图标库里的名字在 sprite 里不存在: {missing}")

    def test_legacy_emoji_map_targets_exist(self) -> None:
        sprite = _sprite()
        missing = sorted({n for n in _legacy_targets() if n not in sprite})
        self.assertEqual(missing, [], f"旧 emoji 映射指向了不存在的图标: {missing}")

    def test_legacy_map_covers_ship_defaults(self) -> None:
        """出厂默认的 4 块表图标必须在兼容映射里 —— 老安装升级后不能变成空白。"""
        src = ICONS_JS.read_text(encoding="utf-8")
        for emoji in ("🎤", "🧯", "🛋", "❄"):
            self.assertIn(emoji, src, f"兼容映射里缺 {emoji}")


class TestFormUsesPicker(unittest.TestCase):

    def test_no_free_text_icon_input(self) -> None:
        src = METER_FORM.read_text(encoding="utf-8")
        self.assertNotRegex(
            src, r'data-field="icon"',
            "设置页里又出现 data-field=\"icon\" 的文本输入框 —— 图标应改由选择器提供")
        self.assertIn("meterIconPickerHtml", src, "设置页没有渲染图标选择器")
        self.assertIn("data-icon-value", src, "读回逻辑没读选择器的选中值")

    def test_readback_reads_picker(self) -> None:
        src = METER_FORM.read_text(encoding="utf-8")
        self.assertIn(".meter-icon-choice.active", src,
                      "readSettings 没从选中项读图标,保存会把图标清空")


class TestCanvasAndTextHaveNoIcon(unittest.TestCase):

    def test_charts_legend_has_no_icon(self) -> None:
        src = CHARTS.read_text(encoding="utf-8")
        self.assertNotIn("${m.icon}", src,
                         "canvas 图例还在拼图标 —— canvas 画不了 SVG,会退化成字面量")

    def test_weekly_plain_text_has_no_icon(self) -> None:
        src = WEEKLY.read_text(encoding="utf-8")
        bad = [ln.strip() for ln in src.split("\n")
               if "METER_META(" in ln and ".icon}" in ln]
        self.assertEqual(bad, [], "纯文本(复制到剪贴板)的行里还在拼图标:\n" + "\n".join(bad))


class TestBackendKeepsIconString(unittest.TestCase):

    def test_normalize_keeps_icon_value(self) -> None:
        from modules.stores.meters import normalize_tables

        out = normalize_tables([{"key": "m1", "label": "大厅", "icon": "mic", "multiplier": 1}])
        self.assertEqual(out[0]["icon"], "mic", "后端把图标名吃掉了")

    def test_normalize_keeps_legacy_emoji(self) -> None:
        from modules.stores.meters import normalize_tables

        out = normalize_tables([{"key": "m1", "label": "大厅", "icon": "🎤", "multiplier": 1}])
        self.assertEqual(out[0]["icon"], "🎤", "后端把旧 emoji 吃掉了(老数据会变空白)")

    def test_non_string_icon_falls_back_to_empty(self) -> None:
        from modules.stores.meters import normalize_tables

        out = normalize_tables([{"key": "m1", "label": "大厅", "icon": {"x": 1}, "multiplier": 1}])
        self.assertEqual(out[0]["icon"], "", "非字符串图标值应归一成空串(前端会退回纯文字)")


_ICONS_JS_HARNESS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = process.env.MS_ROOT;
const sandbox = {
  console, JSON, Object, Array, String, Number, Math,
  // 最小 DOM:没有 sprite(known() 为空)→ 未知值必须走"转义后的纯文本"分支
  document: {
    readyState: 'complete',
    querySelectorAll: () => [],
    addEventListener: () => {},
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'js/shared/icons.js'), 'utf8'),
                sandbox, { filename: 'icons.js' });
const out = {
  known:  sandbox.meterIconHtml('mic'),
  legacy: sandbox.meterIconHtml('\u{1F3A4}'),
  danger: sandbox.meterIconHtml('<img src=x onerror=alert(1)>'),
  empty:  sandbox.meterIconHtml(''),
  picker: sandbox.meterIconPickerHtml('mic'),
};
process.stdout.write(JSON.stringify(out));
"""


class TestMeterIconHelperContract(unittest.TestCase):
    """直接跑真实的 icons.js —— 三种输入(图标名 / 旧 emoji / 恶意串)的行为都要对。"""

    @classmethod
    def setUpClass(cls) -> None:
        import json
        import os
        import subprocess

        env = dict(os.environ, MS_ROOT=str(MS))
        proc = subprocess.run(["node", "-e", _ICONS_JS_HARNESS],
                              capture_output=True, text=True, env=env, timeout=60)
        assert proc.returncode == 0, "node 执行失败:\n%s" % proc.stderr
        cls.out = json.loads(proc.stdout)

    def test_unknown_values_are_escaped_text(self) -> None:
        # 沙箱里没有 sprite → 所有值都解析不出图标名,必须转义成纯文本
        self.assertIn("&lt;img", self.out["danger"], "恶意串没被转义,会被当成标签")
        self.assertNotIn("<img", self.out["danger"], "裸 <img> 出现在输出里")
        self.assertIn("meter-icon-text", self.out["danger"], "未知值应走纯文本兜底")
        self.assertIn("meter-icon-text", self.out["known"], "图标名在无 sprite 时也该安全兜底")

    def test_empty_icon_renders_nothing(self) -> None:
        self.assertEqual(self.out["empty"], "", "空图标不该渲染任何东西")

    def test_picker_lists_library(self) -> None:
        html = self.out["picker"]
        self.assertIn("meter-icon-picker", html)
        self.assertGreaterEqual(html.count("data-icon-value="), 12, "选择器里的图标太少")


if __name__ == "__main__":
    unittest.main()
