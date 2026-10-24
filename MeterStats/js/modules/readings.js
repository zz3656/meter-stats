/**
 * 抄表模块 — 录入/编辑/删除 + 表格渲染。
 * 
 * 通过 Api.readings.* 调用后端,通过 State.get/set("readings") 管理状态。
 * 替代: render_records.js (抄表记录表) + render_edit.js (抄表编辑弹窗)。
 */

// ==================== 数据刷新 ====================

/** 刷新抄表数据并触发全量渲染 */
function refreshReadings() {
    Api.readings.list().then(function(data) {
        State.set("readings", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载抄表数据失败: " + err);
    });
}

// ==================== CRUD 操作 ====================

/** 添加抄表记录 */
function addReading(date, hall, fire, private_room, ac, note, rehearsal, programming) {
    Api.readings.create({
        date: date, hall: hall, fire: fire,
        private_room: private_room, ac: ac,
        note: note, rehearsal: rehearsal, programming: programming
    }).then(function(res) {
        refreshReadings();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

/** 更新抄表记录 */
function updateReading(oldDate, fields) {
    Api.readings.update(oldDate, fields).then(function(res) {
        refreshReadings();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

/** 删除抄表记录 */
function deleteReadingRemoteOnly(date) {
    Api.readings.delete(date).then(function(res) {
        refreshReadings();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

// ==================== 水电 CRUD (通过 Api.utilities) ====================

/** 刷新水电数据 */
function refreshWaterReadings() {
    Api.utilities.list().then(function(data) {
        State.set("water", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载水电数据失败: " + err);
    });
}

/** 删除水电记录 */
function deleteWaterReadingRemote(date) {
    Api.utilities.delete(date).then(function() {
        refreshWaterReadings();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

/** 保存/更新水电记录 */
function saveWaterReadingRemote(row) {
    return Api.utilities.create(row).then(function() {
        refreshWaterReadings();
    });
}

// ==================== 表格渲染 ====================

/** 渲染抄表记录表格 (替代 renderHistory) */
function renderReadingTable(readings) {
    var readTbody = document.querySelector('#history-table tbody');
    var readEmpty = document.getElementById('history-empty');
    if (!readTbody) return;

    var monthSel = document.getElementById('history-month');
    var month = monthSel ? monthSel.value : '';
    var filtered = month ? readings.filter(function(r) { return r.date.startsWith(month); }) : readings;

    if (!filtered || filtered.length === 0) {
        readTbody.innerHTML = '';
        readEmpty.style.display = 'block';
        readEmpty.textContent = (month ? month : '全部') + ' 暂无抄表记录';
        return;
    }
    readEmpty.style.display = 'none';
    var sortedReadings = filtered.slice().sort(function(a, b) { return b.date.localeCompare(a.date); });

    readTbody.innerHTML = sortedReadings.map(function(r) {
        var tags = [];
        if (r.rehearsal) tags.push('<span class="tag tag-rehearsal" title="排练">排练</span>');
        if (r.programming) tags.push('<span class="tag tag-programming" title="编程">编程</span>');
        var tagsHtml = tags.length ? tags.join(' ') : '';
        return (
            '<tr data-date="' + r.date + '" data-type="reading">' +
                '<td>' + r.date + '</td>' +
                '<td>' + (r.hall == null ? '—' : r.hall.toFixed(2)) + '</td>' +
                '<td>' + (r.fire == null ? '—' : r.fire.toFixed(2)) + '</td>' +
                '<td>' + (r.private_room == null ? '—' : r.private_room.toFixed(2)) + '</td>' +
                '<td>' + (r.ac == null ? '—' : r.ac.toFixed(2)) + '</td>' +
                '<td style="color:var(--text-muted);font-size:12px;">' + (r.note ? escapeHtml(r.note) : '—') + tagsHtml + '</td>' +
                '<td>' +
                    '<button class="edit-btn" data-action="edit-reading" data-date="' + r.date + '">编辑</button> ' +
                    '<button class="delete-btn" data-action="delete-reading" data-date="' + r.date + '" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;">删除</button>' +
                '</td>' +
            '</tr>'
        );
    }).join('');

    // 编辑按钮绑定
    readTbody.querySelectorAll('[data-action="edit-reading"]').forEach(function(btn) {
        btn.addEventListener('click', function() { enterEditMode(btn.dataset.date, 'reading'); });
    });
    // 删除按钮绑定
    readTbody.querySelectorAll('[data-action="delete-reading"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var date = btn.dataset.date;
            showModal({
                title: '删除抄表记录', icon: '🗑️',
                body: '确认删除 <strong>' + date + '</strong> 的抄表记录?<br><span style="opacity:0.7">此操作不可恢复。</span>',
                confirmText: '删除'
            }).then(function(ok) {
                if (!ok) return;
                deleteReadingRemoteOnly(date);
                showAlert('已删除抄表 ' + date, 'success');
                refreshAndRender();
            });
        });
    });

    // 水电表底表格渲染 (同文件内)
    renderWaterTable();
}

/** 渲染水电表底表格 (renderHistory 的后半部分) */
function renderWaterTable() {
    var waterTbody = document.querySelector('#water-history-table tbody');
    var waterEmpty = document.getElementById('water-history-empty');
    if (!waterTbody) return;

    var waterMonthSel = document.getElementById('water-history-month');
    var waterMonth = waterMonthSel ? waterMonthSel.value : '';
    var waterFiltered = waterMonth
        ? (State.get("water") || []).filter(function(w) { return w.date.startsWith(waterMonth); })
        : (State.get("water") || []);

    if (!waterFiltered || waterFiltered.length === 0) {
        waterTbody.innerHTML = '';
        waterEmpty.style.display = 'block';
        waterEmpty.textContent = (waterMonth ? waterMonth : '全部') + ' 暂无水电表底记录';
        return;
    }
    waterEmpty.style.display = 'none';
    var sortedWater = waterFiltered.slice().sort(function(a, b) { return b.date.localeCompare(a.date); });

    waterTbody.innerHTML = sortedWater.map(function(w) {
        return (
            '<tr data-date="' + w.date + '" data-type="water">' +
                '<td>' + w.date + '</td>' +
                '<td>' + (w.main_meter == null ? '—' : w.main_meter.toFixed(1)) + '</td>' +
                '<td>' + (w.sub_meter == null ? '—' : w.sub_meter.toFixed(1)) + '</td>' +
                '<td>' + (w.water == null ? '—' : w.water.toFixed(1)) + '</td>' +
                '<td style="color:var(--text-muted);font-size:12px;">' + (w.note ? escapeHtml(w.note) : '—') + '</td>' +
                '<td>' +
                    '<button class="edit-btn" data-action="edit-water" data-date="' + w.date + '">编辑</button> ' +
                    '<button class="delete-btn" data-action="delete-water" data-date="' + w.date + '" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;">删除</button>' +
                '</td>' +
            '</tr>'
        );
    }).join('');

    // 水电编辑按钮绑定
    waterTbody.querySelectorAll('[data-action="edit-water"]').forEach(function(btn) {
        btn.addEventListener('click', function() { enterWaterEditMode(btn.dataset.date); });
    });
    // 水电删除按钮绑定
    waterTbody.querySelectorAll('[data-action="delete-water"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var date = btn.dataset.date;
            showModal({
                title: '删除水电表底', icon: '🗑️',
                body: '确认删除 <strong>' + date + '</strong> 的水电表底记录?<br><span style="opacity:0.7">此操作不可恢复。</span>',
                confirmText: '删除'
            }).then(function(ok) {
                if (!ok) return;
                Api.utilities.delete(date).then(function() {
                    showAlert('已删除水电表底 ' + date, 'success');
                    refreshAndRender();
                });
            });
        });
    });
}

// ==================== 编辑弹窗逻辑 ====================

/** 非当日编辑二次确认 */
function confirmNonTodayEdit(recordLabel, recordDate) {
    if (recordDate === todayStr()) return Promise.resolve(true);
    return showModal({
        title: '修改非当日记录', icon: '⚠️', iconKind: 'warn',
        body: '你正在修改 <strong>' + recordDate + '</strong> 的记录。<br><span style="opacity:0.7">该记录不是今日录入,请确认修改内容无误后继续。</span>',
        confirmText: '确认修改', confirmKind: 'primary'
    }).then(function(ok) { return !!ok; });
}

/** 抄表记录编辑 — 弹窗形式 (替代 enterEditMode) */
function enterEditMode(date, type) {
    if (type !== 'reading') return; // 水电由 enterWaterEditMode 处理
    confirmNonTodayEdit('抄表记录', date).then(function(confirmed) {
        if (!confirmed) return;
        var row = (State.get("readings") || []).find(function(r) { return r.date === date; });
        if (!row) return;

        var setVal = function(elId, val) { var el = document.getElementById(elId); if (el) el.value = val; };
        setVal('reading-edit-date', row.date);
        setVal('reading-edit-hall', row.hall != null ? row.hall : '');
        setVal('reading-edit-fire', row.fire != null ? row.fire : '');
        setVal('reading-edit-private_room', row.private_room != null ? row.private_room : '');
        setVal('reading-edit-ac', row.ac != null ? row.ac : '');
        var rehEl = document.getElementById('reading-edit-rehearsal');
        if (rehEl) rehEl.checked = !!row.rehearsal;
        var progEl = document.getElementById('reading-edit-programming');
        if (progEl) progEl.checked = !!row.programming;
        setVal('reading-edit-note', row.note || '');

        var modalEl = document.getElementById('reading-edit-modal-backdrop');
        var confirmBtn = document.getElementById('reading-edit-confirm');
        var cancelBtn = document.getElementById('reading-edit-close');

        var doSave = function() {
            if (_submitting) return;
            var ids = { date: 'reading-edit-date', hall: 'reading-edit-hall', fire: 'reading-edit-fire',
                        private_room: 'reading-edit-private_room', ac: 'reading-edit-ac', note: 'reading-edit-note' };
            var num = function(id) { var v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };
            var hallV = num(ids.hall), fireV = num(ids.fire), prV = num(ids.private_room), acV = num(ids.ac);
            var allVals = [hallV, fireV, prV, acV];
            if (allVals.every(function(v) { return v === null; })) { showAlert('请至少填写一块表的读数', 'error'); return; }
            if (allVals.some(function(v) { return v !== null && isNaN(v); })) { showAlert('读数必须是数字', 'error'); return; }

            var newDate = document.getElementById(ids.date).value;
            if (!newDate) { showAlert('请选择日期', 'error'); return; }

            // 检查日期冲突: 用 Api.readings.list 查当前数据
            Api.readings.list().then(function(allReadings) {
                var conflict = allReadings.find(function(r) { return r.date === newDate; });
                if (conflict && newDate !== date) {
                    showModal({
                        title: '覆盖已有数据', icon: '⚠️', iconKind: 'warn',
                        body: '<strong>' + newDate + '</strong> 已存在抄表记录,合并(覆盖)它吗?',
                        confirmText: '覆盖', confirmKind: 'primary'
                    }).then(function(overOK) {
                        if (!overOK) return;
                        Api.readings.delete(newDate).then(function() {
                            saveNewReading();
                        });
                    });
                } else {
                    saveNewReading();
                }
            });

            function saveNewReading() {
                setSubmitting(true);
                Api.readings.update(date, {
                    date: newDate,
                    hall: hallV === null ? undefined : hallV,
                    fire: fireV === null ? undefined : fireV,
                    private_room: prV === null ? undefined : prV,
                    ac: acV === null ? undefined : acV,
                    note: document.getElementById(ids.note).value.trim(),
                    rehearsal: document.getElementById('reading-edit-rehearsal').checked,
                    programming: document.getElementById('reading-edit-programming').checked,
                }).then(function() {
                    showAlert('✓ ' + date + ' 抄表已更新为 ' + newDate, 'success');
                    closeReadingEditModal();
                    refreshAndRender();
                }).catch(function(err) {
                    showAlert('更新失败: ' + err.message, 'error');
                }).finally(function() { setSubmitting(false); });
            }
        };

        // 解绑/绑定事件 (防止重复绑定)
        var newConfirm = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
        newConfirm.addEventListener('click', doSave);
        var newCancel = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
        newCancel.addEventListener('click', closeReadingEditModal);

        modalEl.addEventListener('click', function handler(e) {
            if (e.target === modalEl) { closeReadingEditModal(); modalEl.removeEventListener('click', handler); };
        });

        modalEl.classList.add('show');
        document.getElementById('reading-edit-hall')?.focus();
    });
}

function closeReadingEditModal() {
    var modalEl = document.getElementById('reading-edit-modal-backdrop');
    if (modalEl) modalEl.classList.remove('show');
}

/** 水电表底编辑 — 弹窗形式 (替代 enterWaterEditMode) */
function enterWaterEditMode(date) {
    confirmNonTodayEdit('水电表底', date).then(function(confirmed) {
        if (!confirmed) return;
        Api.utilities.list().then(function(waterAll) {
            var waterRow = waterAll.find(function(w) { return w.date === date; });
            if (!waterRow) return;

            var hasExistingWater = waterRow.main_meter != null || waterRow.sub_meter != null || waterRow.water != null;
            var setVal = function(elId, val) { var el = document.getElementById(elId); if (el) el.value = val; };
            setVal('water-edit-date', waterRow.date);
            setVal('water-edit-main_meter', waterRow.main_meter != null ? waterRow.main_meter : '');
            setVal('water-edit-sub_meter', waterRow.sub_meter != null ? waterRow.sub_meter : '');
            setVal('water-edit-water', waterRow.water != null ? waterRow.water : '');
            setVal('water-edit-note', waterRow.note || '');

            var modalEl = document.getElementById('water-edit-modal-backdrop');
            var confirmBtn = document.getElementById('water-edit-confirm');
            var cancelBtn = document.getElementById('water-edit-close');

            var doSave = function() {
                if (_submitting) return;
                var numE = function(id) { var v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };
                var newDate = document.getElementById('water-edit-date').value;
                var mainMeter = numE('water-edit-main_meter');
                var subMeter = numE('water-edit-sub_meter');
                var waterVal = numE('water-edit-water');
                var newNote = document.getElementById('water-edit-note').value.trim();

                var waterInputEmpty = [mainMeter, subMeter, waterVal].every(function(v) { return v === null; });
                var waterInputInvalid = [mainMeter, subMeter, waterVal].some(function(v) { return v !== null && isNaN(v); });
                if (waterInputInvalid) { showAlert('读数必须是数字', 'error'); return; }
                if (!newDate) { showAlert('日期不能为空', 'error'); return; }

                setSubmitting(true);
                if (hasExistingWater) {
                    if (waterInputEmpty) {
                        Api.utilities.delete(date).then(function() { finishWaterEdit(); });
                    } else {
                        Api.utilities.create({ date: newDate, main_meter: mainMeter, sub_meter: subMeter, water: waterVal, note: newNote }).then(function() { finishWaterEdit(); });
                    }
                } else {
                    if (!waterInputEmpty) {
                        Api.utilities.create({ date: newDate, main_meter: mainMeter, sub_meter: subMeter, water: waterVal, note: newNote }).then(function() { finishWaterEdit(); });
                    } else {
                        finishWaterEdit();
                    }
                }

                function finishWaterEdit() {
                    showAlert('✓ ' + date + ' 水电表底已更新', 'success');
                    closeWaterEditModal();
                    refreshAndRender();
                }
            };

            var newConfirm = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
            newConfirm.addEventListener('click', doSave);
            var newCancel = cancelBtn.cloneNode(true);
            cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
            newCancel.addEventListener('click', closeWaterEditModal);

            modalEl.addEventListener('click', function handler(e) {
                if (e.target === modalEl) { closeWaterEditModal(); modalEl.removeEventListener('click', handler); };
            });

            modalEl.classList.add('show');
            document.getElementById('water-edit-main_meter')?.focus();
        });
    });
}

function closeWaterEditModal() {
    var modalEl = document.getElementById('water-edit-modal-backdrop');
    if (modalEl) modalEl.classList.remove('show');
}

// ==================== 充值记录表格渲染 ====================

/** 渲染充值记录表格 (替代 renderChargeLog) */
function renderChargeTable(charges) {
    var tbody = document.querySelector('#charge-table tbody');
    var empty = document.getElementById('charge-list-empty');
    var summary = document.getElementById('charge-summary');

    var monthSel = document.getElementById('charge-month');
    var month = monthSel ? monthSel.value : '';
    var filtered = month ? (charges || []).filter(function(c) { return c.date.startsWith(month); }) : charges;

    if (!charges || charges.length === 0 || filtered.length === 0) {
        tbody.innerHTML = '';
        empty.style.display = 'block';
        empty.textContent = month ? (month + ' 暂无充值记录') : '还没有充值记录';
        summary.style.display = 'none';
        return;
    }
    empty.style.display = 'none';
    summary.style.display = 'flex';

    var sorted = filtered.slice().sort(function(a, b) { return b.date.localeCompare(a.date); });

    tbody.innerHTML = sorted.map(function(c) {
        var totalKwh = 0;
        for (var i = 0; i < CHARGE_METERS.length; i++) {
            var m = CHARGE_METERS[i];
            totalKwh += realKwh(c[m.key] || 0, m.key);
        }
        var totalYuan = totalKwh * ELECTRICITY_PRICE;
        var cells = '';
        for (var i = 0; i < CHARGE_METERS.length; i++) {
            var m = CHARGE_METERS[i];
            var v = c[m.key] || 0;
            cells += '<td>' + (v > 0 ? v.toFixed(1) : '—') + '</td>';
        }
        var noteCell = c.note ? escapeHtml(c.note) : '—';
        return (
            '<tr data-charge-id="' + c.id + '">' +
                '<td>' + c.date + '</td>' +
                cells +
                '<td>¥ ' + totalYuan.toFixed(2) + '</td>' +
                '<td style="text-align:left;color:var(--text-muted);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + noteCell + '">' + noteCell + '</td>' +
                '<td>' +
                    '<button class="edit-btn" data-action="edit-charge" data-id="' + c.id + '">编辑</button> ' +
                    '<button class="delete-btn" data-action="delete-charge" data-id="' + c.id + '" style="color:var(--danger);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:4px;font-size:12px;font-family:inherit;">删除</button>' +
                '</td>' +
            '</tr>'
        );
    }).join('');

    // 编辑/删除 绑定
    tbody.querySelectorAll('[data-action="edit-charge"]').forEach(function(btn) {
        btn.addEventListener('click', function() { enterChargeEditMode(btn.dataset.id); });
    });
    tbody.querySelectorAll('[data-action="delete-charge"]').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var id = btn.dataset.id;
            var target = (charges || []).find(function(c) { return c.id === id; });
            if (!target) return;
            showModal({
                title: '删除充值记录', icon: '🗑️',
                body: '确认删除 <strong>' + target.date + '</strong> 的充值记录?<br><span style="opacity:0.7">此操作不可恢复。</span>',
                confirmText: '删除'
            }).then(function(ok) {
                if (!ok) return;
                Api.charges.delete(id).then(function() {
                    showAlert('已删除 ' + target.date + ' 的充值记录', 'success');
                    refreshAndRender();
                });
            });
        });
    });

    // 汇总(本月 = 当前自然月)
    var now = new Date();
    var monthKey = formatDate(now).slice(0, 7);
    var monthCharges = charges.filter(function(c) { return c.date.startsWith(monthKey); });
    var monthCount = monthCharges.length;
    var monthKwh = 0;
    for (var i = 0; i < monthCharges.length; i++) {
        var mc = monthCharges[i];
        for (var j = 0; j < CHARGE_METERS.length; j++) {
            monthKwh += realKwh(mc[CHARGE_METERS[j].key] || 0, CHARGE_METERS[j].key);
        }
    }
    var monthYuan = monthKwh * ELECTRICITY_PRICE;

    document.getElementById('summary-count').textContent = monthCount;
    document.getElementById('summary-kwh').textContent = monthKwh.toFixed(0) + ' 度';
    document.getElementById('summary-yuan').textContent = '¥ ' + monthYuan.toFixed(2);
}

/** 充值记录编辑 — 弹窗形式 (替代 enterChargeEditMode) */
function enterChargeEditMode(id) {
    Api.charges.list().then(function(charges) {
        var c = charges.find(function(x) { return x.id === id; });
        if (!c) return;

        confirmNonTodayEdit('充值记录', c.date).then(function(confirmed) {
            if (!confirmed) return;

            var setVal = function(elId, val) { var el = document.getElementById(elId); if (el) el.value = val; };
            setVal('charge-edit-date', c.date);
            setVal('charge-edit-hall', c.hall || '');
            setVal('charge-edit-fire', c.fire || '');
            setVal('charge-edit-private_room', c.private_room || '');
            setVal('charge-edit-ac', c.ac || '');
            setVal('charge-edit-note', c.note || '');

            var modalEl = document.getElementById('charge-edit-modal-backdrop');
            var confirmBtn = document.getElementById('charge-edit-confirm');
            var cancelBtn = document.getElementById('charge-edit-close');

            var doSave = function() {
                if (_submitting) return;
                var date = document.getElementById('charge-edit-date').value;
                if (!date) { showAlert('请选择日期', 'error'); return; }

                var num = function(id) { var v = document.getElementById(id).value; return v === '' ? 0 : parseFloat(v); };

                var updated = {
                    date: date,
                    hall: num('charge-edit-hall'),
                    fire: num('charge-edit-fire'),
                    private_room: num('charge-edit-private_room'),
                    ac: num('charge-edit-ac'),
                    note: document.getElementById('charge-edit-note').value.trim(),
                };

                var allZero = true;
                for (var i = 0; i < CHARGE_METERS.length; i++) {
                    if (updated[CHARGE_METERS[i].key] !== 0) { allZero = false; break; }
                }
                if (allZero) { showAlert('至少填写一块表的充值度数', 'error'); return; }

                setSubmitting(true);
                Api.charges.update(id, updated).then(function() {
                    showAlert('✓ ' + c.date + ' 充值记录已更新', 'success');
                    closeChargeEditModal();
                    refreshAndRender();
                }).catch(function(err) {
                    showAlert('更新失败: ' + err.message, 'error');
                }).finally(function() { setSubmitting(false); });
            };

            var newConfirm = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
            newConfirm.addEventListener('click', doSave);
            var newCancel = cancelBtn.cloneNode(true);
            cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
            newCancel.addEventListener('click', closeChargeEditModal);

            modalEl.addEventListener('click', function handler(e) {
                if (e.target === modalEl) { closeChargeEditModal(); modalEl.removeEventListener('click', handler); };
            });

            modalEl.classList.add('show');
            document.getElementById('charge-edit-hall')?.focus();
        });
    });
}

function closeChargeEditModal() {
    var modalEl = document.getElementById('charge-edit-modal-backdrop');
    if (modalEl) modalEl.classList.remove('show');
}

// ==================== 刷新入口 ====================

/** 刷新并渲染抄表和充值表格 (替代 refreshAndRender 中的相关部分) */
function refreshAndRenderTables() {
    Api.readings.list().then(function(readings) {
        State.set("readings", readings.sort(function(a, b) { return a.date.localeCompare(b.date); }));
        renderReadingTable(State.get("readings"));

        return Api.charges.list();
    }).then(function(charges) {
        State.set("charges", charges.sort(function(a, b) { return a.date.localeCompare(b.date); }));
        renderChargeTable(State.get("charges"));

        return Api.utilities.list();
    }).then(function(water) {
        State.set("water", water.sort(function(a, b) { return a.date.localeCompare(b.date); }));
    }).catch(function(err) {
        showAlert('加载数据失败: ' + err);
    });
}

// ==================== 全量刷新入口 (替代旧版 app.js 的 renderAll) ====================

/**
 * 全量加载数据并渲染所有模块。
 * 替代旧版 app.js 中的 renderAll()，供 init.js、nas_sync.js、toast.js、admin.js 调用。
 */
async function renderAll() {
    // 1. 从后端获取全部数据（snapshot 接口一次拉所有）
    try {
        var data = await Api.reports.snapshot({});
        State.set("readings", (data.readings || []).slice().sort(function(a, b) { return a.date.localeCompare(b.date); }));
        State.set("charges", (data.charges || []).slice().sort(function(a, b) { return a.date.localeCompare(b.date); }));
        State.set("water", (data.readings_water || []).slice().sort(function(a, b) { return a.date.localeCompare(b.date); }));
        State.set("items", data.items || []);
        State.set("purchases", data.purchases || []);
        State.set("duty", data.duty || []);
    } catch (e) {
        console.warn('snapshot 失败:', e);
        // 回退：各模块自行加载
    }

    // 2. 渲染所有模块的表格
    renderReadingTable(State.get("readings"));
    renderWaterTable();
    renderChargeTable(State.get("charges"));
    renderItemTable(State.get("items"));
    renderLendHistory(State.get("items"));
    renderPurchaseTable(State.get("purchases"));
    renderDutyTable(State.get("duty"), '');

    // 3. 渲染报表（图表）
    var reports = window.Api ? window.Api.reports : null;
    if (reports) {
        try {
            var snap = await Api.reports.snapshot({});
            renderTrendChart(State.get("readings"), State.get("charges"));
        } catch(e) { /* 图表非关键，失败不影响主功能 */ }
    }

    // 4. 触发饼图（如果可见）
    if (typeof triggerVisiblePie === 'function') triggerVisiblePie();
    if (typeof renderMonthlyPie === 'function') renderMonthlyPie(State.get("readings"));
    if (typeof renderDailyPie === 'function') renderDailyPie(State.get("readings"));

    // 5. 更新状态栏
    updateStatusBar(State.get("readings"), State.get("charges"));

    // 6. 刷新月份选择器
    if (typeof populateDutyMonthSelector === 'function') populateDutyMonthSelector();
    if (typeof refreshMonthSelectors === 'function') refreshMonthSelectors();
    if (typeof refreshDayCopySelect === 'function') refreshDayCopySelect(State.get("readings"), State.get("charges"));

    // 7. 更新状态栏预警
    updateStatusBar(State.get("readings"), State.get("charges"));

    // 8. 检查水电迁移（仅首次）
    if (typeof checkAndPromptMigration === 'function' && !window.MIGRATION_CHECKED) {
        setTimeout(checkAndPromptMigration, 1500);
    }
}

// refreshAndRender 别名 — 兼容旧代码调用（被各 modules 广泛使用）
var refreshAndRender = refreshAndRenderTables;

// 全局暴露（供 init.js、admin.js 跨 script 标签调用）
if (typeof window !== 'undefined') {
    window.renderAll = renderAll;
    window.refreshAndRender = refreshAndRender;
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshReadings, addReading, updateReading, deleteReadingRemoteOnly,
                       renderReadingTable, renderWaterTable, renderChargeTable, refreshAndRenderTables,
                       enterEditMode, closeReadingEditModal, enterWaterEditMode, closeWaterEditModal,
                       enterChargeEditMode, closeChargeEditModal, renderAll, refreshAndRender };
}
