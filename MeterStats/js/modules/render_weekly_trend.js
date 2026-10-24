// ===== 每周汇报:4 块表电费详细趋势 =====
// 4 张表(大厅/消防/包厢/空调)各自独立展示,详尽呈现上周 vs 上上周的用电度数、费用、变化量与变化百分比。
// 由 loadWeeklyReport() 在汇总区块之后调用。

/**
 * 渲染"4 块表电费详细趋势"区块
 * @param {string} targetStart - 目标周(上周)起始日 (YYYY-MM-DD)
 * @param {string} targetEnd   - 目标周(上周)结束日 (YYYY-MM-DD)
 * @param {string} prevStart   - 对比周(上上周)起始日
 * @param {string} prevEnd     - 对比周(上上周)结束日
 */
function renderWeeklyMeterTrend(targetStart, targetEnd, prevStart, prevEnd) {
  const wrap = document.getElementById('weekly-meter-trend');
  if (!wrap) return;

  const readings = CURRENT_READINGS || [];
  const charges = CURRENT_CHARGES || [];
  const mKeys = ['hall', 'fire', 'private_room', 'ac'];

  // 数据不足(整体空场景)直接隐藏
  if (readings.length < 2) {
    wrap.style.display = 'none';
    return;
  }

  wrap.style.display = '';

  const cards = mKeys.map(k => _buildMeterTrendCard(k, readings, charges, targetStart, targetEnd, prevStart, prevEnd)).join('');

  const grid = document.getElementById('weekly-meter-trend-grid');
  if (grid) grid.innerHTML = cards;

  // 整体趋势条(汇总 4 块表)
  const summaryEl = document.getElementById('weekly-meter-trend-summary');
  if (summaryEl) summaryEl.innerHTML = _buildMeterTrendOverallSummary(readings, charges, targetStart, targetEnd, prevStart, prevEnd);
}

/**
 * 构造单个表的趋势卡片 HTML
 */
