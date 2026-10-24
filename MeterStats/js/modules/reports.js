/**
 * 报表模块 — 月报/年报/水电 + 趋势图 + 饼图。
 * 
 * 替代: render_charts.js, render_pie_charts.js, render_monthly.js,
 *       render_yearly.js, render_stats.js, render_weekly.js。
 */

// ==================== 数据加载 (复用 Api.reports) ====================

/**
 * 日期只留 月-日（2026-07-01 → 07-01）。
 * 页面和复制到 Numbers 都不需要年份——月份由所选报表决定。
 * 注意：它曾在 copyMonthlyReportTSV 内部以局部变量存在，导致
 * renderMonthlyReportTable 调用时 ReferenceError，所以提升到顶层。
 */
function shortDate(s) {
    var m = /^\d{4}-(\d{2}-\d{2})$/.exec(String(s || ''));
    return m ? m[1] : s;
}

function loadMonthlyReport(month) {
    if (!month) month = document.getElementById('report-month').value;
    if (!month) return Promise.resolve(null);
    return Api.reports.monthlyReport(month).then(function(data) {
        _currentReport = data;
        renderMonthlyReportTable(data);
        triggerVisiblePie();
        // 月度水电与月报同月份联动
        try { loadMonthlyUtilities(month); } catch (e) { /* 水电失败不影响用电部分 */ }
        return data;
    }).catch(function(err) {
        showAlert("加载月报失败: " + err);
        throw err;
    });
}

function loadYearlyReport(year) {
    if (!year) year = document.getElementById('yearly-year').value;
    if (!year) return Promise.resolve(null);
    return Api.reports.yearlyReport(year).then(function(data) {
        _currentYearly = data;   // 缓存供复制
        renderYearlyResult(data);
        return data;
    }).catch(function(err) {
        showAlert("加载年报失败: " + err);
        throw err;
    });
}

function loadMonthlyUtilities(month) {
    // 水电区块在「月度报告」页底部，月份跟随 report-month
    if (!month) {
        var sel = document.getElementById('report-month');
        month = sel ? sel.value : '';
    }
    if (!month) return Promise.resolve(null);
    return Api.reports.monthlyUtilities(month).then(function(data) {
        _currentUtilities = data;   // 缓存供复制
        // ⚠️ 必须用 renderMonthlyUtilities（旧版实现）：后端返回的是
        // {has_data, cur, main_kwh, sub_kwh, kitchen_kwh, water_usage, ...}，
        // 不是 {total:{...}}。旧的 renderUtilitiesHTML 判断 data.total 永远为假，
        // 结果只渲染出"月份: xxxx"一行。
        renderMonthlyUtilities(data);
        return data;
    }).catch(function(err) {
        showAlert("加载水电数据失败: " + err);
        throw err;
    });
}

/** 月度水电报表渲染（与 /api/monthly-utilities 返回结构对应） */
function renderMonthlyUtilities(data) {
    var box = document.getElementById('utilities-result');
    if (!box) return;
    var copyBtn = document.getElementById('btn-copy-utilities');
    if (!data) {
        box.innerHTML = '<div class="report-empty">加载失败,请检查后端</div>';
        if (copyBtn) copyBtn.style.display = 'none';
        return;
    }
    if (!data.has_data) {
        // 该月没录表底时，指出最近一次录入的月份，避免看着像功能失效
        var lastMonth = (function() {
            var arr = (window.CURRENT_WATER_READINGS || []).map(function(x) {
                return x.month || String(x.date || '').slice(0, 7);
            }).filter(Boolean).sort();
            return arr.length ? arr[arr.length - 1] : null;
        })();
        box.innerHTML = '<div class="report-empty">' + (data.msg || '该月未录入水电表底') +
            (lastMonth ? '<div style="margin-top:6px;font-size:12px;">最近一次录入：' + lastMonth +
                        '（切换到该月份可查看）</div>' : '') + '</div>';
        if (copyBtn) copyBtn.style.display = 'none';
        return;
    }
    var fmt = function(v, suffix) {
        return v == null ? '—' : v.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + '<small>' + suffix + '</small>';
    };
    var yuan = function(v) {
        return v == null ? '—' : '¥ ' + v.toLocaleString('zh-CN', { minimumFractionDigits: 2 });
    };
    box.innerHTML =
        '<div class="stat-grid" style="margin-top:8px;">' +
          '<div class="stat-card hall">' +
            '<div class="label">总表 ×' + (data.mult_main || 50) + '</div>' +
            '<div class="value">' + fmt(data.main_kwh, '度') + '</div>' +
            '<div class="sub">' + (data.prev_date ? data.prev_date + ' → ' + data.cur.date : '缺上月表底') + '</div>' +
          '</div>' +
          '<div class="stat-card fire">' +
            '<div class="label">分表 ×' + (data.mult_sub || 40) + '</div>' +
            '<div class="value">' + fmt(data.sub_kwh, '度') + '</div>' +
            '<div class="sub">' + (data.cur.sub_meter == null ? '未录入' : '表底 ' + data.cur.sub_meter) + '</div>' +
          '</div>' +
          '<div class="stat-card total">' +
            '<div class="label">厨房(总表−分表)</div>' +
            '<div class="value">' + fmt(data.kitchen_kwh, '度') + '</div>' +
            '<div class="sub" style="color:var(--primary);font-weight:600;">电费 ' + yuan(data.kitchen_cost) + '</div>' +
          '</div>' +
          '<div class="stat-card ac">' +
            '<div class="label">水表(用水)</div>' +
            '<div class="value">' + fmt(data.water_usage, '吨') + '</div>' +
            '<div class="sub" style="color:var(--success);font-weight:600;">水费 ' + yuan(data.water_cost) + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="sub" style="color:var(--text-muted);font-size:12px;margin-top:8px;">' +
          '总表/分表/水表每月抄一次(读数递增),总表 ×' + (data.mult_main || 50) + '、分表 ×' + (data.mult_sub || 40) +
          ' 后为实际用电,厨房用电 = 总表实际 − 分表实际(不直接抄)。电价 ' + data.price_electricity +
          ' 元/度 · 水价 ' + data.price_water + ' 元/吨。' +
        '</div>';
    if (copyBtn) copyBtn.style.display = '';
}

