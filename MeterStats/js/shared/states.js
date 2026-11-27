/**
 * 空态与加载态(2026-11-27)
 * ────────────────────────────────────────────────────────────────────────
 * 此前空态就是一行灰字(「还没有物品」「暂无抄表记录」),加载时什么提示都没有 ——
 * 用户看到白屏/灰字,既不知道"是空的"还是"还没加载出来",也不知道下一步该做什么。
 *
 * 这里提供两件东西:
 *   emptyStateHtml({icon,title,hint,action})  空态:图标 + 一句说明 + **下一步做什么**
 *   skeletonRowsHtml(rows,cols)               加载态:骨架行,而不是转圈
 *
 * 原则(见 DESIGN.md):
 *   - 空态必须"教界面":告诉用户为什么空、在哪添加
 *   - 加载态用骨架占位,保持布局不跳动;不做居中 spinner
 *   - 尊重 prefers-reduced-motion(骨架呼吸动画在 CSS 里关掉)
 */
(function (global) {
  'use strict';

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /**
   * 空态。
   * @param {{icon?:string,title:string,hint?:string,action?:{label:string,onclick?:string}}} o
   * @returns {string}
   */
  function emptyStateHtml(o) {
    o = o || {};
    var iconName = o.icon || 'clipboard';
    var iconHtml = typeof global.icon === 'function' ? global.icon(iconName, 'empty-icon') : '';
    var action = '';
    if (o.action && o.action.label) {
      // onclick 只允许传给受信任的静态调用串(调用方是本仓库代码),不是用户输入
      action = '<button type="button" class="btn btn-secondary btn-sm empty-action"' +
        (o.action.onclick ? ' onclick="' + esc(o.action.onclick) + '"' : '') + '>' +
        esc(o.action.label) + '</button>';
    }
    return '<div class="empty-state">' +
      iconHtml +
      '<p class="empty-title">' + esc(o.title || '这里还没有数据') + '</p>' +
      (o.hint ? '<p class="empty-hint">' + esc(o.hint) + '</p>' : '') +
      action +
      '</div>';
  }

  /** 表格里的空态(自动包一层 <tr><td colspan>)。 */
  function emptyRowHtml(colspan, o) {
    return '<tr class="empty-row"><td colspan="' + (colspan || 1) + '">' +
      emptyStateHtml(o) + '</td></tr>';
  }

  /** 骨架行:cols 个占位单元格 × rows 行。 */
  function skeletonRowsHtml(rows, cols) {
    rows = Math.max(1, rows || 4);
    cols = Math.max(1, cols || 4);
    var cells = '';
    for (var c = 0; c < cols; c++) {
      // 首列窄一点(日期/名称),数值列宽一点,视觉上更接近真实表格
      var w = c === 0 ? 64 : (c === cols - 1 ? 48 : 76);
      cells += '<td><span class="skeleton" style="width:' + w + 'px"></span></td>';
    }
    var row = '<tr class="skeleton-row">' + cells + '</tr>';
    return new Array(rows + 1).join(row);
  }

  /** 卡片骨架(余量预警这类卡片网格用)。 */
  function skeletonCardsHtml(n) {
    var one = '<div class="stat-card skeleton-card"><span class="skeleton" style="width:60%"></span>' +
      '<span class="skeleton skeleton-lg" style="width:40%"></span>' +
      '<span class="skeleton" style="width:80%"></span></div>';
    return new Array((n || 4) + 1).join(one);
  }

  /** 启动时给主要表格铺骨架,数据到了由各渲染函数覆盖。 */
  // 表格 id → [行数, 列数]。tbody 没有 id,所以按 table 定位。
  var BOOT_TABLES = [
    ['history-table', 6, 6],
    ['charge-table', 4, 4],
    ['water-history-table', 3, 3],
    ['item-table', 4, 7],
    ['lend-history-table', 3, 5],
    ['purchase-table', 3, 8],
    ['duty-table', 4, 6]
  ];

  function showBootSkeletons() {
    if (!document.querySelector) return;
    BOOT_TABLES.forEach(function (spec) {
      var tbody = document.querySelector('#' + spec[0] + ' tbody');
      if (tbody) tbody.innerHTML = skeletonRowsHtml(spec[1], spec[2]);
    });
  }

  /** 兜底:渲染结束后清掉没被覆盖的骨架(否则会一直停在骨架上)。 */
  function clearSkeletons(root) {
    var scope = root || document;
    if (!scope.querySelectorAll) return;
    scope.querySelectorAll('.skeleton-row, .skeleton-card').forEach(function (el) {
      if (el.parentNode) el.parentNode.removeChild(el);
    });
  }

  global.emptyStateHtml = emptyStateHtml;
  global.emptyRowHtml = emptyRowHtml;
  global.skeletonRowsHtml = skeletonRowsHtml;
  global.skeletonCardsHtml = skeletonCardsHtml;
  global.showBootSkeletons = showBootSkeletons;
  global.clearSkeletons = clearSkeletons;
})(typeof window !== 'undefined' ? window : this);
