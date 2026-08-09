# Fangcun Next 0.2.1 修复交接

基线：`11b9b26`
分支：`codex/fangcun-next-0.2.1-fixes`

## 已修复

1. `review --api` 统一进入 `_save_review`，先推导 verdict 再做最终 Schema 与证据校验。
2. `init` 可接管仅预置合法 `config.json` 的空项目；部分残缺状态继续拒绝静默修复。
3. `save-events` 在提交前校验事件概述中的规范角色名；旧事件版本保持不可变，修正后应保存新版本。
4. `review-stage --api` 复用 Host Agent 的绑定与保存门禁；阶段证据允许纯空白形式差异，不放宽正文匹配。
5. `confirm-stage` 强制记录实际确认人和 `confirmation_ref`；Skill 要求阶段审核后结束当前任务，只能在编剧后续明确确认时调用。

## 验证

- unit：116 项通过；
- regression：155 项通过；
- smoke：4 项通过；
- 合计：275 项通过；
- API 测试使用本地 mock，未调用真实模型；
- 未修改已安装 Skill 和 `bige-dawang-v020-fresh` 测试项目。

## 边界

平台无关 CLI 只能强制审计字段和工作流停顿，不能加密证明调用者一定是真人。接入 OpenClaw/飞书后，应由 Adapter 把 `confirmation_ref` 绑定到真实用户 ID 与消息 ID。
