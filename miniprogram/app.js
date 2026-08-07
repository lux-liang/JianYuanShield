// 寻源路小程序入口
const { API_BASE, apiConfigStatus } = require('./utils/config');

App({
  globalData: {
    apiBase: API_BASE,
    apiConfig: apiConfigStatus(),
    splashShown: false,
  },
  onLaunch() {
    // 预留：可在此做一次 /api/health 预热
  },
});
