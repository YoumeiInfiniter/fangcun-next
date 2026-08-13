# Fangcun Next v0.3.7 Release Notes

## 质量优先稳定化候选实现

- 新增与 `capacity_forecast`、`episode_outline` hash 绑定的版本化 `capacity_plan`；新项目的 medium/high 容量风险不再由笼统的 `accept_current_plan` 放行。
- 新增 `episode_execution_brief`，Writer 消费任务视图，Reviewer/Rewriter 仍消费同一份完整不可变 `episode_context`。
- 删除 0.3.6 `_contract_semantic_coverage_errors` 及其保存路径；exact required quote、规划标签泄漏和格式/结构异常由确定性门禁处理，剧情落实交给逐 Beat Reviewer。
- 新增绑定草稿版本、哈希、规则集和配置哈希的 `draft_quality`；统计量只作为 risk signal，不设置跨题材统一的旁白/短句/问句硬阈值。
- Reviewer 报告支持逐 Beat、八项质量维度和系统 risk signal 完整性检查；warning 不自动重写，blocked 最多签发一次定向 rewrite ticket。
- 新增默认三集 provisional batch context；批内临时草稿、审核和连续性全部标记未确认，前集变更会使后续临时产物失效，正式连续性仍只由编剧定稿更新。

## 兼容与边界

- 旧 0.3.5/0.3.6 项目、历史草稿和旧容量决定记录保持可读；旧决定不会被转换为新 `capacity_plan`。
- 本候选实现仅完成开发模型自测；未执行真实模型/API、飞书写入、全局部署、远程推送或 main 合并。独立 Reviewer 仍需复审公开案例和隐藏变体。
