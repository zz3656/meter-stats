async function renderAll() {
  // 一次拉全部数据(snapshot 优先,失败回退到 5 个独立 GET)
  await fetchSnapshot();
  CURRENT_READINGS = (CURRENT_READINGS || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_CHARGES = (CURRENT_CHARGES || []).slice().sort((a, b) => a.date.localeCompare(b.date));

  renderStats(CURRENT_READINGS, CURRENT_CHARGES);
  renderChargeAlert(CURRENT_READINGS, CURRENT_CHARGES);
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  triggerVisiblePie();
  renderHistory(CURRENT_READINGS);
  renderChargeLog(CURRENT_CHARGES);
  renderItemTable(CURRENT_ITEMS);
  renderLendHistory(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
  renderDutyTable(CURRENT_DUTY, '');
  populateDutyMonthSelector();
  checkDutyReminder();
  refreshMonthSelectors();
  refreshDayCopySelect(CURRENT_READINGS, CURRENT_CHARGES);
  updateStatusBar(CURRENT_READINGS, CURRENT_CHARGES);
  // 水电数据迁移检测（只在首次加载时检查一次）
  if (!MIGRATION_CHECKED) {
    setTimeout(checkAndPromptMigration, 1500);
  }
}

// 通用:写入后端 → 重新拉数据 → 重渲染
async function refreshAndRender() {
  CURRENT_READINGS = (await fetchReadings()).sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_CHARGES = (await fetchCharges()).sort((a, b) => a.date.localeCompare(b.date));
  CURRENT_WATER_READINGS = (await fetchWaterReadings()).sort((a, b) => a.date.localeCompare(b.date));
  await fetchItems();
  await fetchPurchases();
  renderStats(CURRENT_READINGS, CURRENT_CHARGES);
  renderChargeAlert(CURRENT_READINGS, CURRENT_CHARGES);
  renderTrendChart(CURRENT_READINGS, CURRENT_CHARGES);
  triggerVisiblePie();
  renderHistory(CURRENT_READINGS);
  renderChargeLog(CURRENT_CHARGES);
  renderItemTable(CURRENT_ITEMS);
  renderLendHistory(CURRENT_ITEMS);
  renderPurchaseTable(CURRENT_PURCHASES);
  refreshMonthSelectors();
  refreshDayCopySelect(CURRENT_READINGS, CURRENT_CHARGES);
  updateStatusBar(CURRENT_READINGS, CURRENT_CHARGES);
}

// 顶部状态条:上次抄表 / 本月用电 / 本月电费 / 预警
function updateStatusBar(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const bar = document.getElementById('status-bar');
  if (!readings || readings.length === 0) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';

  const sorted = [...readings].sort((a, b) => a.date.localeCompare(b.date));
  const last = sorted[sorted.length - 1];
  const gap = daysBetween(last.date, todayStr());
  document.getElementById('st-last-reading').textContent =
    gap <= 0 ? `今天已抄表(${last.date})` : `上次抄表 ${last.date} · ${gap} 天前`;

  // 本月(最后数据月)用电 + 电费
  const monthKey = last.date.slice(0, 7);
  const monthRs = sorted.filter(r => r.date.startsWith(monthKey));
  let kwh = 0;
  if (monthRs.length >= 2) {
    const f = monthRs[0], l = monthRs[monthRs.length - 1];
    for (const k of ['hall', 'fire', 'private_room', 'ac']) {
      kwh += realKwh(f[k] - l[k], k) + sumChargesBetween(charges, k, f.date, l.date);
    }
  }
  document.getElementById('st-month-kwh').textContent = `本月用电 ${kwh.toFixed(0)} 度`;
  document.getElementById('st-month-cost').textContent = `电费 ¥ ${(kwh * ELECTRICITY_PRICE).toFixed(0)}`;

  // 预警:剩余天数 < 7 的表数量
  let alertCount = 0;
  for (const m of CHARGE_METERS) {
    const remaining = last[m.key] * MULTIPLIER(m.key);
    const usage = calcMonthlyDailyUsage(readings, charges, m.key);
    if (usage && usage.daily > 0 && remaining / usage.daily < 7) alertCount++;
  }
  const el = document.getElementById('st-alerts');
  el.textContent = alertCount > 0 ? `${alertCount} 块表需关注` : '余量正常';
  el.className = alertCount > 0 ? 'em' : '';
}
