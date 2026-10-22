
// ========== 年度汇总 ==========
async function fetchYearlyReport(year) {
  try {
    const r = await fetch(`api/yearly-report?year=${encodeURIComponent(year)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn('年度汇总加载失败:', e);
    return null;
  }
}

window._yearlyChart = null;  // 年度柱状图实例(切换年份前必须 destroy)

function renderYearlyReport(data) {
  const box = document.getElementById('yearly-result');
  const copyBtn = document.getElementById('btn-copy-yearly');
  // 销毁旧图表,避免 canvas 残留/重复
  if (_yearlyChart) { _yearlyChart.destroy(); _yearlyChart = null; }
  if (!data || !data.months || data.months.length === 0) {
    box.innerHTML = '<div class="report-empty">该年暂无抄表数据</div>';
    copyBtn.style.display = 'none';
    return;
  }
  copyBtn.style.display = 'inline-block';

  // 按表累计(年度合计行)
  const keys = ['hall', 'fire', 'private_room', 'ac'];
  const totals = {};
  keys.forEach(k => totals[k] = data.months.reduce((s, m) => s + (m.by_meter[k] || 0), 0));

  const rows = data.months.map(m => `
    <tr>
      <td class="col-date">${m.month}</td>
      <td>${fmtKwh(m.by_meter.hall)}</td>
      <td>${fmtKwh(m.by_meter.fire)}</td>
      <td>${fmtKwh(m.by_meter.private_room)}</td>
      <td>${fmtKwh(m.by_meter.ac)}</td>
      <td class="col-total">${fmtKwh(m.total_kwh)}</td>
      <td class="col-total">¥ ${m.total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
    </tr>`).join('');

  box.innerHTML = `
    <div class="chart-wrap" style="height:240px;margin-bottom:16px;"><canvas id="chart-yearly"></canvas></div>
    <div class="table-container">
      <table class="report-grid-table">
        <thead>
          <tr>
            <th class="col-date">月份</th><th>1#大厅</th><th>2#消防</th><th>3#包厢</th><th>4#空调</th>
            <th class="col-total">合计(度)</th><th class="col-total">电费(元)</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
          <tr class="total-row">
            <td class="col-date">年度合计</td>
            <td>${fmtKwh(totals.hall)}</td><td>${fmtKwh(totals.fire)}</td>
            <td>${fmtKwh(totals.private_room)}</td><td>${fmtKwh(totals.ac)}</td>
            <td class="col-total">${fmtKwh(data.year_total_kwh)}</td>
            <td class="col-total">¥ ${data.year_total_cost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
          </tr>
        </tbody>
      </table>
    </div>`;

  // 12 个月 4 表堆叠柱状图(主题色,与 legend 一致)
  const canvas = document.getElementById('chart-yearly');
  _yearlyChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.months.map(m => m.month.slice(5)),
      datasets: [
        { label: '1#' + LABELS('hall'), data: data.months.map(m => m.by_meter.hall), backgroundColor: COLORS('hall') },
        { label: '2#' + LABELS('fire'), data: data.months.map(m => m.by_meter.fire), backgroundColor: COLORS('fire') },
        { label: '3#' + LABELS('private_room'), data: data.months.map(m => m.by_meter.private_room), backgroundColor: COLORS('private_room') },
        { label: '4#' + LABELS('ac'), data: data.months.map(m => m.by_meter.ac), backgroundColor: COLORS('ac') },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label} ${fmtKwh(ctx.raw)} 度` } },
      },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, title: { display: true, text: '用电(度)' } },
      },
    },
  });
}

function copyYearlyTSV(data) {
  const lines = ['工程部管理系统年度汇总报表', `统计年份\t${data.year}`, ''];
  lines.push(['月份', '1#大厅', '2#消防', '3#包厢', '4#空调', '合计(度)', '电费(元)'].join('\t'));
  data.months.forEach(m => {
    lines.push([m.month, m.by_meter.hall, m.by_meter.fire, m.by_meter.private_room, m.by_meter.ac, m.total_kwh, m.total_cost].join('\t'));
  });
  lines.push(['年度合计', '', '', '', '', data.year_total_kwh, data.year_total_cost].join('\t'));
  const tsv = lines.join('\n');

  // 生成 HTML 表格(Numbers/Excel 粘贴时优先使用)
  const html = '<table><thead><tr>' +
    ['月份','1#大厅','2#消防','3#包厢','4#空调','合计(度)','电费(元)'].map(h => `<th>${h}</th>`).join('') +
    '</tr></thead><tbody>' +
    data.months.map(m => `<tr><td>${m.month}</td><td>${m.by_meter.hall}</td><td>${m.by_meter.fire}</td><td>${m.by_meter.private_room}</td><td>${m.by_meter.ac}</td><td>${m.total_kwh}</td><td>¥ ${m.total_cost.toFixed(2)}</td></tr>`).join('') +
    `<tr><td colspan="5"><b>年度合计</b></td><td>${data.year_total_kwh}</td><td>¥ ${data.year_total_cost.toFixed(2)}</td></tr>` +
    '</tbody>';

  if (navigator.clipboard && window.ClipboardItem) {
    const htmlBlob = new Blob([html], { type: 'text/html' });
    const tsvBlob = new Blob([tsv], { type: 'text/plain' });
    navigator.clipboard.write([new ClipboardItem({ 'text/html': htmlBlob, 'text/plain': tsvBlob })]).then(
      () => showAlert('✓ 年度汇总已复制,可粘贴到 Excel/Numbers', 'success'),
      () => copyTextWithFallback(tsv, '✓ 年度汇总已复制,可粘贴到 Excel')
    );
  } else {
    copyTextWithFallback(tsv, '✓ 年度汇总已复制,可粘贴到 Excel');
  }
}

