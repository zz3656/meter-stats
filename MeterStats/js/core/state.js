/**
 * 全局状态管理器（简化版）。
 *
 * 替代分散在全局的 readings/charges/items/purchases/duty 变量。
 * 每个模块通过 State.get() 读取数据，通过 State.set() 写入并触发刷新。
 *
 * 使用:
 *   var data = State.get("readings");
 *   State.set("readings", newData);  // 写入后调用 refreshAll() 刷新 UI
 */

// ===== 跨模块共享状态 =====
// ⚠️ 这些是前端模块化重构时丢失声明的全局变量。
// readings.js / charges.js / utilities.js / admin.js / reports.js 直接引用裸标识符，
// 读取未声明变量会抛 ReferenceError，导致表单提交/报表渲染整体失败。
// 必须用 var（顶层 var 是 window 属性，允许其它脚本重新赋值；let/const 跨文件赋值会报错）。
var _submitting = false;      // 防重复提交标志
var _currentReport = null;    // 当前月份报表缓存（供「复制表格」使用，reports.js 写入）
var _currentYearly = null;    // 当前年份汇总缓存（供「复制」使用）
var _currentUtilities = null; // 当前月份水电缓存（供月度报告复制使用）

/** 设置防重复提交状态 */
function setSubmitting(val) {
    _submitting = val;
}

const State = (() => {
    var data = {};

    // data key → 旧版全局变量名。
    // ⚠️ 模块化重构后存在两套数据源：新模块走 State.get()，而 reports.js /
    // accessibility.js / admin.js / init.js 仍在读裸全局 CURRENT_xxx。
    // 若不同步，CURRENT_READINGS 永远是 []，导致余量预警、趋势图、单天用电、
    // 首屏月份选项全部拿不到数据（且不报错，极难排查）。
    var GLOBAL_ALIAS = {
        readings: 'CURRENT_READINGS',
        charges: 'CURRENT_CHARGES',
        water: 'CURRENT_WATER_READINGS',
        items: 'CURRENT_ITEMS',
        purchases: 'CURRENT_PURCHASES',
        duty: 'CURRENT_DUTY',
    };

    return {
        /** 获取数据 */
        get: function(key) {
            return data[key];
        },

        /** 设置数据（同时同步到旧版全局变量） */
        set: function(key, value) {
            data[key] = value;
            var alias = GLOBAL_ALIAS[key];
            if (alias) {
                window[alias] = value;
            }
        },

        /** 初始化所有数据为 [] */
        init: function() {
            // "water" 必须在列表里:renderAll() 会 State.set("water", …),
            // 漏了它 → State.get("water") 初始是 undefined,
            // 渲染水电表时 .sort() 直接抛 TypeError。
            var keys = ["readings", "charges", "water", "items", "purchases", "duty", "settings"];
            for (var i = 0; i < keys.length; i++) {
                if (data[keys[i]] === undefined) data[keys[i]] = [];
            }
        },

        /**
         * 清空所有数据(切门店时调用)。
         *
         * 必须连报表缓存一起清:_currentReport / _currentYearly / _currentUtilities
         * 存的是上一个门店的月报/年报/水电报表,不清 → 切店后「复制表格」复制的是
         * 上一家店的数字。
         */
        reset: function() {
            data = {};
            // ⚠️ 不能写 init():仓库里没有全局 init 函数,那是 ReferenceError。
            // State.init() 是同一个闭包里的方法,等价于重新初始化所有键。
            State.init();
            _currentReport = null;
            _currentYearly = null;
            _currentUtilities = null;
        },

        /** 获取所有数据 */
        all: function() {
            return data;
        }
    };
})();

State.init();
