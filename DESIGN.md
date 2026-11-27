# Design

视觉系统的现状说明书。改样式前先读这份,以及 `PRODUCT.md`(战略层:为什么这么设计)。

## Theme

**双主题同等对待**:`light`(办公/白天)与 `dark`(酒吧后场/夜班)都是一等公民,任何 token 改动必须两个主题都过 `tests/test_contrast.py`。

基调:**安静、低刺激、长时可读**。2026-11-27 的「安静化」把整套对比度从"截图好看"调到"连看 30 分钟不累":

| token | 旧值(问题) | 现值 | 说明 |
|---|---|---|---|
| 暗 `--bg` | `#0d0f14`(纯黑) | `#14161c` | 暗光下纯黑与文字的高反差最伤眼 |
| 暗 `--text` | `#e8eaf0` → **15.94:1** | `#d5d9e2` → **12.8:1** | 近纯白在暗底上会"发光" |
| 暗 `--text-muted` | `#6b7280` → **3.96:1** ✗ | `#8b93a3` → **5.9:1** | 旧值不过 WCAG AA |
| 暗 `--text-faint` | `#4a5058` → **2.35:1** ✗ | `#868ea0` → **5.1:1** | 旧值基本隐形 |
| 亮 `--text-faint` | `#a6adb8` → **3.87:1** ✗ | `#67707c` → **5.0:1** | 同上 |
| `--primary` | `#6366f1` / `#818cf8` | `#5b5fd6` / `#8f97f2` | 降一档饱和,长看不发紫光 |

`--text-faint` 在 `--bg-surface`(表单内嵌底)上约 4.4:1 —— 该底色上放的是 `--text` 级文字,faint 不用在那里,这个例外写在 `tests/test_contrast.py` 的注释里。

## Color

**Neutral 主导,颜色只做信号**(约 10% 面积)。语义色固定一组:

`--danger` / `--warn` / `--success` / `--info`(经 `--tint-1..5` 做浅染)。

4 块表的身份色 `--hall`(蓝)/ `--fire`(红)/ `--private`(绿)/ `--ac`(橙)是**数据语义**,不可省 —— 但只出现在:卡片左侧 2px 竖条、图表系列、表头小点。**不得**用作大面积填充。

**实心主色(CTA)是全屏唯一的强信号**,只给真正的主动作(抄表 / 保存 / 登录)。辅助开关(如「大字」)一律幽灵按钮 —— 2026-11-27 之前它是实心紫,成了屏幕上最响的元素,已改。

## Typography

- 单一字族(SF Pro / system-ui 栈),靠字重与字号建立层级;产品 UI 不需要 display/body 配对。
- 字号阶梯:**12 / 12.5 / 13 / 14 / 16 / 18 / 22 / 28 / 36px**。最小 12px(旧代码里 11px 出现 22 次,已不允许:小字是长看疲劳的主要来源)。
- 表格表头:**12px、`--text-secondary`、不做 `text-transform: uppercase`** —— 中文大写变换无意义,只会显得又小又灰。
- 数字一律 `font-variant-numeric: tabular-nums`,报表列必须对齐。
- 正文行宽 ≤75ch(报表说明文字);数据表可以更宽。

## Layout

- 桌面:左侧栏 236px + 主内容;≤900px 侧栏转抽屉;≤600px 卡片纵向堆叠、header 简化。
- 间距节奏:4 / 8 / 12 / 16 / 24 / 32。卡片 padding 14–16px,表格单元格 9px 10px(2026-11-27 从 8px 提到 9px)。
- 断点策略写在 `style.css` 顶部注释里,**新增组件必须考虑 ≤600px 与 ≤480px**。

## Components

| 组件 | 约定 |
|---|---|
| 按钮 | 主按钮=实心主色;次按钮=描边;文字按钮=中性,hover 才上语义色。三者高度分别 40/36/30(触屏 +4) |
| 行内操作(编辑/删除) | **中性 `--text-muted`**,hover 才上色(编辑→主色,删除→danger + 软底)。旧实现每行 2 个彩色链接,12 行 = 24 个彩色元素抢注意力 |
| 表格 | 行分隔线 `--border-subtle`(极轻);表头下边框 `--border`;hover 整行 `--bg-hover` |
| 卡片 | `--card` 底 + 1px `--border` + `--radius: 8–10px`;不用渐变、不用多层阴影(暗色下 `--shadow: none`) |
| 弹窗 | 遮罩 `--backdrop`;≤600px 变底部 sheet |
| 空态 | 必须给"下一步做什么",不能只写"暂无数据" |
| 焦点 | 全站 `:focus-visible` 主题色 2px 描边(表单控件靠自身边框+柔光环,避免每次点击都出环) |


