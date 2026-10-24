// ===== 图表实例(全局变量) =====
let trendChart = null;
// 饼图实例 dailyPieChart / monthlyPieChart / _monthlyPieChart / pieChart
// 已迁出至 render_pie_charts.js,本文件只保留折线图。

function refreshDayCopySelect(readings, charges) {
  const sel = document.getElementById('day-copy-date');
  if (!sel) return;
  const rs = (readings || []).filter(r => r.hall != null).sort((a, b) => a.date.localeCompare(b.date));
  if (rs.length < 2) {
    sel.innerHTML = '<option value="">(需至少两次抄表)</option>';
    return;
  }
  // 列出每一天:首次抄表日 → 最新抄表日前一天(最新日无当天用电,不列)
  const first = new Date(rs[0].date);
  const last = new Date(rs[rs.length - 1].date);
  const copyDates = [];
  for (let d = new Date(first); d < last; d.setDate(d.getDate() + 1)) {
    copyDates.push(formatDate(d));
  }
  sel.innerHTML = copyDates.map(dd => `<option value="${dd}">${dd}</option>`).join('');
  // 默认选昨天(最新抄表日的前一天;今天录入表底 → 算出的正是昨日用电)
  sel.value = copyDates.length ? copyDates[copyDates.length - 1] : '';
}

// 计算某一天的用电:找到该天所在的抄表区间 [a, b](a.date ≤ day < b.date),
// 用电 = (a读数-b读数)×倍率+充值 均摊到区间每一天(日均,与每日用电图一致)
// 同时返回"昨日"(前一天)各区域用电,用于对比
function calcDayUsage(readings, charges, day) {
  const rs = (readings || []).filter(r => r.hall != null).sort((a, b) => a.date.localeCompare(b.date));
  // 找区间:day 属于 [rs[i].date, rs[i+1].date)
  let a = null, b = null;
  for (let i = 0; i < rs.length - 1; i++) {
    if (day >= rs[i].date && day < rs[i + 1].date) { a = rs[i]; b = rs[i + 1]; break; }
  }
  if (!a || !b) return null;  // 最新抄表日之后没有区间,算不出
  const spanDays = Math.round((new Date(b.date) - new Date(a.date)) / 86400000);
  if (spanDays <= 0) return null;
  const per = {};
  let totalKwh = 0, totalCost = 0;
  for (const m of CHARGE_METERS) {
    if (a[m.key] == null || b[m.key] == null) { per[m.key] = null; continue; }
    const total = realKwh(a[m.key] - b[m.key], m.key) + sumChargesBetween(charges, m.key, a.date, b.date);
    const kwh = total / spanDays;  // 日均
    const cost = kwh * ELECTRICITY_PRICE;
    per[m.key] = { kwh, cost };
    totalKwh += kwh; totalCost += cost;
  }
  // 昨日用电 = 前一天(day-1)的均摊日均;用于对比
  let yPer = null;
  const yDateObj = new Date(day);
  yDateObj.setDate(yDateObj.getDate() - 1);
  const yDate = formatDate(yDateObj);
  let yA = null, yB = null;
  for (let i = 0; i < rs.length - 1; i++) {
    if (yDate >= rs[i].date && yDate < rs[i + 1].date) { yA = rs[i]; yB = rs[i + 1]; break; }
  }
  if (yA && yB) {
    const yDays = Math.round((new Date(yB.date) - new Date(yA.date)) / 86400000);
    if (yDays > 0) {
      yPer = {};
      for (const m of CHARGE_METERS) {
        if (yA[m.key] == null || yB[m.key] == null) { yPer[m.key] = null; continue; }
        const total = realKwh(yA[m.key] - yB[m.key], m.key) + sumChargesBetween(charges, m.key, yA.date, yB.date);
        yPer[m.key] = { kwh: total / yDays };
      }
    }
  }
  return { date: day, prevDate: a.date, nextDate: b.date, spanDays, per, totalKwh, totalCost, yPer, yPrevDate: yDate };
}