// 月度报告复制(粘贴到 Excel/Numbers 自动成表):每日明细 + 每表总用电 + 合计 + 电费
// 不含标题行，直接输出表格数据，方便 Numbers/Excel 粘贴时自动成表
function copyReportTSV(data) {
  // ========== HTML 表格 (Numbers/Excel 粘贴时直接成表，最可靠) ==========
  const headerCells = ['日期','1#大厅','2#消防','3#包厢','4#空调','合计(度)']
    .map(h => `<th>${h}</th>`).join('');

  // 数据行
  const dataRows = data.days.map(d =>
    `<tr><td>${d.date}</td><td>${d.hall}</td><td>${d.fire}</td><td>${d.private_room}</td><td>${d.ac}</td><td>${d.total}</td></tr>`
  ).join('');

  // 汇总行: 第一列 + 其余数据列
  const summaryRows = [
    ['各表总用电', data.summary.by_meter.hall, data.summary.by_meter.fire,
     data.summary.by_meter.private_room, data.summary.by_meter.ac, data.summary.total_kwh],
    ['月度合计', '', '', '', '', data.summary.total_kwh],
    ['本月电费', '', '', '', '', `¥ ${data.summary.total_cost.toFixed(2)}`]
  ].map(row => {
    const dataCells = row.slice(1).map(v => `<td>${v}</td>`).join('');
    return `<tr><td>${row[0]}</td>${dataCells}</tr>`;
  }).join('');

  const html = `<table><thead><tr>${headerCells}</tr></thead><tbody>${dataRows}${summaryRows}</tbody></table>`;

  // App 端:Swift 桥接处理纯文本 (含 \t)，写入 .tabularText
  // Docker 端:用 clipboard.write() 同时写入 HTML + TSV，粘贴到表格软件自动成表
  // 注意: WKWebView (App 端) 不支持 navigator.clipboard API，必须走 Swift 桥接
  // 延迟检查 handler（wkWebView 可能在页面加载后注册 handler）
  let retryCount = 0;
  const MAX_RETRIES = 50; // 5秒超时 (50 * 100ms)
  const checkAndCopy = () => {
    retryCount++;
    if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.macOSCopyToClipboard) {
      return true;
    }
    if (window.webkit && retryCount < MAX_RETRIES) {
      setTimeout(checkAndCopy, 100);
      return false;
    }
    // 超时：Swift 桥接不可用，走 DOM 回退（浏览器路径）
    console.log('[copyReport] Swift 桥接不可用，走 DOM 回退');
    return false;
  };
  if (checkAndCopy()) {
    // App 端: 通过 Swift 桥接写入剪贴板。同时发送 HTML 和 TSV，Swift 端都写入
    const lines = ['日期', '大厅', '消防', '包厢', '空调', '合计(度)'].join('\t');
    const dataLines = data.days.map(d =>
      [d.date, d.hall, d.fire, d.private_room, d.ac, d.total].join('\t')
    ).join('\n');
    const summaryLines = [
      ['各表总用电', data.summary.by_meter.hall, data.summary.by_meter.fire,
       data.summary.by_meter.private_room, data.summary.by_meter.ac, data.summary.total_kwh].join('\t'),
      ['月度合计', '', '', '', '', data.summary.total_kwh].join('\t'),
      ['本月电费', '', '', '', '', `¥ ${data.summary.total_cost.toFixed(2)}`].join('\t')
    ].join('\n');
    const tsv = [lines, dataLines, '', summaryLines].join('\n');

    // 发送 HTML 和 TSV 到 Swift，Swift 端写入 .string + .tabularText
    const payload = JSON.stringify({ html: html, tsv: tsv });
    window.webkit.messageHandlers.macOSCopyToClipboard.postMessage(payload);
    showAlert('✓ 月度报告已复制,可直接粘贴到 Numbers/Excel', 'success');
  } else if (navigator.clipboard && navigator.clipboard.write && window.ClipboardItem) {
    // 浏览器: 用多格式写入 (HTML + TSV)，Numbers/Excel 优先使用 HTML
    const htmlBlob = new Blob([html], { type: 'text/html' });
    const lines = ['日期', '大厅', '消防', '包厢', '空调', '合计(度)'].join('\t');
    const dataLines = data.days.map(d =>
      [d.date, d.hall, d.fire, d.private_room, d.ac, d.total].join('\t')
    ).join('\n');
    const summaryLines = [
      ['各表总用电', data.summary.by_meter.hall, data.summary.by_meter.fire,
       data.summary.by_meter.private_room, data.summary.by_meter.ac, data.summary.total_kwh].join('\t'),
      ['月度合计', '', '', '', '', data.summary.total_kwh].join('\t'),
      ['本月电费', '', '', '', '', `¥ ${data.summary.total_cost.toFixed(2)}`].join('\t')
    ].join('\n');
    const tsvBlob = new Blob([[['日期', '大厅', '消防', '包厢', '空调', '合计(度)'].join('\t'),
      dataLines, '', summaryLines].join('\n')], { type: 'text/plain' });
    navigator.clipboard.write([new ClipboardItem({ 'text/html': htmlBlob, 'text/plain': tsvBlob })]).then(
      () => showAlert('✓ 月度报告已复制,可直接粘贴到 Numbers/Excel', 'success'),
      () => {
        // 如果 ClipboardItem 失败，用隐藏的 <table> DOM + execCommand('copy')
        copyTableViaDOM(html, '✓ 月度报告已复制');
      }
    );
  } else {
    // App 内 fallback: WKWebView 不支持 execCommand('copy')，
    // 临时把表格插入页面顶部让用户手动复制（Ctrl+A → Ctrl+C）
    console.log('[copyReport] App 内无 Swift 桥接，显示表格供手动复制');
    const container = document.getElementById('report-container');
    if (container) {
      // 移除之前的临时表格（如果有）
      const old = document.getElementById('__copyTempTable');
      if (old) old.remove();

      const tempDiv = document.createElement('div');
      tempDiv.id = '__copyTempTable';
      tempDiv.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:white;padding:20px;max-height:80vh;overflow:auto;';
      tempDiv.innerHTML = '<h3>📋 复制说明：选中下方表格后 Ctrl+C 粘贴到 Excel/Numbers</h3>' + html;
      container.insertBefore(tempDiv, container.firstChild);
      showAlert('表格已显示在页面顶部，请手动选中后 Ctrl+C 复制', 'info');
    } else {
      showAlert('复制失败，请截图保存', 'error');
    }
  }
}

