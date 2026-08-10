# 审核与重写

## 同源审核

Reviewer 必须收到：完整 episode_contract、同一份原文事件与摘录、上一集确认剧本、连续性状态、编剧覆盖指令、当前草稿、格式配置。缺关键输入时报告“证据不足”，不假装完成审核。

## 审核维度

1. 原文和改编依据；
2. 集纲落实；
3. 因果完整；
4. 人物认知；
5. 台词连接；
6. 人物声音；
7. 上一集承接；
8. 集末钩子；
9. 连续性；
10. 可拍性；
11. 时长提示（不阻断）；
12. 格式。

## 严重度

- error：事实冲突、因果断裂、人物提前知情、核心集纲未落实、无依据重大原创、无法解析格式；
- warning：时长偏差、节奏可优化、台词可更有性格、类型表达不足；
- suggestion：纯创意偏好。

时长超出默认不得判为 error；编剧可接受任何 warning。

## 可拍性严重度

- error：核心剧情、因果、认知变化或合同要求的 `required_visual_beats` 只被概述，
  没有实际演出，导致观众无法理解发生过程；
- warning：剧情可以理解和拍摄，但关键表演层、可见反应或空间变化过薄；
- suggestion：不影响理解与拍摄的纯审美优化。

不得因动作行短就自动报错，也不得因存在 `△` 就判定可拍性通过。

## 草稿时长指标

`save-draft` 由 Runtime 计算并保存 `draft_metrics`（绑定 `context_hash +
draft_version + draft_hash`）。Reviewer 使用该指标评价节奏，不得猜测或覆盖秒数；
最终审核报告的 `timing_advisory` 来自系统值。模型返回不同秒数只记录为
`legacy_model_estimate`。

## 证据要求

每个 error 必须带结构化 `evidence`（`evidence_type: source|adaptation`），程序会在绑定的
episode_context 中验证 event_id/chapter/source_span/excerpt_hash/quote 或
adaptation_decision_id 是否真实存在；任意字符串或不存在引用拒绝保存。
审核报告必须显式携带 `context_hash`、`draft_hash`、`draft_version`，缺任一拒绝保存，
不允许自动补齐；无证据的 error 拒绝保存（不自动降级）。

## 重写原则

- 只修复审核中明确的问题；
- 保留已经成立的内容；
- 必须重新读取原文证据；
- 不自由生成另一版故事；
- 一次自动重写后仍有问题，交给编剧或等待明确指令；
- 重写后重新审核同一问题，不临时不断新增创意标准。
