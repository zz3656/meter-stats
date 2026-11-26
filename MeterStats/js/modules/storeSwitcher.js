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
    // 隐藏时把下拉内容清空 —— 残留的是上一位用户的门店名
    // (登出后切换器 display:none 期间仍在 DOM 里 = 跨用户信息泄露)。
    sel.innerHTML = '';
    sel.value = '';
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
async function onStoreContextChanged(state, reason) {
  renderStoreSwitcher(state);
  if (reason === 'switch' || reason === 'recovered') {
    // 切店后要重新加载电表配置(每店自己的表集合)+ 重新拉全量数据 + 重画报表。
    // ⚠️ 顺序不能反:先 loadMeterConfig 再 renderMeterUi 再 loadAppData。
    // 反了就是「按上一家店的表渲染表单,填进去的却是新店的数据」——
    // 而且不会报错,只会让度数算错。
    try {
      if (typeof loadMeterConfig === 'function') await loadMeterConfig();
      if (typeof window.renderMeterUi === 'function') window.renderMeterUi();
    } catch (e) {
      console.warn('切店后重载表配置失败:', e);
    }
    // 电表设置页:表单是按上一家店加载的,切店必须重载。
    // 不重载的话表单还留着上一家店的数值、「当前门店」标签也不变 ——
    // 用户会以为改动"串到别家店了";更糟的是此时按保存,会把上一家店的
    // 表集合/倍率写进刚切过去的门店(保存的 ?store= 取的是实时门店)。
    try {
      var meterSection = document.getElementById('section-settings-meter');
      if (meterSection && meterSection.style.display !== 'none'
          && typeof loadMeterSettings === 'function') {
        loadMeterSettings();
      }
    } catch (e) {
      console.warn('切店后重载电表设置页失败:', e);
    }
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
