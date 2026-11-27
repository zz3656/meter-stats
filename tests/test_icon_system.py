"""图标系统护栏(标准库 unittest,零依赖)。

**为什么**:2026-11-27 把常驻界面的 emoji 换成了内联 SVG sprite。emoji 在不同系统
渲染差异大、颜色不受主题控制(是"颜色太杂"的主要来源);而 SVG 图标跟随
currentColor,两套主题自动一致。

但换来一个新风险:图标名是字符串,**打错了不会报错,只会静默不显示**。
这条测试把三件事钉住:

1. 所有 `#i-NAME` 引用(HTML 里的 `<use>` 与 JS 里的 `icon('NAME')`)都能在 sprite 里找到
2. sprite 里没有"定义了但没人用"的图标(死图标 = 白带的维护负担)
3. 常驻界面(侧栏/标题/按钮/卡片头/状态栏)里不允许再出现 emoji

运行:
    python3 -m unittest tests.test_icon_system -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Set

REPO = Path(__file__).resolve().parent.parent
MS = REPO / "MeterStats"
INDEX = MS / "index.html"

EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
CHROME_HINT = re.compile(
    r'<button|<div class=|<span class=|<a |<h[1-4]|<option|<label|item-icon|<title')
USE_REF = re.compile(r'href="#i-([a-z0-9-]+)"')
CALL_REF = re.compile(r"""\bicon\((['"])([a-z0-9-]+)\1""")


def _sprite() -> Set[str]:
    html = INDEX.read_text(encoding="utf-8")
    return set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', html))


def _js_files() -> list[Path]:
    return sorted((MS / "js").rglob("*.js")) + [MS / "admin.js"]


def _indirect_refs() -> Set[str]:
    """间接引用:图标名先存进映射表、再以变量传给 icon() 的地方。

    目前只有 theme.js 的 `const ICONS = { dark: 'moon', light: 'sun', auto: 'monitor' }`
    —— 静态扫描抓不到 `icon(name)` 里的具体名字,所以直接读那张表。
    """
    src = (MS / "js" / "shared" / "theme.js").read_text(encoding="utf-8")
    m = re.search(r"const ICONS = \{([^}]*)\}", src)
    assert m, "theme.js 里的 ICONS 映射表找不到了(改结构要同步这条测试)"
    return set(re.findall(r"[\"']([a-z0-9-]+)[\"']", m.group(1)))


class TestIconReferences(unittest.TestCase):

    def test_all_use_refs_exist(self) -> None:
        sprite = _sprite()
        self.assertGreater(len(sprite), 20, "sprite 里图标太少,可能没解析到")
        missing = {n for n in USE_REF.findall(INDEX.read_text(encoding="utf-8")) if n not in sprite}
        for f in _js_files():
            for _, name in CALL_REF.findall(f.read_text(encoding="utf-8")):
                if name not in sprite:
                    missing.add(name)
        for name in _indirect_refs():        # 映射表里的名字同样必须存在
            if name not in sprite:
                missing.add(name)
        self.assertEqual(missing, set(),
                         f"这些图标名在 sprite 里不存在(打错字只会静默不显示): {sorted(missing)}")

    def test_no_unused_symbols(self) -> None:
        sprite = _sprite()
        html = INDEX.read_text(encoding="utf-8")
        used = set(USE_REF.findall(html))
        for f in _js_files():
            used |= {n for _, n in CALL_REF.findall(f.read_text(encoding="utf-8"))}
        used |= _indirect_refs()
        unused = sprite - used
        self.assertEqual(unused, set(), f"sprite 里定义了但没人用的图标: {sorted(unused)}")

    def test_icons_js_loaded_before_consumers(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        icons_at = html.find("js/shared/icons.js")
        self.assertGreater(icons_at, 0, "index.html 没有引入 js/shared/icons.js")
        for consumer in ("js/shared/theme.js", "js/shared/accessibility.js", "admin.js"):
            at = html.find(consumer)
            self.assertGreater(at, icons_at,
                               f"{consumer} 在 icons.js 之前加载,里面调用 icon() 会报 undefined")


class TestNoChromeEmoji(unittest.TestCase):

    def test_index_html_chrome_has_no_emoji(self) -> None:
        offenders = []
        for no, line in enumerate(INDEX.read_text(encoding="utf-8").split("\n"), 1):
            if EMOJI.search(line) and CHROME_HINT.search(line):
                offenders.append(f"index.html:{no}: {line.strip()[:90]}")
        self.assertEqual(offenders, [],
                         "常驻界面里还有 emoji(应该用 <svg class=\"icon\"><use href=\"#i-…\"/></svg>):\n"
                         + "\n".join(offenders))

    def test_js_rendered_headings_have_no_emoji(self) -> None:
        """JS 里拼出来的标题/按钮也不许带 emoji。"""
        pat = re.compile(r"<h[1-4][^>]*>[^'\"<]*" + EMOJI.pattern)
        offenders = []
        for f in _js_files():
            for no, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
                if pat.search(line):
                    offenders.append(f"{f.relative_to(MS)}:{no}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "JS 渲染的标题里还有 emoji:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