function getSnapshot(params) {
    return Api.reports.snapshot(params);
}

// ==================== 表格渲染 ====================

function renderMonthlyReportTable(report) {
    if (!report) return;
    var tableWrap = document.getElementById('monthly-report-table');
    var reportBody = document.getElementById('report-body');
    var reportEmpty = document.getElementById('report-empty');
    var statGrid = document.getElementById('monthly-stat-grid');

    if (!report || !report.days) {
        if (tableWrap) tableWrap.style.display = 'none';
        if (reportEmpty) reportEmpty.style.display = 'block';
        if (statGrid) statGrid.style.display = 'none';
        return;
    }
    if (reportEmpty) reportEmpty.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'block';

    var KEYS = ['hall', 'fire', 'private_room', 'ac'];
    var sums = { hall: 0, fire: 0, private_room: 0, ac: 0, total: 0 };
    var peak = { date: '', total: -1 };

    var html = '';
    for (var i = 0; i < report.days.length; i++) {
        var dd = report.days[i];
        KEYS.forEach(function(k) { sums[k] += (dd[k] || 0); });
        sums.total += (dd.total || 0);
        if ((dd.total || 0) > peak.total) { peak = { date: dd.date, total: dd.total || 0 }; }

        html += '<tr><td class="col-date">' + shortDate(dd.date) + '</td>';
        html += '<td>' + (dd.hall != null ? dd.hall.toFixed(2) : '—') + '</td>';
        html += '<td>' + (dd.fire != null ? dd.fire.toFixed(2) : '—') + '</td>';
        html += '<td>' + (dd.private_room != null ? dd.private_room.toFixed(2) : '—') + '</td>';
        html += '<td>' + (dd.ac != null ? dd.ac.toFixed(2) : '—') + '</td>';
        html += '<td class="col-total">' + (dd.total != null ? dd.total.toFixed(2) : '—') + '</td></tr>';
    }
    // 合计行
    html += '<tr class="yearly-total-row"><td class="col-date">合计</td>' +
            '<td>' + sums.hall.toFixed(2) + '</td>' +
            '<td>' + sums.fire.toFixed(2) + '</td>' +
            '<td>' + sums.private_room.toFixed(2) + '</td>' +
            '<td>' + sums.ac.toFixed(2) + '</td>' +
            '<td class="col-total">' + sums.total.toFixed(2) + '</td></tr>';
    if (reportBody) reportBody.innerHTML = html;

    // 概况卡
    if (statGrid) {
        var days = report.days.length || 1;
        var kwh = sums.total;
        var cost = kwh * ELECTRICITY_PRICE;
        var avg = kwh / days;
        var fmtN = function(v) { return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 1 }); };
        statGrid.style.display = '';
        statGrid.innerHTML =
            '<div class="trend-stat"><div class="trend-stat-label">本月总用电</div>' +
            '<div class="trend-stat-value">' + fmtN(kwh) + '<small>度</small></div>' +
            '<div class="trend-stat-sub">' + report.month + ' · ' + days + ' 天</div></div>' +
            '<div class="trend-stat"><div class="trend-stat-label">本月电费</div>' +
            '<div class="trend-stat-value">¥' + fmtN(cost) + '</div>' +
            '<div class="trend-stat-sub">电价 ' + ELECTRICITY_PRICE + ' 元/度</div></div>' +
            '<div class="trend-stat"><div class="trend-stat-label">日均用电</div>' +
            '<div class="trend-stat-value">' + fmtN(avg) + '<small>度/天</small></div>' +
            '<div class="trend-stat-sub">约 ¥' + fmtN(avg * ELECTRICITY_PRICE) + '/天</div></div>' +
            '<div class="trend-stat"><div class="trend-stat-label">最高单日</div>' +
            '<div class="trend-stat-value">' + fmtN(peak.total) + '<small>度</small></div>' +
            '<div class="trend-stat-sub">' + (peak.date ? shortDate(peak.date) : '—') + '</div></div>';
    }

    var copyBtn = document.getElementById('btn-copy-report');
    if (copyBtn) copyBtn.style.display = '';
}

