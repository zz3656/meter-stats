/**
 * 申购模块 — 提交/审核/入库。
 */

function refreshPurchases() {
    Api.purchases.list().then(function(data) {
        State.set("purchases", data);
        refreshAndRender();
    }).catch(function(err) {
        showAlert("加载申购数据失败: " + err);
    });
}

function addPurchase(name, qty, unit, est_price, supplier) {
    Api.purchases.create({ name: name, qty: qty, unit: unit, est_price: est_price, supplier: supplier }).then(function(res) {
        if (res.ok) refreshPurchases();
    }).catch(function(err) {
        showAlert("添加失败: " + err);
    });
}

function updatePurchase(id, name, qty, unit, est_price, supplier) {
    Api.purchases.update(id, { name: name, qty: qty, unit: unit, est_price: est_price, supplier: supplier }).then(function(res) {
        if (res.ok) refreshPurchases();
    }).catch(function(err) {
        showAlert("更新失败: " + err);
    });
}

function stockItem(id, qty) {
    Api.purchases.stock(id, { qty: qty }).then(function(res) {
        if (res.ok) refreshPurchases();
    }).catch(function(err) {
        showAlert("入库失败: " + err);
    });
}

function deletePurchase(id) {
    Api.purchases.delete(id).then(function(res) {
        if (res.ok) refreshPurchases();
    }).catch(function(err) {
        showAlert("删除失败: " + err);
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshPurchases, addPurchase, updatePurchase, stockItem, deletePurchase };
}
