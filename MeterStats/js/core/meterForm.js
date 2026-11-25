/**
 * 表输入表单 —— 按**当前门店**的表集合渲染 / 收集 / 回填。
 *
 * P2「每店自己的表数量与倍率」。改造前有 6 组表单(抄表/充值的 录入·新增·编辑)
 * 各自写死 4 个 `<input>`，共 24 个；`<label>` 里的乘率提示(「读数 × 160」)
 * 也写死了 25 处。门店换成 2 块表或改一块表的倍率，页面就得跟着错。
 *
 * 这里把「一组表输入」收成一个渲染器：
 *   renderAll()  按 window.METER_KEYS 重渲染 6 组容器
 *   collect()    收集一组输入 → 旧 4 表顶层字段 / 自定义表 meters 字典
 *   fill()       把一行数据回填进一组输入(读值时走 meterValue)
 *   clear()      清空一组输入
 *   renderHead() 渲染表格表头(列数跟着表集合走)
 *
 * ⚠️ 输入框 id 规则固定为「前缀 + 表 key」(`reading-add-hall` / `charge-edit-m1`)，
 * 与改造前完全一致 —— 下游按 id 取值/回填的代码因此不用大改。
 */
(function () {
  'use strict';

  // 旧 4 表:值在记录顶层字段(与后端 modules/stores/meters.py::LEGACY_KEYS 同一份)
  var LEGACY_KEYS = ['hall', 'fire', 'private_room', 'ac'];

  // 6 组表单:容器 id / input id 前缀 / 版式 / 语义
  var GROUPS = [
    { id: 'mf-reading-entry', prefix: '',              style: 'row',   mode: 'reading' },
    { id: 'mf-charge-entry',  prefix: 'charge-',       style: 'row',   mode: 'charge' },
    { id: 'mf-reading-add',   prefix: 'reading-add-',  style: 'block', mode: 'reading' },
    { id: 'mf-charge-add',    prefix: 'charge-add-',   style: 'block', mode: 'charge' },
    { id: 'mf-reading-edit',  prefix: 'reading-edit-', style: 'block', mode: 'reading' },
    { id: 'mf-charge-edit',   prefix: 'charge-edit-',  style: 'block', mode: 'charge' },
  ];

  function currentKeys() {
    var ks = window.METER_KEYS;
    return (ks && ks.length) ? ks.slice() : LEGACY_KEYS.slice();
  }

  /**
   * 倍率提示 —— 必须由 multiplier 生成。
   *
   * 写死「读数 × 160」的后果:门店把倍率改成 80,页面还写着 × 160,
   * 用户按提示手算就得到两倍的度数。这条不是装饰文案,是计算依据。
   */
  function hintFor(mult, mode) {
    var isOne = (mult === 1 || mult === '1');
    if (mode === 'charge') return isOne ? '表读数' : ('表读数 ×' + mult);
    return isOne ? '读数即实际电量' : ('读数 × ' + mult);
  }

  function inputHtml(id, mode, style) {
    var ph = mode === 'charge' ? '没充就留空' : '例如 65.30';
    var min = mode === 'charge' ? ' min="0"' : '';
    var w = style === 'block' ? ' style="width:100%;"' : '';
    return '<input type="number" id="' + id + '" step="0.01" placeholder="' + ph + '"' + min + w + ' />';
  }

  function rowHtml(label, input) {
    return '<div class="form-row reading"><label>' + label + '</label>' + input + '</div>';
  }

  function blockHtml(label, input) {
    return '<div style="margin-bottom:12px;">'
      + '<label style="display:block;font-size:13px;font-weight:510;'
      + 'margin-bottom:6px;color:var(--text);">' + label + '</label>'
      + input + '</div>';
  }

  function specById(id) {
    for (var i = 0; i < GROUPS.length; i++) if (GROUPS[i].id === id) return GROUPS[i];
    return null;
  }

  function renderOne(spec) {
    var el = document.getElementById(spec.id);
    if (!el) return;
    var wrap = spec.style === 'block' ? blockHtml : rowHtml;
    el.innerHTML = currentKeys().map(function (k, i) {
      var meta = (typeof window.METER_META === 'function')
        ? window.METER_META(k) : { label: k, multiplier: 1 };
      var text = (i + 1) + '#' + (meta.label || k);
      var label = (typeof escapeHtml === 'function' ? escapeHtml(text) : text)
        + ' <span class="hint">'
        + (typeof escapeHtml === 'function' ? escapeHtml(hintFor(meta.multiplier, spec.mode)) : '')
        + '</span>';
      return wrap(label, inputHtml(spec.prefix + k, spec.mode, spec.style));
    }).join('');
  }

  var MeterForm = {
    GROUPS: GROUPS,
    LEGACY_KEYS: LEGACY_KEYS,
    keys: currentKeys,

    /** 重渲染全部 6 组(切门店 / 加载完表元数据之后调用) */
    renderAll: function () {
      for (var i = 0; i < GROUPS.length; i++) renderOne(GROUPS[i]);
    },

    /** 重渲染单组(容器 id) */
    render: function (containerId) {
      var spec = specById(containerId);
      if (spec) renderOne(spec);
    },

    /**
     * 收集一组输入的值。
     *
     * 返回 { all, legacy, meters, hasNaN }:
     *   all    {key: 数字|null|NaN}  —— 空输入是 null,非数字是 NaN(交给调用方报错)
     *   legacy 旧 4 表 → 顶层字段
     *   meters 自定义表 → meters 字典(空值不入)
     *   hasNaN 有没有填了非数字
     */
    collect: function (prefix, keys) {
      var ks = keys || currentKeys();
      var all = {}, legacy = {}, meters = {}, hasNaN = false;
      ks.forEach(function (k) {
        var el = document.getElementById(prefix + k);
        var raw = el ? String(el.value).trim() : '';
        var num = null;
        if (raw !== '') {
          num = parseFloat(raw);
          if (isNaN(num)) hasNaN = true;
        }
        all[k] = num;
        if (LEGACY_KEYS.indexOf(k) >= 0) legacy[k] = num;
        else if (num !== null && !isNaN(num)) meters[k] = num;
      });
      return { all: all, legacy: legacy, meters: meters, hasNaN: hasNaN, keys: ks };
    },

    /** 把一行数据回填进一组输入(读值走 meterValue,自定义表也能填) */
    fill: function (row, prefix, keys) {
      var ks = keys || currentKeys();
      ks.forEach(function (k) {
        var el = document.getElementById(prefix + k);
        if (!el) return;
        var v = (typeof window.meterValue === 'function') ? window.meterValue(row, k) : row[k];
        el.value = (v == null) ? '' : v;
      });
    },

    /** 清空一组输入 */
    clear: function (prefix, keys) {
      var ks = keys || currentKeys();
      ks.forEach(function (k) {
        var el = document.getElementById(prefix + k);
        if (el) el.value = '';
      });
    },

    /** 把收集结果拍成接口要的载荷:旧 4 表顶层 + meters 字典(可选) */
    toPayload: function (collected, opts) {
      var options = opts || {};
      var out = {};
      if (options.keepNullLegacy) {
        // POST 语义:没填的旧表字段照旧送 null(与改造前一致)
        Object.keys(collected.legacy).forEach(function (k) { out[k] = collected.legacy[k]; });
      } else {
        Object.keys(collected.legacy).forEach(function (k) {
          if (collected.legacy[k] !== null) out[k] = collected.legacy[k];
        });
      }
      if (Object.keys(collected.meters).length) out.meters = collected.meters;
      return out;
    },

    /**
     * 渲染表格表头。
     *
     * @param {string} trId   `<tr>` 的 id
     * @param {string[]} before 表列之前的固定列(如「日期」)
     * @param {string[]} after  表列之后的固定列(如「备注」「操作」)
     */
    renderHead: function (trId, before, after) {
      var tr = document.getElementById(trId);
      if (!tr) return;
      var ks = currentKeys();
      var cells = (before || []).map(function (t) { return '<th>' + t + '</th>'; });
      cells = cells.concat(ks.map(function (k, i) {
        var meta = (typeof window.METER_META === 'function')
          ? window.METER_META(k) : { label: k };
        var text = (i + 1) + '#' + (meta.label || k);
        return '<th>' + (typeof escapeHtml === 'function' ? escapeHtml(text) : text) + '</th>';
      }));
      cells = cells.concat((after || []).map(function (t) { return '<th>' + t + '</th>'; }));
      tr.innerHTML = cells.join('');
    },
  };

  // ==================== 电表设置页(P2:增删表) ====================

  var SETTINGS_ICONS = ['⚡', '🍸', '🔥', '💡', '🌡️', '🔌', '🧊', '🎛️'];

  /**
   * 下一个可用的表 key:`m1` / `m2` …，避开已用的。
   *
   * 刻意不用旧 4 表的 key(hall/fire/private_room/ac)作为新表名 ——
   * 那 4 个 key 的值固定写记录顶层字段,新表复用会让「这块表的数据在哪」
   * 变成需要猜的事(虽然后端允许,但人看着会乱)。
   */
  function nextMeterKey(used) {
    var taken = used || [];
    var n = 1;
    while (taken.indexOf('m' + n) >= 0) n++;
    return 'm' + n;
  }

  function _esc(x) {
    return (typeof escapeHtml === 'function') ? escapeHtml(x) : String(x == null ? '' : x);
  }
  function _escAttr(x) {
    return (typeof escapeAttr === 'function') ? escapeAttr(x) : _esc(x);
  }

  /**
   * 渲染设置页的表定义单元格。
   *
   * @param {HTMLElement} form 容器
   * @param {Array} list        [{key,label,icon,multiplier}]
   * @param {Function} onDelete 点删除时回调(收到 key)
   */
  function renderSettings(form, list, onDelete) {
    if (!form) return;
    var canDelete = list.length > 1;   // 至少保留 1 块表
    form.innerHTML = list.map(function (m, i) {
      var key = String(m.key || '');
      var label = String(m.label || '');
      var icon = String(m.icon || '⚡');
      var mult = (m.multiplier != null && !isNaN(m.multiplier)) ? m.multiplier : '';
      return '' +
        '<div class="meter-cell" data-meter-key="' + _escAttr(key) + '">' +
          '<div class="meter-cell-title">' +
            _esc(icon + ' ' + (i + 1) + '#' + (label || key)) +
            (canDelete
              ? '<button type="button" class="meter-del-btn" data-remove-key="' + _escAttr(key) + '" ' +
                'title="删除这块表" style="float:right;color:var(--danger);background:none;' +
                'border:none;cursor:pointer;font-size:14px;line-height:1;">✕</button>'
              : '') +
          '</div>' +
          '<div class="meter-cell-row"><label>表名</label>' +
            '<input type="text" class="meter-input" data-key="' + _escAttr(key) + '" data-field="label" ' +
            'value="' + _escAttr(label) + '" maxlength="20"></div>' +
          '<div class="meter-cell-row"><label>倍率</label>' +
            '<input type="number" class="meter-input" data-key="' + _escAttr(key) + '" data-field="multiplier" ' +
            'min="1" step="1" value="' + _escAttr(mult) + '"></div>' +
          '<div class="meter-cell-row"><label>图标</label>' +
            '<input type="text" class="meter-input" data-key="' + _escAttr(key) + '" data-field="icon" ' +
            'value="' + _escAttr(icon) + '" maxlength="4"></div>' +
        '</div>';
    }).join('');

    // 事件委托式绑定 —— 不用内联 onclick,省掉把 key 拼进 JS 字符串(XSS 面)
    if (typeof onDelete === 'function' && form.querySelectorAll) {
      form.querySelectorAll('.meter-del-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          onDelete(btn.getAttribute('data-remove-key'));
        });
      });
    }
  }

  /** 把设置页的输入读回 [{key,label,icon,multiplier}] */
  function readSettings(form) {
    var out = [];
    if (!form || !form.querySelectorAll) return out;
    form.querySelectorAll('.meter-cell').forEach(function (cell) {
      var item = { key: cell.getAttribute('data-meter-key') || '', label: '', icon: '', multiplier: NaN };
      cell.querySelectorAll('.meter-input').forEach(function (inp) {
        var f = inp.getAttribute('data-field');
        if (f === 'label') item.label = inp.value;
        else if (f === 'icon') item.icon = inp.value;
        // 刻意不兜底成 1:非法值原样交给后端拒绝,而不是替用户静默改掉
        else if (f === 'multiplier') item.multiplier = parseInt(inp.value, 10);
      });
      out.push(item);
    });
    return out;
  }

  /** 设置页的列表 → 接口载荷(数组)。倍率非法值原样传,交给后端拒绝。 */
  function settingsPayload(list) {
    return (list || []).map(function (m) {
      return {
        key: String(m.key || ''),
        label: String(m.label || ''),
        icon: String(m.icon || ''),
        multiplier: m.multiplier,
      };
    });
  }

  MeterForm.SETTINGS_ICONS = SETTINGS_ICONS;
  MeterForm.settingsPayload = settingsPayload;
  MeterForm.nextMeterKey = nextMeterKey;
  MeterForm.renderSettings = renderSettings;
  MeterForm.readSettings = readSettings;

  window.MeterForm = MeterForm;

  /**
   * 重渲染所有依赖表集合的界面:6 组表单 + 两个记录表表头。
   *
   * 加载完表元数据、以及切门店之后都要调一次 —— 漏掉表头就是
   * 「表单是 2 块表、表格还是 4 列」这种错位。
   */
  window.renderMeterUi = function renderMeterUi() {
    MeterForm.renderAll();
    MeterForm.renderHead('reading-thead-row', ['日期'], ['备注', '']);
    MeterForm.renderHead('charge-thead-row', ['日期'], ['金额', '备注', '']);
  };
})();
