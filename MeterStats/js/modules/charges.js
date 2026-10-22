/**
 * 充值模块 — 录入/编辑/删除 + 展示。
 */

function refreshCharges() {
    Api.charges.list().then(function(data) {
        State.set("charges", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载充值数据失败: " + err);
    });
}

function addCharge(date, hall, fire, private_room, ac) {
    Api.charges.create({ date: date, hall: hall, fire: fire, private_room: private_room, ac: ac }).then(function(res) {
        if (res.ok) refreshCharges();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

function updateCharge(id, date, hall, fire, private_room, ac) {
    Api.charges.update(id, { date: date, hall: hall, fire: fire, private_room: private_room, ac: ac }).then(function(res) {
        if (res.ok) refreshCharges();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

function deleteCharge(id) {
    Api.charges.delete(id).then(function(res) {
        if (res.ok) refreshCharges();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshCharges, addCharge, updateCharge, deleteCharge };
}
