"""前端「同名全局 / 转义 / 口径」静态护栏(标准库 unittest,零依赖)。

前端没有构建步骤,`index.html` 用 30 多个 `<script>` 按顺序把全局符号糊在一起。
这套护栏锁死三类**已经发生过**的事故:

1. **同名全局静默覆盖**(本文件的主力)
   `escapeHtml` 曾经有两份:utils.js 的强版(连引号一起转义)与 admin.js 的弱版
   (只转义 `& < >`),而 admin.js 后加载 → 运行时生效的是弱版,自由文本进属性值
   就能把属性打断。这一轮又清出 4 对同名副本,而且**每一对内容都不同**:
   `submitUtilityAdd` / `refreshDayCopySelect` / `checkDutyReminder` / `calcDayUsage`
   —— 谁生效只取决于 `<script>` 顺序,改被覆盖的那份等于什么都没做。
   逐条人工比对是防不住的,所以直接扫源码:同名全局函数/函数表达式不得跨文件重复。

2. **`module.exports` 里塞别的文件的标识符**
   `reports.js` 的导出里列了 `renderTrendChart` / `renderMonthlyPie` / `copyDayUsage`
   等 5 个不属于本文件的裸标识符(还有清理同名副本时漏掉的)。浏览器里 `module`
   未定义所以看不出来,Node 下 `require` 直接 ReferenceError。

3. **表集合/倍率写死**
   门店可以自定义表(2 表门店)与倍率(总表 ×100)。写死 `['hall','fire',
   'private_room','ac']` 会让饼图「扇区 2 项、明细 4 行」并读 undefined 抛错;
   写死 `|| 50` 会让月报底部写着「总表 ×50」而与实际配置矛盾。

运行:
    python3 -m unittest tests.test_frontend_globals -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Dict, List, Set

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
JS_DIR = METERSTATS / "js"
ADMIN_JS = METERSTATS / "admin.js"
INDEX_HTML = METERSTATS / "index.html"

# ⚠️ 必须要求**顶格**(第 0 列):缩进 2 格的 function 是在 IIFE 内部,属于局部,
#    不算全局符号(meterForm.js / overview.js 各有一个局部 `_esc`,不是冲突)。
_FUNC_DECL = re.compile(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(')
_FUNC_EXPR = re.compile(
    r'^(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b')
# `window.escapeHtml = function escapeHtml(...)` 这种显式挂 window 的也要算全局
_WINDOW_FN = re.compile(
    r'^window\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b')


def _js_files() -> List[Path]:
    return sorted(JS_DIR.rglob("*.js")) + [ADMIN_JS]


def _toplevel_globals(path: Path) -> Set[str]:
    """本文件在**全局作用域**声明的函数名(声明在缩进行里的属于局部,不算)。"""
    out: Set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        for pattern in (_FUNC_DECL, _FUNC_EXPR, _WINDOW_FN):
            m = pattern.match(line)
            if m:
                out.add(m.group(1))
    return out


class TestNoShadowedGlobals(unittest.TestCase):
    """同一个全局函数名只允许在一个文件里声明。"""

    def test_no_duplicate_global_function_names(self) -> None:
        owner: Dict[str, Set[str]] = {}
        for path in _js_files():
            for name in _toplevel_globals(path):
                owner.setdefault(name, set()).add(path.relative_to(METERSTATS).as_posix())

        dups = {name: sorted(files) for name, files in owner.items() if len(files) > 1}
        self.assertEqual(
            dups, {},
            "同一全局函数在多个文件里声明 → 谁生效只取决于 index.html 的 script 顺序,"
            "改被覆盖的那份等于没改。删掉副本,只留一份。",
        )

    def test_escape_helpers_have_single_definition(self) -> None:
        """escapeHtml / escapeAttr 只能各有一份(弱版覆盖强版是真实事故)。"""
        for name in ("escapeHtml", "escapeAttr"):
            files = [p.relative_to(METERSTATS).as_posix()
                     for p in _js_files() if name in _toplevel_globals(p)]
            self.assertEqual(files, ["js/helpers/utils.js"], f"{name} 有多份定义: {files}")

    def test_removed_shadow_copies_stay_removed(self) -> None:
        """这 4 对同名副本已清理,别在「被覆盖的那个文件」里再加回来。"""
        cases = {
            "js/modules/utilities.js": "submitUtilityAdd",
            "js/modules/reports.js": "refreshDayCopySelect",
            "js/modules/duty.js": "checkDutyReminder",
        }
        for rel, name in cases.items():
            src = (METERSTATS / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                f"function {name}(", src,
                f"{rel} 里又定义了 {name} —— 它的实现在别处,这里会被静默覆盖",
            )


class TestModuleExports(unittest.TestCase):
    """`module.exports` 只能列本文件定义的标识符(否则 Node 下 require 直接炸)。"""

    def test_exports_reference_local_names_only(self) -> None:
        problems: List[str] = []
        for path in _js_files():
            src = path.read_text(encoding="utf-8")
            m = re.search(r"module\.exports\s*=\s*\{(.*?)\}", src, re.S)
            if not m:
                continue
            names = [n.strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()]
            local = set(re.findall(
                r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)', src, re.M)) | set(
                re.findall(r'^(?:var|let|const)\s+([A-Za-z_$][\w$]*)', src, re.M))
            missing = [n for n in names if n not in local]
            if missing:
                problems.append(f"{path.relative_to(METERSTATS).as_posix()}: {missing}")
        self.assertEqual(problems, [], "导出里出现本文件未定义的标识符")


class TestUsersTableEscaping(unittest.TestCase):
    """用户管理表格:username / name 是自由文本,后端不校验字符集。"""

    def setUp(self) -> None:
        self.src = ADMIN_JS.read_text(encoding="utf-8")
        start = self.src.find("function renderUsersTable(")
        self.assertNotEqual(start, -1, "renderUsersTable 不见了")
        end = self.src.find("\n}", start)
        self.body = self.src[start:end]

    def test_free_text_is_escaped(self) -> None:
        for raw in ("${u.username}", "${u.name}"):
            self.assertNotIn(raw, self.body, f"{raw} 直接进了 innerHTML —— 存储型 XSS")
        self.assertIn("escapeHtml(u.username)", self.body)
        self.assertIn("escapeHtml(u.name)", self.body)

    def test_no_inline_onclick_with_username(self) -> None:
        """拼 onclick 字符串时用户名里一个单引号就能把那行按钮打断。"""
        self.assertNotIn("onclick=\"editAdminUser(", self.body)
        self.assertIn("data-user-action", self.body)

    def test_attribute_position_uses_escape_attr(self) -> None:
        self.assertIn("escapeAttr", self.body)


class TestMeterConfigDriven(unittest.TestCase):
    """表集合 / 倍率必须跟门店配置走,不能写死 4 表与 50/40。"""

    def test_pie_charts_do_not_hardcode_four_meters(self) -> None:
        src = (JS_DIR / "modules" / "render_pie_charts.js").read_text(encoding="utf-8")
        self.assertNotIn("['hall', 'fire', 'private_room', 'ac']", src)
        self.assertNotIn('["hall", "fire", "private_room", "ac"]', src)
        self.assertIn("window.METER_KEYS", src)

    def test_pie_charts_read_values_through_meter_value(self) -> None:
        """自定义表存在 row.meters 里,直接 row[key] 会得到 undefined → NaN%。"""
        src = (JS_DIR / "modules" / "render_pie_charts.js").read_text(encoding="utf-8")
        self.assertIn("meterValue(", src)
        self.assertNotIn("realKwh(first[k] - last[k]", src)
        self.assertNotIn("realKwh(prev[k] - next[k]", src)

    def test_no_literal_multiplier_fallback(self) -> None:
        """`|| 50` / `|| 40` 字面量兜底会让 ×100 的门店看到「总表 ×50」。"""
        offenders: List[str] = []
        for path in _js_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//", 1)[0]      # 注释里提到 50/40 是说明,不是兜底
                if re.search(r"\|\|\s*(50|40)\b", code) or re.search(r"\?\?\s*(50|40)\b", code):
                    offenders.append(f"{path.relative_to(METERSTATS).as_posix()}:{lineno}")
        self.assertEqual(offenders, [], "倍率兜底请用 window.MAIN_METER_MULT / SUB_METER_MULT")

    def test_meter_config_exposes_multiplier_globals(self) -> None:
        src = (JS_DIR / "core" / "meterConfig.js").read_text(encoding="utf-8")
        self.assertIn("window.MAIN_METER_MULT", src)
        self.assertIn("window.SUB_METER_MULT", src)
        self.assertIn("config.main_mult", src)
        self.assertIn("config.sub_mult", src)


class TestIndexHtmlWiring(unittest.TestCase):
    """index.html 里引用的本地资源必须真的存在(改名/删文件别只改一半)。"""

    def test_local_script_and_link_targets_exist(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="([^"]+)"', html)
        missing = []
        for ref in refs:
            if ref.startswith(("http://", "https://", "//", "data:", "#")):
                continue
            clean = ref.split("?", 1)[0]
            if not clean:
                continue
            if not (METERSTATS / clean).is_file():
                missing.append(ref)
        self.assertEqual(missing, [], "index.html 引用了不存在的本地资源")

    def test_every_js_module_loaded(self) -> None:
        """js/ 下的模块必须在 index.html 里被引入,否则等于死代码/漏接线。"""
        html = INDEX_HTML.read_text(encoding="utf-8")
        not_loaded = []
        for path in sorted(JS_DIR.rglob("*.js")):
            rel = path.relative_to(METERSTATS).as_posix()
            if rel not in html:
                not_loaded.append(rel)
        self.assertEqual(not_loaded, [], "有 JS 文件没被 index.html 引入")


if __name__ == "__main__":
    unittest.main()
