// ===== 主题管理 =====
const THEME_KEY = 'meter_theme_mode';
const THEMES = ['dark', 'light', 'auto'];
const ICONS = { dark: '🌙', light: '☀️', auto: '💻' };

function getPreferredTheme() {
  return localStorage.getItem(THEME_KEY) || 'auto';
}
function getEffectiveTheme() {
  const mode = getPreferredTheme();
  if (mode === 'auto') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return mode;
}
function applyTheme() {
  const theme = getEffectiveTheme();
  document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : '');
  updateThemeIcon();
}
function updateThemeIcon() {
  const icon = ICONS[getPreferredTheme()] || ICONS.auto;
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = icon;
}
function setTheme(mode) {
  localStorage.setItem(THEME_KEY, mode);
  applyTheme();
  // 重新渲染图表(颜色可能受影响)
  renderCharts();
}
function cycleTheme() {
  const current = getPreferredTheme();
  const idx = THEMES.indexOf(current);
  const next = THEMES[(idx + 1) % THEMES.length];
  setTheme(next);
}