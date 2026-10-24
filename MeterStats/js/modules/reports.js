/**
 * 报表模块 — 月报/年报/水电 + 趋势图 + 饼图。
 * 
 * 替代: render_charts.js, render_pie_charts.js, render_monthly.js,
 *       render_yearly.js, render_stats.js, render_weekly.js。
 */

// ==================== 数据加载 (复用 Api.reports) ====================

function loadMonthlyReport(month) {
    if (!month) month = document.getElementById('report-month').value;
    if (!month) return Promise.resolve(null);
    return Api.reports.monthlyReport(month).then(function(data) {
        _currentReport = data;
        renderMonthlyReportTable(data);
        triggerVisiblePie();
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
        renderYearlyResult(data);
        return data;
    }).catch(function(err) {
        showAlert("加载年报失败: " + err);
        throw err;
    });
}

function loadMonthlyUtilities(month) {
    if (!month) month = document.getElementById('utilities-month').value;
    if (!month) return Promise.resolve(null);
    return Api.reports.monthlyUtilities(month).then(function(data) {
        document.getElementById('utilities-result').innerHTML = renderUtilitiesHTML(data);
        return data;
    }).catch(function(err) {
        showAlert("加载水电报表失败: " + err);
        throw err;
    });
}

function getSnapshot(params) {
    return Api.reports.snapshot(params);
}

// ==================== 表格渲染 ====================

function renderMonthlyReportTable(report) {
    if (!report) return;
    var tableWrap = document.getElementById('monthly-report-table');
    var reportBody = document.getElementById('report-body');
    var reportSummary = document.getElementById('report-summary');
    var reportEmpty = document.getElementById('report-empty');

    if (!report || !report.days) {
        tableWrap.style.display = 'none';
        reportEmpty.style.display = 'block';
        return;
    }
    reportEmpty.style.display = 'none';
    tableWrap.style.display = 'block';

    var html = '';
    for (var i = 0; i < report.days.length; i++) {
        var dd = report.days[i];
        html += '<tr><td class="col-date">' + dd.date + '</td>';
        html += '<td>' + (dd.hall != null ? dd.hall.toFixed(2) : '—') + '</td>';
        html += '<td>' + (dd.fire != null ? dd.fire.toFixed(2) : '—') + '</td>';
        html += '<td>' + (dd.private_room != null ? dd.private_room.toFixed(2) : '—') + '</td>';
        html += '<td>' + (dd.ac != null ? dd.ac.toFixed(2) : '—') + '</td>';
        html += '<td class="col-total">' + (dd.total != null ? dd.total.toFixed(2) : '—') + '</td></tr>';
    }
    reportBody.innerHTML = html;

    if (report.summary) {
        reportSummary.innerHTML = '总计: ' + report.summary.total_kwh.toFixed(1) + ' 度, ¥' + (report.summary.total_kwh * ELECTRICITY_PRICE).toFixed(2);
    }

    document.getElementById('btn-copy-report').style.display = '';
    document.getElementById('btn-export-word').style.display = '';
}

