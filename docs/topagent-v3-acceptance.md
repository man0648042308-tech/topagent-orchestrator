# TopAgent v3 能力证据与“提示词散文”判定

更新日期：2026-08-17

## 七段证据链

任何能力声明至少回答下表。缺少入口和执行代码，只能叫设计；缺测试或运行产物，只能叫
实现候选；缺指标、恢复、审计，不能叫可运营能力。

| 证据 | 必须能检查什么 | v3 位置 |
|---|---|---|
| 入口 | 人或程序如何触发 | `python -m topagent`、MCP、HTTP API |
| 执行代码 | 不是 Prompt 描述，而是实际控制流 | `topagent/runtime/`, `bus/`, `memory/` |
| 测试 | 正向、伪造、故障、恢复 | `tests/` |
| 运行产物 | 可复核输出而非聊天声称 | SQLite、ArtifactStore、workspace |
| 指标 | 成功/失败/积压/重试能计数 | `/api/metrics`、Dashboard |
| 失败恢复 | 崩溃、超时、重复、冲突怎么办 | lease/retry/dead-letter、memory conflict |
| 审计 | 谁在何时做了什么，输入输出是否被篡改 | execution/event/hash/attestation/audit |

## 证明“仍然只是散文”需要的反证

下面任一关键项失败，都足以降低对应能力等级；多项同时失败可判定体系仍以 Prompt
角色扮演为主：

1. 调用 pipeline step 后没有新增 execution_id。
2. 改写 Agent 输出后没有 hash 不一致或新 Artifact 记录。
3. 声称 QA 独立审核，但 producer/verifier 是同一个 execution_id 或 verifier 为空。
4. 杀死 worker 后，leased/processing 消息永远卡住，不能重排。
5. 同一幂等键并发投递产生多份任务。
6. Agent 文件写着“在线”，但没有 heartbeat/presence，窗口仍显示运行中。
7. 记忆冲突时旧事实被静默覆盖，没有冲突或 supersedes 记录。
8. Capability 标“已上线”，但其 contract 没有可执行测试或测试失败。
9. 换一台机器克隆后无法初始化 Registry、运行 fake executor 和打开 health API。
10. 密钥能从当前工作树、安装脚本、日志或 API 响应中直接恢复。

## 本次已取得的证据

```text
python -m unittest discover -s tests -v
Ran 26 tests ... OK

python -m topagent init
agents=19, skills=22, capabilities=8

MCP initialize
serverInfo.version=3.0.0
tools/list 返回 13 个带独立 closed inputSchema 的工具
```

测试覆盖：

- Dispatcher 的身份、trace、Artifact、attestation、默认质量优先与显式 `free-only` 拒绝。
- Runtime 身份签名消息和 legacy 未认证消息。
- 消息并发幂等、错误 delivery 拒绝、ACK、重试、死信和租约恢复。
- Scheduler 从消息到执行再到 ACK 的闭环和 presence。
- Router dry-run 无密钥访问、Provider 故障转移、未知类型回退。
- 记忆 candidate/promote/search/archive、冲突与显式 supersede。
- Registry 与 Skill 渐进式全文加载。
- Control Center health/metrics/静态 Dashboard。
- DPAPI round-trip、密文不含明文、删除与旧格式迁移解析。

## 尚未取得、不得冒充的证据

- 真实付费 Provider/Claude 的 Golden Run（本次没有擅自扣费）。
- 多进程、容器或跨主机 Agent 隔离。
- manju-studio 三条真实视频 Golden Case。
- video-notes 固定视频样本快照回归。
- 长时压力、断电注入和 SQLite 文件损坏恢复演练。
- OTLP/外部告警、RBAC、多租户。
