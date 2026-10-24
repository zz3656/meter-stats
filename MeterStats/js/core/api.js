/**
 * 统一 API 调用封装 (完整版)。
 * 
 * 覆盖后端 routing.py 中全部 47 个 /api/* 端点。
 * 每个模块通过 Api.xxx.yyy() 调用后端，而不是直接写 fetch('/api/...')。
 */
var Api = (() => {
    function _request(method, path, body) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (body) opts.body = JSON.stringify(body);
        
        // 获取 token: 优先 ADMIN_TOKEN 全局变量，回退到 localStorage
        var token = (typeof ADMIN_TOKEN !== 'undefined' && ADMIN_TOKEN) 
            ? ADMIN_TOKEN 
            : localStorage.getItem('token');
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;

        // 后端 auth_handler.py 从 query param 提取 token
        // 如果路径不含 token，追加 query param 以兼容后端
        if (token && path.indexOf('token=') === -1) {
            var separator = path.indexOf('?') !== -1 ? '&' : '?';
            path = path + separator + 'token=' + encodeURIComponent(token);
        }

        // path 已包含 '/api' 前缀（如 '/api/readings'），不能再拼一次，
        // 否则会请求 /api/api/xxx —— 后端无此路由，直接断开连接，
        // WKWebView/浏览器里表现为 "TypeError: Load failed"。
        return fetch(path, opts).then(function(res) {
            return res.json().then(function(data) {
                if (!res.ok) throw new Error(data.error || '请求失败');
                return data;
            });
        });
    }

    // 抄表模块 API (4个端点)
    var readings = {
        list: function(params) {
            return _request('GET', '/api/readings' + (params ? '?' + new URLSearchParams(params).toString() : ''));
        },
        create: function(data) { return _request('POST', '/api/readings', data); },
        update: function(date, data) { return _request('PUT', '/api/readings/' + date, data); },
        delete: function(date) { return _request('DELETE', '/api/readings/' + date); },
    };

    // 充值模块 API (4个端点)
    var charges = {
        list: function(params) {
            return _request('GET', '/api/charges' + (params ? '?' + new URLSearchParams(params).toString() : ''));
        },
        create: function(data) { return _request('POST', '/api/charges', data); },
        update: function(id, data) { return _request('PUT', '/api/charges/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/charges/' + id); },
    };

    // 水电模块 API (5个端点)
    var utilities = {
        list: function() { return _request('GET', '/api/readings-water'); },
        create: function(data) { return _request('POST', '/api/readings-water', data); },
        update: function(date, data) { return _request('PUT', '/api/readings-water/' + date, data); },
        delete: function(date) { return _request('DELETE', '/api/readings-water/' + date); },
        monthly: function(ym) { return _request('GET', '/api/readings-water/monthly?ym=' + ym); },
    };

    // 物品模块 API (7个端点)
    var items = {
        list: function() { return _request('GET', '/api/items'); },
        create: function(data) { return _request('POST', '/api/items', data); },
        update: function(id, data) { return _request('PUT', '/api/items/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/items/' + id); },
        lend: function(id, data) { return _request('PUT', '/api/items/' + id + '/lend', data); },
        return: function(id, data) { return _request('PUT', '/api/items/' + id + '/return', data); },
    };

    // 申购模块 API (5个端点)
    var purchases = {
        list: function() { return _request('GET', '/api/purchases'); },
        create: function(data) { return _request('POST', '/api/purchases', data); },
        update: function(id, data) { return _request('PUT', '/api/purchases/' + id, data); },
        stock: function(id, data) { return _request('PUT', '/api/purchases/' + id + '/stock', data); },
        delete: function(id) { return _request('DELETE', '/api/purchases/' + id); },
    };

    // 值班模块 API (7个端点)
    var duty = {
        list: function() { return _request('GET', '/api/duty'); },
        create: function(data) { return _request('POST', '/api/duty', data); },
        update: function(id, data) { return _request('PUT', '/api/duty/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/duty/' + id); },
        handle: function(id, data) { return _request('POST', '/api/duty/' + id + '/handle', data); },
        image: function(id, fileData) { return _request('POST', '/api/duty/' + id + '/image', fileData); },
        imageUpload: function(id, file) {
            var formData = new FormData();
            formData.append('image', file);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/duty/' + id + '/image?' + (localStorage.getItem('token') ? 'token=' + encodeURIComponent(localStorage.getItem('token')) : ''), opts).then(function(res) { return res.json(); });
        },
    };

    // 报表模块 API (8个端点)
    var reports = {
        health: function() { return _request('GET', '/api/health'); },
        version: function() { return _request('GET', '/api/version'); },
        snapshot: function(params) { return _request('GET', '/api/snapshot?' + new URLSearchParams(params).toString()); },
        export: function(params) { return _request('GET', '/api/export?' + new URLSearchParams(params).toString()); },
        monthlyReport: function(month) { return _request('GET', '/api/monthly-report?month=' + month); },
        yearlyReport: function(year) { return _request('GET', '/api/yearly-report?year=' + year); },
        monthlyUtilities: function(month) { return _request('GET', '/api/monthly-utilities?month=' + month); },
        reportCache: function() { return _request('GET', '/api/admin/report-cache'); },
    };

    // 系统 API (3个端点)
    var system = {
        login: function(user, pass) { return _request('POST', '/api/auth/login', { username: user, password: pass }); },
        logout: function() { return _request('GET', '/api/auth/logout'); },
        me: function() { return _request('GET', '/api/auth/me'); },
    };

    // 备份/恢复 API (2个端点) — 数据管理页面用
    var backup = {
        doBackup: function() { return _request('POST', '/api/backup'); },
        doRestore: function(file) {
            // 恢复需要 FormData，不走 _request
            var formData = new FormData();
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/restore?' + (localStorage.getItem('token') ? 'token=' + encodeURIComponent(localStorage.getItem('token')) : ''), opts).then(function(res) { return res.json(); });
        },
    };
    var admin = {
        // 用户管理 (4个)
        users: function() { return _request('GET', '/api/admin/users'); },
        createUser: function(data) { return _request('POST', '/api/admin/users', data); },
        updateUser: function(username, data) { return _request('PUT', '/api/admin/users/' + username, data); },
        deleteUser: function(username) { return _request('DELETE', '/api/admin/users/' + username); },
        // 角色管理 (1个)
        roles: function() { return _request('GET', '/api/admin/roles'); },
        // 电表设置 (3个)
        meterSettings: function() { return _request('GET', '/api/admin/meter'); },
        saveMeterSettings: function(data) { return _request('PUT', '/api/admin/meter', data); },
        metersPublic: function() { return _request('GET', '/api/meters'); },
        // 备份管理 (8个)
        backupStatus: function() { return _request('GET', '/api/admin/backup-status'); },
        backupConfig: function() { return _request('GET', '/api/admin/backup-config'); },
        setAutoBackup: function(enabled) { return _request('PUT', '/api/admin/auto-backup', { enabled: enabled }); },
        // ⚠️ 参数名必须是 retention_count：后端读的是它，写成 retention_days 会被静默忽略（永远存 5）
        setBackupRetention: function(count) { return _request('PUT', '/api/admin/backup-retention', { retention_count: count }); },
        backupDelete: function(name) { return _request('GET', '/api/admin/backup-delete?name=' + encodeURIComponent(name)); },
        backupDownload: function(name) { return _request('GET', '/api/admin/backup-download?name=' + encodeURIComponent(name)); },
        dataFiles: function() { return _request('GET', '/api/admin/data-files'); },
        dirListing: function(dir) { return _request('GET', '/api/admin/dir-listing?dir=' + encodeURIComponent(dir)); },
        // 其他管理 (3个)
        auditLog: function() { return _request('GET', '/api/admin/audit'); },
        sessions: function() { return _request('GET', '/api/admin/sessions'); },
        syncFromNAS: function(url) { return _request('POST', '/api/admin/sync-from-nas', { url: url }); },
    };

    // 备份/恢复 API (2个端点) — 独立于 admin，数据管理页面用
    var backup = {
        doBackup: function() { return _request('POST', '/api/backup'); },
        restore: function(file) {
            // 恢复需要 FormData，不走 _request
            var formData = new FormData();
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/restore', opts).then(function(res) { return res.json(); });
        },
    };

    // 导入/导出 API (3个端点)
    var dataimport = {
        import: function(model, file) {
            var formData = new FormData();
            formData.append('model', model);
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/import', opts).then(function(res) { return res.json(); });
        },
        importTemplate: function(model) { return _request('GET', '/api/import/template?model=' + model); },
        export: function(params) { return _request('GET', '/api/export?' + new URLSearchParams(params).toString()); },
    };

    // 上传 API (1个端点)
    var upload = {
        doUpload: function(file, category) {
            var formData = new FormData();
            formData.append('file', file);
            if (category) formData.append('category', category);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/upload', opts).then(function(res) { return res.json(); });
        },
    };

    // Admin 恢复上传 API (1个端点)
    var adminRestore = {
        upload: function(file) {
            var formData = new FormData();
            formData.append('zip_file', file);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/admin/restore-upload?' + (localStorage.getItem('token') ? 'token=' + encodeURIComponent(localStorage.getItem('token')) : ''), opts).then(function(res) { return res.json(); });
        },
    };

    // Admin 导入 API (1个端点)
    var adminImport = {
        doImport: function(model, file) {
            var formData = new FormData();
            formData.append('model', model);
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            if (localStorage.getItem('token')) opts.headers['Authorization'] = 'Bearer ' + localStorage.getItem('token');
            return fetch('/api/import?' + (localStorage.getItem('token') ? 'token=' + encodeURIComponent(localStorage.getItem('token')) : ''), opts).then(function(res) { return res.json(); });
        },
    };

    // NAS 代理 API (1个端点)
    var proxy = {
        nasData: function(url) { return _request('GET', '/api/proxy/nas-data?url=' + encodeURIComponent(url)); },
    };

    // 图片配置 API (2个端点)
    var images = {
        config: function() { return _request('GET', '/api/admin/images'); },
        saveConfig: function(data) { return _request('PUT', '/api/admin/images', data); },
    };

    // 水电迁移 API (2个端点)
    var migrate = {
        water: function() { return _request('POST', '/api/admin/migrate-water'); },
        waterStatus: function() { return _request('GET', '/api/admin/migrate-water-status'); },
    };

    return { 
        readings: readings, charges: charges, utilities: utilities, 
        items: items, purchases: purchases, duty: duty, 
        reports: reports, system: system,
        admin: admin, backup: backup, dataimport: dataimport,
        upload: upload, proxy: proxy, images: images, migrate: migrate,
        adminRestore: adminRestore, adminImport: adminImport
    };
})();
