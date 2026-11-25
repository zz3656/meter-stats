/**
 * 门店切换器(P1)—— 侧栏顶部下拉。
 *
 * 可见条件(与设计文档一致:仅总部/多店用户可见):
 *   - 总部账号(all_stores=true):即使只有 1 家店也要显示 ——
 *     它同时是「当前在哪家店」的指示器。
 *   - 可见门店 ≥ 2 家:多店员工/主管需要切。
 *   - 其它:单店用户没有可切的对象,不显示(不占地方也不误导)。
 *
 * 本文件只管 DOM。门店状态一律问 window.StoreContext,自己不要存一份。
 */

/** 当前可见门店列表里选中的那家 */
function currentStoreOptionId(stores) {
  var id = '';
  try {
    if (typeof StoreContext !== 'undefined' && StoreContext) id = StoreContext.getStoreId() || '';
  } catch (e) { id = ''; }
  for (var i = 0; i < stores.length; i++) {
    if (String(stores[i].id) === id) return id;
  }
  return stores.length ? String(stores[0].id) : '';
}

/** 渲染切换器(下拉内容 + 可见性) */
function renderStoreSwitcher(state) {
  var wrap = document.getElementById('store-switcher');
  var sel = document.getElementById('store-select');
  if (!wrap || !sel) return;

  var stores = (state && state.stores) || [];
  var allStores = !!(state && state.allStores);
  var visible = allStores || stores.length > 1;

  if (!visible || !stores.length) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = 'block';

  var selected = currentStoreOptionId(stores);
  var html = '';
  for (var i = 0; i < stores.length; i++) {
    var s = stores[i];
    var sid = String(s.id == null ? '' : s.id);
    var name = String(s.name || sid);
    html += '<option value="' + escapeAttr(sid) + '"'
          + (sid === selected ? ' selected' : '') + '>'
          + escapeHtml(name) + '</option>';
  }
  sel.innerHTML = html;
  sel.value = selected;
}

/** 切换门店:改状态 → 清缓存 → 重拉数据 → 提示 */
async function switchStoreTo(storeId) {
  var ok = false;
  try {
    ok = await StoreContext.switchTo(storeId);
  } catch (e) {
    ok = false;
  }
  if (!ok) {
    showAlert('切换门店失败:该门店不可访问', 'error');
    renderStoreSwitcher({
      stores: StoreContext.getStores(),
      allStores: StoreContext.getAllStores(),
    });
    return;
  }
  var name = storeId;
  var stores = StoreContext.getStores();
  for (var i = 0; i < stores.length; i++) {
    if (String(stores[i].id) === String(storeId)) name = stores[i].name || storeId;
  }
  showAlert('已切换到「' + name + '」', 'success');
}

/** 门店上下文变化 → 渲染切换器;需要重拉数据时统一重拉 */
function onStoreContextChanged(state, reason) {
  renderStoreSwitcher(state);
  if (reason === 'switch' || reason === 'recovered') {
    // 切店后要重新拉全量数据 + 重新加载电表配置 + 重画报表。
    // 门店上下文已经清过缓存,这里拉回来的就是新门店的数据。
    try {
      if (typeof window.loadAppData === 'function') window.loadAppData();
    } catch (e) {
      console.warn('切店后重新加载数据失败:', e);
    }
  }
  if (reason === 'no-store') {
    showAlert('账号未分配门店,请联系管理员', 'error');
  }
}

/** 绑定切换器事件(只绑一次) */
function bindStoreSwitcher() {
  var sel = document.getElementById('store-select');
  if (!sel || sel.dataset.storeBound === '1') return;
  sel.dataset.storeBound = '1';
  sel.addEventListener('change', function () {
    switchStoreTo(sel.value);
  });
}

/** 初始化:订阅门店上下文 + 首次渲染 */
function initStoreSwitcher() {
  bindStoreSwitcher();
  if (typeof StoreContext === 'undefined' || !StoreContext) return;
  StoreContext.onChange(onStoreContextChanged);
  renderStoreSwitcher({
    stores: StoreContext.getStores(),
    allStores: StoreContext.getAllStores(),
  });
}
