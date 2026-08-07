# 寻源路 · 鉴源盾微信小程序端

“寻源路”是鉴源盾的移动端来源保护与登记核验入口。它演示三类严格隔离的能力：

1. 已登记内容的 `protect → verify` 来源保护闭环；
2. 签名 MEA 逐图证据驱动的单模型部署建议；
3. `infer/single` 的单样本模型工程评估。

工程评估不是既有内容盲检，不能输出来源、平台合规或司法取证结论。小程序不会仅凭“运行了真实检查点”就把结果标为可引用。

## 1. 可信门禁

页面统一使用 `utils/trust.js` 执行 fail-closed 门禁。只有以下三项同时满足，并且 `result_provenance` 与当前场景严格对应，才显示“可引用”：

| 场景 | 必须满足的三元组 |
|---|---|
| 来源保护登记 | `mode=real_checkpoint`、`claim_valid=true`、`result_provenance=registered_protection_record` |
| 登记来源核验 | `mode=real_checkpoint`、`claim_valid=true`、`result_provenance=registered_blind_verification` |

下列情况一律不可引用：

- `/api/infer/single` 单样本模型评估；
- MEA 多模型单样本评估；
- `demo_simulation` 演示输出；
- `capability_unavailable`、请求失败或字段缺失；
- `claim_valid` 不为布尔值 `true`；
- `result_provenance` 缺失、未知或与页面场景不匹配；
- 旧版本历史记录缺少完整可信三元组。

这里的“可引用”仅表示本次技术记录通过系统定义的模型、签名与登记来源门禁，不自动等同于司法采信、监管认定或平台合规。

## 2. 功能概览

| 模块 | 行为与边界 |
|---|---|
| 来源保护登记 | 上传授权图片、创作者标识和模型，调用 `/api/provenance/protect`，获取 `content_id` 与保护图。 |
| 登记来源核验 | 使用 `content_id` 和待核验传播图调用 `/api/provenance/verify`，展示匹配信号及可信门禁。 |
| 单样本工程评估 | 调用 `/api/infer/single` 展示嵌入、攻击模拟、解码指标；固定不可引用。 |
| MEA 部署建议 | 严格验签 `collaboration-recommendation.v2`，展示 217 身份等权 cluster bootstrap、96 项选择族、硬约束 Pareto、选择稳定率与旧/新统计消融；只输出建议，不自动执行双水印。 |
| 平台合规能力门禁 | 盲检能力未实现期间不上传所选批量图片、不计算合规率，只显示不可判定。 |
| 完整性审计 | 展示 Ed25519 验签、公钥指纹和审计阻断项；不把验签包装成法律结论。 |
| 本地任务历史 | 保存最近 15 条保护、核验或评估展示记录，并在每次读取时重新执行可信门禁。 |
| 技术记录卡 | 可生成带有效门禁状态的图片；无效结果会醒目标注“禁止作来源/合规/取证结论”。 |

## 3. 目录结构

```text
miniprogram/
├── app.js
├── app.json
├── app.wxss
├── project.config.json
├── sitemap.json
├── assets/
├── components/
├── pages/
│   ├── home/                 # 保护、核验、完整性审计、历史与关于
│   └── mea/                  # 多模型单样本工程评估
├── scripts/
│   └── check-trust-gate.js   # 可信门禁与静态文案检查
└── utils/
    ├── config.js             # HTTPS 后端与 extConfig 配置
    ├── request.js            # request/uploadFile 封装
    ├── format.js             # 指标格式化
    ├── history.js            # fail-closed 本地历史
    └── trust.js              # 三元可信门禁唯一实现
```

项目为原生微信小程序，当前没有 npm 依赖。

## 4. 运行配置

### 4.1 后端地址

仓库默认不配置公网服务器。开发或发布时可在 `utils/config.js` 填写 HTTPS 构建地址，推荐由微信 `extConfig` 注入：