function _buildMeterTrendCard(meterKey, readings, charges, targetStart, targetEnd, prevStart, prevEnd) {
  const meta = METER_META(meterKey);
  const t = calcPeriodUsage(readings, charges, meterKey, targetStart, targetEnd);
  const p = calcPeriodUsage(readings, charges, meterKey, prevStart, prevEnd);

  const tCost = t.kwh * ELECTRICITY_PRICE;
  const pCost = p.kwh * ELECTRICITY_PRICE;
  const kwhDelta = t.kwh - p.kwh;
  const costDelta = tCost - pCost;

  // 变化百分比与箭头
  const trend = _formatChange(t.kwh, p.kwh);
  const trendClass = _changeColorClass(t.kwh, p.kwh);

  // 表格行的"涨跌"格子:同时显示度数差和百分比,带颜色
  const deltaText = trend.sign === 'flat'
    ? '—'
    : `${trend.sign === 'up' ? '+' : '−'}${Math.abs(kwhDelta).toFixed(1)} 度 (${trend.label})`;
  const deltaCellStyle = trendClass === 'up' ? 'color:var(--danger);font-weight:600;'
    : trendClass === 'down' ? 'color:var(--success);font-weight:600;'
    : 'color:var(--text-muted);';

  const costDeltaText = trend.sign === 'flat'
    ? '—'
    : `${trend.sign === 'up' ? '+' : '−'}¥${Math.abs(costDelta).toFixed(2)} (${trend.label})`;
  const costDeltaStyle = trendClass === 'up' ? 'color:var(--danger);font-weight:600;'
    : trendClass === 'down' ? 'color:var(--success);font-weight:600;'
    : 'color:var(--text-muted);';

  // 上周数据是否有充值(影响提示)
  const chargeHint = t.chargeKwh > 0
    ? `<span style="display:inline-block;margin-left:6px;font-size:11px;color:var(--text-muted);">(含 ${t.chargeKwh.toFixed(1)} 度充值)</span>`
    : '';

  return `
    <div class="meter-trend-card" data-meter="${meterKey}">
      <div class="meter-trend-head" style="border-left:4px solid ${meta.color};">
        <span class="meter-trend-icon">${meta.icon}</span>
        <span class="meter-trend-title">${meta.label}</span>
        <span class="meter-trend-badge ${trendClass}">${trend.arrow} ${trend.label}</span>
      </div>
      <div class="meter-trend-table-wrap">
        <table class="history-table meter-trend-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>上周</th>
              <th>上上周</th>
              <th>变化</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>用电度数</td>
              <td><strong>${t.kwh.toFixed(1)}</strong> 度${chargeHint}</td>
              <td>${p.kwh.toFixed(1)} 度</td>
              <td style="${deltaCellStyle}">${deltaText}</td>
            </tr>
            <tr>
              <td>电费</td>
              <td><strong>¥${tCost.toFixed(2)}</strong></td>
              <td>¥${pCost.toFixed(2)}</td>
              <td style="${costDeltaStyle}">${costDeltaText}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

/**
 * 构造整体趋势汇总行(放在 4 张卡片下方)
 */
function _buildMeterTrendOverallSummary(readings, charges, targetStart, targetEnd, prevStart, prevEnd) {
  const mKeys = ['hall', 'fire', 'private_room', 'ac'];
  let totalT = 0, totalP = 0, totalCostT = 0, totalCostP = 0;
  const perMeter = mKeys.map(k => {
    const t = calcPeriodUsage(readings, charges, k, targetStart, targetEnd);
    const p = calcPeriodUsage(readings, charges, k, prevStart, prevEnd);
    totalT += t.kwh;
    totalP += p.kwh;
    totalCostT += t.kwh * ELECTRICITY_PRICE;
    totalCostP += p.kwh * ELECTRICITY_PRICE;
    return { key: k, t, p };
  });

  const trend = _formatChange(totalT, totalP);
  const trendClass = _changeColorClass(totalT, totalP);
  const kwhDelta = totalT - totalP;
  const costDelta = totalCostT - totalCostP;

  const kwhDeltaText = trend.sign === 'flat'
    ? '0 度'
    : `${trend.sign === 'up' ? '+' : '−'}${Math.abs(kwhDelta).toFixed(1)} 度`;
  const costDeltaText = trend.sign === 'flat'
    ? '¥0.00'
    : `${trend.sign === 'up' ? '+' : '−'}¥${Math.abs(costDelta).toFixed(2)}`;

  const colorStyle = trendClass === 'up' ? 'color:var(--danger);'
    : trendClass === 'down' ? 'color:var(--success);'
    : 'color:var(--text-muted);';

  return `
    <div class="meter-trend-overall">
      <div class="meter-trend-overall-item">
        <span class="meter-trend-overall-label">4 块表合计用电</span>
        <span class="meter-trend-overall-value">上周 <strong>${totalT.toFixed(1)}</strong> 度 · 上上周 <strong>${totalP.toFixed(1)}</strong> 度</span>
      </div>
      <div class="meter-trend-overall-item">
        <span class="meter-trend-overall-label">合计电费</span>
        <span class="meter-trend-overall-value">上周 <strong>¥${totalCostT.toFixed(2)}</strong> · 上上周 <strong>¥${totalCostP.toFixed(2)}</strong></span>
      </div>
      <div class="meter-trend-overall-item">
        <span class="meter-trend-overall-label">整体变化</span>
        <span class="meter-trend-overall-value" style="${colorStyle}">${trend.arrow} ${trend.label} (${kwhDeltaText} / ${costDeltaText})</span>
      </div>
    </div>
  `;
}

/**
 * 计算变化百分比并返回结构化展示信息
 * @returns {{ sign: 'up'|'down'|'flat', pct: number, label: string, arrow: string }}
 */
function _formatChange(curr, prev) {
  if (prev <= 0 && curr <= 0) {
    return { sign: 'flat', pct: 0, label: '持平', arrow: '→' };
  }
  if (prev <= 0) {
    // 上周没数据,但本周有 → 视为"新增"
    return { sign: 'up', pct: Infinity, label: '新增', arrow: '▲' };
  }
  const pct = ((curr - prev) / prev) * 100;
  if (Math.abs(pct) < 0.05) {
    return { sign: 'flat', pct: 0, label: '持平', arrow: '→' };
  }
  if (pct > 0) {
    return { sign: 'up', pct, label: `↑${pct.toFixed(1)}%`, arrow: '▲' };
  }
  return { sign: 'down', pct, label: `↓${Math.abs(pct).toFixed(1)}%`, arrow: '▼' };
}

/**
 * 根据变化方向返回颜色 class 名
 * 'up' = 上涨(危险红), 'down' = 下降(成功绿), 'flat' = 持平
 */
function _changeColorClass(curr, prev) {
  if (prev <= 0 && curr <= 0) return 'flat';
  if (prev <= 0) return 'up';
  const pct = ((curr - prev) / prev) * 100;
  if (Math.abs(pct) < 0.05) return 'flat';
  return pct > 0 ? 'up' : 'down';
}
