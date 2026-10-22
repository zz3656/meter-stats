/**
 * 物品模块 — 增删改 + 借还。
 */

function refreshItems() {
    Api.items.list().then(function(data) {
        State.set("items", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载物品数据失败: " + err);
    });
}

function addItem(name, qty, unit) {
    Api.items.create({ name: name, qty: qty, unit: unit }).then(function(res) {
        if (res.ok) refreshItems();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

function updateItem(id, name, qty, unit) {
    Api.items.update(id, { name: name, qty: qty, unit: unit }).then(function(res) {
        if (res.ok) refreshItems();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

function deleteItem(id) {
    Api.items.delete(id).then(function(res) {
        if (res.ok) refreshItems();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

function lendItem(id, borrower, qty) {
    Api.items.lend(id, { borrower: borrower, qty: qty }).then(function(res) {
        if (res.ok) refreshItems();
    }).catch(function(err) {
        showAlert("借出失败: " + err);
    });
}

function returnItem(id, qty) {
    Api.items.return(id, { qty: qty }).then(function(res) {
        if (res.ok) refreshItems();
    }).catch(function(err) {
        showAlert("归还失败: " + err);
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshItems, addItem, updateItem, deleteItem, lendItem, returnItem };
}
