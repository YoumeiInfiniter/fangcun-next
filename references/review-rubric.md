# 审核与重写

## 同源审核

Reviewer 必须收到与 Writer 相同的不可变 `episode_context` 快照、Writer 专用
`episode_execution_brief`、同一份原文事件与摘录、上一集确认剧本、连续性状态、编剧覆盖
指令、当前草稿、草稿绑定版本/哈希、格式配置和系统 `draft_metrics`。缺关键输入时报告
“证据不足”，不假装完成审核。

容量预估、时长和 risk signal 是辅助信息，不把单一侯府或其他单一题材样本固化为所有题材
的硬规则。编剧是最终作者；系统负责确定性绑定、证据、格式和报告门禁。

## v0.3.7 报告出口

新报告必须声明 `review_contract_version: "0.3.7"`，并同时提供：

1. `beat_checks`：execution brief 中每个 core beat 恰好一条。检查 status、因果、对白链、
   可见反应、必需画面和草稿行证据。`summarized`、`missing` 或检查项为 false 必须是 error；
2. `dimension_checks`：恰好覆盖八项 `source_fidelity`、`character_knowledge`、
   `dialogue_pairing`、`shootability`、`narration_substitution`、`previous_episode_bridge`、
   `ending_hook`、`continuity`；
3. `required_quote_checks`：每条 exact/semantic/legacy 台词义务都有 quote_id、原文 quote、
   mode、status、severity、draft_evidence 和 fix。exact 逐字核对，semantic 必须有状态和
   草稿证据，legacy 也不能无出口；semantic missing/mismatch 或 exact 缺失最终 blocked；
4. `risk_signal_checks`：逐条给出 confirmed、rebutted、accepted 或 not_applicable 和说明。

Runtime 以 `issues` 加上述结构化出口和系统 hard errors 的综合结果派生 verdict：任一 error
（包括 beat/dimension/required quote/system gate）为 `blocked`，否则任一 warning 为
`warning`，其余为 `pass`。模型自行填写的 verdict 只保存为 `model_verdict`，不能覆盖系统
推导；结构缺失、重复或未知项拒绝保存。

## 质量维度与严重度

- `source_fidelity`：原文/改编依据与当前剧本一致；
- `character_knowledge`：人物只使用当时已经知道的信息；
- `dialogue_pairing`：问题—回答、铺垫—包袱、台词—回应形成连接；
- `shootability`：关键动作、因果和结果实际可演出，不用概述代替；
- `narration_substitution`：旁白不能替代 brief 要求的关键表演和可见反应；
- `previous_episode_bridge`：上一集承接和人物状态连续；
- `ending_hook`：集末钩子落实并可驱动下一集；
- `continuity`：与已确认事实、道具、地点、关系和公开信息一致。

`error`：事实冲突、因果断裂、人物提前知情、core beat/required quote 未落实、关键表演被
概述或无法解析格式；`warning`：可理解但节奏、表演层或类型表达可改进；`suggestion`：纯
创意偏好。时长偏差默认不阻断，系统 `draft_metrics` 是唯一保存的时长事实。

动作/表演描写要写主体、行为、对象和可见结果；“两人争执”“她回忆往事”“现场一片混乱”
不能代替关键过程。Beat ID、EP/B 编号、paywall/付费点、审核维度和 risk 标签是内部规划
信息，不得进入剧本正文。

## 证据要求

每个模型 `issues` 的 error 必须带 `evidence`（`evidence_type: source|adaptation`），并由
Runtime 在绑定 `episode_context` 中验证 event/chapter/span/quote 或 adaptation decision。
`draft_evidence` 必须引用绑定草稿真实行号和片段；系统生成的 gate issue 以已验证的结构化
检查为证据，不要求重复伪造原文引用。

## 重写原则

- 只修复审核中明确列出的问题，保留已经成立的内容；
- 必须重新读取原文证据和 execution brief；
- 不得用旁白/总结替代必需画面、因果、回应或可见反应；
- 不新增审核未要求的内容，不自由生成另一版故事；
- 一次自动重写后仍有问题，交给编剧或等待明确指令；
- 重写后重新审核同一问题，不临时新增创意标准。
