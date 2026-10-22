/**
 * 统一 API 调用封装。
 * 
 * 每个模块通过 Api.readings.list() 等方式调用后端 API，
 * 而不是直接写 fetch('/api/readings')。
 */
var Api = (() => {
    function _request(method, path, body) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (body) opts.body = JSON.stringify(body);
        
        var token = localStorage.getItem('token');
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;

        return fetch('/api' + path, opts).then(function(res) {
            return res.json().then(function(data) {
                if (!res.ok) throw new Error(data.error || '请求失败');
                return data;
            });
        });
    }

    // 抄表模块 API
    var readings = {
        list: function(params) {
            return _request('GET', '/api/readings' + (params ? '?' + new URLSearchParams(params).toString() : ''));
        },
        create: function(data) { return _request('POST', '/api/readings', data); },
        update: function(date, data) { return _request('PUT', '/api/readings/' + date, data); },
        delete: function(date) { return _request('DELETE', '/api/readings/' + date); },
    };

    // 充值模块 API
    var charges = {
        list: function(params) {
            return _request('GET', '/api/charges' + (params ? '?' + new URLSearchParams(params).toString() : ''));
        },
        create: function(data) { return _request('POST', '/api/charges', data); },
        update: function(id, data) { return _request('PUT', '/api/charges/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/charges/' + id); },
    };

    // 水电模块 API
    var utilities = {
        list: function() { return _request('GET', '/api/readings-water'); },
        create: function(data) { return _request('POST', '/api/readings-water', data); },
        update: function(date, data) { return _request('PUT', '/api/readings-water/' + date, data); },
        delete: function(date) { return _request('DELETE', '/api/readings-water/' + date); },
        monthly: function(ym) { return _request('GET', '/api/readings-water/monthly?ym=' + ym); },
    };

    // 物品模块 API
    var items = {
        list: function() { return _request('GET', '/api/items'); },
        create: function(data) { return _request('POST', '/api/items', data); },
        update: function(id, data) { return _request('PUT', '/api/items/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/items/' + id); },
        lend: function(id, data) { return _request('PUT', '/api/items/' + id + '/lend', data); },
        return: function(id, data) { return _request('PUT', '/api/items/' + id + '/return', data); },
    };

    // 申购模块 API
    var purchases = {
        list: function() { return _request('GET', '/api/purchases'); },
        create: function(data) { return _request('POST', '/api/purchases', data); },
        update: function(id, data) { return _request('PUT', '/api/purchases/' + id, data); },
        stock: function(id, data) { return _request('PUT', '/api/purchases/' + id + '/stock', data); },
        delete: function(id) { return _request('DELETE', '/api/purchases/' + id); },
    };

    // 值班模块 API
    var duty = {
        list: function() { return _request('GET', '/api/duty'); },
        create: function(data) { return _request('POST', '/api/duty', data); },
        update: function(id, data) { return _request('PUT', '/api/duty/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/duty/' + id); },
        handle: function(id, data) { return _request('POST', '/api/duty/' + id + '/handle', data); },
    };

    // 报表模块 API
    var reports = {
        health: function() { return _request('GET', '/api/health'); },
        version: function() { return _request('GET', '/api/version'); },
        snapshot: function(params) { return _request('GET', '/api/snapshot?' + new URLSearchParams(params).toString()); },
        export: function(params) { return _request('GET', '/api/export?' + new URLSearchParams(params).toString()); },
        monthlyReport: function(month) { return _request('GET', '/api/monthly-report?month=' + month); },
        yearlyReport: function(year) { return _request('GET', '/api/yearly-report?year=' + year); },
        monthlyUtilities: function(month) { return _request('GET', '/api/monthly-utilities?month=' + month); },
    };

    // 系统 API
    var system = {
        login: function(user, pass) { return _request('POST', '/api/auth/login', { user: user, password: pass }); },
        logout: function() { return _request('GET', '/api/auth/logout'); },
        me: function() { return _request('GET', '/api/auth/me'); },
    };

    return { readings: readings, charges: charges, utilities: utilities, items: items, purchases: purchases, duty: duty, reports: reports, system: system };
})();
