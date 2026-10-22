/**
 * 抄表模块 — 录入/编辑/删除 + 展示。
 * 
 * 从 State.get("readings") 读取数据，通过 Api.readings.xxx() 调用后端。
 */

// 刷新抄表数据并渲染
function refreshReadings() {
    Api.readings.list().then(function(data) {
        State.set("readings", data);
        // 触发所有依赖 readings 的渲染函数
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载抄表数据失败: " + err);
    });
}

// 添加抄表记录
function addReading(date, hall, fire, private_room, ac) {
    Api.readings.create({ date: date, hall: hall, fire: fire, private_room: private_room, ac: ac }).then(function(res) {
        if (res.ok) refreshReadings();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

// 更新抄表记录
function updateReading(date, hall, fire, private_room, ac) {
    Api.readings.update(date, { date: date, hall: hall, fire: fire, private_room: private_room, ac: ac }).then(function(res) {
        if (res.ok) refreshReadings();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

// 删除抄表记录
function deleteReading(date) {
    Api.readings.delete(date).then(function(res) {
        if (res.ok) refreshReadings();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshReadings, addReading, updateReading, deleteReading };
}
