# Fangcun Next 第五轮真实流程修复交接

日期：2026-08-09
分支：`codex/fangcun-next-round5`
起点：`8d20f3e`
测试来源：首轮本地真实项目反馈；生产项目全程只读，未执行飞书、OpenClaw 或模型 API。

## 1. 本轮目标

本轮不是继续堆 Prompt，而是修复首轮真实使用暴露的确定性根因：原文误切、事件只有孤立台词、无关关键词污染、阶段产物未经审核即 approved、上游版本漂移、集纲 JSON/Markdown 分裂、角色名漂移、阶段 Prompt 过大，以及容量预估把时长下限误当精确目标。

## 2. 已完成的技术修复

1. 原文切章：普通句子“第二节是体育课。”不再被当章节；`第N节` 只在全文没有主章节且存在多个独立节标题时作为降级切分。
2. 双 span 证据：`source_span` 保持精确证据，新增 `retrieval_span` 提供触发—行动—反应—结果上下文；旧事件在读取时动态补齐，不改历史文件。
3. 检索去污染：存在直接事件/章节锚点时不再全书搜重复关键词；显式锚点即使超过字符预算也不会被静默丢弃。
4. 台词锚点：显式区分单句 `quote` 与不可拆 `pair`；pair 缺任一端、跨章或无法绑定真实事件时在集纲保存阶段拒绝。
5. `must_keep`：自由文本必须在当前原文证据中解析，或显式绑定本集事件/改编决策；不存在的依据在保存阶段拒绝。
6. Schema 运行时：补齐轻量校验器原先缺失的 `oneOf`、`anyOf`、`allOf`、`const`、结构化 `additionalProperties`、`maxItems`、`uniqueItems`。
7. 阶段状态机：改编指引、故事大纲、集纲统一为 `stage_context → needs_writer_confirmation → bound review → writer confirm`；绑定项目实例、配置哈希、上游版本与内容哈希。
8. 防绕过：省略或伪造 `stage_context_hash`、漏绑上游、配置变化、上游变化、旧 AI 产物无输入绑定、审核绑定不一致时均拒绝进入下游。
9. 集纲单一事实源：JSON 保存后自动渲染 Markdown，二者共享 `outline_sync_id`；旧 `--outline-md` 不再维护第二份事实。
10. 微批次：继续保留按集 upsert；只有显式 `--replace` 才整表替换。
11. 实体规范名：从原文事件提取角色名，阻断 3–4 字角色名的明确错序；允许项目配置 `entity_aliases`。
12. 容量预估：区分时长下限与偏好区间，输出维持集数、删减/合并、增集/延长、阶段性覆盖等方案；支持编剧指定 `episode_timing_overrides` 和 `planning_checkpoints`，始终只作建议。
13. Prompt 体积：全量事件改为紧凑路由目录，完整事件文件按 ID 定点读取；真实测试项目事件上下文从约 96k 字降至约 29k 字路由目录。
14. 剧本动作质量：Writer 明确具体、可拍、情绪与衔接标准；Reviewer 明确区分动作行和情节提要，蒙太奇等不作为全局硬模板。

## 3. 真实测试项目只读复核

对 `fangcun-next-test-projects/bige-dawang` 只读运行新版模块：

- EP1–3 不再出现原测试中第14章的无关关键词摘录；
- EP1 直接事件/台词证据约 7422 字，全部来自本集锚定章节；EP2 约 4475 字；EP3 约 7610 字；
- EP1 的事件摘录包含事件前因、人物行动、对方反应和结果，不再只有约十几个字的单句；
- 角色门禁复现并定位 `季之来 → 季来之`，同时发现旧集纲中的另一处明确错序；
- 旧项目 `episode_outline` 为 v003，而可读版仍是 v001，本轮自动同步机制可消除此类漂移；
- 旧项目的改编/故事/集纲为无 `stage_context_hash` 的旧 AI 产物，新版会阻止其直接继续下游。

## 4. 旧测试项目迁移建议

不要直接覆盖原测试项目。复制项目后执行：

1. 保留现有原文和事件资产；新版检索会只读动态生成 rich retrieval span。
2. 若编剧确认继续采用改编指引 v003，把该文件以 `--manual-import --manual-reason` 导入为新逻辑版本，并用明确人工审核理由确认。
3. 基于该确认版重新生成、审核并确认故事大纲；旧 story v001 与 adaptation v003 的来源关系无法证明，不应继续沿用。
4. 重新生成 EP1–5 集纲；JSON 会自动同步 Markdown，并在保存时阻断错名、无效 must_keep 和台词锚点。
5. 只生成 EP1 剧本，完成 Writer → Reviewer → 定稿闭环后再决定是否继续 EP2–5。

## 5. 验证命令

```bash
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH=. .venv/bin/python tests/regression/test_round1_bypass.py
PYTHONPATH=. .venv/bin/python tests/regression/test_round2_bypass.py
PYTHONPATH=. .venv/bin/python tests/regression/test_round3_external_acceptance.py
PYTHONPATH=. .venv/bin/python tests/regression/test_round4_external_acceptance.py
PYTHONPATH=. .venv/bin/python tests/regression/test_round5_real_workflow_acceptance.py
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
```

发布前还必须执行编译、`git diff --check`、发布包生成、包内私密扫描和解压后独立 smoke。

## 6. 已知边界

- 本轮只保证确定性输入、状态、版本、证据和审核门禁；创作成片质量仍需用户用真实案例比较。
- 角色错序检查只对 3–4 字规范名做精确字符排列检测，不做模糊猜测，避免误伤。
- 时长和事件密度永不因系统建议自动回滚上游；编剧可在剧本阶段接受超时。
- 尚未接入飞书、OpenClaw、Token 统计或线上权限。
