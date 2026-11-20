# ai-video Agent 运行资料

本目录保留正式 Agent SDK 会话使用的 Skill、导演规则资料与工具权限。创作任务由当前会话按需读取领域 MCP，按 Skill 验收后提交结构化结果；待确认候选由本地程序提交，已正式写入的结果再发布简短报告。

- `skills/`：通用对话、任务结果协议和各创作任务 Skill。
- `director_rules/`：导演规则目录与正文，供规则推荐和分镜环节读取。
- `permissions/`：桌面端允许的工具动作。

架构和逐环节验收记录见主仓 `plugins/ai-video/docs/agent-interaction-architecture.md`、`agent-stage-migration-review.md` 与 `agent-test-bridge.md`。桌面插件只使用前端 `callBackend/onBackendEvent` 和后端 `@sdk.handler/sdk.send_event` 通信。
