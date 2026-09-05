// ===== 全局数据 =====
let CURRENT_WATER_READINGS = []; // 水电表底数据 (main_meter/sub_meter/water)

async function fetchWaterReadings() {
  try {
    const data = await api('GET', '/api/readings-water');
    CURRENT_WATER_READINGS = data;
    return data;
  } catch (e) {
    console.warn('fetchWaterReadings 失败:', e);
    CURRENT_WATER_READINGS = [];
    return [];
  }
}

async function saveWaterReadingRemote(row) {
  return api('POST', '/api/readings-water', row);
}
async function deleteWaterReadingRemote(date) {
  return api('DELETE', `/api/readings-water/${date}`);
}

// 后端写入
async function saveReadingRemote(row) {
  return api('POST', '/api/readings', row);
}
async function updateReadingRemote(date, fields) {
  return api('PUT', `/api/readings/${date}`, fields);
}
async function deleteReadingRemote(date) {
  return api('DELETE', `/api/readings/${date}`);
}
async function saveChargeRemote(row) {
  return api('POST', '/api/charges', row);
}
async function updateChargeRemote(id, fields) {
  return api('PUT', `/api/charges/${id}`, fields);
}
async function deleteChargeRemote(id) {
  return api('DELETE', `/api/charges/${id}`);
}
async function saveDutyRemote(row) {
  return api('POST', '/api/duty', row);
}
async function updateDutyRemote(id, fields) {
  return api('PUT', `/api/duty/${id}`, fields);
}
async function deleteDutyRemote(id) {
  return api('DELETE', `/api/duty/${id}`);
}

// 同步本地缓存(写入成功后调)
function realKwh(value, key) {
  return value * MULTIPLIER(key);
}