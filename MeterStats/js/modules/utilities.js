/**
 * 水电模块 — 录入/编辑 + 展示。
 */

function refreshUtilities() {
    Api.utilities.list().then(function(data) {
        State.set("readings_water", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载水电数据失败: " + err);
    });
}

function addWaterReading(date, main_meter, sub_meter, water) {
    Api.utilities.create({ date: date, main_meter: main_meter, sub_meter: sub_meter, water: water }).then(function(res) {
        if (res.ok) refreshUtilities();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

function updateWaterReading(date, main_meter, sub_meter, water) {
    Api.utilities.update(date, { date: date, main_meter: main_meter, sub_meter: sub_meter, water: water }).then(function(res) {
        if (res.ok) refreshUtilities();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

function deleteWaterReading(date) {
    Api.utilities.delete(date).then(function(res) {
        if (res.ok) refreshUtilities();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshUtilities, addWaterReading, updateWaterReading, deleteWaterReading };
}
