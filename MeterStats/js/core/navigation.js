/**
 * 侧栏导航 / 页面切换。
 *
 * ⚠️ 模块化重构时这些函数随旧 app.js 一起丢失，但 index.html 的内联
 * onclick 仍在调用（switchSection 10 次、switchSettingsPage 6 次、
 * toggleGroup 3 次、toggleSidebar 1 次），缺失导致点击侧栏报
 * "ReferenceError: switchSection is not defined"，页面无法切换。
 *
 * 本文件只负责导航 DOM 切换，不承载业务逻辑。
 */

// 这些 section 显示底部状态条（设置页/录入页不显示）
const SIDEBAR_VISIBLE_SECTIONS = new Set([
  'reading', 'charge', 'utility',
  'reading-record',  // 已合并充值记录（三 Tab）
  'item-record', 'purchase-record', 'item-add', 'purchase-add',
  'duty', 'duty-record',
  'report-monthly', 'report-trend', 'report-utilities', 'report-weekly', 'report-yearly',
  'overview',
]);

/**
 * 顶部状态条（📅上次抄表 / ⚡本月用电 / 💰电费 / 🚨余量）的显示页面白名单。
 *
 * 这条只跟"用电"有关，而且报表页自己的概况卡已经把同样的数字说得更清楚，
 * 所以只在「用电记录」页显示，其它页面（物品/申购/工作/报表/设置）一律隐藏。
 */
const STATUS_BAR_SECTIONS = new Set(['reading-record']);

/** 当前可见的 content-section 的 id（去掉 section- 前缀） */
function currentVisibleSection() {
  const el = Array.from(document.querySelectorAll('.content-section'))
    .find(s => s.style.display !== 'none' && s.offsetParent !== null);
  return el ? el.id.replace(/^section-/, '') : '';
}

/**
 * 按当前页面同步状态条可见性。
 * updateStatusBar() 更新完数据后也要调这个 —— 不能直接 display='flex'，
 * 否则会把切页时设好的隐藏覆盖掉，导致每个页面顶部都冒出来。
 */
function syncStatusBarVisibility(hasData) {
  const bar = document.getElementById('status-bar');
  if (!bar) return;
  if (hasData === false) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = STATUS_BAR_SECTIONS.has(currentVisibleSection()) ? 'flex' : 'none';
}

/**
 * section 显示后的收尾工作：图表重建 + 进入页面时按需加载数据。
 *
 * ⚠️ 图表实例在各模块里用顶层 `let` 声明（trendChart / monthlyPieChart / _yearlyChart），
 * 顶层 let 是全局词法绑定、**不会挂到 window 上**，所以不能用 window[name] 探测，
 * 必须用裸标识符 + typeof 判断。
 */
function _afterSectionShown(sectionId) {
  setTimeout(function() {
    try {
      if (sectionId === 'report-trend') {
        var cv = document.getElementById('chart-trend');
        // Chart.js 在 display:none 的容器里创建时 canvas 会是 0x0，
        // 之后 resize() 恢复不了 → 必须在可见后重建。
        if (cv && cv.width === 0 && typeof renderTrendChart === 'function') {
          renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
        } else if (typeof trendChart !== 'undefined' && trendChart) {
          trendChart.resize();
        }
        var daySel = document.getElementById('day-copy-date');
        if (typeof renderDailyPie === 'function' && daySel && daySel.value) {
          renderDailyPie(daySel.value);
        }
      }

      if (sectionId === 'report-monthly') {
        var mSel = document.getElementById('report-month');
        if (typeof loadMonthlyReport === 'function' && mSel && mSel.value) {
          loadMonthlyReport();
        }
      }

      if (sectionId === 'report-yearly') {
        var ySel = document.getElementById('yearly-year');
        if (typeof loadYearlyReport === 'function' && ySel && ySel.value) {
          loadYearlyReport();
        }
      }

      if (sectionId === 'report-weekly') {
        if (typeof loadWeeklyReport === 'function') loadWeeklyReport();
      }

      // 用电记录（抄表 / 充值 / 水电 三 Tab）：进页面刷新三个表格
      if (sectionId === 'reading-record') {
        if (typeof renderReadingTable === 'function') renderReadingTable(State.get('readings'));
        if (typeof renderChargeTable === 'function') renderChargeTable(State.get('charges'));
        if (typeof renderWaterTable === 'function') renderWaterTable();
      }
    } catch (e) { /* 图表/报表非关键，失败不影响主功能 */ }
  }, 100);
}


