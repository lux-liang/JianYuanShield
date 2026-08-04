# 第三方组件、数据与权利归属

本文件记录鉴源盾当前比赛版本直接调用、加载或用于正式实验的第三方代码、模型权重与数据集。它是发布闭包的一部分，不改变任何上游许可证，也不把平台集成工作表述为底层算法原创。

本仓库尚未由权利人选定统一的对外开源许可证。因此，除下列第三方材料按其各自条款使用外，不能仅凭仓库可见性推定鉴源盾项目代码获得了额外许可。比赛展示与复现实验不得扩展为商业部署或再分发授权。

## 模型与评测代码

| 组件 | 固定来源 | 本项目用途 | 上游作者/论文 | 许可证与约束 |
| --- | --- | --- | --- | --- |
| LIDMark | `vpsg-research/LIDMark`，commit `fc1c8f93e3ce496d273dde866f3e5ec191e4d0e4` | 在线 adapter、身份隔离训练/评测 | Junjiang Wu、Liejun Wang、Zhiqing Guo，*All in One: Unifying Deepfake Detection, Tampering Localization, and Source Tracing with a Robust Landmark-Identity Watermark* | Apache License 2.0；随冻结源码保留上游 `LICENSE`、README、版权与署名信息 |
| KAD-Net | `vpsg-research/KAD-Net`，commit `45ec63df4b21fb916ffe746ea2ba1201fa66766d` | 在线 adapter、协议评测与几何同步消融 | Sijia He、Yunfeng Diao、Yongming Li、Chen Sun、Liejun Wang、Zhiqing Guo，*KAD-Net: Kolmogorov-Arnold and Differential-Aware Networks for Robust and Sensitive Proactive Deepfake Forensics* | Apache License 2.0；随冻结源码保留上游 `LICENSE`、README、版权与署名信息 |
| MEA 实验代码 | `vpsg-research/MEA`，commit `4169ff91a22a0e4b6d467b454bc19f9ef31cf7d6` | 4×4 有向多重嵌入红队实验及基线集成 | Lixin Jia、Haiyang Sun、Zhiqing Guo、Yunfeng Diao、Dan Ma、Gaobo Yang，*Uncovering and Mitigating Destructive Multi-Embedding Attacks in Deepfake Proactive Forensics* | 仓库根目录声明 Apache License 2.0；其嵌套基线仍受各自上游条款约束 |
| SepMark | MEA snapshot 内 `codes/SepMark`；原始项目 `sh1newu/SepMark` | 在线 adapter、单模型评测与 MEA 基线 | Xiaoshuai Wu、Xin Liao、Bo Ou，*SepMark: Deep Separable Watermarking for Unified Source Tracing and Deepfake Detection* | 上游 README 明确“strictly for non-commercial academic use only”；本比赛版本仅作非商业科研、评测与展示，不据此授予再分发或商业使用权 |
| WaveGuard | MEA snapshot 内 `codes/WaveGuard`；原始项目 `Twoh11/WaveGuard` | 在线 adapter、单模型评测与 MEA 基线 | *WaveGuard: Robust Deepfake Detection and Source Tracing via Dual-Tree Complex Wavelet and Graph Neural Networks* | 当前冻结子目录未附独立 LICENSE；使用范围限定为经项目成员授权的比赛科研评测。任何外部分发或商业使用前必须取得权利人明确许可 |
| SimSwap | `neuralchen/SimSwap`，commit `bd7b7686a17f41dd11cfcd5d82f7e4c5eb94b780` | official-SimSwap/LFW n256 真实换脸鲁棒性轨道 | Renwang Chen、Xuanhong Chen、Bingbing Ni、Yanhao Ge，*SimSwap: An Efficient Framework For High Fidelity Face Swapping* | Creative Commons Attribution-NonCommercial 4.0 International；仅用于非商业学术评测，保留署名、许可证链接及修改说明，不用于违法或不道德场景 |

正式发布包必须携带上述冻结源码中相应的 LICENSE/README，并保持源码 commit、checkpoint SHA-256、实验配置和 evidence manifest 一致。权重文件的来源与哈希由 `WEIGHT_MANIFEST.json`、SimSwap `run_config.json` 和签名 release-core 进一步绑定；源码许可证不自动覆盖数据集、预训练权重或第三方人物肖像权。

## 数据集

| 数据 | 用途 | 权利与使用边界 |
| --- | --- | --- |
| Labeled Faces in the Wild（LFW） | 四模型统一协议、MEA、SimSwap n256 身份隔离评测 | 数据不属于本项目。发布包不重新许可 LFW；获取、展示和再分发必须遵守 LFW 官方页面、图片原始来源及适用的人格权/隐私规则。比赛演示只使用经审核的最小样本，不展示不必要的身份信息 |
| CelebA-HQ | 部分上游模型训练与说明 | 数据不属于本项目。仓库与发布包不以代码许可证重新许可该数据；训练或分发方须单独核验 CelebA/CelebA-HQ 条款 |

## Python、Android 与容器依赖

Python 直接和传递依赖的精确版本、包标识及完整集合记录在 `requirements.lock` 和 `supply-chain/python-dependencies.cdx.json`。Android 依赖由 Gradle 锁定配置及构建产物元数据记录；容器基础镜像由 `supply-chain/build-manifest.json` 的不可变 digest 绑定。发布前应从实际归档重新生成 SBOM，并随包保存各依赖许可证文本；SBOM 中出现组件不表示其作者为鉴源盾背书。

## 本届作品贡献边界

鉴源盾本届可由仓库实现和证据直接复核的增量包括：来源登记与核验协议、身份隔离评测协议、负控制与阈值标定、MEA 有向冲突实验及风险策略、内容寻址证据闭包、签名与 Claim-as-Code 门禁、跨端产品化和部署安全。LIDMark、KAD-Net、SepMark、WaveGuard、MEA 与 SimSwap 的底层算法、论文与既有成果归其相应作者和权利人所有；平台集成、适配或复现实验不改变该归属。

