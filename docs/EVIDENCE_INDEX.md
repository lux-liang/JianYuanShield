# 鉴源盾答辩证据索引

这份索引把答辩中的关键表述映射到代码、测试和运行时证据。原则是：没有证据路径的句子，不作为既成事实讲述。

| 答辩表述 | 代码入口 | 回归测试 | 运行时证据 |
|---|---|---|---|
| 创作者通过设备密钥完成一次性持钥证明 | `system/backend/creator_identity.py` | `tests/test_creator_identity.py` | 来源记录中的 challenge 与公钥指纹 |
| 图片具有显式与隐式 AIGC 标识 | `system/backend/aigc_labeling.py` | `tests/test_aigc_labeling.py` | 保护 PNG 与 producer seal |
| 来源凭证可自包含携带并验签 | `system/backend/provenance.py` | `tests/test_provenance.py` | `source-credential.json` |
| 审计链能发现删尾和数据库回滚 | `system/backend/audit_ledger.py` | `tests/test_audit_ledger.py` | 签名事件链与独立 anchor |
| 撤销需要原创作者再次签名 | `system/backend/provenance.py` | `tests/test_provenance.py` | revocation intent 与 revoke event |
| 四模型使用真实 checkpoint 且失败关闭 | `system/backend/model_adapters.py` | `tests/test_model_adapter_registry.py` | `WEIGHT_MANIFEST.json` 与模型状态 API |
| 正式攻击集合固定且不可静默缩减 | `configs/evaluation_protocol.v1.json` | `tests/test_protocol.py` | 每个 run 的 `run_config.json` |
| 逐图结果绑定数据、协议与 checkpoint | `system/evaluation/evidence.py` | `tests/test_evaluation_evidence.py` | dataset/checkpoint/source manifest |
| KAD-Net、SepMark、WaveGuard 结果经过原子晋升 | `scripts/promote_benchmark_run.py` | `tests/test_promote_benchmark_run.py` | canonical 相对符号链接 |
| 多水印推荐由 4×4 矩阵实时重算 | `system/backend/collaboration.py` | `tests/test_collaboration_policy.py` | MEA 五件套与签名 bundle |
| SimSwap 结果包含三类负控和隔离 holdout | `system/scripts/run_simswap_lfw_robustness.py` | `tests/test_simswap_lfw_robustness.py` | n256 results、pair manifest、message registry |
| 页面结论随证据漂移自动熄灭 | `system/backend/claims.py` | `tests/test_claims.py` | `/api/claims`、`/api/evidence/audit` |
| release-core 使用固定 Ed25519 签名者 | `system/backend/signing.py` | `tests/test_signing.py` | manifest、signature、public key fingerprint |
| 离线交付固定镜像、依赖与 SBOM | `scripts/offline_bundle.py` | `tests/test_offline_bundle.py` | release archive、CycloneDX、attestation |

## 不能越界的表述

| 不应表述 | 应改为 |
|---|---|
| 可以识别任意未知 AI 图片 | 可核验经过本系统登记和保护的内容 |
| 达到司法级证据 | 提供可验证技术记录；法律效力取决于部署、程序与采信规则 |
| 全面抵抗 Deepfake | 在固定 official SimSwap/LFW 协议下报告结果与边界 |
| 四模型平均准确率领先 | 分模型、分攻击、分 decoder 报告各自主指标 |
| 平台压缩后文件仍完全相同 | 字节可能变化，水印恢复与标识完整性分别判断 |
| 推荐策略永远是 SepMark | 当前冻结 MEA 证据下推荐 SepMark，证据变化后重新计算 |

## 评委追问时的回答结构

每个技术问题按四句话回答：

1. 先给边界：我们解决什么、不解决什么；
2. 再给机制：关键协议或算法如何工作；
3. 再给证据：对应哪个测试、原始结果或签名清单；
4. 最后给限制：在哪些攻击或部署条件下会失败。

这种结构比堆术语更可信，也能把 Claim-as-Code 的设计哲学贯穿整场答辩。

