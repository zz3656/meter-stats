"""文档与代码的一致性护栏(标准库 unittest,零依赖)。

**为什么要有这个文件**:2026-11-27 用户反馈「项目介绍和更新日志里看不到分店功能」——
核实后发现 CHANGELOG 0.5.0 把多门店写得清清楚楚,但**项目门面 README 一个字都没提**,
结构树里还缺 `modules/stores/` 这个多门店核心目录。功能做完了、门面没跟上,而且没有任何
机制会发现这件事。

所以把这些「文档必须与现实相符」的点变成断言,而不是靠人记得:

1. 每个 `MeterStats/modules/*/` 目录都必须出现在 `AGENTS.md` 与 `README.md` 的结构树里
2. 每个顶层 `MeterStats/*.py` 模块都必须出现在 `AGENTS.md` 的结构树里
   (顶层模块还牵涉打包:漏了文档的人往往也漏了打包清单 —— 那个坑踩过,导致应用启动即崩)
3. 文档里写的用例数 / 测试文件数必须等于实际值
4. `MeterStats/VERSION` 必须等于 CHANGELOG 最新一版的版本号
5. 多门店这类**已发布能力**必须在 README 功能表里有入口(防止再次"做完不写")
6. `ServerManager.swift` 必须**枚举** `*.py`,不许回到硬编码清单
7. 单个文档不许长到「实施计划」那种体量(曾经 4 份计划占全部文档 70%)

这些检查全部是「文档 vs 现实」的机械比对,不涉及业务逻辑,跑起来是毫秒级。

运行:
    python3 -m unittest tests.test_docs_consistency -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent
METERSTATS = REPO / "MeterStats"
TESTS = REPO / "tests"
AGENTS = REPO / "AGENTS.md"
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"
VERSION = METERSTATS / "VERSION"
SERVER_MANAGER = METERSTATS / "ServerManager.swift"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestStructureTreesMatchReality(unittest.TestCase):
    """结构树必须覆盖真实的目录与顶层模块。"""

    def test_every_module_dir_is_documented(self) -> None:
        dirs = sorted(p.name for p in METERSTATS.glob("modules/*/")
                      if p.is_dir() and not p.name.startswith("_"))
        self.assertGreaterEqual(len(dirs), 8, "modules/ 下的目录数异常")
        for doc in (AGENTS, README):
            text = _read(doc)
            missing = [d for d in dirs if f"{d}/" not in text]
            self.assertEqual(
                missing, [],
                f"{doc.name} 的结构树里缺这些模块目录: {missing}"
                "(功能做完不写文档,用户就以为没这功能)",
            )

    def test_every_top_level_module_is_documented(self) -> None:
        modules = sorted(p.name for p in METERSTATS.glob("*.py"))
        self.assertIn("backup_paths.py", modules, "顶层模块清单异常")
        text = _read(AGENTS)
        missing = [m for m in modules if m not in text]
        self.assertEqual(
            missing, [],
            f"AGENTS.md 结构树缺顶层模块: {missing}。"
            "顶层模块同时牵涉打包清单(漏了 = 应用启动即 ModuleNotFoundError)",
        )


class TestDocumentedCountsAreReal(unittest.TestCase):
    """文档里写的用例数/文件数不能漂。"""

    def _actual(self) -> tuple[int, int]:
        files = sorted(TESTS.glob("test_*.py"))
        cases = sum(len(re.findall(r"^\s*def test_", _read(f), re.M)) for f in files)
        return len(files), cases

    def test_case_count_matches_docs(self) -> None:
        n_files, n_cases = self._actual()
        self.assertGreater(n_cases, 500, "用例数统计异常")
        for doc in (AGENTS, README):
            text = _read(doc)
            documented = {int(m) for m in re.findall(r"(\d+) 项", text)}
            self.assertTrue(documented, f"{doc.name} 里找不到「N 项」形式的用例数")
            wrong = {n for n in documented if n != n_cases and n > 100}
            self.assertEqual(
                wrong, set(),
                f"{doc.name} 写的用例数是 {sorted(documented)},实际 {n_cases}",
            )

    def test_test_file_count_matches_agents(self) -> None:
        n_files, _ = self._actual()
        m = re.search(r"\*\*(\d+)\*\* 个测试文件", _read(AGENTS))
        self.assertIsNotNone(m, "AGENTS.md 里找不到「N 个测试文件」")
        self.assertEqual(int(m.group(1)), n_files,  # type: ignore[union-attr]
                         f"AGENTS.md 写 {m.group(1)} 个测试文件,实际 {n_files}")


class TestVersionConsistency(unittest.TestCase):
    """VERSION 与 CHANGELOG 顶部章节必须一致。"""

    def test_version_matches_changelog_head(self) -> None:
        version = _read(VERSION).strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        headings = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", _read(CHANGELOG), re.M)
        self.assertTrue(headings, "CHANGELOG 里没有任何 `## [x.y.z]` 章节")
        self.assertEqual(headings[0], version,
                         f"VERSION={version} 但 CHANGELOG 第一个章节是 {headings[0]}")


class TestCapabilitiesAreDiscoverable(unittest.TestCase):
    """已发布能力必须在门面(README)里有入口。"""

    REQUIRED_IN_README_FEATURES = {
        "多门店": "0.5.0 起的核心能力:门店隔离/切换器/每店表计/门店总览",
        "抄表管理": "主业务",
        "充值管理": "主业务",
        "报表分析": "主业务",
        "数据备份": "主业务",
    }

    def test_feature_table_lists_capabilities(self) -> None:
        text = _read(README)
        for keyword, why in self.REQUIRED_IN_README_FEATURES.items():
            self.assertIn(keyword, text,
                          f"README 里找不到「{keyword}」({why})—— 功能做完必须写进功能表")

    def test_upgrade_migration_is_documented(self) -> None:
        """0.4.x → 0.5.x 的数据布局迁移必须写在 README 的升级章节里。"""
        text = _read(README)
        self.assertIn("自动迁移", text, "README 未说明数据布局自动迁移")
        self.assertIn("stores/main/", text, "README 未说明新数据目录位置")
        self.assertIn("回滚", text, "README 未说明回滚方式")


class TestPackagingStaysGeneric(unittest.TestCase):
    """打包链路不许回到硬编码清单(新增模块会静默漏包)。"""

    def test_server_manager_enumerates_python_files(self) -> None:
        raw = _read(SERVER_MANAGER)
        # 剥掉 Swift 行注释再判断 —— 文件里那段注释**故意**保留了旧硬编码清单作为反面说明
        code = "\n".join(re.sub(r"//.*$", "", ln) for ln in raw.splitlines())
        self.assertIn('hasSuffix(".py")', code,
                      "ServerManager.swift 必须枚举 bundle 里的 *.py;"
                      "硬编码清单会让新增顶层模块漏进 runtime → 启动即 ImportError")
        # 不该被「点名」的模块:它们只能靠枚举发现
        for named in ('"app_handler.py"', '"report.py"', '"storage.py"', '"routing.py"'):
            self.assertNotIn(named, code,
                             f"ServerManager.swift 又点名了 {named} —— 应改回枚举* .py")


class TestDocsDoNotBlowUp(unittest.TestCase):
    """单个文档不许长到「实施计划」那种体量(曾经 4 份计划占全部文档 70%)。"""

    LIMIT = 2000
    EXEMPT = {"CHANGELOG.md", "README.Docker.md"}   # 按版本累积 / CI 生成

    def test_no_giant_docs(self) -> None:
        offenders: List[str] = []
        candidates = [p for p in REPO.glob("*.md")] + [p for p in (REPO / "docs").rglob("*.md")]
        for p in candidates:
            if p.name in self.EXEMPT:
                continue
            n = len(_read(p).splitlines())
            if n > self.LIMIT:
                offenders.append(f"{p.relative_to(REPO).as_posix()} ({n} 行)")
        self.assertEqual(
            offenders, [],
            f"这些文档超过 {self.LIMIT} 行,考虑归档或拆成「现状 + 待办」: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
