// ===== 元数据（从 /api/meters 动态获取，含 fallback 默认值）=====
window.METER_CONFIG = {
  hall:   { label: '大厅',   icon: '🎤', multiplier: 160, color: '#2563eb' },
  fire:   { label: '消防',   icon: '🧯', multiplier: 1,   color: '#dc2626' },
  private_room: { label: '包厢', icon: '🛋️', multiplier: 160, color: '#059669' },
  ac:     { label: '空调',   icon: '❄️', multiplier: 160, color: '#d97706' },
};

// 快捷访问数组（保持顺序不变）
window.METER_KEYS = ['hall', 'fire', 'private_room', 'ac'];
window.METER_META = (key) => window.METER_CONFIG[key] || { label: key, icon: '', multiplier: 1, color: '#888' };
window.MULTIPLIER = (key) => window.METER_META(key).multiplier;
window.LABELS = (key) => window.METER_META(key).label;
window.COLORS = (key) => window.METER_META(key).color;

// 加载元数据（异步，不阻塞页面加载）
async function loadMeterConfig() {
  try {
    const resp = await fetch('/api/meters', { credentials: 'same-origin' });
    if (resp.ok) {
      const data = await resp.json();
      if (data.meters) {
        for (const [key, val] of Object.entries(data.meters)) {
          METER_CONFIG[key] = { ...METER_CONFIG[key], ...val };
        }
        // 更新快捷访问
      }
    }
  } catch (e) {
    // 静默失败，使用默认值
  }
}