function renderYearlyResult(yearData) {
    var result = document.getElementById('yearly-result');
    if (!result) return;
    if (!yearData || !yearData.months || yearData.months.length === 0) {
        result.innerHTML = '<div class="report-empty">该年份没有数据</div>';
        var cb0 = document.getElementById('btn-copy-yearly');
        if (cb0) cb0.style.display = 'none';
        return;
    }

    var fmtN = function(v, d) {
        if (v == null) return '—';
        return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
    };
    var yuan = function(v) { return v == null ? '—' : '¥ ' + fmtN(v, 2); };

    // ---- 年度合计 ----
    var tKwh = 0, tCost = 0, tByMeter = { hall: 0, fire: 0, private_room: 0, ac: 0 };
    var peakMonth = null, peakKwh = -1;
    yearData.months.forEach(function(m) {
        var k = m.total_kwh || 0;
        tKwh += k;
        tCost += m.total_cost || 0;
        if (k > peakKwh) { peakKwh = k; peakMonth = m.month; }
        var bm = m.by_meter || {};
        Object.keys(tByMeter).forEach(function(kk) { tByMeter[kk] += bm[kk] || 0; });
    });
    var monthCount = yearData.months.length;
    var avgMonth = monthCount ? tKwh / monthCount : 0;
    var ut = yearData.utilities_total;
    var price = ELECTRICITY_PRICE || 0.9;

    var html = '';

    // ---- 概况卡（与每日/每周/月度同一套视觉）----
    html += '<div class="trend-stat-grid">';
    html += '<div class="trend-stat"><div class="trend-stat-label">年度总用电</div><div class="trend-stat-value">' +
            fmtN(tKwh, 0) + '<small>度</small></div><div class="trend-stat-sub">' + monthCount + ' 个月</div></div>';
    html += '<div class="trend-stat"><div class="trend-stat-label">年度电费</div><div class="trend-stat-value">' +
            yuan(tCost) + '</div><div class="trend-stat-sub">电价 ' + price + ' 元/度</div></div>';
    html += '<div class="trend-stat"><div class="trend-stat-label">月均用电</div><div class="trend-stat-value">' +
            fmtN(avgMonth, 0) + '<small>度</small></div><div class="trend-stat-sub">约 ' + yuan(avgMonth * price) + '</div></div>';
    html += '<div class="trend-stat"><div class="trend-stat-label">用电最高月</div><div class="trend-stat-value">' +
            fmtN(peakKwh, 0) + '<small>度</small></div><div class="trend-stat-sub">' + (peakMonth || '—') + '</div></div>';
    if (ut) {
        html += '<div class="trend-stat"><div class="trend-stat-label">年度厨房用电</div><div class="trend-stat-value">' +
                fmtN(ut.kitchen_kwh, 0) + '<small>度</small></div><div class="trend-stat-sub" style="color:var(--primary);font-weight:600;">' +
                yuan(ut.kitchen_cost) + '</div></div>';
        html += '<div class="trend-stat"><div class="trend-stat-label">年度用水</div><div class="trend-stat-value">' +
                fmtN(ut.water_usage, 0) + '<small>吨</small></div><div class="trend-stat-sub" style="color:var(--success);font-weight:600;">' +
                yuan(ut.water_cost) + '</div></div>';
    }
    html += '</div>';

    // ---- 各月用电趋势图 ----
    html += '<h3 class="yearly-section-title">📈 各月用电趋势</h3>';
    html += '<div class="chart-wrap"><canvas id="chart-yearly-bar"></canvas></div>';

    // ---- 用电明细表 ----
    html += '<h3 class="yearly-section-title">⚡ 各月用电</h3>';
    html += '<div class="table-container"><table class="history-table yearly-table"><thead><tr>' +
            '<th>月份</th><th>1#大厅</th><th>2#消防</th><th>3#包厢</th><th>4#空调</th>' +
            '<th class="col-total">合计(度)</th><th>电费(元)</th></tr></thead><tbody>';
    yearData.months.forEach(function(m) {
        var bm = m.by_meter || {};
        html += '<tr><td>' + m.month + '</td>' +
                '<td>' + fmtN(bm.hall, 0) + '</td>' +
                '<td>' + fmtN(bm.fire, 1) + '</td>' +
                '<td>' + fmtN(bm.private_room, 0) + '</td>' +
                '<td>' + fmtN(bm.ac, 0) + '</td>' +
                '<td class="col-total">' + fmtN(m.total_kwh, 1) + '</td>' +
                '<td>' + fmtN(m.total_cost, 2) + '</td></tr>';
    });
    html += '<tr class="yearly-total-row"><td>合计</td>' +
            '<td>' + fmtN(tByMeter.hall, 0) + '</td>' +
            '<td>' + fmtN(tByMeter.fire, 1) + '</td>' +
            '<td>' + fmtN(tByMeter.private_room, 0) + '</td>' +
            '<td>' + fmtN(tByMeter.ac, 0) + '</td>' +
            '<td class="col-total">' + fmtN(tKwh, 1) + '</td>' +
            '<td>' + fmtN(tCost, 2) + '</td></tr>';
    html += '</tbody></table></div>';

    // ---- 水电明细表 ----
    var hasUtil = yearData.months.some(function(m) {
        return m.utilities && m.utilities.has_data;
    });
    if (hasUtil) {
        html += '<h3 class="yearly-section-title">💧 各月水电</h3>';
        html += '<div class="table-container"><table class="history-table yearly-table"><thead><tr>' +
                '<th>月份</th><th>总表(度)</th><th>分表(度)</th><th>厨房(度)</th>' +
                '<th>厨房电费</th><th>用水(吨)</th><th>水费</th></tr></thead><tbody>';
        yearData.months.forEach(function(m) {
            var u = m.utilities || {};
            if (!u.has_data) {
                html += '<tr style="opacity:.55;"><td>' + m.month + '</td>' +
                        '<td colspan="6" style="text-align:center;">该月未录入水电表底</td></tr>';
                return;
            }
            html += '<tr><td>' + m.month + '</td>' +
                    '<td>' + fmtN(u.main_kwh, 0) + '</td>' +
                    '<td>' + fmtN(u.sub_kwh, 0) + '</td>' +
                    '<td class="col-total">' + fmtN(u.kitchen_kwh, 0) + '</td>' +
                    '<td>' + fmtN(u.kitchen_cost, 2) + '</td>' +
                    '<td>' + fmtN(u.water_usage, 1) + '</td>' +
                    '<td>' + fmtN(u.water_cost, 2) + '</td></tr>';
        });
        if (ut) {
            html += '<tr class="yearly-total-row"><td>合计</td>' +
                    '<td>' + fmtN(ut.main_kwh, 0) + '</td>' +
                    '<td>' + fmtN(ut.sub_kwh, 0) + '</td>' +
                    '<td class="col-total">' + fmtN(ut.kitchen_kwh, 0) + '</td>' +
                    '<td>' + fmtN(ut.kitchen_cost, 2) + '</td>' +
                    '<td>' + fmtN(ut.water_usage, 1) + '</td>' +
                    '<td>' + fmtN(ut.water_cost, 2) + '</td></tr>';
        }
        html += '</tbody></table></div>';
        html += '<div class="sub" style="color:var(--text-muted);font-size:12px;margin-top:8px;">' +
                '总表 ×' + ((yearData.months.find(function(m){return m.utilities && m.utilities.mult_main;}) || {utilities:{}}).utilities.mult_main || 50) +
                '、分表 ×' + ((yearData.months.find(function(m){return m.utilities && m.utilities.mult_sub;}) || {utilities:{}}).utilities.mult_sub || 40) +
                ' 为实际用电；厨房用电 = 总表实际 − 分表实际。</div>';
    }

    result.innerHTML = html;

    // 图表必须在 innerHTML 之后绘制（canvas 才存在）
    drawYearlyBarChart(yearData);

    var copyBtn = document.getElementById('btn-copy-yearly');
    if (copyBtn) copyBtn.style.display = '';
}

