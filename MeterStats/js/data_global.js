// ===== 全局数据 =====
// 使用 METER 命名空间避免全局变量污染。所有模块通过 window.METER 访问共享状态。
// 同时保留全局函数名以兼容现有调用 (fetchSnapshot, fetchReadings 等)。

window.STORAGE_KEY_READINGS = 'meter_readings_cache';
window.STORAGE_KEY_CHARGES = 'meter_charges_cache';

// 集中命名空间 (新代码优先用这个)
window.METER = {
    STORAGE_KEY_READINGS: 'meter_readings_cache',
    STORAGE_KEY_CHARGES: 'meter_charges_cache',
};

// 全局数据 — 必须挂在 window 上，因为 fetchSnapshot() 通过 window[globalKey] 赋值
window.CURRENT_READINGS = []; // 抄表数据
window.CURRENT_CHARGES = []; // 充值数据
window.CURRENT_WATER_READINGS = []; // 水电表底数据 (main_meter/sub_meter/water)
window.CURRENT_ITEMS = []; // 物品列表
window.CURRENT_PURCHASES = []; // 申购列表
window.CURRENT_DUTY = []; // 值班记录

// API 调用封装 (各模块通过 METER.api 访问)
async function _api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body && ['POST', 'PUT'].includes(method)) {
        opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    if (!r.ok) {
        const err = await r.text();
        throw new Error(`HTTP ${r.status}: ${err}`);
    }
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('text/')) return null;
    return r.json();
}

// 快照: 一次性拉取所有数据 (前端启动用)
async function fetchSnapshot() {
    try {
        const data = await _api('GET', '/api/snapshot');
        if (data) {
            for (const [key, value] of Object.entries(data)) {
                if (key.startsWith('_')) continue;
                // 特殊映射: readings_water → CURRENT_WATER_READINGS (不是 CURRENT_READINGS_WATER)
                const specialMap = { 'readings_water': 'CURRENT_WATER_READINGS' };
                const globalKey = specialMap[key] || `CURRENT_${key.toUpperCase()}`;
                if (globalKey in window) {
                    window[globalKey] = value;
                }
            }
        }
    } catch (e) {
        console.warn('snapshot 加载失败,回退到逐个拉取:', e);
    }
}

// 各数据模型 API (通过 window.METER.<model> 访问,同时暴露全局函数以兼容)
async function fetchReadings() {
    try { const data = await _api('GET', '/api/readings'); CURRENT_READINGS = data; return data; }
    catch (e) { console.warn('fetchReadings 失败:', e); CURRENT_READINGS = []; return []; }
}
async function fetchCharges() {
    try { const data = await _api('GET', '/api/charges'); CURRENT_CHARGES = data; return data; }
    catch (e) { console.warn('fetchCharges 失败:', e); CURRENT_CHARGES = []; return []; }
}
async function fetchWaterReadings() {
    try { const data = await _api('GET', '/api/readings-water'); CURRENT_WATER_READINGS = data; return data; }
    catch (e) { console.warn('fetchWaterReadings 失败:', e); CURRENT_WATER_READINGS = []; return []; }
}
async function fetchItems() {
    try { const data = await _api('GET', '/api/items'); 
        // 后端 handle_get 始终返回分页格式 {data, total, page, limit}
        // 提取实际数组（向后兼容：如果直接返回数组则直接用）
        CURRENT_ITEMS = Array.isArray(data) ? data : (data.data || []); 
        return CURRENT_ITEMS; 
    } catch (e) { console.warn('fetchItems 失败:', e); CURRENT_ITEMS = []; return []; }
}
async function fetchPurchases() {
    try { const data = await _api('GET', '/api/purchases'); CURRENT_PURCHASES = data; return data; }
    catch (e) { console.warn('fetchPurchases 失败:', e); CURRENT_PURCHASES = []; return []; }
}

// 后端写入 (通过 window.METER.<model>Remote 访问,同时暴露全局函数以兼容)
async function saveReadingRemote(row) { return _api('POST', '/api/readings', row); }
async function updateReadingRemote(date, fields) { return _api('PUT', `/api/readings/${date}`, fields); }
async function deleteReadingRemote(date) { return _api('DELETE', `/api/readings/${date}`); }
async function saveChargeRemote(row) { return _api('POST', '/api/charges', row); }
async function updateChargeRemote(id, fields) { return _api('PUT', `/api/charges/${id}`, fields); }
async function deleteChargeRemote(id) { return _api('DELETE', `/api/charges/${id}`); }
async function saveDutyRemote(row) { return _api('POST', '/api/duty', row); }
async function updateDutyRemote(id, fields) { return _api('PUT', `/api/duty/${id}`, fields); }
async function deleteDutyRemote(id) { return _api('DELETE', `/api/duty/${id}`); }
async function saveWaterReadingRemote(row) { return _api('POST', '/api/readings-water', row); }
async function deleteWaterReadingRemote(date) { return _api('DELETE', `/api/readings-water/${date}`); }

// 同步本地缓存 (写入成功后调)
function realKwh(value, key) {
    return value * (typeof MULTIPLIER === 'function' ? MULTIPLIER(key) : 1);
}

// 挂载到 METER 命名空间 (新代码用这个)
window.METER.api = _api;
window.METER.fetchSnapshot = fetchSnapshot;
window.METER.fetchReadings = fetchReadings;
window.METER.fetchCharges = fetchCharges;
window.METER.fetchWaterReadings = fetchWaterReadings;
window.METER.fetchItems = fetchItems;
window.METER.fetchPurchases = fetchPurchases;
window.METER.saveReadingRemote = saveReadingRemote;
window.METER.updateReadingRemote = updateReadingRemote;
window.METER.deleteReadingRemote = deleteReadingRemote;
window.METER.saveChargeRemote = saveChargeRemote;
window.METER.updateChargeRemote = updateChargeRemote;
window.METER.deleteChargeRemote = deleteChargeRemote;
window.METER.saveDutyRemote = saveDutyRemote;
window.METER.updateDutyRemote = updateDutyRemote;
window.METER.deleteDutyRemote = deleteDutyRemote;
window.METER.saveWaterReadingRemote = saveWaterReadingRemote;
window.METER.deleteWaterReadingRemote = deleteWaterReadingRemote;
window.METER.realKwh = realKwh;
