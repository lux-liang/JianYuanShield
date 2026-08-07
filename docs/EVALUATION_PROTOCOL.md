# 统一评测协议说明

机器可读的唯一语义来源是 `configs/evaluation_protocol.v1.json`，解析与校验入口位于 `system/evaluation/protocol.py`。本文只解释原则，不复制会随配置变化的模型状态或历史结果。

## 图像与随机性

- 对外比较使用 RGB、`uint8`、`[0,255]` 作为规范表示。
- 模型内部颜色空间、尺寸和值域差异必须由 adapter 显式转换并写入元数据。
- 数据集必须有不可变 manifest；人脸任务按身份划分训练、验证和测试集。
- 不允许用“排序后前 N 张”替代预先登记的抽样方案。
- 随机攻击以协议 seed 和稳定 image ID 派生逐图 seed，避免所有图片复用同一噪声模板。
- 训练 seed、数据 seed 和攻击 seed 分开记录。

## 指标语义

协议定义：

```text
BER = mean(original_bits != decoded_bits)
accuracy = 1 - BER
success = accuracy >= protocol.success_threshold
```

默认阈值由 JSON 协议读取；评测脚本不得自行写另一套 PASS/MARGINAL 阈值。若某模型需要校准阈值，应建立新协议版本，并给出正负样本上的 ROC、FAR 和 FRR。

视觉质量必须分开报告：

- `watermarked_vs_original`：嵌入造成的变化；
- `attacked_vs_original`：完整传播或攻击链造成的变化；
- MEA 可额外报告第二次嵌入相对第一重水印图的变化。

以下指标不能混称“准确率”：

- 水印存在性 detector；
- 消息 tracer/decoder；
- 创作者 ID bit；
- 人脸 landmark 定位误差；
- 完整内容登记匹配。

## 模型注册不等于结果完成

协议中的 `models` 只登记输入语义、消息结构和 adapter 状态。模型出现在配置或 API 中，不代表：

- checkpoint 已纳入证据包；
- 数据集和划分可以复核；
- 正负样本已经完成；
- benchmark 已通过 Claim-as-Code 门禁。

运行时可用性由 adapter 和 checkpoint 检查决定；对外可发布性由 `configs/claims_manifest.v1.json` 决定。

## 攻击语义

攻击 ID、参数、类别和 evidence level 全部从机器可读协议读取。特别注意：

- 平台转码配置是记录明确参数的代理，不能直接称作平台实测；
- `deepfake_proxy_v1` 是局部编辑代理，不能称作 FaceSwap、SimSwap 或真实 Deepfake benchmark；
- 真实平台与真实换脸实验必须记录软件版本、参数、失败样本和输出 manifest。
- 独立真实换脸轨道固定为 official SimSwap/LFW n256：256 对 source-target、512 个身份全局不复用，64 calibration 与 192 holdout 身份集合零交叉，逐模型报告 registered-positive、unwatermarked、wrong-message、cross-record 控制下的 TAR/FRR/FAR、Wilson 区间、流程内 ArcFace 迁移、迁移条件分组及质量指标；该轨道不回写 `deepfake_proxy_v1`。SimSwap source identity conditioning 与迁移测量复用同一个 ArcFace checkpoint，因此不能将其表述为独立身份验证器。

后端演示、正式评测和客户端不得各自实现一套不同参数的同名攻击。

## MEA 多重嵌入报告

每个来源模型 A、后嵌模型 B 的单元格至少报告：

1. A 的单嵌恢复基线；
2. B 的单嵌恢复基线；
3. 二次嵌入后 A 的消息保留率；
4. 二次嵌入后 B 的消息成功率；
5. 两阶段视觉质量；
6. 消息长度、decoder 语义、样本量、错误数和区间；
7. 逐图原始记录。

不同消息容量和 decoder 语义不能仅用同一阈值合并排名。矩阵失败是红队发现，不自动证明系统防御成功。

## 统计要求

- 同一图像、同一指标才可做配对比较；不同 image ID 命名规则必须先统一。
- 同一批图片在多个训练 seed 下形成层级数据，不能直接池化为更多独立图片。
- 至少分别报告图像内变异和 seed 间变异；样本量由预注册方案或功效分析确定。
- 多重比较需要校正；同时报告效应量和置信区间，不能只给 p 值。
- 正式分析不得在输入缺失时仍输出 `complete`。

## Artifact 最低集合

进入答辩主结论的每次评测必须包含：

```text
dataset manifest + split
checkpoint hash + model card
code commit + protocol hash
command + environment + seed
per-image results
summary generated from raw rows
negative controls + failures
evidence signature + externally pinned public-key fingerprint
```

缺少上述关键项时，结果保留为 `review_required` 或 `blocked`。历史 CSV 不覆盖；完成语义审计和统一重跑后写入新的版本化目录。
