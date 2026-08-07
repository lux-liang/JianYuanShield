# GPU 规模实验记录 · 2026-08-07

## 实验目的

扩大真实 SimSwap / LFW 身份隔离评测规模，检查四种水印模型在更大样本上的运行稳定性，并为后续正式协议升级提供候选证据。既有 n256 release-core 继续承担正式发布基线。

## 运行范围

- GPU：NVIDIA H100 80GB，独占映射一张空闲卡执行。
- 样本：1024 对身份隔离 LFW 配对。
- 校准 / 留出：256 / 768 对。
- 水印模型：LIDMark、KAD-Net、SepMark、WaveGuard。
- 预期模型结果：4096 行。
- 预期 ArcFace 身份嵌入：7168 行。
- 随机种子：20260807。
- 输出分类：`custom_real_run`，未替代、未冒充当前签名 release-core。

## 完成状态

运行目录：`reports/simswap-lfw-robustness-n1024-v2-s20260807`

| 检查项 | 结果 |
|---|---:|
| processed pairs | 1024 / 1024 |
| result rows | 4096 / 4096 |
| identity embedding rows | 7168 / 7168 |
| error rows | 0 |
| summary status | complete |
| identity overlap | 0 |

## 内容寻址

- `results.csv`: `744bdf6cea930141a46994c6bfd3a70c095a0342d37f37a15c6f5eb3cd728e6b`
- `identity_embeddings.csv`: `e1f81351ff1db152e001df9b382129512995d88608b463e675222cc21346bb8f`
- `pair_manifest.json`: `85b681898e3dbe82ad6196fbf532564de9e41c0ee15148426b94a69524638bb9`
- `message_registry.json`: `f6cd3f8faaca36068379150c397c36207a958ee5e08ac919722017f7c31561b8`
- `assets_manifest.json`: `14d3dffe28e15fbaaa3c7b641f149a9780a732c6658d844dae8613ccc60362eb`

## 失败关闭记录

首次启动在 WaveGuard 预检阶段发现 `pkg_resources` 缺失；第二次启动暴露 KAD-Net 官方依赖 `timm==1.0.14` 未进入主环境。两次输出均隔离保留，未复用为正式结论。修复采用独立 runtime overlay，没有修改项目锁定环境；完成 KAD-Net GPU 编码预检后，使用新的 v2 输出目录从头运行。

## 发布边界

本次结果可用于规模稳定性说明和协议升级评审，但在完成独立验证、正式 profile 纳入、Manifest 覆盖与 Ed25519 签名以前，不用于替换当前已签名 n256 性能主张。
