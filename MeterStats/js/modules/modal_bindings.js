/**
 * 弹窗按钮绑定（集中管理）。
 *
 * ⚠️ 模块化重构时整段丢失 —— 旧 app.js 2690-2720 / 3680-3760 那批
 * `getElementById('xxx-close')?.addEventListener(...)` 全部没搬过来。
 * 症状：弹窗里的「取消」点了没反应，弹窗关不掉（只能刷新页面）。
 * 这些按钮在 HTML 里没有 onclick，全靠这里挂监听。
 *
 * 约定：所有绑定都做存在性判断，缺 DOM 不报错（移动端/精简布局可能不含某些弹窗）。
 */
(function () {
  'use strict';

  function on(id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  }

  /** 点遮罩空白处关闭（点内容区不关） */
  function onBackdrop(backdropId, closeFn) {
    var b = document.getElementById(backdropId);
    if (!b) return;
    b.addEventListener('click', function (e) {
      if (e.target === b) closeFn();
    });
  }

  // ==================== 抄表 / 水电（同一弹窗，按可见面板路由）====================
  on('reading-add-confirm', function () {
    // 弹窗里已经没有 Tab 了，哪个面板可见就提交哪个
    var utilityPanel = document.querySelector('#reading-add-modal-backdrop .tab-panel[data-panel="utility"]');
    var isUtility = utilityPanel && utilityPanel.style.display !== 'none';
    if (isUtility) {
      if (typeof submitUtilityAdd === 'function') submitUtilityAdd('modal');
    } else {
      if (typeof submitReadingAdd === 'function') submitReadingAdd('modal');
    }
  });
  on('reading-add-close', function () {
    if (typeof closeReadingAddModal === 'function') closeReadingAddModal();
  });
  onBackdrop('reading-add-modal-backdrop', function () {
    if (typeof closeReadingAddModal === 'function') closeReadingAddModal();
  });

  // ==================== 充值 ====================
  on('charge-add-confirm', function () {
    if (typeof submitChargeAdd === 'function') submitChargeAdd('modal');
  });
  on('charge-add-close', function () {
    if (typeof closeChargeAddModal === 'function') closeChargeAddModal();
  });
  onBackdrop('charge-add-modal-backdrop', function () {
    if (typeof closeChargeAddModal === 'function') closeChargeAddModal();
  });

  // ==================== 物品借出 ====================
  on('lend-confirm', function () {
    var id = (document.getElementById('lend-item-id') || {}).value;
    var qty = (document.getElementById('lend-qty') || {}).value;
    var borrower = (document.getElementById('lend-borrower') || {}).value;
    var note = (document.getElementById('lend-note') || {}).value;
    if (!id) return;
    var bImgs = (typeof getFieldImages === 'function') ? getFieldImages('lend-borrower') : [];
    // 借出人必填，但「填名字」和「传张图」满足其一即可
    if ((!borrower || !String(borrower).trim()) && !bImgs.length) {
      showAlert('请填写借出人，或直接传一张照片', 'error'); return;
    }
    if (!qty || parseFloat(qty) <= 0) { showAlert('借出数量必须大于 0', 'error'); return; }
    if (typeof lendItem === 'function') lendItem(id, String(borrower || '').trim(), qty, (note || '').trim(), bImgs);
    if (typeof closeLendModal === 'function') closeLendModal();
  });
  on('lend-close', function () {
    if (typeof closeLendModal === 'function') closeLendModal();
  });
  onBackdrop('lend-modal-backdrop', function () {
    if (typeof closeLendModal === 'function') closeLendModal();
  });

  // ==================== 物品归还 ====================
  on('return-confirm', function () {
    var id = (document.getElementById('return-item-id') || {}).value;
    var qty = (document.getElementById('return-qty') || {}).value;
    var note = (document.getElementById('return-note') || {}).value;
    var returnBy = (document.getElementById('return-by') || {}).value;
    if (!id) return;
    if (!qty || parseFloat(qty) <= 0) { showAlert('归还数量必须大于 0', 'error'); return; }
    var rImgs = (typeof getFieldImages === 'function') ? getFieldImages('return-by') : [];
    if ((!returnBy || !String(returnBy).trim()) && !rImgs.length) {
      showAlert('请填写归还人，或直接传一张照片', 'error'); return;
    }
    if (typeof returnItem === 'function') returnItem(id, qty, (note || '').trim(), String(returnBy || '').trim(), rImgs);
    if (typeof closeReturnModal === 'function') closeReturnModal();
  });
  on('return-close', function () {
    if (typeof closeReturnModal === 'function') closeReturnModal();
  });
  onBackdrop('return-modal-backdrop', function () {
    if (typeof closeReturnModal === 'function') closeReturnModal();
  });

  // ==================== 充值计算器 ====================
  on('topup-close', function () {
    if (typeof closeTopupModal === 'function') closeTopupModal();
  });
  onBackdrop('topup-modal-backdrop', function () {
    if (typeof closeTopupModal === 'function') closeTopupModal();
  });

  // ==================== 物品新增 ====================
  on('item-add-confirm', function () {
    var v = function (id) { var el = document.getElementById(id); return el ? el.value : ''; };
    var name = v('item-add-name').trim();
    var qty = parseFloat(v('item-add-qty'));
    if (!name) { showAlert('请填写物品名称', 'error'); return; }
    if (isNaN(qty) || qty < 0) { showAlert('数量必须 ≥ 0', 'error'); return; }
    if (typeof addItem === 'function') {
      addItem(name, qty, v('item-add-unit').trim() || '个', v('item-add-note').trim());
    }
    ['item-add-name', 'item-add-qty', 'item-add-unit', 'item-add-note'].forEach(function (id) {
      var el = document.getElementById(id); if (el) el.value = '';
    });
    if (typeof closeItemAddModal === 'function') closeItemAddModal();
  });

  // ==================== 申购新增 ====================
  on('purchase-add-confirm', function () {
    var v = function (id) { var el = document.getElementById(id); return el ? el.value : ''; };
    var name = v('purchase-add-name').trim();
    var qty = parseFloat(v('purchase-add-qty'));
    var price = parseFloat(v('purchase-add-price'));
    // 物品名称：写名字，或直接拍张照（不知道叫什么的时候）
    var nameImgs = (typeof getFieldImages === 'function') ? getFieldImages('purchase-add-name') : [];
    if (!name && !nameImgs.length) { showAlert('请填写物品名称，或拍一张照片', 'error'); return; }
    if (isNaN(qty) || qty <= 0) { showAlert('数量必须大于 0', 'error'); return; }
    if (typeof addPurchase === 'function') {
      addPurchase(
        v('purchase-add-date') || todayStr(),
        name,
        qty,
        v('purchase-add-unit').trim() || '个',
        isNaN(price) ? 0 : price,
        v('purchase-add-supplier').trim(),
        v('purchase-add-note').trim(),
        (typeof getFieldImages === 'function') ? getFieldImages('purchase-add-note') : [],
        nameImgs
      );
    }
    if (typeof closePurchaseAddModal === 'function') closePurchaseAddModal();
  });

  // ==================== 工作记录新增 ====================
  // 后端字段是 duty_type / record_time / shift / status / fault_area / note，
  // 其中 status 必填 —— 新增的记录本来就是「未处理」，所以固定传这个值，
  // 弹窗里不再让用户选（选了「已处理」等于绕过后续处理流程）。
  on('duty-add-confirm', function () {
    var v = function (id) { var el = document.getElementById(id); return el ? el.value : ''; };
    var type = v('duty-add-type');
    var shift = v('duty-add-shift');
    var time = v('duty-add-time');
    if (!type) { showAlert('请选择类型', 'error'); return; }
    if (!shift) { showAlert('请选择班次', 'error'); return; }
    // 故障信息必填：文字和图片可以同时填，满足其一即可
    var faultInfo = v('duty-add-note').trim();
    var noteImgs = (typeof getFieldImages === 'function') ? getFieldImages('duty-add-note') : [];
    if (!faultInfo && !noteImgs.length) {
      showAlert('请填写故障信息（文字或照片都可以）', 'error'); return;
    }
    // datetime-local → "YYYY-MM-DD HH:MM:SS"
    var recordTime = time ? time.replace('T', ' ') + ':00' : '';
    if (typeof addDuty === 'function') {
      addDuty(type, recordTime, shift, '未处理', v('duty-add-fault-area').trim(), faultInfo, noteImgs);
    }
    if (typeof closeDutyAddModal === 'function') closeDutyAddModal();
  });

  // ==================== 工作记录：处理弹窗 ====================
  on('duty-handle-confirm', function () {
    var v = function (id) { var el = document.getElementById(id); return el ? el.value : ''; };
    var id = v('duty-handle-id');
    var time = v('duty-handle-time');
    var shift = v('duty-handle-shift');
    var method = v('duty-handle-method');
    var note = v('duty-handle-note');
    if (!id) { showAlert('记录 ID 缺失，请重新打开', 'error'); return; }
    if (!shift) { showAlert('请选择班次', 'error'); return; }
    var mImgs = (typeof getFieldImages === 'function') ? getFieldImages('duty-handle-method') : [];
    if (!method.trim() && !mImgs.length) {
      showAlert('请填写处理方案，或直接传一张照片', 'error'); return;
    }
    var handleTime = time ? (time.length > 16 ? time : time.replace('T', ' ') + ':00') : '';
    if (typeof handleDuty === 'function') handleDuty(id, handleTime, shift, method.trim(), note.trim(), mImgs);
    if (typeof closeDutyHandleModal === 'function') closeDutyHandleModal();
  });
  on('duty-handle-close', function () {
    if (typeof closeDutyHandleModal === 'function') closeDutyHandleModal();
  });
  onBackdrop('duty-handle-modal-backdrop', function () {
    if (typeof closeDutyHandleModal === 'function') closeDutyHandleModal();
  });

  // ==================== 无入口的死弹窗（只挂关闭，防止将来启用后卡住）====================
  ['item-add', 'purchase-add', 'duty-add'].forEach(function (name) {
    var backdropId = name + '-modal-backdrop';
    var hide = function () {
      var b = document.getElementById(backdropId);
      if (b) b.classList.remove('show');
    };
    on(name + '-close', hide);
    onBackdrop(backdropId, hide);
  });

  // ==================== Esc 关闭最上层弹窗（旧 app.js 也有，同样丢了）====================
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var layers = [
      ['reading-add-modal-backdrop', 'closeReadingAddModal'],
      ['charge-add-modal-backdrop', 'closeChargeAddModal'],
      ['lend-modal-backdrop', 'closeLendModal'],
      ['return-modal-backdrop', 'closeReturnModal'],
      ['topup-modal-backdrop', 'closeTopupModal'],
      ['charge-edit-modal-backdrop', 'closeChargeEditModal'],
      ['reading-edit-modal-backdrop', 'closeReadingEditModal'],
      ['water-edit-modal-backdrop', 'closeWaterEditModal'],
    ];
    for (var i = 0; i < layers.length; i++) {
      var b = document.getElementById(layers[i][0]);
      if (b && b.classList.contains('show')) {
        var fn = window[layers[i][1]];
        if (typeof fn === 'function') fn();
        else b.classList.remove('show');
        e.preventDefault();
        return;
      }
    }
    // 确认弹窗兜底（showModal 自己管理 resolve，这里只隐藏会挂住 Promise，故不处理）
  });
})();
