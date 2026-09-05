// ===== 水电数据迁移 =====
window.MIGRATION_CHECKED = false;

async function checkMigrateStatus() {
  try {
    const data = await api('GET', '/api/admin/migrate-water-status');
    return data;
  } catch (e) {
    console.warn('迁移检测失败:', e);
    return null;
  }
}

async function executeMigration() {
  try {
    const data = await api('POST', '/api/admin/migrate-water');
    return data;
  } catch (e) {
    console.warn('迁移执行失败:', e);
    return { ok: false, error: e.message };
  }
}

async function checkAndPromptMigration() {
  if (MIGRATION_CHECKED) return;
  MIGRATION_CHECKED = true;

  const status = await checkMigrateStatus();
  if (!status || !status.needs_migration) return;

  const { water_in_readings, water_dates, conflicts_with_existing, existing_water_count } = status;
  const datesText = water_dates.length <= 5
    ? water_dates.join('、')
    : `${water_dates.length} 个日期`;

  const confirm = await showModal({
    title: '🔄 数据升级提示',
    icon: '⬆️',
    iconKind: 'warn',
    body: `
      <p>检测到 <strong>${water_in_readings} 条抄表记录</strong>包含水电字段（总表/分表/水表）。</p>
      <p>涉及日期：<strong>${datesText}</strong></p>
      <p>本次升级将水电数据分离到独立文件，保证：</p>
      <ul style="text-align:left;font-size:13px;color:var(--text-muted);">
        <li>总表/分表/水表可以独立增删，不干扰电表抄表</li>
        <li>每月水电费用计算完全准确</li>
        <li>自动备份当前数据（可随时回滚）</li>
      </ul>
      ${conflicts_with_existing > 0
        ? `<p style="color:var(--warning);font-size:13px;">⚠️ 已有 ${conflicts_with_existing} 条独立水电记录将被覆盖</p>`
        : ''}
      <p style="margin-top:12px;">是否立即执行升级？</p>
    `,
    confirmText: '立即升级',
    confirmKind: 'primary',
    cancelText: '稍后再说',
  });

  if (!confirm) return;

  // 显示迁移中
  const overlay = el('toast-overlay');
  const content = el('toast-content');
  if (overlay && content) {
    overlay.style.display = 'flex';
    content.className = 'toast-content info';
    content.innerHTML = '⏳ 正在迁移数据，请稍候...';
  }

  const result = await executeMigration();

  // 隐藏 toast
  if (overlay && content) {
    setTimeout(() => {
      overlay.style.display = 'none';
    }, 500);
  }

  if (result.ok) {
    showAlert(
      `✅ 迁移完成！${result.migrated_count} 条水电记录已分离。`,
      'success'
    );
    // 刷新数据
    await refreshAndRender();
  } else {
    showAlert(`迁移失败：${result.error}`, 'error');
  }
}