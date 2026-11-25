/**
 * 统一 API 调用封装 (完整版)。
 * 
 * 覆盖后端 routing.py 中全部 47 个 /api/* 端点。
 * 每个模块通过 Api.xxx.yyy() 调用后端，而不是直接写 fetch('/api/...')。
 */
var Api = (() => {
    // ===== 门店参数 =====

    /**
     * 这些端点**不带** store 参数。规则在 StoreContext.isStoreFreePath()
     * (js/core/storeContext.js —— 门店参数规则的唯一真相源),
     * 这里只做转发 + 兜底,别再抄一份规则。
     *
     * 兜底只守住「绝不能带 store」的两类(引导端点 + 身份端点):
     * 多带一个失效的 store 到引导端点 → 404 → 用户永久锁死。
     * (/api/health 与 /api/version 带不带 store 都无害 —— 后端对公开端点
     *  跳过门店闸,多余的 query 参数没人读。)
     */
    function _isStoreFree(path) {
        try {
            if (typeof StoreContext !== 'undefined' && StoreContext
                && typeof StoreContext.isStoreFreePath === 'function') {
                return !!StoreContext.isStoreFreePath(path);
            }
        } catch (e) { /* StoreContext 没加载 */ }
        var p = String(path || '').split('?')[0];
        if (p.indexOf('/api/auth/') === 0) return true;
        if (p === '/api/stores' || p.indexOf('/api/stores/') === 0) return true;
        return false;
    }

    /**
     * 门店 ID 合法性 —— 口径只有一处:StoreContext.isValidStoreId()
     * (与后端 registry.is_valid_store_id 等价)。
     * StoreContext 没加载时退回本地判断(等价于后端的 \A[A-Za-z0-9_-]{1,32}\Z:
     * 长度 1-32 + 逐字符白名单 —— 不能用 /^...$/,JS 的 $ 会放行尾随换行)。
     */
    function _isValidStoreId(id) {
        var s = String(id == null ? '' : id);
        try {
            if (typeof StoreContext !== 'undefined' && StoreContext
                && typeof StoreContext.isValidStoreId === 'function') {
                return !!StoreContext.isValidStoreId(s);
            }
        } catch (e) { /* StoreContext 没加载 */ }
        return s.length >= 1 && s.length <= 32 && !/[^A-Za-z0-9_-]/.test(s);
    }

    /** 当前门店 ID。拿不到 / 不合法 → 空串(不带参数,让后端按用户范围默认)。 */
    function _currentStoreId() {
        try {
            if (typeof StoreContext === 'undefined' || !StoreContext) return '';
            var id = StoreContext.getStoreId();
            if (!id) return '';
            return _isValidStoreId(id) ? String(id) : '';
        } catch (e) {
            return '';
        }
    }

    /** query 里是不是已经有 store 参数了(避免重复拼)。 */
    function _hasStoreParam(path) {
        var q = String(path || '').split('?')[1];
        if (!q) return false;
        var parts = q.split('&');
        for (var i = 0; i < parts.length; i++) {
            var kv = parts[i].split('=');
            var name = kv[0];
            try { name = decodeURIComponent(name); } catch (e) { /* 原样比 */ }
            if (name === 'store') return true;
        }
        return false;
    }

    /** 给请求路径拼上当前门店。 */
    function _appendStore(path) {
        if (_isStoreFree(path)) return path;
        if (_hasStoreParam(path)) return path;
        var store = _currentStoreId();
        if (!store) return path;
        var separator = path.indexOf('?') !== -1 ? '&' : '?';
        return path + separator + 'store=' + encodeURIComponent(store);
    }

    /** 统一取 token —— 只走 admin.js 的 currentAuthToken()(AGENTS.md 的约定)。 */
    function _authToken() {
        try {
            if (typeof currentAuthToken === 'function') {
                var t = currentAuthToken();
                if (t) return t;
            }
        } catch (e) { /* admin.js 还没加载 */ }
        try {
            if (typeof ADMIN_TOKEN !== 'undefined' && ADMIN_TOKEN) return ADMIN_TOKEN;
        } catch (e) { /* ignore */ }
        try { return localStorage.getItem('token') || ''; } catch (e) { return ''; }
    }

    function _request(method, path, body) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (body) opts.body = JSON.stringify(body);

        // token:只走 admin.js 的 currentAuthToken()(AGENTS.md 约定)
        var token = _authToken();
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;

        // 后端 auth_handler.py 从 query param 提取 token
        // 如果路径不含 token，追加 query param 以兼容后端
        if (token && path.indexOf('token=') === -1) {
            var separator = path.indexOf('?') !== -1 ? '&' : '?';
            path = path + separator + 'token=' + encodeURIComponent(token);
        }

        // 拼当前门店(store-free 端点除外)
        path = _appendStore(path);

        // path 已包含 '/api' 前缀（如 '/api/readings'），不能再拼一次，
        // 否则会请求 /api/api/xxx —— 后端无此路由，直接断开连接，
        // WKWebView/浏览器里表现为 "TypeError: Load failed"。
        return fetch(path, opts).then(function(res) {
            return res.json().then(function(data) {
                if (!res.ok) {
                    // 门店失效(被删 / 权限被收回)→ 交给门店上下文恢复。
                    // 不在这里处理:恢复要重新引导 + 重拉数据,得由上层统一做。
                    if (typeof StoreContext !== 'undefined' && StoreContext
                        && typeof StoreContext.handleStoreError === 'function') {
                        try {
                            StoreContext.handleStoreError(res.status, data && data.error);
                        } catch (e) { /* 恢复失败不掩盖原始错误 */ }
                    }
                    throw new Error(data.error || '请求失败');
                }
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
        confirm: function(id) { return _request('PUT', '/api/charges/' + id + '/confirm', {}); },
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
        createBatch: function(data) { return _request('POST', '/api/items/batch', data); },
        update: function(id, data) { return _request('PUT', '/api/items/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/items/' + id); },
        lend: function(id, data) { return _request('PUT', '/api/items/' + id + '/lend', data); },
        return: function(id, data) { return _request('PUT', '/api/items/' + id + '/return', data); },
        deleteLendRecord: function(id, recordId) { return _request('DELETE', '/api/items/' + id + '/lend/' + recordId); },
    };

    // 申购模块 API (5个端点)
    var purchases = {
        list: function() { return _request('GET', '/api/purchases'); },
        create: function(data) { return _request('POST', '/api/purchases', data); },
        update: function(id, data) { return _request('PUT', '/api/purchases/' + id, data); },
        stock: function(id, data) { return _request('PUT', '/api/purchases/' + id + '/stock', data); },
        delete: function(id) { return _request('DELETE', '/api/purchases/' + id); },
    };

    // 值班模块 API (5个端点)
    var duty = {
        list: function() { return _request('GET', '/api/duty'); },
        create: function(data) { return _request('POST', '/api/duty', data); },
        update: function(id, data) { return _request('PUT', '/api/duty/' + id, data); },
        delete: function(id) { return _request('DELETE', '/api/duty/' + id); },
        handle: function(id, data) { return _request('POST', '/api/duty/' + id + '/handle', data); },
        // ⚠️ 这里原来还有 image(id, fileData) 与 imageUpload(id, file) —— 已删(2026-11-25):
        //   1) 它们打的 /api/duty/<id>/image 在后端**不存在** ——
        //      routing.py 只特判精确的 /api/duty/image,/api/duty/7/image
        //      会落到 _POST_PREFIX['/api/duty'] → handle_post_duty(建值班记录,吃 JSON)。
        //   2) 后端没有「按 id 存图」的语义,那个 id 参数本来就没意义 ——
        //      留着就是个骗人的 API。
        //   3) 零调用点(grep 过 MeterStats/ 全目录)。
        //   真正要传图片走 js/helpers/utils.js::uploadImages() → POST /api/duty/image
        //   (字段 image + scope)—— 那是后端唯一存在的 multipart 图片端点。
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

    var admin = {
        // 用户管理 (4个)
        users: function() { return _request('GET', '/api/admin/users'); },
        createUser: function(data) { return _request('POST', '/api/admin/users', data); },
        // 用户 ID 走 query —— 后端 handle_put_users 从 query 取 id(?id=),
        // 路径形式(/api/admin/users/3)会被判「无效的用户ID」。
        updateUser: function(uid, data) { return _request('PUT', '/api/admin/users?id=' + encodeURIComponent(uid), data); },
        // 用户 ID 同样走 query —— 后端 handle_delete_users 也只从 query 取 id(?id=)。
        // 路径形式(/api/admin/users/3)会被判「无效的用户ID」,删除用户功能整个是坏的。
        deleteUser: function(uid) { return _request('DELETE', '/api/admin/users?id=' + encodeURIComponent(uid)); },
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
        // NAS 同步凭据(远端 v0.4.1 起接口需要登录,本机保存远端账号密码)
        nasConfig: function() { return _request('GET', '/api/admin/nas-config'); },
        saveNasConfig: function(data) { return _request('PUT', '/api/admin/nas-config', data); },
    };

    // 备份/恢复 API —— 独立于 admin，数据管理页面用。
    //
    // ⚠️ 这里原来声明过两次 var backup,后者覆盖前者 → Api.backup.doRestore 是
    // undefined,js/modules/backup.js 的 doRestore() 一调就抛 TypeError。
    //   合并成一份,两个方法名都留着(doRestore / restore 是同一件事)。
    //
    // ⚠️ doBackup() 走 _request → 会带上 ?store=。
    //   那只是「访问权校验」(门店闸要知道你在哪家店、有没有权限),
    //   **不代表备份是按门店做的** —— 后端写的是 base_data_dir(),整包数据。
    //   (admin.js 的备份下载/删除刻意不带 store,那是另一码事。)
    var backup = {
        doBackup: function() { return _request('POST', '/api/backup'); },
        doRestore: function(file) { return restoreUpload(file); },
        restore: function(file) { return restoreUpload(file); },
    };

    // 恢复走 /api/admin/restore-upload(与 Api.adminRestore.upload 同款):
    // POST /api/restore 要的是 JSON {zip_path: 服务器磁盘上的路径}
    // (后端 modules/backup/handler.py:551)—— 浏览器手里只有 File,走不通那条路;
    // 只有把文件本身 multipart 送上去才是浏览器能走通的恢复方式。
    //
    // ⚠️ multipart 的文件名必须以 .zip 结尾:后端按 filename="([^"]+\.zip)" 提取。
    // ⚠️ body 必须挂上:只 new + append 的话请求发出去不带任何数据。
    // ⚠️ ?store= 只是访问权校验,恢复写的仍是 base_data_dir() 整包数据 ——
    //    别让后人以为「恢复是按门店做的」。
    function restoreUpload(file) {
        var formData = new FormData();
        formData.append('zip_file', file);
        var opts = { method: 'POST', headers: {} };
        opts.body = formData;
        var token = _authToken();
        if (token) opts.headers['Authorization'] = 'Bearer ' + token;
        var path = '/api/admin/restore-upload';
        var sep = path.indexOf('?') !== -1 ? '&' : '?';
        if (token) path = path + sep + 'token=' + encodeURIComponent(token);
        path = _appendStore(path);
        return fetch(path, opts).then(function(res) { return res.json(); });
    }

    // 导入/导出 API (3个端点)
    var dataimport = {
        import: function(model, file) {
            var formData = new FormData();
            formData.append('model', model);
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            opts.body = formData;
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = '/api/import';
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            path = _appendStore(path);
            return fetch(path, opts).then(function(res) { return res.json(); });
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
            opts.body = formData;
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = '/api/upload';
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            path = _appendStore(path);
            return fetch(path, opts).then(function(res) { return res.json(); });
        },
    };

    // Admin 恢复上传 API (1个端点)
    // 与 Api.backup.doRestore / restore 共用同一个实现(别留两份)。
    var adminRestore = {
        upload: function(file) { return restoreUpload(file); },
    };

    // Admin 导入 API (1个端点)
    var adminImport = {
        doImport: function(model, file) {
            var formData = new FormData();
            formData.append('model', model);
            formData.append('file', file);
            var opts = { method: 'POST', headers: {} };
            opts.body = formData;
            var token = _authToken();
            if (token) opts.headers['Authorization'] = 'Bearer ' + token;
            var path = '/api/import';
            var sep = path.indexOf('?') !== -1 ? '&' : '?';
            if (token) path = path + sep + 'token=' + encodeURIComponent(token);
            path = _appendStore(path);
            return fetch(path, opts).then(function(res) { return res.json(); });
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

    // 分店模块 API (5个端点) — 门店管理页用
    var stores = {
        list: function() { return _request('GET', '/api/stores'); },
        current: function() { return _request('GET', '/api/stores/current'); },
        create: function(data) { return _request('POST', '/api/stores', data); },
        update: function(id, data) { return _request('PUT', '/api/stores/' + encodeURIComponent(id), data); },
        remove: function(id) { return _request('DELETE', '/api/stores/' + encodeURIComponent(id)); },
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
        adminRestore: adminRestore, adminImport: adminImport,
        stores: stores
    };
})();
