/**
 * 报表模块 — 月报/年报/水电。
 */

function loadMonthlyReport(month) {
    return Api.reports.monthlyReport(month).then(function(data) {
        return data;
    }).catch(function(err) {
        showAlert("加载月报失败: " + err);
        throw err;
    });
}

function loadYearlyReport(year) {
    return Api.reports.yearlyReport(year).then(function(data) {
        return data;
    }).catch(function(err) {
        showAlert("加载年报失败: " + err);
        throw err;
    });
}

function loadMonthlyUtilities(month) {
    return Api.reports.monthlyUtilities(month).then(function(data) {
        return data;
    }).catch(function(err) {
        showAlert("加载水电报表失败: " + err);
        throw err;
    });
}

function getSnapshot(params) {
    return Api.reports.snapshot(params);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { loadMonthlyReport, loadYearlyReport, loadMonthlyUtilities, getSnapshot };
}