## Icons

**统一线性图标,不用 emoji。** 2026-11-27 起常驻界面(侧栏/标题/按钮/状态栏/徽标)的 emoji 全部换成
内联 SVG sprite:

- sprite 定义在 `index.html` 的 `<svg id="icon-sprite">`,43 个 `<symbol id="i-NAME">`
- 静态 HTML:`<svg class="icon"><use href="#i-clipboard"></use></svg>`
- JS 拼字符串:`icon('clipboard')`(`js/shared/icons.js` 提供;未知名字返回空串并 warn,不抛错)
- 规格统一:**24×24 viewBox、stroke 1.6、`currentColor`、圆头圆角** —— 颜色自动跟随主题与状态
- 尺寸:行内 `1.05em`;标签/按钮 `1.15em`;`h1/h2` 内 `1em`

**为什么不用 emoji**:①同一条侧栏在 Win/mac/Android 渲染差异很大;②emoji 自带颜色,
不受 `currentColor` 与主题控制 —— 这是"颜色太杂"的主要来源;③emoji 无法跟随 hover/active 变色。

**表计图标(2026-11-27 起也可选库)**:设置页从 18 格图标库里点选(`METER_ICON_LIB`),
值是图标名;旧数据里的 emoji 通过 `LEGACY_EMOJI_ICON` 照旧渲染(不迁移数据)。
`meterIconHtml()` 解析不出图标名时退回"转义后的原文",所以用户手敲的字符不会被吞。
**canvas 图例不画图标**(canvas 画不了 SVG),改用标签 + 线条颜色区分。

护栏:`tests/test_icon_system.py` 校验「引用的名字都存在 / 没有定义了没人用的图标 /
icons.js 在消费者之前加载 / 常驻界面与 JS 标题里没有 emoji」。


## Empty & Loading States

**空态要教界面,加载态要有占位**(product register 的硬要求)。

- 空态 = `emptyStateHtml({icon, title, hint, action})` → 图标 + 一句说明 +
  **一句「下一步做什么」**(例:"点右上角「+ 抄表」录入今天的读数")。
  表格内用 `emptyRowHtml(colspan, …)` 自动包 `<tr><td colspan>`。
- 加载态 = 骨架行 `skeletonRowsHtml(rows, cols)`,**不用居中转圈**:
  骨架保持表格行高与列宽,数据到达时原地替换,布局不跳动。
  首屏由 `renderAll()` 在**发起请求前**调用 `showBootSkeletons()`,
  渲染后 `clearSkeletons()` 兜底(避免没被覆盖的骨架留在页面上)。
- 骨架呼吸动画在 `prefers-reduced-motion: reduce` 下关闭(只留静态灰条)。

**禁止**:裸文本当空态(`textContent = '还没有物品'`)。`tests/test_states.py` 会报错。

## Motion

- 150–180ms,`ease-out`;**只用于状态反馈**(hover / 展开 / 载入),不做入场编排。
- 已支持 `prefers-reduced-motion: reduce`:全部动效降到 0.01ms。
- 禁用 bounce / elastic / 视差。

## Accessibility

- 目标 WCAG 2.1 AA,由 `tests/test_contrast.py` 机械校验(主文字 11–14.5:1、其余 ≥4.5:1、主色块白字 ≥4.5:1)。
- 触屏目标:桌面 ≥30px,≤768px ≥40px(表格行内操作)。
- 「大字模式」是**叠加放大**,不是替代方案;打开后不得改变布局语义。

## 改动纪律

1. 改 token → 跑 `python3 -m unittest tests.test_contrast`。
2. 改样式 → 两主题 × 桌面/移动 四种组合都要截图对比(不是只看一种)。
3. 删 CSS 前先确认"没有任何元素能命中",否则会连带删掉活状态的唯一样式(踩过:`compare-table` 误删调查见 CHANGELOG 0.5.8)。