function renderYearlyResult(yearData) {
    var result = document.getElementById('yearly-result');
    if (!yearData || !yearData.months) { result.innerHTML = '<div class="report-empty">选择年份查看年度汇总</div>'; return; }
    var html = '';
    for (var i = 0; i < yearData.months.length; i++) {
        var m = yearData.months[i];
        html += '<div style="margin-bottom:8px;">' + m.month + ': ' + (m.total_kwh || 0).toFixed(1) + ' 度, ¥' + (m.total_cost || 0).toFixed(2) + '</div>';
    }
    result.innerHTML = html;
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

function renderTrendChart(readings, charges) {
    // 复用 render_charts.js 逻辑 - 已在 data_fetch.js 的 refreshAndRender 中调用
}

function triggerVisiblePie() {
    // 在可见报表页时渲染饼图
}

function renderMonthlyPie(month) {
    if (!_currentReport || !_currentReport.pies) return;
}

function renderDailyPie(day) {
    // 单日饼图渲染
}

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

function copyDayUsage() {
    var sel = document.getElementById('day-copy-date');
    if (!sel || !sel.value) { showAlert('请先选择日期(需至少两次抄表)', 'error'); return; }
    var date = sel.value;
    var usage = calcDayUsage(CURRENT_READINGS, CURRENT_CHARGES, date);
    if (!usage) { showAlert(date + ' 没有可用的用电区间,无法计算', 'error'); return; }
    var lines = ['【' + date + ' 各区域用电】'];
    for (var i = 0; i < CHARGE_METERS.length; i++) {
        var m = CHARGE_METERS[i];
        var p = usage.per[m.key];
        if (p == null) { lines.push(m.icon + ' ' + m.label + ': —'); continue; }
        lines.push(m.icon + ' ' + m.label + ': ' + p.kwh.toFixed(1) + ' 度,¥' + p.cost.toFixed(2));
    }
    lines.push('— 合计: ' + usage.totalKwh.toFixed(1) + ' 度,¥' + usage.totalCost.toFixed(2));
    var spanNote = usage.spanDays > 1 ? '(区间 ' + usage.prevDate + ' → ' + usage.nextDate + ' 共 ' + usage.spanDays + ' 天均摊)' : '(区间 ' + usage.prevDate + ' → ' + usage.nextDate + ')';
    lines.push(spanNote);
    copyTextWithFallback(lines.join('\n'), '✓ 单天用电已复制,可直接粘贴到群里');
}

// ==================== 状态栏和选择器刷新 (从旧版 app.js 迁移) ====================

/** 更新底部状态栏 */
function updateStatusBar(readings, charges) {
    readings = (readings || []).filter(function(r) { return r.hall != null; });
    var bar = document.getElementById('status-bar');
    if (!bar) return;
    if (!readings || readings.length === 0) { bar.style.display = 'none'; return; }
    bar.style.display = 'flex';

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

    function fillSelect(selId, opts) {
        var sel = document.getElementById(selId);
        if (!sel) return;
        var prev = sel.value;
        sel.innerHTML = opts;
        var newVal = prev && months.includes(prev) ? prev : (months.length > 0 ? months[months.length - 1] : '');
        if (sel.value !== newVal) sel.value = newVal;
    }

    var opts = months.length === 0
        ? '<option value="">(暂无数据)</option>'
        : months.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');

    fillSelect('stats-month', opts);
    fillSelect('history-month', opts);

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
        yearSel.innerHTML = yopts;
        var prevY = yearSel.value;
        var newY = prevY && years.includes(prevY) ? prevY : (years.length > 0 ? years[years.length - 1] : '');
        if (yearSel.value !== newY) {
            yearSel.value = newY;
            loadYearlyReport();
        }
    }

    // 充值记录月份
    var cMonths = [];
    charges.forEach(function(c) { cMonths.push(c.date.slice(0, 7)); });
    cMonths = Array.from(new Set(cMonths)).sort();
    var chargeSel = document.getElementById('charge-month');
    if (chargeSel) {
        var copts = cMonths.length === 0
            ? '<option value="">(暂无数据)</option>'
            : cMonths.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');
        chargeSel.innerHTML = copts;
        var prevC = chargeSel.value;
        var newC = prevC && cMonths.includes(prevC) ? prevC : (cMonths.length > 0 ? cMonths[cMonths.length - 1] : '');
        if (chargeSel.value !== newC) chargeSel.value = newC;
    }

    // 水电表底月份
    var wMonths = [];
    water.forEach(function(r) { wMonths.push(r.date.slice(0, 7)); });
    wMonths = Array.from(new Set(wMonths)).sort();
    var waterHistSel = document.getElementById('water-history-month');
    if (waterHistSel) {
        var wopts = wMonths.length === 0
            ? '<option value="">(暂无数据)</option>'
            : wMonths.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');
        waterHistSel.innerHTML = wopts;
        var prevW = waterHistSel.value;
        var newW = prevW && wMonths.includes(prevW) ? prevW : (wMonths.length > 0 ? wMonths[wMonths.length - 1] : '');
        if (waterHistSel.value !== newW) waterHistSel.value = newW;
    }

    // 月度水电
    var uMonths = [];
    water.forEach(function(r) { uMonths.push(r.date.slice(0, 7)); });
    uMonths = Array.from(new Set(uMonths)).sort();
    var utilSel = document.getElementById('utilities-month');
    if (utilSel) {
        var uopts = uMonths.length === 0
            ? '<option value="">(暂无数据)</option>'
            : uMonths.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');
        utilSel.innerHTML = uopts;
        var prevU = utilSel.value;
        var newU = prevU && uMonths.includes(prevU) ? prevU : (uMonths.length > 0 ? uMonths[uMonths.length - 1] : '');
        if (utilSel.value !== newU) {
            utilSel.value = newU;
            loadMonthlyUtilities();
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

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { loadMonthlyReport, loadYearlyReport, loadMonthlyUtilities, getSnapshot,
                       renderMonthlyReportTable, renderYearlyResult, renderUtilitiesHTML,
                       renderTrendChart, triggerVisiblePie, renderMonthlyPie, renderDailyPie,
                       refreshDayCopySelect, calcDayUsage, copyDayUsage,
                       updateStatusBar, refreshMonthSelectors, checkAndPromptMigration };
}
