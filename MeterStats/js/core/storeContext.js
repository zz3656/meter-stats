/**
 * 门店上下文(P1)—— 当前门店 + 可见门店列表 + 切店事件。
 *
 * 这是前端**唯一的**门店状态源。任何地方想知道「现在是哪家店」都问这里,
 * 不要自己存一份 —— 两份状态必然会不同步。
 *
 * 设计要点(每条都对应后端的既有行为,别凭印象改):
 *
 * 1. **门店选择存在 localStorage,不存后端。**
 *    后端的门店是「每个请求带 ?store=」的**请求级**上下文,不是会话状态
 *    (见 routing._store_gate / _requested_store)。门店 ID 在全局注册表里,
 *    本地记住即可;存后端会导致换浏览器要重新切店。
 *
 * 2. **引导端点(/api/stores、/api/stores/current)必须能不带 store 参数调用。**
 *    锁死链路:管理员删掉了用户当前所在的门店 → 前端还留着那个 ID →
 *    列表请求带着它 → 后端 404 → 连门店列表都拿不到 → 无从切店 → 用户永久卡死。
 *    所以「取列表」这件事永远不能依赖「当前店是有效的」。
 *
 * 3. **切店必须清干净上一家店的数据。**
 *    State / window.CURRENT_* / localStorage 离线缓存 / 报表缓存 / 充值归属缓存,
 *    全都要清。漏一个就出现「切到 B 店,页面还显示 A 店的数据」。
 *    离线缓存(meter_readings_v1 / meter_charges_v1)最阴险:后端不可用时会
 *    回退读它,不清就是把 A 店的数据当成 B 店的显示出来。
 *
 * 4. **门店 ID 必须先校验再拼进 URL。**
 *    后端会校验(registry.is_valid_store_id),前端也校验一次:
 *    不把任意字符串原样透传进 ?store=。
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'meter_current_store';
  // 后端用 re.compile(r"\A[A-Za-z0-9_-]{1,32}\Z")。
  // ⚠️ JS 的 $ 会匹配「结尾换行符之前」,与 Python 的 \Z 不等价 ——
  //    "s002\n" 在 JS 里能通过 /^[...]{1,32}$/,在 Python 里通不过。
  //    所以这里不用 ^...$,改成「长度检查 + 逐字符白名单」。
  var STORE_ID_MAX_LEN = 32;

  var state = {
    storeId: '',        // 当前门店 ID('' = 还没定)
    stores: [],         // 当前用户可见的门店列表
    allStores: false,   // 是否总部账号(all_stores=true)
    ready: false,       // bootstrap 是否完成
    noStore: false,     // 账号未分配门店(要显示空态)
    recovering: false,  // 失效恢复进行中(防重入)
  };

  var listeners = [];
  // init() 重入保护:引导期间再调 init() 复用同一次 Promise,
  // 不重复打后端、也不让两次引导的选店结果互相覆盖。
  var initPromise = null;

  // ===== 基础工具 =====

  /**
   * 门店 ID 是否合法 —— 与后端 registry.is_valid_store_id 等价。
   * 暴露成公开方法:测试与其它模块要用同一套口径。
   */
  function isValidStoreId(id) {
    if (typeof id !== 'string') return false;
    if (id.length < 1 || id.length > STORE_ID_MAX_LEN) return false;
    for (var i = 0; i < id.length; i++) {
      var ch = id.charAt(i);
      var ok = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9') || ch === '_' || ch === '-';
      if (!ok) return false;
    }
    return true;
  }

  function _localStorage() {
    try { return window.localStorage; } catch (e) { return null; }
  }

  function _readPersisted() {
    var ls = _localStorage();
    if (!ls) return '';
    try { return String(ls.getItem(STORAGE_KEY) || ''); } catch (e) { return ''; }
  }

  function _persist(id) {
    var ls = _localStorage();
    if (!ls) return;
    try {
      if (id) ls.setItem(STORAGE_KEY, id);
      else ls.removeItem(STORAGE_KEY);
    } catch (e) { /* 隐私模式等,忽略 */ }
  }

  /** 离线缓存键。accessibility.js 里是顶层 const,加载顺序在本文件之后,
   *  这里用 try/catch 兜底(取不到时用字面量)。 */
  function _offlineCacheKeys() {
    var readings = 'meter_readings_v1';
    var charges = 'meter_charges_v1';
    try { readings = STORAGE_KEY_READINGS; } catch (e) { /* 尚未加载 */ }
    try { charges = STORAGE_KEY_CHARGES; } catch (e) { /* 尚未加载 */ }
    return { readings: readings, charges: charges };
  }

  function _hasStore(id) {
    if (!id) return false;
    for (var i = 0; i < state.stores.length; i++) {
      if (String(state.stores[i].id) === id) return true;
    }
    return false;
  }

  /**
   * 后端「这个账号没有可用门店」有**两条**不同的 403 文案(routing.py::_store_gate):
   *   - 「账号未分配门店」     —— 一个店都没分到
   *   - 「账号未分配有效门店」 —— 分到的店全被管理员删了
   * 两条都是「空态」而不是「致命错误」,都要置 noStore;
   * 只认第一条的话,第二种用户会看到一屏空白而不是「请联系管理员」。
   */
  function _isNoStoreMessage(msg) {
    var s = String(msg || '');
    return s.indexOf('未分配门店') >= 0 || s.indexOf('未分配有效门店') >= 0;
  }

  function _notify(reason) {
    var snapshot = {
      storeId: state.storeId,
      stores: state.stores.slice(),
      allStores: state.allStores,
      ready: state.ready,
      noStore: state.noStore,
    };
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](snapshot, reason || 'init'); } catch (e) {
        console.warn('门店上下文监听器抛错:', e);
      }
    }
  }

  // ===== 缓存清理 =====

  /**
   * 清掉上一家店留在前端的全部痕迹。
   *
   * 5 类,少一类就是一次跨店串数据:
   *   1. State 里的业务数据(readings/charges/water/items/purchases/duty)
   *   2. 裸全局快照 window.CURRENT_*(报表模块读的是它们,不是 State)
   *   3. localStorage 离线缓存(后端不可用时的回退数据源 —— 最阴险的一个)
   *   4. 报表缓存(上一个店的月报/年报/水电报表)
   *   5. 充值归属缓存(上一个店的表底序列算出来的归属区间)
   */
  function clearCaches() {
    // 1. State
    try {
      if (typeof State !== 'undefined' && State && typeof State.reset === 'function') {
        State.reset();
      }
    } catch (e) { console.warn('清理 State 失败:', e); }
    // 2. 裸全局快照
    window.CURRENT_READINGS = [];
    window.CURRENT_CHARGES = [];
    window.CURRENT_WATER_READINGS = [];
    window.CURRENT_ITEMS = [];
    window.CURRENT_PURCHASES = [];
    window.CURRENT_DUTY = [];
    // 3. 离线缓存
    var ls = _localStorage();
    if (ls) {
      var keys = _offlineCacheKeys();
      try { ls.removeItem(keys.readings); } catch (e) { /* 忽略 */ }
      try { ls.removeItem(keys.charges); } catch (e) { /* 忽略 */ }
    }
    // 4. 报表缓存
    //    变量(_currentReport / _currentYearly / _currentUtilities)归 state.js 所有,
    //    由它导出的 resetReportCaches() 清 —— 这里不伸手碰别人的变量。
    try {
      if (typeof resetReportCaches === 'function') resetReportCaches();
      else console.warn('resetReportCaches 不可用,报表缓存可能残留');
    } catch (e) { console.warn('清理报表缓存失败:', e); }
    // 5. 充值归属缓存
    try {
      if (typeof resetChargeAttrCache === 'function') resetChargeAttrCache();
    } catch (e) { console.warn('清理充值归属缓存失败:', e); }
  }

  // ===== 对外 API =====

  var StoreContext = {
    /** 当前门店 ID('' = 尚未确定) */
    getStoreId: function () { return state.storeId; },

    /** 当前用户可见的门店列表 */
    getStores: function () { return state.stores.slice(); },

    /** 是否总部账号(all_stores=true) */
    getAllStores: function () { return state.allStores; },

    /** bootstrap 是否完成 */
    isReady: function () { return state.ready; },

    /** 账号未分配门店(前端要显示空态,而不是一屏报错) */
    hasNoStore: function () { return state.noStore; },

    /** 门店 ID 合法性(与后端同一套口径) */
    isValidStoreId: isValidStoreId,

    /** 订阅变更。返回退订函数。cb(state, reason) */
    onChange: function (cb) {
      if (typeof cb !== 'function') return function () {};
      listeners.push(cb);
      return function () {
        var i = listeners.indexOf(cb);
        if (i >= 0) listeners.splice(i, 1);
      };
    },

    /**
     * 引导:取可见门店列表 + 后端默认店,决定当前该待在哪家店。
     *
     * 选店规则(优先级从高到低):
     *   1. localStorage 里记住的店 —— 但必须在可见列表里,否则作废
     *   2. 后端 /api/stores/current 给的默认店(也要在可见列表里)
     *   3. 兜底:可见列表第一家(后端默认店拿不到时,口径与后端
     *      routing.py::_store_gate 的默认解析一致 —— 它也落到「有权访问的第一家」)
     *   4. 都没有 → 当前店为空(账号未分配门店)
     */
    init: function (reason) {
      // 已在引导中 → 复用同一次,不重复打后端
      if (initPromise) return initPromise;
      var p = (async function () {
        var listRes = null, curRes = null, listErr = null, curErr = null;
        try { listRes = await Api.stores.list(); } catch (e) { listErr = e; }
        try { curRes = await Api.stores.current(); } catch (e) { curErr = e; }

        // 列表拿不到 → 可能是「账号未分配门店」(403),也可能后端挂了
        if (listErr || !listRes || listRes.ok === false) {
          var msg = (listErr && listErr.message) || (listRes && listRes.error) || '';
          state.stores = [];
          state.allStores = false;
          state.noStore = _isNoStoreMessage(msg);
          state.storeId = '';
          _persist('');
          state.ready = true;
          _notify(state.noStore ? 'no-store' : (reason || 'init'));
          return '';
        }

        state.stores = listRes.stores || [];
        state.allStores = !!listRes.all_stores;
        state.noStore = state.stores.length === 0;

        var picked = '';
        var remembered = _readPersisted();
        if (isValidStoreId(remembered) && _hasStore(remembered)) {
          picked = remembered;
        } else if (curRes && curRes.ok !== false
                   && isValidStoreId(String(curRes.store_id || ''))
                   && _hasStore(String(curRes.store_id))) {
          picked = String(curRes.store_id);
        } else if (state.stores.length > 0
                   && isValidStoreId(String(state.stores[0].id || ''))) {
          // 后端默认店拿不到(current() 失败)→ 兜底到可见列表第一家。
          // 不兜底的话 storeId 为空而 noStore=false → 第三种状态,UI 无从显示。
          picked = String(state.stores[0].id);
        }
        state.storeId = picked;
        _persist(picked);
        state.ready = true;
        _notify(reason || 'init');
        return picked;
      })();
      initPromise = p;
      var done = function () { if (initPromise === p) initPromise = null; };
      p.then(done, done);
      return p;
    },

    /**
     * 切店。返回 false 表示拒绝(非法 ID / 不在可见列表里)。
     *
     * 只做「换店 + 清缓存 + 通知」;**不负责重新拉数据** ——
     * 数据刷新由 UI 层(切换器)订阅 onChange 后统一触发,
     * 避免这里和 UI 各刷一次。
     */
    switchTo: function (id) {
      // ⚠️ 不做 trim:trim 完 's002\n' 会变成合法的 's002' 被放行,
      // 而 isValidStoreId('s002\n') 是 false —— 两处口径必须一致。
      var sid = String(id == null ? '' : id);
      if (!isValidStoreId(sid)) return Promise.resolve(false);
      if (!_hasStore(sid)) return Promise.resolve(false);
      if (sid === state.storeId) return Promise.resolve(true);
      _persist(sid);
      state.storeId = sid;
      clearCaches();
      _notify('switch');
      return Promise.resolve(true);
    },

    /**
     * 登出时清空本地状态(门店选择也清掉 —— 换人登录不该继承上一家店)。
     *
     * 必须连 5 类缓存一起清:admin.js 的 clearAuth() 只隐藏按钮、清 token、显示登录页,
     * **不刷新页面** —— 内存里的数据与 localStorage 里的离线缓存都还在。
     * 用户 B 登入后若后端不可用,accessibility.js 会回退去读 meter_readings_v1 /
     * meter_charges_v1 → 把用户 A 的抄表记录显示给用户 B。
     */
    reset: function () {
      clearCaches();
      state.storeId = '';
      state.stores = [];
      state.allStores = false;
      state.ready = false;
      state.noStore = false;
      _persist('');
      // 先通知再退订:让还挂着的订阅者知道「登出了」,然后把订阅清空 ——
      // 登出再登入时 UI 会重新订阅 onChange,不退订会重复注册 → 同一次切店刷两遍数据。
      _notify('reset');
      listeners = [];
    },

    /** 清缓存(对外暴露,便于测试与特殊场景) */
    clearCaches: clearCaches,

    /**
     * 门店失效恢复入口 —— 由 api.js 在收到 403/404 且文案指向门店时调用。
     *
     * 两种情况要分开处理:
     *   - 「无权访问门店」/「门店不存在」:当前选中的店没了或权限被收回了
     *     → 清干净旧店的数据,退回后端默认店,重新引导,重新拉数据。
     *   - 「未分配门店」:账号被管理员取消了门店,不是「切错店」
     *     → 置空态,不重试。
     */
    handleStoreError: function (status, text) {
      var msg = String(text || '');
      if (state.recovering) return;
      if (_isNoStoreMessage(msg)) {
        // 账号已经没有门店了 → 旧店的数据(尤其 localStorage 离线缓存)必须清,
        // 不然用户会继续看着一个自己已经无权访问的门店的数据。
        clearCaches();
        state.storeId = '';
        state.stores = [];
        state.allStores = false;
        state.noStore = true;
        state.ready = true;
        _persist('');
        _notify('no-store');
        return;
      }
      var storeBroken = (status === 404 && msg.indexOf('门店不存在') >= 0)
                    || (status === 403 && msg.indexOf('无权访问门店') >= 0);
      if (!storeBroken) return;
      state.recovering = true;
      state.storeId = '';
      _persist('');
      // 恢复前必须清缓存:当前店已经失效(被删 / 权限被收回),
      // 旧店的数据留着就是跨店串数据 —— 尤其离线缓存,后端此刻不可用时
      // accessibility.js 会把它当成新门店的数据兜底显示出来。
      clearCaches();
      // 用闭包里的 StoreContext 而不是 this —— 被解构调用时 this 会是 undefined。
      StoreContext.init('recovered').then(function () {
        state.recovering = false;
      }, function () {
        state.recovering = false;
      });
    },
  };

  window.StoreContext = StoreContext;
})();
