/**
 * 图标助手(2026-11-27)
 * ────────────────────────────────────────────────────────────────────────
 * 统一用内联 SVG sprite(index.html 里的 #icon-sprite)+ <use> 引用,
 * 替代此前散落各处的 emoji。理由:
 *   - emoji 在不同系统/字号下渲染差异大(同一条侧栏在 Win/mac/Android 长得都不一样)
 *   - emoji 自带颜色,不受主题控制 → 是"颜色太杂"的主要来源
 *   - 线性图标可以跟随 currentColor,两套主题自动一致
 *
 * 用法:
 *   静态 HTML : <svg class="icon"><use href="#i-clipboard"></use></svg>
 *   JS 拼字符串: '<h2>' + icon('flame') + ' 余量预警</h2>'
 *
 * 约束:引用的名字必须在 sprite 里存在 —— tests/test_icon_system.py 会校验。
 */
(function (global) {
  'use strict';

  var NAMES = null;

  function known() {
    if (NAMES) return NAMES;
    var set = {};
    document.querySelectorAll('#icon-sprite symbol[id^="i-"]').forEach(function (el) {
      set[el.id.slice(2)] = true;
    });
    NAMES = set;
    return set;
  }

  /**
   * @param {string} name sprite 里的图标名(不含 i- 前缀)
   * @param {string} [cls] 追加的 class
   * @returns {string} SVG 标记。未知名返回空串(不抛错,避免一个图标名打错整页白屏)
   */
  function icon(name, cls) {
    if (known()[name] !== true) {
      if (global.console && console.warn) console.warn('[icon] 未定义的图标:', name);
      return '';
    }
    return '<svg class="icon' + (cls ? ' ' + cls : '') + '" aria-hidden="true" focusable="false">' +
      '<use href="#i-' + name + '"></use></svg>';
  }

  /** 把一个占位元素替换成图标(用于必须静态写死 emoji 的位置) */
  function fillIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function (el) {
      var name = el.getAttribute('data-icon');
      if (!name) return;
      el.innerHTML = icon(name);
      el.removeAttribute('data-icon');
    });
  }


  /* ── 表计图标库(2026-11-27)───────────────────────────────────────────────
   * 表计图标此前是一个自由文本输入框,用户敲 emoji(🎤🧯🛋️❄️)。问题:
   *   ①emoji 跨系统渲染不一致;②自带颜色,不受主题控制;③手输容易输错/输成空格;
   *   ④canvas 图表图例里只能当文字,和 DOM 里的图标长得完全不一样。
   * 改成从固定图标库里选。**不做数据迁移**:`store.json` 里旧的 emoji 照旧能渲染
   * (见 LEGACY_EMOJI_ICON),用户下次进设置页选一次就换成图标名。
   */
  var METER_ICON_LIB = [
    { name: 'mic',         label: '话筒' },
    { name: 'fire-ext',    label: '灭火器' },
    { name: 'sofa',        label: '沙发' },
    { name: 'snowflake',   label: '制冷' },
    { name: 'fan',         label: '风扇' },
    { name: 'thermometer', label: '温度' },
    { name: 'bulb',        label: '照明' },
    { name: 'plug',        label: '电源' },
    { name: 'speaker',     label: '音响' },
    { name: 'tv',          label: '屏幕' },
    { name: 'fridge',      label: '冰柜' },
    { name: 'kettle',      label: '热水' },
    { name: 'utensils',    label: '厨房' },
    { name: 'wifi',        label: '网络' },
    { name: 'door',        label: '门禁' },
    { name: 'droplet',     label: '用水' },
    { name: 'zap',         label: '总电' },
    { name: 'chart-bar',   label: '计量' },
  ];

  // 旧数据里的 emoji → 图标名。只用于**渲染**,不改数据。
  var LEGACY_EMOJI_ICON = {
    '🎤': 'mic', '🧯': 'fire-ext', '🛋': 'sofa', '🛋️': 'sofa',
    '❄': 'snowflake', '❄️': 'snowflake', '🧊': 'snowflake', '🌬': 'fan', '🌀': 'fan',
    '💡': 'bulb', '🔌': 'plug', '🔊': 'speaker', '📺': 'tv', '🧊️': 'fridge',
    '☕': 'kettle', '🍳': 'utensils', '📶': 'wifi', '🚪': 'door',
    '💧': 'droplet', '⚡': 'zap', '📊': 'chart-bar', '📈': 'chart-bar',
  };

  function escapeText(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /** 把 store.json 里的 icon 值解析成 sprite 图标名;解析不出返回 null。 */
  function meterIconName(value) {
    var v = String(value == null ? '' : value).trim();
    if (!v) return null;
    if (LEGACY_EMOJI_ICON[v]) return LEGACY_EMOJI_ICON[v];
    if (known()[v] === true) return v;                  // 已经是图标名
    return null;
  }

  /**
   * 表计图标的 HTML。解析不出图标名时**退回转义后的原文**
   * (用户自己敲的 emoji / 任意字符都不会被吞掉,也不需要数据迁移)。
   */
  function meterIconHtml(value, cls) {
    var name = meterIconName(value);
    if (!name) {
      var raw = String(value == null ? '' : value).trim();
      return raw ? '<span class="meter-icon-text">' + escapeText(raw) + '</span>' : '';
    }
    return icon(name, 'meter-icon ' + (cls || ''));
  }

  /** 表计图标的选择器(设置页用):网格按钮,当前值高亮。 */
  function meterIconPickerHtml(current) {
    var active = meterIconName(current);
    return '<div class="meter-icon-picker" data-field="icon">' + METER_ICON_LIB.map(function (it) {
      return '<button type="button" class="meter-icon-choice' + (active === it.name ? ' active' : '') + '"' +
        ' data-icon-value="' + it.name + '" title="' + escapeText(it.label) + '"' +
        ' aria-label="' + escapeText(it.label) + '">' + icon(it.name) + '</button>';
    }).join('') + '</div>';
  }

  global.icon = icon;
  global.fillIcons = fillIcons;
  global.meterIconName = meterIconName;
  global.meterIconHtml = meterIconHtml;
  global.meterIconPickerHtml = meterIconPickerHtml;
  global.METER_ICON_LIB = METER_ICON_LIB;
  global.LEGACY_EMOJI_ICON = LEGACY_EMOJI_ICON;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { fillIcons(); });
  } else {
    fillIcons();
  }
})(typeof window !== 'undefined' ? window : this);
