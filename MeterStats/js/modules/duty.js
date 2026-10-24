/**
 * 值班模块 — 增删改 + 表格渲染。
 * 
 * 替代: render_duty_images.js, render_duty_image_upload.js, render_tables.js (renderDutyTable)。
 */

// ==================== 数据刷新 ====================

function refreshDuty() {
    fetchDuty().then(function(data) {
        State.set("duty", data);
        renderDutyTable(State.get("duty"), '');
        populateDutyMonthSelector();
        checkDutyReminder();
    }).catch(function(err) {
        showAlert("加载值班数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

function addDuty(type, time, shift, fault_area, note, images) {
    Api.duty.create({ type: type, time: time, shift: shift, fault_area: fault_area, note: note, images: images })
        .then(function() { refreshDuty(); })
        .catch(function(err) { showAlert("添加失败: " + err); });
}

function updateDuty(id, fields) {
    Api.duty.update(id, fields).then(function() { refreshDuty(); })
        .catch(function(err) { showAlert("更新失败: " + err); });
}

function deleteDuty(id) {
    Api.duty.delete(id).then(function() { refreshDuty(); })
        .catch(function(err) { showAlert("删除失败: " + err); });
}

function handleDuty(id, time, shift, method, note, images) {
    Api.duty.handle(id, { time: time, shift: shift, method: method, note: note, images: images })
        .then(function() { refreshDuty(); })
        .catch(function(err) { showAlert("处理失败: " + err); });
}

// ==================== 表格渲染 (替代 renderDutyTable) ====================

function renderDutyTable(dutyList, filterMonth) {
    var tbody = document.querySelector('#duty-table tbody');
    var empty = document.getElementById('duty-list-empty');
    if (!tbody) return;

    if (!dutyList || dutyList.length === 0) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }

    var filtered = dutyList;
    if (filterMonth && filterMonth !== '') {
        filtered = dutyList.filter(function(d) { return d.record_time && d.record_time.startsWith(filterMonth); });
    }

    var sorted = filtered.slice().sort(function(a, b) { return (b.record_time || '').localeCompare(a.record_time || ''); });

    if (sorted.length === 0) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }

    if (empty) empty.style.display = 'none';

    tbody.innerHTML = sorted.map(function(d) {
        var statusColor = d.status === '已处理' ? 'var(--success)' : 'var(--warn)';
        var isHandle = d.duty_type === '处理';
        var displayType = isHandle ? '🔧 处理记录' : escapeHtml(d.duty_type || '—');
        var displayHandle = isHandle ? escapeHtml(d.note || '—') : escapeHtml(d.handle_method || '—');
        var displayNote = isHandle ? '' : escapeHtml(d.note || '—');
        var images = (d.images || []);
        var imageThumbs = images.map(function(fn) {
            var imgSrc = getDutyImageUrl(fn);
            return '<img src="' + imgSrc + '" class="duty-image-thumb" onclick="openLightbox(\'' + imgSrc + '\')" title="点击查看大图" />';
        }).join('');
        return '<tr class="' + (isHandle ? 'handle-row' : '') + '">' +
            '<td>' + (d.record_time || '—') + '</td>' +
            '<td>' + displayType + '</td>' +
            '<td>' + escapeHtml(d.shift || '—') + '</td>' +
            '<td>' + escapeHtml(d.fault_area || '—') + '</td>' +
            '<td><span style="color:' + statusColor + ';font-weight:510;">' + escapeHtml(d.status || '—') + '</span></td>' +
            '<td>' + displayHandle + '</td>' +
            '<td>' + displayNote + (imageThumbs ? '<div class="duty-image-cell">' + imageThumbs + '</div>' : '') + '</td>' +
            '<td>' +
                (d.status === '未处理' ? '<button class="save-btn" data-action="handle-duty" data-id="' + d.id + '">处理</button>' : '') +
                ' <button class="del-btn" data-action="del-duty" data-id="' + d.id + '">删除</button>' +
            '</td>' +
        '</tr>';
    }).join('');

    // 绑定删除按钮
    tbody.querySelectorAll('[data-action="del-duty"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id = btn.dataset.id;
            showModal({ title: '删除记录', body: '确定删除这条工作记录?', icon: '🗑', confirmText: '删除', confirmKind: 'danger' })
                .then(function(ok) {
                    if (!ok) return;
                    Api.duty.delete(id).then(function() {
                        showAlert('✓ 已删除', 'success');
                        refreshDuty();
                    }).catch(function(e) { showAlert('删除失败:' + e.message, 'error'); });
                });
        });
    });

    // 绑定处理按钮
    tbody.querySelectorAll('[data-action="handle-duty"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id = btn.dataset.id;
            var duty = dutyList.find(function(d) { return d.id === id; });
            if (!duty) return;
            openDutyHandleModal(id, duty);
        });
    });
}

/** 填充工作记录月份下拉 */
function populateDutyMonthSelector() {
    var sel = document.getElementById('duty-record-month');
    if (!sel) return;

    var months = new Set();
    (State.get("duty") || []).forEach(function(d) {
        if (d.record_time) { months.add(d.record_time.substring(0, 7)); }
    });

    var sorted = [...months].sort().reverse();
    sel.innerHTML = '<option value="">全部</option>' + sorted.map(function(m) { return '<option value="' + m + '">' + m + '</option>'; }).join('');
}

/** 检查值班提醒 (有待处理记录时显示横幅) */
function checkDutyReminder() {
    var dutyList = State.get("duty") || [];
    var hasUnprocessed = dutyList.some(function(d) { return d.status === '未处理'; });
    var reminder = document.getElementById('duty-reminder');
    if (reminder) {
        reminder.style.display = hasUnprocessed ? 'block' : 'none';
    }
}

// ==================== 导出 ====================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshDuty, addDuty, updateDuty, deleteDuty, handleDuty,
                       renderDutyTable, populateDutyMonthSelector, checkDutyReminder };
}
