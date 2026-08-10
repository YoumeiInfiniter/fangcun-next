# 集纲阶段（episode_contract）

每集必须包含执行所需的最小合同：

- 集数、标题；
- 对应原文章节、事件 ID 或改编依据；
- 开场承接；
- 本集核心目标；
- 必须保留事件；
- 不可拆散因果链（causal_chains）；
- 人物开场认知、结尾认知；
- 关键台词候选及出处（dialogue_anchors）；
- 允许压缩、合并和删除项；
- 禁止新增项；
- 集末钩子；
- 建议时长；
- 与下一集的接口；
- 本集戏剧功能（episode_function，供 Craft 路由）。

集纲合同 V2（在同一次集纲生成中产出，不新增独立模型阶段）：

- `episode_focus`：观众看完本集最应记住的核心变化，可涵盖多个相关事件；
- `required_story_beats`：只放不可省略的剧情变化，每项绑定 `event_ids` 或
  `adaptation_decision_id`；
- `required_quotes`：只放必须保留或必须成对保留的原文台词，绑定
  `source_event_id`，成对使用 `setup`/`payoff` 与 `pair_id`；
- `project_rule_refs`：只引用当前项目已确认规则 ID，不复制规则正文；
- `optional_beats`：可压缩、删除或延后的内容；
- `beat_plan`：与 `required_story_beats` 对应的呈现计划，包含 function、
  事件 ID、presentation、estimated_seconds、entry_state、visible_outcome、
  `required_visual_beats`（只在关键动作、反应和局面变化上标注，不要求所有动作扩写）；
- `overflow_options`：对可选 Beat 给出 `compress` / `defer` / `accept_overflow`，
  只提供选择，不替编剧决定。

禁止事项：

- 不把项目规则、柔性风格提示或关系边界混入 `must_keep`；
- 不按固定事件数、固定动作数或固定场次数约束所有集数；
- 不新增独立的 Beat Plan 模型调用；
- 旧 `must_keep` 可继续读取，但新版本应优先使用 V2 字段。

来源绑定规则：

- 原著内容在 `source_event_ids` / `source_chapters` 中填写真实锚点；
- 新增或主动改编内容在 `adaptation_basis` 中使用 `{id, text}`，id 必须来自已确认改编决策；
- `must_keep` 若依赖改编决定，写成 `{text, adaptation_decision_id}`，禁止靠相似文字自动匹配；
- 没有原文锚点的新增场景可以留空 source 数组，但必须有结构化 adaptation basis。

输出 episode-outline.schema.json 兼容 JSON（每集一个对象，汇总为 episodes 数组）。
