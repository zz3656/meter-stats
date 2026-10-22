/**
 * 值班模块 — 创建/图片上传。
 */

function refreshDuty() {
    Api.duty.list().then(function(data) {
        State.set("duty", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载值班数据失败: " + err);
    });
}

function addDuty(date, content) {
    Api.duty.create({ date: date, content: content }).then(function(res) {
        if (res.ok) refreshDuty();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

function updateDuty(id, date, content) {
    Api.duty.update(id, { date: date, content: content }).then(function(res) {
        if (res.ok) refreshDuty();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

function deleteDuty(id) {
    Api.duty.delete(id).then(function(res) {
        if (res.ok) refreshDuty();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshDuty, addDuty, updateDuty, deleteDuty };
}
