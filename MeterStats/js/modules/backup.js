/**
 * 备份模块 — 手动备份/恢复。
 */

function doBackup() {
    return Api.backup.doBackup();
}

function doRestore(file) {
    return Api.backup.doRestore(file);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { doBackup, doRestore };
}