/** 各月用电趋势：12 个月堆叠柱状（4 块表叠成当月总量） */
function drawYearlyBarChart(yearData) {
    var cv = document.getElementById('chart-yearly-bar');
    if (!cv) return;
    var KEYS = ['hall', 'fire', 'private_room', 'ac'];
    var labels = yearData.months.map(function(m) { return String(m.month).slice(5) + '月'; });
    var datasets = KEYS.map(function(k) {
        return {
            label: LABELS(k),
            data: yearData.months.map(function(m) { return (m.by_meter || {})[k] || 0; }),
            backgroundColor: COLORS(k) + 'dd',
            stack: 's',
            borderRadius: 3,
        };
    });

    if (window._yearlyBarChart) { window._yearlyBarChart.destroy(); window._yearlyBarChart = null; }
    window._yearlyBarChart = new Chart(cv.getContext('2d'), {
        type: 'bar',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 }, padding: 12 } },
                tooltip: {
                    callbacks: {
                        label: function(c) {
                            var v = c.parsed.y;
                            if (v == null || v <= 0) return null;
                            return c.dataset.label + ': ' + Math.round(v).toLocaleString() + ' 度';
                        },
                        footer: function(items) {
                            var sum = items.reduce(function(acc, it) { return acc + (it.parsed.y || 0); }, 0);
                            return '合计: ' + Math.round(sum).toLocaleString() + ' 度';
                        },
                    },
                },
            },
            scales: {
                x: { stacked: true, grid: { display: false } },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    title: { display: true, text: '用电 (度)' },
                    ticks: { callback: function(v) { return Number(v).toLocaleString(); } },
                },
            },
        },
    });
}

function renderUtilitiesHTML(data) {
    if (!data) return '<div class="report-empty">选择月份查看水电数据</div>';
    var html = '<div style="padding:12px;">';
    if (data.month) html += '<p><strong>月份:</strong> ' + data.month + '</p>';
    if (data.total) {
        html += '<table class="history-table"><thead><tr><th>总表</th><th>分表</th><th>水表</th></tr></thead><tbody>';
        html += '<tr><td>' + (data.total.main_meter != null ? data.total.main_meter.toFixed(1) : '—') + '</td>';
        html += '<td>' + (data.total.sub_meter != null ? data.total.sub_meter.toFixed(1) : '—') + '</td>';
        html += '<td>' + (data.total.water != null ? data.total.water.toFixed(1) : '—') + '</td></tr>';
        html += '</tbody></table>';
    }
    html += '</div>';
    return html;
}

// ==================== 趋势图 + 饼图 (复用现有逻辑) ====================

// 注意: renderTrendChart / triggerVisiblePie / renderDailyPie / renderMonthlyPie
// 的真实实现由 js/modules/render_charts.js + render_pie_charts.js 提供（本文件之后加载）。
// 这里不要留空壳 —— 空定义会因后加载顺序覆盖掉 accessibility.js 里的真实
// triggerVisiblePie，导致占比饼图永远不渲染。


