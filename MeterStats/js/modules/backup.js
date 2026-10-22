/**
 * 备份模块 — 手动备份/恢复。
 */

function doBackup() {
    return Api.system.backup ? null : fetch('/api/backup', { method: 'POST' }).then(function(res) {
        return res.json();
    });
}

function doRestore(file) {
    var formData = new FormData();
    formData.append('file', file);
    return fetch('/api/restore', { method: 'POST', body: formData }).then(function(res) {
        return res.json();
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { doBackup, doRestore };
}
