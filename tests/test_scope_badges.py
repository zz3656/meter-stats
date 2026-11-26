"""设置项「作用范围」标注测试(标准库 unittest,零依赖)。

分店改造后,同一个应用里混着两类设置:

- **按店**:表集合、电价/水价、总表/分表倍率 → `stores/<id>/store.json`
- **全局**:用户与门店归属、门店注册表、备份目录/自动备份/保留份数、NAS 凭据

界面上不标出来,用户改错地方也看不出来 —— 最典型的是总部账号在 A 店改完电价,
以为"全局改了",切到 B 店发现还是旧值,报表金额就这么一直错着。

所以每个设置块标题旁必须有一个范围徽标:`🌐 全局` / `🏪 本店`。

另外图片目录有个反直觉的点:它是个**全局覆盖项**,一旦填了可写路径,
所有门店的值班照片会混进同一个目录 —— 与「照片按店隔离」正好相反。
所以它必须带警示文案,不能只写"必须是数据目录内的子目录"。

运行:
    python3 -m unittest tests.test_scope_badges -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO / "MeterStats" / "index.html"
STORES_JS = REPO / "MeterStats" / "js" / "modules" / "stores.js"
STYLE_CSS = REPO / "MeterStats" / "style.css"


class TestScopeBadges(unittest.TestCase):
    def setUp(self) -> None:
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def _section(self, section_id: str, next_id: str) -> str:
        start = self.html.index('id="%s"' % section_id)
        end = self.html.index('id="%s"' % next_id, start)
        return self.html[start:end]

    def test_css_has_scope_badge(self) -> None:
        css = STYLE_CSS.read_text(encoding="utf-8")
        self.assertIn(".scope-badge", css)

    def test_meter_page_marks_all_three_blocks_as_store_scoped(self) -> None:
        """电表设置页三块(表集合 / 计费单价 / 水电倍率)全部按店。"""
        seg = self._section("section-settings-meter", "section-settings-data")
        self.assertEqual(seg.count("🏪 本店"), 3,
                         "电表设置页应有 3 个「本店」徽标,实际 %d 个" % seg.count("🏪 本店"))
        for title in ("📝 电表设置", "💰 计费单价", "🔢 水电表倍率"):
            block = seg[seg.index(title):]
            block = block[:block.index("</div>") + 6]
            self.assertIn("🏪 本店", block, "%s 这块没标范围" % title)

    def test_data_page_marks_everything_global(self) -> None:
        seg = self._section("section-settings-data", "section-settings-roles")
        self.assertEqual(seg.count("🌐 全局"), 5,
                         "数据管理页应标 5 处全局,实际 %d 处" % seg.count("🌐 全局"))
        for title in ("备份与恢复", "自动备份", "图片目录", "从 NAS 同步", "备份列表"):
            idx = seg.index(title)
            block = seg[idx:idx + 400]
            self.assertIn("🌐 全局", block, "%s 这块没标全局" % title)

    def test_users_page_marks_global(self) -> None:
        seg = self._section("section-settings-users", "section-settings-meter")
        self.assertIn("🌐 全局", seg, "用户管理是全局设置,没标注")

    def test_stores_page_marks_global(self) -> None:
        src = STORES_JS.read_text(encoding="utf-8")
        self.assertIn("🌐 全局", src, "门店管理页是全局设置,没标注")

    def test_badges_explain_themselves(self) -> None:
        """徽标要有 tooltip —— 光有图标,第一次看的人不知道该不该改这里。"""
        badges = re.findall(r'class="badge-status (?:info|success) scope-badge"[^>]*title="([^"]+)"',
                            self.html)
        self.assertTrue(badges, "徽标没有 title 说明")
        self.assertIn("全站生效", " ".join(badges))
        self.assertIn("当前门店", " ".join(badges))

    def test_image_dir_warns_about_global_override(self) -> None:
        seg = self._section("section-settings-data", "section-settings-roles")
        idx = seg.index("图片目录")
        block = seg[idx:idx + 1200]
        self.assertIn("全局覆盖", block,
                      "图片目录没提示它是全局覆盖 —— 会破坏照片按店隔离")
        self.assertIn("混进同一个目录", block)
        self.assertIn("stores/&lt;店&gt;/images/", block)
        self.assertNotIn("必须是数据目录内的子目录", block,
                         "旧的 placeholder 会让人以为它只是改个路径")


if __name__ == "__main__":
    unittest.main()
