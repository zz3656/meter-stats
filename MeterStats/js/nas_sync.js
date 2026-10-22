/**
 * NAS 数据同步 — 从 NAS Docker 实例拉取全部数据到本地。
 *
 * 通过本地后端 /api/proxy/nas-data 代理请求 NAS，解决 WKWebView 跨域问题。
 * 拉取数据后通过 /api/admin/sync-from-nas 写入本地文件。
 */

// 从 NAS 同步按钮点击处理
async function adminSyncFromNAS() {
  const btn = document.getElementById('admin-sync-nas-btn');
  if (!btn) return;

  // 从输入框读取 NAS 地址（如果没有配置，用默认值）
  const urlInput = document.getElementById('nas-sync-url-input');
  let remoteUrl = (urlInput?.value || '').trim();

  // 验证 URL
  if (!remoteUrl) {
    showAlert('请先输入 NAS 地址（如 http://192.168.x.x:8765）', 'info');
    urlInput?.focus();
    return;
  }

  // 补全协议
  if (!remoteUrl.startsWith('http://') && !remoteUrl.startsWith('https://')) {
    remoteUrl = 'http://' + remoteUrl;
  }

  const original = btn.textContent;
  btn.textContent = '⏳ 同步中…';
  btn.disabled = true;

  try {
    // 第一步：通过本地后端代理从 NAS 拉取数据（解决跨域问题）
    // 使用 api() 函数发 POST 请求，body 中包含 nasUrl（避免 WKWebView 绝对路径 fetch 被拦截）
    const proxyRes = await api('POST', '/api/proxy/nas-data', { nasUrl: remoteUrl });

    if (!proxyRes.ok) {
      const err = proxyRes.error || '无法从 NAS 获取数据';
      showAlert('同步失败: ' + err, 'error');
      return;
    }

    const files = proxyRes.files;
    const fileNames = Object.keys(files);

    if (fileNames.length === 0) {
      showAlert('NAS 上没有数据文件', 'info');
      return;
    }

    // 确认弹窗
    const ok = await showModal({
      icon: '🔄',
      iconKind: 'warn',
      title: '确认从 NAS 同步数据？',
      body: `将从 <b>${remoteUrl}</b> 拉取以下 ${fileNames.length} 个文件覆盖本地数据：<br><br>`
        + `<code>${fileNames.join(', ')}</code><br><br>`
        + `⚠️ 本地现有数据会被覆盖，但同步前会自动备份到 backup/ 目录。`,
      confirmText: '确认同步',
      cancelText: '取消',
      confirmKind: 'danger',
    });

    if (!ok) {
      showAlert('已取消同步', 'info');
      return;
    }

    btn.textContent = '⏳ 同步中…';

    // 第二步：通过本地后端写入文件
    const syncRes = await api('POST', '/api/admin/sync-from-nas', { files: files });

    if (!syncRes.ok) {
      const err = syncRes.error || '写入本地数据失败';
      showAlert('同步失败: ' + err, 'error');
      return;
    }

    const syncedCount = (syncRes.restored || []).length;

    // 刷新页面数据
    await renderAll();

    if (syncedCount > 0) {
      showAlert(`✅ 已从 NAS 同步 ${syncedCount} 个数据文件`, 'success');
      setTimeout(() => { if (typeof loadBackupList === 'function') loadBackupList(); }, 500);
    } else {
      showAlert('同步完成但没有写入新数据（可能和本地一致）', 'info');
    }

  } catch (e) {
    btn.textContent = original;
    showAlert('同步失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    setTimeout(() => { btn.textContent = original; }, 2000);
  }
}