// 通过隐藏的 <table> DOM 元素 + execCommand('copy') 复制
// 这是最兼容的方案：浏览器从 DOM 结构复制，粘贴到 Numbers/Excel 自动成表
function copyTableViaDOM(html, successMsg) {
  try {
    const div = document.createElement('div');
    div.innerHTML = html;
    div.style.position = 'fixed';
    div.style.opacity = '0';
    document.body.appendChild(div);

    const range = document.createRange();
    range.selectNodeContents(div);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    document.execCommand('copy');
    document.body.removeChild(div);
    sel.removeAllRanges();

    showAlert(successMsg, 'success');
  } catch (e) {
    showAlert('复制失败,请手动选择复制', 'error');
  }
}

// 每月用电复制:复制当前月各区域度数 + 金额 + 对比上月,可直接粘贴到群
function copyMonthUsage() {
  if (!_monthCopyData || !_monthCopyData.monthKey) { showAlert('暂无本月用电数据可复制', 'error'); return; }
  const d = _monthCopyData;
  const lines = [`【${d.monthKey} 各区域用电】`];
  let hasData = false;
  for (const m of CHARGE_METERS) {
    const kwh = d.per[m.key];
    if (kwh == null || kwh <= 0) { lines.push(`${m.icon} ${m.label}: —`); continue; }
    hasData = true;
    // 对比上月
    let vsP = '';
    const prevKwh = d.prev[m.key];
    if (d.hasPrev && prevKwh != null && prevKwh > 0) {
      const diff = kwh - prevKwh;
      const pct = (diff / prevKwh) * 100;
      vsP = ` 较上月${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
    }
    lines.push(`${m.icon} ${m.label}: ${kwh.toFixed(1)} 度,¥${(kwh * ELECTRICITY_PRICE).toFixed(2)}${vsP}`);
  }
  if (!hasData) { showAlert('本月暂无用电数据可复制', 'error'); return; }
  // 合计行
  let vsTotal = '';
  if (d.hasPrev && d.prevTotal > 0) {
    const diff = d.monthTotal - d.prevTotal;
    const pct = (diff / d.prevTotal) * 100;
    vsTotal = ` 较上月${diff >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(1)}%`;
  }
  lines.push(`— 合计: ${d.monthTotal.toFixed(1)} 度,¥${(d.monthTotal * ELECTRICITY_PRICE).toFixed(2)}${vsTotal}`);
  lines.push(`(当月日均 ${(d.monthTotal / d.monthDays).toFixed(1)} 度/天)`);
  const text = lines.join('\n');
  copyTextWithFallback(text, '✓ 每月用电已复制,可直接粘贴到群里');
}