// 生成汇报文本并复制:度数 + 金额 + 对比昨日 + 对比本月日均,可直接粘贴到群
function copyDayUsage() {
  const sel = document.getElementById('day-copy-date');
  if (!sel || !sel.value) { showAlert('请先选择日期(需至少两次抄表)', 'error'); return; }
  const date = sel.value;
  const usage = calcDayUsage(CURRENT_READINGS, CURRENT_CHARGES, date);
  if (!usage) { showAlert(`${date} 没有可用的用电区间,无法计算`, 'error'); return; }
  const lines = [`【${date} 各区域用电】`];
  let hasData = false;
  // 合计的对比基数:昨日总用电 / 本月日均总用电
  let yTotal = 0, yHas = false, mTotal = 0, mHas = false;
  for (const m of CHARGE_METERS) {
    const p = usage.per[m.key];
    if (p == null) { lines.push(`${m.icon} ${m.label}: —`); continue; }
    hasData = true;
    // 较昨日:前一天(day-1)的均摊日均
    let vsY = '';
    if (usage.yPer && usage.yPer[m.key]) {
      const y = usage.yPer[m.key].kwh;
      yTotal += y; yHas = true;
      if (y > 0) {
        const diff = p.kwh - y;
        const pct = (diff / y) * 100;
        const arrow = diff >= 0 ? '↑' : '↓';
        vsY = ` 较昨日${arrow}${Math.abs(pct).toFixed(1)}%`;
      } else if (y === 0) {
        vsY = ` 较昨日↑—`;
      }
    }
    // 较本月日均:复用 calcMonthlyDailyUsage 的 daily(当月优先,含充值口径)
    let vsM = '';
    const avg = calcMonthlyDailyUsage(CURRENT_READINGS, CURRENT_CHARGES, m.key);
    if (avg && avg.daily > 0) {
      const diff = p.kwh - avg.daily;
      const pct = (diff / avg.daily) * 100;
      const arrow = diff >= 0 ? '↑' : '↓';
      vsM = ` 较本月日均${arrow}${Math.abs(pct).toFixed(1)}%`;
      mTotal += avg.daily; mHas = true;
    }
    lines.push(`${m.icon} ${m.label}: ${p.kwh.toFixed(1)} 度,¥${p.cost.toFixed(2)}${vsY}${vsM}`);
  }
  if (!hasData) { showAlert(`${date} 没有可计算的用电数据`, 'error'); return; }
  // 合计行:总度数/金额 + 较昨日 + 较本月日均
  let vsYTotal = '', vsMTotal = '';
  if (yHas && yTotal > 0) {
    const diff = usage.totalKwh - yTotal;
    const pct = (diff / yTotal) * 100;
    vsYTotal = ` 较昨日${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  if (mHas && mTotal > 0) {
    const diff = usage.totalKwh - mTotal;
    const pct = (diff / mTotal) * 100;
    vsMTotal = ` 较本月日均${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  lines.push(`— 合计: ${usage.totalKwh.toFixed(1)} 度,¥${usage.totalCost.toFixed(2)}${vsYTotal}${vsMTotal}`);
  const spanNote = usage.spanDays > 1 ? `(区间 ${usage.prevDate} → ${usage.nextDate} 共 ${usage.spanDays} 天均摊)` : `(区间 ${usage.prevDate} → ${usage.nextDate})`;
  lines.push(spanNote);
  const text = lines.join('\n');
  copyTextWithFallback(text, '✓ 单天用电已复制,可直接粘贴到群里');
}

// 复制文本:优先 Clipboard API(WKWebView 受限时 fallback 到 execCommand)
function copyTextWithFallback(text, successMsg) {
  // ⚠️ App(WKWebView) 内必须走 Swift 原生桥：
  // navigator.clipboard 在 WKWebView 里常因缺少用户手势上下文而静默失败，
  // document.execCommand('copy') 也可能被拦，表现为"点了复制没反应"。
  const w = window;
  const bridge = w.webkit && w.webkit.messageHandlers && w.webkit.messageHandlers.macOSCopyToClipboard;
  if (bridge) {
    const esc = String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // Swift 端的解析分支要求 html/tsv 都是 String，html 不能传 null
    const html = '<meta charset="utf-8"><pre style="font-family:inherit;white-space:pre-wrap;font-size:12pt;margin:0;">' + esc + '</pre>';
    bridge.postMessage({ tsv: text, html: html });
    showAlert(successMsg, 'success');
    return;
  }

  const done = () => showAlert(successMsg, 'success');
  const fail = () => {
    // 浏览器环境兜底：隐藏 textarea + execCommand('copy')
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      if (ok) { done(); return; }
    } catch (e) { /* 继续走下方报错 */ }
    showAlert('复制失败,请手动选择复制', 'error');
  };
  if (navigator.clipboard && window.ClipboardItem) {
    navigator.clipboard.writeText(text).then(done, fail);
  } else {
    fail();
  }
}

// 每日用电折线图 — 4 块表各自折线 + 充电叠加
function renderTrendChart(readings, charges) {
  readings = (readings || []).filter(r => r.hall != null);  // 跳过只录水电的行
  const ctx = document.getElementById('chart-trend').getContext('2d');
  if (!readings || readings.length === 0) {
    ctx.canvas.parentElement.innerHTML = '<div class="empty">录入抄表数据后查看每日用电</div>';
    return;
  }

  // X 轴:从首次抄表日到最新抄表日,每天一个点
  const sorted = [...readings].sort((a, b) => a.date.localeCompare(b.date));
  const startDate = new Date(sorted[0].date);
  const endDate = new Date(sorted[sorted.length - 1].date);
  const dayCount = Math.round((endDate - startDate) / 86400000) + 1;
  const dayLabels = [];
  for (let i = 0; i < dayCount; i++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + i);
    dayLabels.push(formatDate(d));
  }

  // 预建 DateString → Index 映射,避免循环里 indexOf 的 O(n²)
  const dateToIndex = new Map();
  for (let i = 0; i < dayCount; i++) {
    dateToIndex.set(dayLabels[i], i);
  }

  // 每天的用电 = 抄表对 [a, b] 的用电均摊到 a .. b-1 的每一天
  // 语义:今天(a)抄表后,到下次抄表(b)之间的用电,属于今天及中间各天
  // (与单天复制口径一致:区间 (a→b) 的用电 = a 日的用电)
  const dailyUsage = {};
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    dailyUsage[key] = new Array(dayCount).fill(null); // 用 null 让线断开
  }

  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    const aIdx = dateToIndex.get(a.date) ?? -1;
    const bIdx = dateToIndex.get(b.date) ?? -1;
    if (aIdx < 0 || bIdx < 0 || bIdx <= aIdx) continue;
    const days = bIdx - aIdx;
    if (days <= 0) continue;
    for (const key of ['hall', 'fire', 'private_room', 'ac']) {
      const delta = realKwh(a[key] - b[key], key);
      const charged = sumChargesBetween(charges, key, a.date, b.date);
      const perDay = (delta + charged) / days;
      // 均摊到 a(含) .. b-1;最新抄表日 b 没有当天的用电(要等下次抄表)
      for (let j = aIdx; j < bIdx; j++) {
        dailyUsage[key][j] = perDay;
      }
    }
  }

  // 每天的充电量(虚线 spike)
  // 用户填的充值度数 = 表度数(跟抄表读数同语义),需要 ×160 才是实际度数
  const dailyCharge = new Array(dayCount).fill(null);
  for (const c of (charges || [])) {
    const idx = dateToIndex.get(c.date);
    if (idx < 0) continue;
    const total = CHARGE_METERS.reduce((s, m) => s + realKwh(c[m.key] || 0, m.key), 0);
    dailyCharge[idx] = total;
  }

  // 整月日均水平线:每块表一条,虚线显示,作为波动参照
  const totalDays = dayCount; // first→last 的天数(已含两端)
  const avgLines = {};
  for (const key of ['hall', 'fire', 'private_room', 'ac']) {
    // 复用饼图公式:实际用电 = (first - last)*倍率 + 期间充值
    const f = sorted[0], l = sorted[sorted.length - 1];
    const totalKwh = realKwh(f[key] - l[key], key) + sumChargesBetween(charges, key, f.date, l.date);
    avgLines[key] = totalDays > 0 ? totalKwh / totalDays : 0;
  }
  const avgLineData = (val) => new Array(dayCount).fill(val);

  // ---------- 只看最近 30 天 ----------
  // 数据从首次抄表至今可能有 140+ 天，全塞进去柱子会挤成一整片，看不出起伏
  const DISPLAY_DAYS = 30;
  const sliceStart = Math.max(0, dayCount - DISPLAY_DAYS);
  const shownLabels = dayLabels.slice(sliceStart);
  const KEY_LIST = ['hall', 'fire', 'private_room', 'ac'];
  const shownUsage = {};
  for (const key of KEY_LIST) shownUsage[key] = dailyUsage[key].slice(sliceStart);

  const dayTotal = new Array(shownLabels.length).fill(0);
  for (let i = 0; i < shownLabels.length; i++) {
    let sum = 0;
    for (const key of KEY_LIST) {
      const v = shownUsage[key][i];
      if (v != null) sum += v;
    }
    dayTotal[i] = sum;
  }
  const sumKwh = dayTotal.reduce((a, b) => a + b, 0);
  const avgKwh = dayTotal.length > 0 ? sumKwh / dayTotal.length : 0;
  let maxIdx = -1, maxVal = 0, minIdx = -1, minVal = Infinity;
  dayTotal.forEach((v, i) => {
    if (v <= 0) return;
    if (v > maxVal) { maxVal = v; maxIdx = i; }
    if (v < minVal) { minVal = v; minIdx = i; }
  });

  const statEl = document.getElementById('trend-stat-grid');
  if (statEl) {
    const fmtN = v => v.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
    statEl.innerHTML =
      '<div class="trend-stat"><div class="trend-stat-label">近 ' + shownLabels.length + ' 天用电</div>' +
      '<div class="trend-stat-value">' + fmtN(sumKwh) + '<small>度</small></div>' +
      '<div class="trend-stat-sub">' + shownLabels[0] + ' ~ ' + shownLabels[shownLabels.length - 1] + '</div></div>' +
      '<div class="trend-stat"><div class="trend-stat-label">日均用电</div>' +
      '<div class="trend-stat-value">' + fmtN(avgKwh) + '<small>度/天</small></div>' +
      '<div class="trend-stat-sub">电费约 ¥' + fmtN(avgKwh * ELECTRICITY_PRICE) + '/天</div></div>' +
      '<div class="trend-stat"><div class="trend-stat-label">最高单日</div>' +
      '<div class="trend-stat-value">' + (maxIdx >= 0 ? fmtN(maxVal) : '—') + '<small>度</small></div>' +
      '<div class="trend-stat-sub">' + (maxIdx >= 0 ? shownLabels[maxIdx] : '—') + '</div></div>' +
      '<div class="trend-stat"><div class="trend-stat-label">最低单日</div>' +
      '<div class="trend-stat-value">' + (minIdx >= 0 ? fmtN(minVal) : '—') + '<small>度</small></div>' +
      '<div class="trend-stat-sub">' + (minIdx >= 0 ? shownLabels[minIdx] : '—') + '</div></div>';
  }

  // ---------- 堆叠柱状：4 块表叠成当天总量 ----------
  const datasets = [
    { label: LABELS('hall'), data: shownUsage.hall, backgroundColor: COLORS('hall') + 'dd', stack: 's', borderRadius: 3 },
    { label: LABELS('fire'), data: shownUsage.fire, backgroundColor: COLORS('fire') + 'dd', stack: 's', borderRadius: 3 },
    { label: LABELS('private_room'), data: shownUsage.private_room, backgroundColor: COLORS('private_room') + 'dd', stack: 's', borderRadius: 3 },
    { label: LABELS('ac'), data: shownUsage.ac, backgroundColor: COLORS('ac') + 'dd', stack: 's', borderRadius: 3 },
  ];

  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: 'bar',
    data: { labels: shownLabels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 }, padding: 12 } },
        tooltip: {
          callbacks: {
            label: (c) => {
              const v = c.parsed.y;
              if (v == null || v <= 0) return null;
              return `${c.dataset.label}: ${v.toFixed(1)} 度`;
            },
            footer: (items) => {
              const sum = items.reduce((acc, it) => acc + (it.parsed.y || 0), 0);
              return '合计: ' + sum.toFixed(1) + ' 度';
            },
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: { maxRotation: 45, minRotation: 0, autoSkip: true, maxTicksLimit: 15 },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          title: { display: true, text: '每日用电 (度)' },
          ticks: { callback: (v) => v.toLocaleString() },
        },
      },
    },
  });
}

// 注: calcMonthPie / drawPieChart / renderDailyPie / renderMonthlyPie /
//   renderPieChart 已迁出至 render_pie_charts.js(独立文件)。