```json
{
  "jysApiBase": "https://api.example.edu.cn"
}
```

约束如下：

- 必须使用标准 HTTPS 域名；拒绝 HTTP、IP、localhost、自定义端口、URL 凭据、查询参数和片段；
- 必须在微信公众平台配置 request、uploadFile 与 downloadFile 合法域名；
- `project.config.json` 开启合法域名校验；
- 未配置时页面显示“配置阻断”，不会尝试上传图片。

### 4.2 API 鉴权

当后端启用 `JYS_REQUIRE_API_KEY` 时，可在受控竞赛演示环境通过 `extConfig.jysApiKey` 注入：

```json
{
  "jysApiBase": "https://api.example.edu.cn",
  "jysApiKey": "replace-with-demo-key"
}
```

不要把 API key 写入仓库。小程序客户端中的静态值可被提取，正式生产必须改用用户会话、短期令牌或受控网关，不能把 `extConfig.jysApiKey` 当作长期秘密。

### 4.3 后端可信依赖

`protect` 或 `verify` 返回 `claim_valid=true` 还依赖后端完成真实检查点注册、来源密钥配置和事件签名。能力未就绪时，接口可能返回不可引用记录或明确的能力错误；小程序不会在前端补造结论。

## 5. 微信开发者工具运行

1. 打开微信开发者工具，导入包含 `project.config.json` 的 `miniprogram/` 目录。
2. 确认 AppID、HTTPS 合法域名和 `extConfig`。
3. 点击“编译”。
4. 首次进入设置本地头像与昵称；昵称仅作为创作者标识默认值，提交保护登记前可修改。
5. 查看首页右上角：`在线` 表示 `/api/health` 可访问，`未配置/离线` 时先修复连接。

## 6. 主流程：保护登记 → 登记核验

### 6.1 创建来源保护登记

1. 选择自己有权处理的图片，或使用后端公开内置样本。
2. 阅读并勾选上传用途提示。
3. 填写 1–128 字符的创作者标识。
4. 选择水印模型。
5. 点击“创建来源保护登记”。
6. 保存页面返回的 32 位 `content_id` 与保护图。
7. 检查 `mode`、后端原始 `claim_valid`、`result_provenance` 和前端有效引用门禁。

保护记录被创建不代表它一定可引用；只有 `registered_protection_record` 对应的完整三元组通过才可引用。

### 6.2 核验已登记来源

1. 输入保护阶段返回的 `content_id`。
2. 选择保护图或经过受控传播后的待核验图片。
3. 确认处理权限与上传用途。
4. 点击“核验已登记来源”。
5. 查看 Bit Accuracy、核验阈值、`verified` 技术匹配信号和可信门禁。

“匹配”与“未匹配”都可能是可引用的技术结果，但前提是核验响应同时满足 `real_checkpoint + claim_valid=true + registered_blind_verification`。门禁未通过时，即使数值高于阈值也不得引用。

## 7. 工程评估与能力边界

### 7.1 `/api/infer/single`

该接口执行“嵌入新水印 → 攻击模拟 → 解码”，用于查看 Bit Accuracy、PSNR 与可视化产物。它不能证明上传图片原本含有水印，也没有登记记录上下文，所以固定显示：

```text
EVALUATION ONLY · 禁止作来源/合规/取证结论
```

即使返回 `mode=real_checkpoint`，也不会变为可引用。

### 7.2 MEA 横评

页面上半部分调用 `/api/collaboration/recommend`：只有 policy、MEA 五件套、release-core 签名、固定 signer、256/217/24/63/10 身份审计、20,000 次 bootstrap 与 96 项选择族全部匹配，才展示部署建议、稳定率和消融。所有交互动作均显示为 `PLANNED` policy hint，不表示系统已自动执行双来源登记或双水印。

