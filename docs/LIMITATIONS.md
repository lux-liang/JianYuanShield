# 当前局限性（诚实版，2026-06-15）

> 本文档基于真实 artifact 数据（见 `_remote_evidence_brief.md`）据实列出硬伤与已知风险，不回避、不粉饰。

---

## 一、模型级局限

### LIDMark
- **ID 比特精度（bit accuracy）当前未测（null）**：真实产物 `mean_bit_accuracy=0.0`，per-seed `bit_accuracy=null`。对外宣传的 99.93% 是 **landmark 定位成功率**（对攻击不敏感指标），**不是水印比特恢复精度**，两者不可混用。
- **样本量 512×3（同批重复）**：3 个 seed 使用同一批 512 张图，合并宣称"1,536 张"实为伪重复；真正 between-seed 方差估计需不重叠样本。
- **几何攻击未测**：当前 landmark 定位成功率在 clean/jpeg/noise/resize 下几乎一致（≈99.93%），说明该指标对攻击不敏感，无法代表水印鲁棒性。
- **Stage2（Deepfake 换脸微调）尚未完成**：主要卖点"Deepfake 穿透溯源"的 ID 比特级证据当前缺失。

### KAD-Net
- **样本量 13,233 张（真全量，checkpoint EC_50.pth，GEOM 微调版）**：JPEG/noise/resize 全部 ≥99%。
- **几何攻击实质失败（已知硬限制）**：crop_center≈68.9%，rotate≈43.7%——即便已进行 GEOM 微调仍失败，须诚实标注，不可隐藏。
- **MEA 矩阵 KAD-Net→KAD-Net first_acc=50%（随机）** 与单模型 clean bit_acc≈100% 存在口径 bug（疑似 `strict=False` 静默丢权重），待排查。

### WaveGuard
- **jpeg50 是真弱点（n=13,233，checkpoint model_state_16.pth）**：bit-acc=88.97%，但 success@0.9 仅 37.3%——大量图像比特精度恰好低于 0.9 阈值。不可称"Q=50 已修复至100%"。
- **除 jpeg50 外≈100%**：clean/jpeg70/jpeg90/noise/resize 的 bit-acc 和 success@0.9 均≈100%；jpeg50 为真实硬限制，须诚实标注。

### SepMark
- **pre-trained checkpoint**（EC_115.pth），非团队从头训练。
- **bit-acc≈85-89%**（clean 87.74%）；"decoder_RF 91.2%"偏高，以 ~88% 为通常引用值或注明特定 decoder；success@0.9 仅 59-72%（128-bit 长消息，门槛严）。

### HiDDeN
- **有真实 13,233 全量评测结果（checkpoint epoch-300），不是"损坏/已剔除"**。
- clean/resize 好（clean bit-acc=99.05%，resize=98.07%）；**JPEG 系列失败（jpeg50 bit-acc=57.09%，success=0%）**——域 gap 为已知局限。
- 是**有效对照 baseline**：在同一评测框架下，HiDDeN 揭示了公开 checkpoint 直接迁移至 LFW 上 JPEG 攻击的局限，与 KAD-Net/WaveGuard 形成鲁棒性对照。须标注 JPEG 失效为局限，不可称"损坏剔除"。

---

## 二、MEA 协议局限

- **对角线多 FAIL**：SepMark→SepMark second=56%、WaveGuard→WaveGuard=62.8%、LIDMark→LIDMark≈51.8%/60.2%、KAD-Net→KAD-Net first=50%、HiDDeN→HiDDeN=51.3%——自鲁棒性全部低于 70% 阈值。**正确叙事**：MEA 是诚实红队诊断，揭示了多水印并存场景下后嵌入会大幅破坏先嵌入水印的溯源能力，属科学发现，而非"创新有效"卖点。
- **LIDMark 整行整列≈随机（49–73%）**：LIDMark 作为 Source 或 Attacker 时，跨模型几乎无可恢复比特信息，印证 ID 比特精度 null 的结论。
- **样本量 128 张/格**：小样本，置信区间宽，结论尚待大样本验证。
- **阈值未与协议对齐**：`grade()` 硬编码 PASS≥0.85，与协议 `success_threshold=0.9` 冲突。

---

## 三、统计口径局限

- **pseudoreplication**：把 3 seed × 512 图拍平成 1,536 个"独立样本"做 bootstrap，得到被低估的 CI（如 [99.94%,100%]、[1.0,1.0]），不是真实 between-seed 方差。
- **指标混用**：landmark 成功率、id_bit_acc、detector（二分类）、tracer（溯源）、message BER 等不同量被并入同一"比特精度"语境做显著性比较，结论可靠性存疑。
- **geometric cherry-pick**：headline 只列 clean/jpeg/noise/resize，几何攻击（crop/rotate）实质失败被淡化为"微调进行中"。

---

## 四、工程级局限

- **所有模型权重在外部 `/data1`**，本仓库不含权重/数据集，可复现性接近为零。
- **requirements.txt 版本锁定问题**：`torch>=2.12`（无效版本）、缺 pytorch_wavelets/einops/face_alignment 等推理必需包。
- **合规 fallback 无 503**：模型不可用时 `/api/compliance/batch` 用灰度熵伪装检测，对外返回看似真实的合规判定，实为无效结论。
- **证据链"司法级"措辞夸大**：实现为单次 manifest Ed25519 签名，无链式哈希/Merkle、无 RFC3161 可信时间戳（本机 `time.time()`），私钥与验签器同机同目录，降级描述为"完整性自校验+来源签名（演示级）"更准确。

---

## 五、待补充的真实数值（需实验回填）

| 缺失项 | 当前状态 | 回填条件 |
|--------|---------|---------|
| LIDMark ID 比特精度 | null（评测进行中） | 真正运行 ID 比特解码评测，不重叠样本 3-seed |
| WaveGuard jpeg50 成功率改进 | 37.3%（真弱点，改进进行中） | 进一步微调后在 n=13,233 独立验证 |
| KAD-Net 几何攻击改进 | crop≈68.9%/rotate≈43.7%（已知硬限制）| 需从根本上改进几何不变性训练 |
| MEA 大样本（128→512+/格） | 进行中 | 修复口径 bug 后大样本重跑 |
| Ed25519 覆盖文件数 | README=22 vs JUDGE_QA 已更新为"接口返回为准" | `evidence_audit` 接口实际返回值 |
