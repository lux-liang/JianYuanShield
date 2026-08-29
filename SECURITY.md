# 鉴源盾内容来源可信取证系统 V1.0 安全政策

## 适用范围

本文档说明鉴源盾内容来源可信取证系统 V1.0 的漏洞报告方式、安全基线和已知边界。详细威胁、已有控制、剩余风险和验证方法见 [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md)。

## 安全问题报告

请不要在公开 issue、讨论区、截图或聊天记录中公布可利用细节、私钥、API Key、密码、真实人物图像或未脱敏来源凭证。请使用下列由申请人确认的私密渠道：

- 安全联系人：[待申请人填写]
- 安全邮箱/私密工单地址：[待申请人填写]
- PGP 指纹（如使用）：[待申请人填写]
- 建议确认时间：[待申请人制定]
- 建议首次状态更新时间：[待申请人制定]

有效报告建议包含：受影响版本与 commit、部署形态、前置条件、最小复现步骤、实际/期望结果、影响范围、经脱敏的日志与缓解建议。在未获得明确授权前，不要访问其他用户对象、下载大量资产、保持持久化访问或执行破坏性测试。

## 支持状态

| 版本 | 安全更新状态 |
| --- | --- |
| V1.0 | 当前软著与交付基线；具体维护期限由著作权人/部署方补充 |
| 早于 V1.0 的开发快照 | 不作为安全支持承诺；应升级到经审核定版 |

## 生产安全基线

1. 使用 digest 固定的已审核镜像，不在生产环境直接运行未冻结工作区。
2. 设置 `JYS_MODE=production`，禁用 demo，强制长度足够的 API 鉴权和精确 HTTPS CORS origin。
3. 通过 secret file、KMS/HSM 或受审计秘密服务提供 API Key、provenance secret 和签名私钥；不将密钥写入仓库、镜像、客户端包、URL 或日志。
4. 从独立可信渠道固定签名公钥指纹，定期演练轮换、吊销、旧证据验证和错误指纹 fail-closed。
5. 只读挂载经审核模型源码和权重，同时核对源码树、检查点、校准产物、权重清单与签名 evidence set。
6. 将 API 和内部网关只绑定回环或私有网络；V1.0 公网部署在边缘终止 TLS，并启用 HSTS、明文跳转、请求体上限、限流和受控转发头。
7. 使用非 root、只读根文件系统、去除 capabilities、`no-new-privileges`、PID/资源限制和最小化可写卷。
8. Web 管理入口启用服务端签名会话、Secure/HttpOnly/SameSite Cookie、CSRF 校验和登录失败限速；多用户公开服务仍需进一步增加 OIDC、细粒度角色、scope 与对象级授权。
9. 建立原图上传、受保护图、来源记录、创作者引用、日志和备份的字段级留存、删除、访问和事件响应规则。
10. 将 GPU 推理放在可回收 worker 与有界队列中，对多副本的总并发、显存、CPU、内存和磁盘设置配额。
11. 静态资源使用不可变版本目录和原子 `current` 链接发布，发布前校验 SHA-256 清单，切换失败时保持或显式恢复上一版本。
12. 在 SPA fallback 之前显式拒绝 dotfile、备份、凭据、密钥、source map 和临时文件路径；部署后必须从公网逐项验证返回 404，而不是只检查磁盘内容或 Caddyfile 文本。

## 当前安全边界

- V1.0 在线入口为 [https://81.70.178.203/jianyuanshield/](https://81.70.178.203/jianyuanshield/)，由边缘层使用自动续期的短期公网 IP 证书提供 TLS 与 HSTS；应用进程和同源网关之间的 HTTP 只限受控内网链路，不得绕过边缘入口上传用户图像或凭证。
- 当前 UI 会话是单管理员部署模型，采用服务端 HMAC 签名会话、Secure/HttpOnly/SameSite Cookie、CSRF 校验和登录失败限速；公开只读状态接口仍可匿名访问，且它不提供租户隔离、对象所有权或用户生命周期管理。
- 当前仓库前端契约只将 KAD-Net 设为 `provenance_ready` 正例；适配器列出其他模型不代表它们已受信。实际状态以 `/api/models/status` 为准。
- 后端与 Android 已实现一次性 Ed25519 创作者挑战；Web 和小程序直连保护表单尚未提交挑战字段，生产模式应拒绝这类请求。
- Ed25519 只证明指定密钥对指定字节签名；`creator_ref` 不是实名，系统时钟不是可信时间，SQLite 不是不可篡改账本，技术记录不自动获得司法采信。
- 当前批量合规接口没有校准后的独立 blind detector，只能返回 `capability_unavailable`。
- 推理超时不能强制停止已在线程中运行的 GPU kernel；当前实现保留槽位直到 worker 真正退出。
- 受保护图、来源记录和核验事件尚未建立完整的 TTL/删除/导出政策。

## 密钥或凭据泄露

1. 立即禁用/轮换泄露的 API Key、签名私钥或 provenance secret，不要等待代码修复后再轮换。
2. 保留经脱敏时间线、访问日志、受影响指纹、记录范围与轮换事件，不覆盖原始证据。
3. 将旧签名者标记为已吊销并保留旧证据的历史验证能力；不用新私钥重签旧事件伪造原时间线。
4. 如泄露材料包含个人图像或可关联标识，按部署方隐私事件响应流程评估通知、删除、备份和法定义务。
5. 在恢复服务前重新验证镜像、模型源码树、权重、校准、数据库/锚点、证据签名与带外公钥指纹。

## 交付前安全验证

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m unittest -v tests.test_security tests.test_api_hardening tests.test_creator_identity tests.test_signing
python scripts/check_documentation.py
python scripts/build_software_copyright_package.py --check
python tools/smoke_public_session.py --base-url https://example.invalid/jianyuanshield --username '<管理员账号>' --password-file /run/secrets/jys_ui_password
```

V1.0 全量自动化基线共 398 项测试，其中 397 项通过、1 项因环境条件跳过；最终结果以发布 commit 归档的测试输出为准。每次部署和证书、域名或边缘配置变更后，仍须复核 TLS、HSTS、明文跳转、鉴权、资源配额、密钥存储、备份/恢复、日志脱敏、数据删除和模型供应链。