页面下半部分对同一图片分别运行四个第三方水印 baseline 的单样本工程评估。该结果只适合观察一次运行的模型输出，不代表正式 benchmark、平台盲检能力或来源结论。

### 7.3 平台合规批量

当前页面仅进行本地能力检查：

- 所选图片只在本机预览；
- 不调用推理接口；
- 不上传图片；
- 不计算合规率；
- 显示 `UNAVAILABLE / CLAIM INVALID / 不可判定`。

只有后端提供经过正负样本校准、契约明确的独立 blind detect 能力后，才能重新评估是否接入。

## 8. 接口依赖

| 接口 | 方法 | 小程序用途 |
|---|---|---|
| `/api/health` | GET | 后端连通性检查。 |
| `/api/models/status` | GET | 仅允许选择同时满足 available/registered/calibrated/trusted 的 provenance-ready 模型。 |
| `/api/samples` | GET | 获取公开内置样本列表。 |
| `/api/samples/{id}/image` | GET | 下载公开内置样本。 |
| `/api/provenance/protect` | POST multipart | 创建来源保护登记。 |
| `/api/provenance/verify` | POST multipart | 按 `content_id` 核验传播图。 |
| `/api/infer/single` | POST multipart | 单样本模型工程评估，固定不可引用。 |
| `/api/collaboration/recommend` | POST JSON | 基于签名 MEA 逐图证据生成单模型部署建议。 |
| `/api/evidence/audit` | GET | 获取签名完整性与审计状态。 |

关键上传字段：

| 接口 | 字段 |
|---|---|
| protect | `file`、`creator_ref`、`model` |
| verify | `file`、`content_id` |
| infer/single | `file`、`model`、`attack`、`return_b64=true` |

## 9. 隐私与本地数据

- 用户自选图片在保护、核验和 MEA/单样本评估前都必须确认处理权限与上传用途；
- `creator_ref`、内容哈希和保护记录会由来源登记后端持久化；页面明确提示该事实；
- 后端返回的保护图会在当前操作期间写入小程序沙箱，以便立即核验；重置流程或页面卸载时删除临时副本，用户主动保存到相册的副本由用户自行管理；
- 服务端原图、衍生图和任务报告的实际留存以部署方公开且可核验的策略为准；
- 最近任务缩略图和展示元数据存于小程序本机，可在“我的”页清空；
- 历史记录不信任旧版 `verdictText`，会根据保存的原始三元字段重新计算门禁；
- 批量合规能力不可用期间，所选批量图片不会上传。

正式发布前仍需补齐隐私政策、删除机制、用户撤回流程、权限分级和服务端留存审计。

## 10. 静态验证

在仓库根目录运行：

```bash
node miniprogram/scripts/check-trust-gate.js
find miniprogram -name '*.js' -print0 | xargs -0 -n1 node --check
```

门禁脚本覆盖：

- protect/verify 两个唯一允许场景的正例；
- mode、claim_valid、result_provenance 和场景错配反例；
- infer-single、MEA、demo、unavailable 和缺字段反例；
- 旧历史记录 fail-closed；
- 页面调用必须显式传入可信场景；
- 禁止重新引入“一键取证”“模型阈值通过”等误导文案。

## 11. 竞赛演示建议

1. 展示首页在线状态与“三元可信门禁”说明。
2. 使用授权样本创建来源保护登记，记录 `content_id`。
3. 使用返回的保护图完成登记来源核验。
4. 解释 `verified` 是匹配信号，`claim_valid` 是后端声明字段，最终“可引用”还必须校验 mode 与场景对应 provenance。
5. 切换到工程评估，展示其即使运行真实检查点也保持不可引用。
6. 展示旧历史记录 fail-closed、合规批量不上传以及 Ed25519 完整性审计边界。

演示结论应限定为“已登记内容的技术保护与核验原型”。鲁棒性主张以冻结协议下的正式 benchmark 为准，产品化、司法采信与监管合规仍需独立评估。
