"""配色对比度护栏(标准库 unittest,零依赖)。

**为什么**:2026-11-27 用户反馈「看久了视觉疲劳」。实测现有 token:
  - 暗色主文字 #e8eaf0 on #0d0f14 = **15.94:1**(过曝,暗光下刺眼)
  - 暗色辅助文字 #6b7280 = **3.96:1**(卡片上 3.49:1)**低于 WCAG AA 的 4.5**
  - 暗色最弱文字 #4a5058 = **2.35:1**(基本等于隐形)
  - 亮色最弱文字 #a6adb8 = **3.87:1**
整套现已按「安静化」重调,这条测试把它钉住,防止以后又因为"好看"把对比拉回去。

判据(见 PRODUCT.md 设计原则 1):
  - 主文字 11–14:1 —— 够清楚,又不至于刺眼
  - 次要/辅助/最弱文字 ≥4.5:1(在 bg 与卡片两种底上都要过)
  - 主色块上的白字 ≥4.5:1

运行:
    python3 -m unittest tests.test_contrast -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Dict

REPO = Path(__file__).resolve().parent.parent
CSS = REPO / "MeterStats" / "style.css"


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _declared(css: str, selector: str) -> Dict[str, str]:
    """某个选择器块里声明的全部 token(原样值)。"""
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\s*\}", css, re.S)
    assert m, f"CSS 里找不到 {selector} 块"
    return {n: v.strip() for n, v in re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", m.group(1))}


def _block(css: str, selector: str) -> Dict[str, str]:
    """只保留 #rrggbb 的 token(算对比度用;rgba 无法直接算)。"""
    return {n: v for n, v in _declared(css, selector).items()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", v)}


class TestThemeContrast(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        css = CSS.read_text(encoding="utf-8")
        cls.all_light = _declared(css, ":root")
        cls.all_dark = _declared(css, '[data-theme="dark"]')
        cls.light = _block(css, ":root")
        cls.dark = _block(css, '[data-theme="dark"]')

    def _check(self, tokens: Dict[str, str], theme: str) -> None:
        bg, card = tokens["--bg"], tokens["--bg-elevated"]

        main = contrast(tokens["--text"], bg)
        self.assertGreaterEqual(main, 11.0,
                                f"[{theme}] 主文字对比 {main:.2f}:1 偏低,长文阅读吃力")
        self.assertLessEqual(main, 14.5,
                             f"[{theme}] 主文字对比 {main:.2f}:1 过高(旧值 15.94 就是"
                             "「截图好看、长看刺眼」);暗底上不要用近纯白")

        for token in ("--text-secondary", "--text-muted", "--text-faint"):
            for name, surface in (("bg", bg), ("card", card)):
                r = contrast(tokens[token], surface)
                self.assertGreaterEqual(
                    r, 4.5, f"[{theme}] {token} 在 {name} 上只有 {r:.2f}:1(<4.5,WCAG AA 不过)")

        white_on_cta = contrast("#ffffff", tokens["--primary-bg"])
        self.assertGreaterEqual(white_on_cta, 4.5,
                                f"[{theme}] 主色块上的白字只有 {white_on_cta:.2f}:1")

        accent = contrast(tokens["--primary"], bg)
        self.assertGreaterEqual(accent, 4.5,
                                f"[{theme}] 主色作文字色在 bg 上只有 {accent:.2f}:1")

    def test_dark_theme(self) -> None:
        self._check(self.dark, "暗色")

    def test_light_theme(self) -> None:
        self._check(self.light, "亮色")

    def test_both_themes_define_same_core_tokens(self) -> None:
        """两套主题必须覆盖同一组核心 token,否则切换主题会掉回亮色默认值。"""
        core = {"--bg", "--bg-elevated", "--text", "--text-secondary", "--text-muted",
                "--text-faint", "--primary", "--primary-bg", "--border"}
        self.assertEqual(core - set(self.all_light), set(), "亮色缺少核心 token")
        self.assertEqual(core - set(self.all_dark), set(), "暗色缺少核心 token")


class TestReducedMotion(unittest.TestCase):

    def test_respects_prefers_reduced_motion(self) -> None:
        """有动效就必须尊重系统「减少动态效果」设置。"""
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", css,
                      "style.css 有 transition/animation,但没有 prefers-reduced-motion 兜底")


class TestNoRawBrandColors(unittest.TestCase):
    """组件规则里不许再出现品牌色的裸值 —— 必须走 token。

    **背景**:2026-11-27 清出过"第三套紫" —— 12 处 `rgba(113,112,255,α)`(#7170ff),
    既不是 --primary(#6366f1 / #8b93f3)也不是 --primary-bg —— 这正是"颜色太杂"的实物证据。
    裸值还有两个问题:①暗色主题下不会跟着变(它写死了亮色紫);
    ②改主色时漏改,同一个界面出现三种紫。
    """

    # 品牌色的裸值形态(hex 与旧 rgba 写法)
    BANNED = [
        r"#6366f1\b", r"#818cf8\b", r"#7170ff\b", r"#5b5fd6\b",
        r"rgba\(\s*113\s*,\s*112\s*,\s*255",   # 已废弃的第三套紫
    ]

    def _component_css(self) -> str:
        """去掉两处 token 定义块后的 CSS(那里允许出现裸值)。"""
        css = CSS.read_text(encoding="utf-8")
        out, i = [], 0
        for selector in (":root", '[data-theme="dark"]'):
            m = re.search(re.escape(selector) + r"\s*\{", css[i:])
            if not m:
                continue
            start = i + m.start()
            depth, j = 0, i + m.end() - 1
            while j < len(css):
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(css[i:start])
            i = j + 1
        out.append(css[i:])
        return "".join(out)

    def test_no_raw_brand_colors(self) -> None:
        body = self._component_css()
        offenders = []
        for pattern in self.BANNED:
            for m in re.finditer(pattern, body):
                line = body[:m.start()].count("\n") + 1
                offenders.append(f"第 {line} 行附近: {m.group(0)}")
        self.assertEqual(offenders, [],
                         "组件规则里还有品牌色裸值,请改用 var(--primary)/var(--tint-*):\n"
                         + "\n".join(offenders[:10]))

    def test_brand_colors_are_tokenized_in_both_themes(self) -> None:
        """两个主题都必须定义 --primary / --primary-bg / --tint-* ,组件才能安全引用。"""
        css = CSS.read_text(encoding="utf-8")
        for selector in (":root", '[data-theme="dark"]'):
            declared = _declared(css, selector)
            for token in ("--primary", "--primary-bg", "--tint-3", "--tint-border", "--info", "--info-soft"):
                self.assertIn(token, declared, f"{selector} 缺少 {token}")


if __name__ == "__main__":
    unittest.main()
