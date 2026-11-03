/**
 * NAS 数据同步 — 从 NAS Docker 实例拉取全部数据到本地。
 *
 * 通过本地后端 /api/proxy/nas-data 代理请求 NAS，解决 WKWebView 跨域问题。
 * 拉取数据后通过 /api/admin/sync-from-nas 写入本地文件。
 *
 * ⚠️ 远端实例从 v0.4.1 起全局启用接口鉴权,拉数据必须带会话。
 *    代理会用本机保存的远端账号密码(nas_sync_user / nas_sync_pass)登录换 token,
 *    所以同步前必须先在「数据管理 → 从 NAS 同步」里保存凭据。
 */

/** 读取已保存的 NAS 同步配置。密码不回传,只显示"是否已配置"。 */
async function loadNasConfig() {
  const userInput = document.getElementById('nas-sync-user-input');
  const passInput = document.getElementById('nas-sync-pass-input');
  const urlInput = document.getElementById('nas-sync-url-input');
  const hint = document.getElementById('nas-config-hint');
  if (!userInput && !passInput && !urlInput) return;

  try {
    const res = await Api.admin.nasConfig();
    if (userInput) userInput.value = res.nas_user || '';
    if (urlInput && res.nas_url) urlInput.value = res.nas_url;
    if (passInput) {
      passInput.value = '';
      passInput.placeholder = res.nas_pass_set ? '已配置（留空表示不改动）' : '远端密码';
    }
    if (hint) {
      hint.textContent = res.nas_pass_set
        ? '✅ 已配置远端账号：' + (res.nas_user || '—') + '（密码已保存，留空即不改动）'
        : '⚠️ 尚未配置远端账号密码 —— 远端 v0.4.1 起接口需要登录，填好账号密码才能同步。';
    }
  } catch (e) {
    if (hint) hint.textContent = '读取 NAS 配置失败: ' + (e.message || e);
  }
}

/** 保存远端 NAS 账号密码（密码留空 = 不改动已保存的值）。 */
async function saveNasConfig() {
  const btn = document.getElementById('save-nas-config-btn');
  const userInput = document.getElementById('nas-sync-user-input');
  const passInput = document.getElementById('nas-sync-pass-input');
  const urlInput = document.getElementById('nas-sync-url-input');

  const user = (userInput?.value || '').trim();
  const pass = passInput?.value || '';
  const url = (urlInput?.value || '').trim();

  if (!user) {
    showAlert('请填写远端账号', 'info');
    userInput?.focus();
    return;
  }

  const body = { nas_user: user, nas_url: url };
  if (pass) body.nas_pass = pass;   // 留空表示"保持原密码"

  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
  try {
    const res = await Api.admin.saveNasConfig(body);
    if (res && res.ok) {
      showAlert('✅ NAS 凭据已保存', 'success');
      await loadNasConfig();
    } else {
      showAlert('保存失败: ' + ((res && res.error) || '未知错误'), 'error');
    }
  } catch (e) {
    showAlert('保存失败: ' + (e.message || e), 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
}

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

  // 补全协议：内网默认 http（NAS 通常没证书），域名/公网默认 https
  // —— 外网部署基本都强制 HTTPS，给 http 会先吃一次 301，慢时直接超时
  if (!/^https?:\/\//i.test(remoteUrl)) {
    const host = remoteUrl.split('/')[0].split(':')[0].toLowerCase();
    const isLan =
      host === 'localhost' || host === '127.0.0.1' ||
      host.startsWith('192.168.') || host.startsWith('10.') ||
      host.endsWith('.local') ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(host);
    remoteUrl = (isLan ? 'http://' : 'https://') + remoteUrl;
  }

  const original = btn.textContent;
  // 先只禁用、不改文案：此时还在等用户确认，显示"同步中"会让取消后看起来卡住
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