function refreshDayCopySelect(readings, charges) {
    var sel = document.getElementById('day-copy-date');
    if (!sel) return;
    var rs = (readings || []).filter(function(r) { return r.hall != null; }).sort(function(a, b) { return a.date.localeCompare(b.date); });
    if (rs.length < 2) { sel.innerHTML = '<option value="">(需至少两次抄表)</option>'; return; }
    var first = new Date(rs[0].date);
    var last = new Date(rs[rs.length - 1].date);
    var copyDates = [];
    for (var d = new Date(first); d < last; d.setDate(d.getDate() + 1)) { copyDates.push(formatDate(d)); }
    sel.innerHTML = copyDates.map(function(dd) { return '<option value="' + dd + '">' + dd + '</option>'; }).join('');
    sel.value = copyDates.length ? copyDates[copyDates.length - 1] : '';
}

function calcDayUsage(readings, charges, day) {
    var rs = (readings || []).filter(function(r) { return r.hall != null; }).sort(function(a, b) { return a.date.localeCompare(b.date); });
    var a = null, b = null;
    for (var i = 0; i < rs.length - 1; i++) {
        if (day >= rs[i].date && day < rs[i + 1].date) { a = rs[i]; b = rs[i + 1]; break; }
    }
    if (!a || !b) return null;
    var spanDays = Math.round((new Date(b.date) - new Date(a.date)) / 86400000);
    if (spanDays <= 0) return null;
    var per = {};
    var totalKwh = 0, totalCost = 0;
    for (var i = 0; i < CHARGE_METERS.length; i++) {
        var m = CHARGE_METERS[i];
        if (a[m.key] == null || b[m.key] == null) { per[m.key] = null; continue; }
        var total = realKwh(a[m.key] - b[m.key], m.key) + sumChargesBetween(charges, m.key, a.date, b.date);
        var kwh = total / spanDays;
        var cost = kwh * ELECTRICITY_PRICE;
        per[m.key] = { kwh: kwh, cost: cost };
        totalKwh += kwh; totalCost += cost;
    }
    return { date: day, prevDate: a.date, nextDate: b.date, spanDays: spanDays, per: per, totalKwh: totalKwh, totalCost: totalCost };
}

// ==================== 状态栏和选择器刷新 (从旧版 app.js 迁移) ====================

/** 更新底部状态栏 */
function updateStatusBar(readings, charges) {
    readings = (readings || []).filter(function(r) { return r.hall != null; });
    var bar = document.getElementById('status-bar');
    if (!bar) return;
    if (!readings || readings.length === 0) { bar.style.display = 'none'; return; }
    // ⚠️ 这里不能直接 display='flex'：updateStatusBar 在数据刷新时会被反复调用，
    // 无条件设成 flex 会把切换页面时设好的隐藏覆盖掉，导致每个页面顶部都冒出来。
    // 交给 syncStatusBarVisibility 按当前页面判断（白名单见 navigation.js）。
    if (typeof syncStatusBarVisibility === 'function') {
        syncStatusBarVisibility(true);
    } else {
        bar.style.display = 'flex';
    }

    var sorted = readings.slice().sort(function(a, b) { return a.date.localeCompare(b.date); });
    var last = sorted[sorted.length - 1];
    var gap = daysBetween(last.date, todayStr());
    var stLast = document.getElementById('st-last-reading');
    if (stLast) {
        stLast.textContent = gap <= 0 ? '今天已抄表(' + last.date + ')' : '上次抄表 ' + last.date + ' · ' + gap + ' 天前';
    }

    // 本月用电 + 电费
    var monthKey = last.date.slice(0, 7);
    var monthRs = sorted.filter(function(r) { return r.date.startsWith(monthKey); });
    var kwh = 0;
    if (monthRs.length >= 2) {
        var f = monthRs[0], l = monthRs[monthRs.length - 1];
        var keys = ['hall', 'fire', 'private_room', 'ac'];
        for (var ki = 0; ki < keys.length; ki++) {
            var k = keys[ki];
            kwh += realKwh(f[k] - l[k], k) + sumChargesBetween(charges, k, f.date, l.date);
        }
    }
    var stKwh = document.getElementById('st-month-kwh');
    if (stKwh) stKwh.textContent = '本月用电 ' + kwh.toFixed(0) + ' 度';
    var stCost = document.getElementById('st-month-cost');
    if (stCost) stCost.textContent = '电费 ¥ ' + (kwh * ELECTRICITY_PRICE).toFixed(0);

    // 预警
    var alertCount = 0;
    for (var mi = 0; mi < CHARGE_METERS.length; mi++) {
        var m = CHARGE_METERS[mi];
        var remaining = last[m.key] * MULTIPLIER(m.key);
        var usage = calcMonthlyDailyUsage(readings, charges, m.key);
        if (usage && usage.daily > 0 && remaining / usage.daily < 7) alertCount++;
    }
    var stAlerts = document.getElementById('st-alerts');
    if (stAlerts) {
        stAlerts.textContent = alertCount > 0 ? alertCount + ' 块表需关注' : '余量正常';
        stAlerts.className = alertCount > 0 ? 'em' : '';
    }
}

