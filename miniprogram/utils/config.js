// API 基址配置
// 开发期：指向 claude-vps 公网后端（demo_simulation 模式，无需 GPU）
// 真机预览时 project.config.json 的 urlCheck=false，免合法域名校验，可直连 http→IP
// 后续接 GPU 真实推理：改成 intern 的 HTTPS 隧道域名即可
const API_BASE = 'http://216.167.91.193:8026';

module.exports = { API_BASE };
