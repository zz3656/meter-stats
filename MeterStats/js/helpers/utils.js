// ===== 工具函数 =====

/** 安全获取 DOM 元素,不存在返回 null */
window.el = (id) => document.getElementById(id);

/**
 * HTML 转义,防止 XSS。
 * 用法: escapeHtml(userInput) 后再插入 innerHTML / 模板字符串。
 * 项目约定:所有来自用户输入(note/name/borrower/supplier/fault_area 等)
 *   拼接到 innerHTML 之前必须先经本函数处理。
 */
window.escapeHtml = function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
};

/**
 * 本地时间 YYYY-MM-DD 字符串(避免 toISOString 的 UTC 坑)。
 */
window.formatDate = function formatDate(d) {
  const dt = d instanceof Date ? d : new Date(d);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
};

/**
 * 本地时间 YYYY-MM-DD HH:MM:SS。
 */
window.formatDateTime = function formatDateTime(d) {
  const dt = d instanceof Date ? d : new Date(d);
  return `${formatDate(dt)} ${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}:${String(dt.getSeconds()).padStart(2, '0')}`;
};

/**
 * 本地时间 YYYY-MM-DDTHH:MM(datetime-local input 格式)。
 */
window.formatDateTimeLocal = function formatDateTimeLocal(d) {
  const dt = d instanceof Date ? d : new Date(d);
  return `${formatDate(dt)}T${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`;
};
