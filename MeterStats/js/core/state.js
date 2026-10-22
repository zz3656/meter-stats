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
const State = (() => {
    var data = {};

    return {
        /** 获取数据 */
        get: function(key) {
            return data[key];
        },

        /** 设置数据 */
        set: function(key, value) {
            data[key] = value;
        },

        /** 初始化所有数据为 [] */
        init: function() {
            var keys = ["readings", "charges", "items", "purchases", "duty", "settings"];
            for (var i = 0; i < keys.length; i++) {
                if (data[keys[i]] === undefined) data[keys[i]] = [];
            }
        },

        /** 获取所有数据 */
        all: function() {
            return data;
        }
    };
})();

State.init();