/** 刷新所有月份/年份选择器 */
function refreshMonthSelectors() {
    var readings = State.get("readings") || [];
    var charges = State.get("charges") || [];
    var water = State.get("water") || [];

    var monthsSet = new Set();
    readings.forEach(function(r) { monthsSet.add(r.date.slice(0, 7)); });
    var months = Array.from(monthsSet).sort();

    // 合并月份：抄表 / 充值 / 水电 任一有数据即出现（三 Tab 共用一个筛选）
    var allMonthsSet = new Set();
    readings.forEach(function(r) { allMonthsSet.add(r.date.slice(0, 7)); });
    charges.forEach(function(c) { allMonthsSet.add(c.date.slice(0, 7)); });
    water.forEach(function(w) { allMonthsSet.add(w.date.slice(0, 7)); });
    var allMonths = Array.from(allMonthsSet).sort();

    function fillSelect(selId, opts, valid) {
        var sel = document.getElementById(selId);
        if (!sel) return;
        var pool = valid || months;
        var prev = sel.value;
        sel.innerHTML = opts;
        var newVal = prev && pool.includes(prev) ? prev : (pool.length > 0 ? pool[pool.length - 1] : '');
        if (sel.value !== newVal) sel.value = newVal;
    }

    var opts = months.length === 0
        ? '<option value="">(暂无数据)</option>'
        : months.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');
    var allOpts = allMonths.length === 0
        ? '<option value="">(暂无数据)</option>'
        : allMonths.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');

    fillSelect('stats-month', opts);
    fillSelect('record-month', allOpts, allMonths);

    // 月度报告月份
    var reportSel = document.getElementById('report-month');
    if (reportSel) {
        fillSelect('report-month', opts);
        if (reportSel.value && document.getElementById('section-report-monthly')) {
            var display = document.getElementById('section-report-monthly').style.display;
            if (display === '' || display === 'flex') renderMonthlyPie(reportSel.value);
        }
    }

    // 年度汇总
    var years = [];
    for (var i = 0; i < months.length; i++) { years.push(months[i].slice(0, 4)); }
    years = Array.from(new Set(years)).sort();

    var yearSel = document.getElementById('yearly-year');
    if (yearSel) {
        var yopts = years.length === 0
            ? '<option value="">(暂无数据)</option>'
            : years.map(function(y) { return '<option value="' + y + '">' + y + ' 年</option>'; }).join('');
        var prevY = yearSel.value;  // 必须在重写 options 之前读取，否则永远是第一个选项
        yearSel.innerHTML = yopts;
        var newY = prevY && years.includes(prevY) ? prevY : (years.length > 0 ? years[years.length - 1] : '');
        if (yearSel.value !== newY) {
            yearSel.value = newY;
            loadYearlyReport();
        }
    }

    // 抄表提醒横幅（init.js 中也有类似逻辑）
    var meterReminder = document.getElementById('meter-reminder');
    if (meterReminder) {
        var lastDate = readings.length > 0 ? readings[readings.length - 1].date : null;
        if (lastDate) {
            var gap = daysBetween(lastDate, todayStr());
            if (gap >= 3) {
                var reminderText = document.getElementById('meter-reminder-text');
                if (reminderText) {
                    reminderText.textContent = '📅 距离上次抄表(' + lastDate + ')已 ' + gap + ' 天,记得去抄 4 块表的表底';
                }
                meterReminder.style.display = 'flex';
            } else {
                meterReminder.style.display = 'none';
            }
        }
    }

    // 首次访问提示
    if (readings.length === 0 && charges.length === 0) {
        var el = document.getElementById('welcome-alert');
        if (el) {
            // 避免重复显示，用 sessionStorage
            if (!sessionStorage.getItem('welcome_shown')) {
                sessionStorage.setItem('welcome_shown', '1');
                showAlert('👋 欢迎!先录入今天的抄表数据开始。', 'info');
            }
        }
    }
}

/** 检查并提示水电数据迁移（从旧版 app.js 迁移） */
async function checkAndPromptMigration() {
    if (window.MIGRATION_CHECKED) return;
    window.MIGRATION_CHECKED = true;

    try {
        var status = await Api.adminTools.migrateWaterStatus();
        if (!status || !status.needs_migration) return;

        var waterDates = status.water_dates || [];
        var datesText = waterDates.length <= 5
            ? waterDates.join('、')
            : waterDates.length + ' 个日期';

        var confirm = await showModal({
            title: '🔄 数据升级提示',
            icon: '⬆️',
            iconKind: 'warn',
            body: '<p>检测到 <strong>' + status.water_in_readings + ' 条抄表记录</strong>包含水电字段（总表/分表/水表）。</p>' +
                '<p>涉及日期：<strong>' + datesText + '</strong></p>' +
                '<p>本次升级将水电数据分离到独立文件，保证：</p>' +
                '<ul style="text-align:left;font-size:13px;color:var(--text-muted);">' +
                '<li>总表/分表/水表可以独立增删，不干扰电表抄表</li>' +
                '<li>每月水电费用计算完全准确</li>' +
                '<li>自动备份当前数据（可随时回滚）</li></ul>' +
                (status.conflicts_with_existing > 0
                    ? '<p style="color:var(--warning);font-size:13px;">⚠️ 已有 ' + status.conflicts_with_existing + ' 条独立水电记录将被覆盖</p>'
                    : '') +
                '<p style="margin-top:12px;">是否立即执行升级？</p>',
            confirmText: '立即升级',
            confirmKind: 'primary',
            cancelText: '稍后再说',
        });

        if (!confirm) return;

        // 执行迁移
        try {
            var result = await Api.adminTools.migrateWater();
            if (result.ok) {
                showAlert('✅ 迁移完成！' + result.migrated_count + ' 条水电记录已分离。', 'success');
                if (typeof refreshAndRender === 'function') refreshAndRender();
            } else {
                showAlert('迁移失败：' + (result.error || '未知错误'), 'error');
            }
        } catch (e) {
            showAlert('迁移请求失败：' + e.message, 'error');
        }
    } catch (e) {
        console.warn('Migration check failed:', e);
    }
}

