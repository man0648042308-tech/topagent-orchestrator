# TopAgent v3 本地运维

## 初始化和测试

```powershell
cd C:\AI_Project
python -m topagent init
python -m unittest discover -s tests -v
python -m compileall -q topagent router mcp-bridge
```

## Control Center

```powershell
python -m topagent serve --host 127.0.0.1 --port 8765
```

访问 `http://127.0.0.1:8765`。默认只绑定本机，除非补上认证与网络边界，不应改为
`0.0.0.0`。

常用只读 API：

```text
GET /api/health
GET /api/metrics
GET /api/runs
GET /api/executions
GET /api/events
GET /api/messages
GET /api/memory
GET /api/agents
GET /api/presence
GET /api/skills
GET /api/capabilities
GET /api/audit
GET /api/events/stream
```

变更 API：

```text
POST /api/runs
POST /api/runs/{run_id}/steps/{step_id}
POST /api/dispatch
POST /api/verify
POST /api/memory/candidates
POST /api/memory/{memory_id}/promote
POST /api/memory/{memory_id}/archive
POST /api/messages/requeue-expired
```

## 密钥

```powershell
python -m topagent secrets set DASHSCOPE_API_KEY
python -m topagent secrets status DASHSCOPE_API_KEY
python -m topagent secrets delete DASHSCOPE_API_KEY
```

不要把值放在命令参数、Markdown 或 issue 中。CI 优先使用 CI Secret 注入环境变量；
DPAPI vault 只适合当前 Windows 用户。

## 消息恢复

过期租约通常由 Scheduler 周期调用 `requeue_expired()` 回收。手工恢复：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/messages/requeue-expired
```

死信不会自动无限重放。先检查 `last_error`、attempts 和对应 execution，再决定重新发消息。

## 数据与备份

本机状态在 `runtime/`：

- `topagent.db`：SQLite WAL 事件/执行/消息/记忆索引。
- `artifacts/`：按 SHA-256 内容寻址的产物。
- `workspaces/`：每次 execution 的工作目录。
- `secrets.enc`：DPAPI 密文。

数据库和 Artifact 可以备份；`secrets.enc` 只能在同一 Windows 用户上下文解密。跨机迁移
密钥时应从 Provider 或安全 Secret Manager 重新注入，不依赖复制 DPAPI 密文。

## 故障排查顺序

1. `/api/health` 是否返回 ok。
2. `/api/executions` 的 error/attestation。
3. `/api/events` 的状态迁移。
4. `/api/messages` 的 lease、attempts、last_error。
5. `/api/presence` 的 worker heartbeat。
6. 对应 Artifact 是否存在且 SHA-256 匹配。
7. 运行相应 capability contract 中的 verification command。
