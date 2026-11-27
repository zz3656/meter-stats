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

  global.icon = icon;
  global.fillIcons = fillIcons;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { fillIcons(); });
  } else {
    fillIcons();
  }
})(typeof window !== 'undefined' ? window : this);