// ==================== 复制到剪贴板 ====================

/**
 * 统一富文本复制：
 * 1) macOS App 内优先走 Swift 桥 macOSCopyToClipboard（同时写 .string/.tabularText/.html，
 *    粘到 Excel / Numbers / 微信 都是表格）—— 之前前端从没调用过这个桥，
 *    导致 WKWebView 里 navigator.clipboard / execCommand 静默失败，"复制"没反应。
 * 2) 浏览器环境回退到 navigator.clipboard → execCommand。
 */
function copyRichText(tsv, html, successMsg) {
    try {
        var handlers = window.webkit && window.webkit.messageHandlers;
        if (handlers && handlers.macOSCopyToClipboard) {
            handlers.macOSCopyToClipboard.postMessage({ html: html || '', tsv: tsv });
            showAlert(successMsg || '✓ 已复制', 'success');
            return;
        }
    } catch (e) { /* 桥不可用则回退 */ }
    copyTextWithFallback(tsv, successMsg);
}

/**
 * 生成 TSV 文本。
 * headers 传 null 表示不输出表头——粘到 Numbers/Excel 时，
 * 多余的表头行会挤掉用户已有的标题行，还得手动删。
 */
function _tsvTable(headers, rows) {
    var out = [];
    if (headers) out.push(headers.join('\t'));
    rows.forEach(function(r) {
        out.push(r.map(function(c) { return c == null ? '' : c; }).join('\t'));
    });
    return out.join('\n');
}

/**
 * 生成粘贴用 HTML 表格。
 *
 * ⚠️ 三个必须注意的点：
 * 1) 必须带 <meta charset="utf-8">。缺这一句时 Numbers / Excel 会按
 *    Latin-1 解析 HTML 片段，中文全部变成「姣吃爛鏊」这类乱码。
 * 2) 保留 thead（列名）但绝不输出 caption（报表标题）：
 *    报表标题会占掉粘贴位置的第一行，列名才是用户表格需要的。
 * 3) 对齐要写三重：<style> 块 + align 属性 + inline style，
 *    并且纯数字单元格还要过一遍 _htmlCell（见下）才能居中。
 */
/**
 * 单元格内容处理（仅用于 HTML 粘贴）。
 *
 * Numbers 粘贴时按内容类型决定单元格格式：
 *   纯数字（3476 / 768.00）→ 数字格式，忽略 HTML 的 text-align，默认右对齐
 *   含文字（8300.0 度 / ¥3510.00 / 总表）→ 文本格式，跟随 text-align 居中
 * 这就是「中文居中、数字不居中」的由来。
 * 给纯数字前置零宽空格 U+200B，使其被判为文本从而一起居中；
 * 零宽字符不可见，显示效果不变。代价：这些格子不再参与数值求和。
 */
function _htmlCell(v) {
    var t = (v == null) ? '' : String(v);
    if (/^-?\d+(\.\d+)?$/.test(t)) return '\u200B' + t;
    return t;
}

function _htmlTable(headers, rows) {
    var h = '<meta charset="utf-8">';
    h += '<style>table,thead,tbody,tr,th,td{text-align:center!important;vertical-align:middle;}</style>';
    h += '<table border="1" align="center" style="border-collapse:collapse;text-align:center;font-family:PingFang SC,Microsoft YaHei,sans-serif;font-size:12pt;">';
    if (headers && headers.length) {
        h += '<thead><tr>' + headers.map(function(x) {
            return '<th align="center" style="text-align:center;vertical-align:middle;padding:5px 9px;background:#f3f4f6;">' + _htmlCell(x) + '</th>';
        }).join('') + '</tr></thead>';
    }
    h += '<tbody>';
    rows.forEach(function(r) {
        h += '<tr>' + r.map(function(c) {
            return '<td align="center" style="text-align:center;vertical-align:middle;padding:5px 9px;">' + _htmlCell(c) + '</td>';
        }).join('') + '</tr>';
    });
    h += '</tbody></table>';
    return h;
}

/** 复制月度报告（用电明细 + 水电） */
function copyMonthlyReportTSV() {
    var d = _currentReport;
    if (!d || !d.days || !d.days.length) {
        showAlert('请先选择月份加载数据', 'info');
        return;
    }
    var n = function(v, dig) {
        if (v == null) return '';
        return Number(v).toFixed(dig == null ? 2 : dig);
    };
    // 日期只留 月-日（用顶层 shortDate，见文件开头）
    // 电表列名不带 "1#" "2#" 序号
    var headers = ['日期', '大厅', '消防', '包厢', '空调', '合计(度)'];
    var rows = [];
    d.days.forEach(function(x) {
        rows.push([shortDate(x.date), n(x.hall), n(x.fire), n(x.private_room), n(x.ac), n(x.total)]);
    });
    var s = d.summary || {};
    var bm = s.by_meter || {};
    rows.push(['各表合计', n(bm.hall, 1), n(bm.fire, 1), n(bm.private_room, 1), n(bm.ac, 1), n(s.total_kwh, 1)]);
    var price = (typeof ELECTRICITY_PRICE !== 'undefined' ? ELECTRICITY_PRICE : 0.9);
    rows.push(['本月电费', '', '', '', '', n((s.total_kwh || 0) * price, 2)]);

    // 只复制抄表数据；水电用「💧 水电用量」旁的独立复制按钮，两者不混在一起
    copyRichText(_tsvTable(headers, rows), _htmlTable(headers, rows), '✓ 抄表数据已复制');
}

