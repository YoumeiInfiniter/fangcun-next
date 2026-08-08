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

输出 episode-outline.schema.json 兼容 JSON（每集一个对象，汇总为 episodes 数组）。