/** 切换到主内容区某个 section（侧栏主导航） */
function switchSection(sectionId) {
  // 隐藏所有 section
  document.querySelectorAll('.content-section').forEach(s => s.style.display = 'none');
  // 显示目标 section（.content-section 默认 display:none，需显式 flex）
  const target = document.getElementById('section-' + sectionId);
  if (target) target.style.display = 'flex';

  // 自动展开所属分组
  const activeBtn = document.querySelector(`.sidebar-item[data-section="${sectionId}"]`);
  if (activeBtn) {
    const group = activeBtn.closest('.sidebar-group');
    if (group && group.classList.contains('collapsed')) {
      group.classList.remove('collapsed');
    }
  }

  // 更新侧栏高亮
  document.querySelectorAll('.sidebar-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === sectionId);
  });

  // 状态条可见性（只在白名单页面显示，见 STATUS_BAR_SECTIONS）
  syncStatusBarVisibility();

  // 移动端:自动关闭侧栏
  const sidebar = document.getElementById('sidebar');
  if (window.innerWidth <= 900 && sidebar) {
    sidebar.classList.remove('mobile-open');
    document.getElementById('sidebar-overlay')?.classList.remove('show');
  }

  // 隐藏容器里初始化的 Chart 尺寸为 0，切回报表时重建；并按需加载该页数据
  _afterSectionShown(sectionId);
}

/** 切换设置类子页面（用户/电表/数据/角色） */
function switchSettingsPage(page) {
  document.querySelectorAll('.content-section').forEach(s => s.style.display = 'none');
  const target = document.getElementById('section-settings-' + page);
  if (target) target.style.display = 'flex';

  document.querySelectorAll('.sidebar-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.section === 'settings-' + page);
  });

  const settingsBtn = document.querySelector('.sidebar-item[data-section="settings-' + page + '"]');
  if (settingsBtn) {
    const group = settingsBtn.closest('.sidebar-group');
    if (group && group.classList.contains('collapsed')) {
      group.classList.remove('collapsed');
    }
  }

  const bar = document.getElementById('status-bar');
  if (bar) bar.style.display = 'none';

  // 加载对应页面数据
  if (page === 'users' && typeof loadAdminUsers === 'function') loadAdminUsers();
  if (page === 'meter' && typeof loadMeterSettings === 'function') loadMeterSettings();
  if (page === 'data') {
    if (typeof loadBackupStatus === 'function') loadBackupStatus();
    // ⚠️ 图片目录与备份目录都要主动加载，否则面板一直停在"加载中..."
    if (typeof loadImageDirConfig === 'function') loadImageDirConfig();
    if (typeof loadBackupDirConfig === 'function') loadBackupDirConfig();
    if (typeof loadBackupList === 'function') loadBackupList();
  }
  if (page === 'roles' && typeof loadRolesInfo === 'function') loadRolesInfo();
}

/** 折叠/展开侧栏分组 */
function toggleGroup(el) {
  const group = el.parentElement;
  if (group) group.classList.toggle('collapsed');
}

/** 桌面端折叠侧栏 / 移动端切换抽屉 */
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (!sidebar) return;

  if (window.innerWidth <= 900) {
    sidebar.classList.toggle('mobile-open');
    overlay?.classList.toggle('show');
  } else {
    sidebar.classList.toggle('collapsed');
    const content = document.querySelector('.content');
    if (content) content.style.maxWidth = sidebar.classList.contains('collapsed') ? '100%' : '';
  }
}

// 暴露到 window（与其它模块一致，供内联 onclick 与跨文件调用）
window.switchSection = switchSection;
window.switchSettingsPage = switchSettingsPage;
window.toggleGroup = toggleGroup;
window.toggleSidebar = toggleSidebar;