/** 复制当月水电用量（总表 / 分表 / 厨房 / 水表，含上下月表底读数） */
function copyUtilitiesTSV() {
    var u = _currentUtilities;
    if (!u || !u.has_data) {
        showAlert('该月没有水电数据', 'info');
        return;
    }
    var f = function(v, dig) {
        if (v == null) return '—';
        return Number(v).toFixed(dig == null ? 1 : dig);
    };
    // 表底读数按原始数值展示（去掉多余小数）
    var meter = function(v) {
        if (v == null) return '—';
        return String(Number(v));
    };
    // 列名用具体月份数字，方便对账
    var curM = (u.cur && u.cur.date) ? parseInt(u.cur.date.slice(5, 7), 10) : null;
    var prevM = u.prev_date ? parseInt(u.prev_date.slice(5, 7), 10) : null;
    var prevLabel = prevM ? prevM + '月表显' : '上月表显';
    var curLabel = curM ? curM + '月表显' : '本月表显';

    var p = u.prev || {};
    var c = u.cur || {};

    // 数字字段不带单位（度/吨/¥），表头与项目名已能看出含义
    var headers = ['项目', prevLabel, curLabel, '用量', '费用'];
    var rows = [
        ['总表', meter(p.main_meter), meter(c.main_meter), f(u.main_kwh), ''],
        ['分表', meter(p.sub_meter), meter(c.sub_meter), f(u.sub_kwh), ''],
        ['厨房', '', '', f(u.kitchen_kwh), f(u.kitchen_cost, 2)],
        ['水表', meter(p.water), meter(c.water), f(u.water_usage), f(u.water_cost, 2)],
    ];
    copyRichText(_tsvTable(headers, rows), _htmlTable(headers, rows), '✓ 水电数据已复制');
}

/** 复制年度汇总（用电 + 水电） */
function copyYearlyTSV() {
    var d = _currentYearly;
    if (!d || !d.months || !d.months.length) {
        showAlert('请先选择年份加载数据', 'info');
        return;
    }
    var f0 = function(v) { return v == null ? '' : Number(v).toFixed(0); };
    var f1 = function(v) { return v == null ? '' : Number(v).toFixed(1); };
    var f2 = function(v) { return v == null ? '' : Number(v).toFixed(2); };

    // 列名不带 "1#" 序号，与月度报告复制的格式保持一致
    var headers = ['月份', '大厅', '消防', '包厢', '空调', '合计(度)', '电费(元)'];
    var rows = d.months.map(function(m) {
        var bm = m.by_meter || {};
        return [m.month, f0(bm.hall), f1(bm.fire), f0(bm.private_room), f0(bm.ac), f1(m.total_kwh), f2(m.total_cost)];
    });
    var tKwh = 0, tCost = 0, tb = { hall: 0, fire: 0, private_room: 0, ac: 0 };
    d.months.forEach(function(m) {
        tKwh += m.total_kwh || 0;
        tCost += m.total_cost || 0;
        var bm = m.by_meter || {};
        Object.keys(tb).forEach(function(k) { tb[k] += bm[k] || 0; });
    });
    rows.push(['合计', f0(tb.hall), f1(tb.fire), f0(tb.private_room), f0(tb.ac), f1(tKwh), f2(tCost)]);

    var tsv = _tsvTable(headers, rows);
    var html = _htmlTable(headers, rows);

    var ut = d.utilities_total;
    if (ut) {
        var uHeaders = ['月份', '总表(度)', '分表(度)', '厨房(度)', '厨房电费', '用水(吨)', '水费'];
        var uRows = d.months.map(function(m) {
            var u = m.utilities || {};
            if (!u.has_data) return [m.month, '未录入', '', '', '', '', ''];
            return [m.month, f0(u.main_kwh), f0(u.sub_kwh), f0(u.kitchen_kwh), f2(u.kitchen_cost), f1(u.water_usage), f2(u.water_cost)];
        });
        uRows.push(['合计', f0(ut.main_kwh), f0(ut.sub_kwh), f0(ut.kitchen_kwh), f2(ut.kitchen_cost), f1(ut.water_usage), f2(ut.water_cost)]);
        tsv += '\n\n' + _tsvTable(uHeaders, uRows);
        html += '<p></p>' + _htmlTable(uHeaders, uRows);
    }

    copyRichText(tsv, html, '✓ 年度汇总已复制');
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { loadMonthlyReport, loadYearlyReport, loadMonthlyUtilities, getSnapshot,
                       renderMonthlyReportTable, renderYearlyResult, renderUtilitiesHTML,
                       renderTrendChart, triggerVisiblePie, renderMonthlyPie, renderDailyPie,
                       refreshDayCopySelect, calcDayUsage, copyDayUsage,
                       updateStatusBar, refreshMonthSelectors, checkAndPromptMigration };
}
