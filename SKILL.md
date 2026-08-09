---
name: fangcun-next
description: |
  小说转短剧剧本改编引擎（新版，编剧最终作者、AI 可控助手）。
  触发方式：「写剧本」「改编短剧」「小说转剧本」「帮我写剧本」「用fangcun」
  「分析这本书」「继续写」「改一下第N集」。
---

# Fangcun Next：小说转短剧 Skill 系统

本 Skill 是 Fangcun 新版，与旧版 `fangcun-v2-dev` 相互独立。旧版代码保留在
`docs/legacy/` 与本仓库 `skills/` 目录中，仅作迁移输入与兼容基线；新版唯一
设计基线是 `docs/specs/fangcun-next-design-spec.md`。

## 一句话定位

把小说原文变成可执行的单集创作契约，让 Writer 只执行当前契约，让 Reviewer
和 Rewriter 看到与 Writer 完全相同的原文证据，让编剧确认的每一集成为后续
集数的最高事实来源。类型差异通过按需加载的 Craft 模块实现，不改变已确认剧情。

## 核心流程

```text
需求确认 → 原文归档与事件资产 → 容量预估(仅参考) → 改编指引
→ AI同源审核 → 编剧确认 → 故事大纲 → AI同源审核 → 编剧确认
→ 集纲(episode_contract) → AI同源审核 → 编剧确认 → 单集上下文(episode_context)
→ Writer → Reviewer(同源审核) → Rewriter(定向修复)
→ 编剧定稿 → 连续性更新 → 后续集数
```

支持的变体：全部集纲完成后写剧本、2集集纲+2集剧本滚动、一次一集、先出5集再
精修、编剧上传自己的版本作为定稿、评论/正文局部修改。因时长超出预期而自动
回退到早期阶段是禁止行为；是否整体重做只由编剧明确决定。

## 命令路由

所有命令通过 `scripts/project_cli.py` 执行（也可安装 console script `fangcun`）。
每个命令都基于同一项目目录 `--dir <project>`。

| 用户说 | 命令 |
|--------|------|
| 初始化项目 | `fangcun init --dir <project> --config <config.json>` |
| 发来原始需求 | `init --brief "..."` 后 `generate-requirements` → `save-requirements` |
| 发来小说文件 | `ingest-source --dir <project> --file <novel.txt>` |
| 提取事件 | 读取 `source/index.json` 及其章节文件，按 `references/prompts/stage_events.md` 生成 JSON，再执行 `save-events --dir <project> --file <events.json>` |
| 容量预估 | `estimate-capacity --dir <project>` |
| 改编指引 | `generate-adaptation`（记录输出的 `stage_context_hash`）→ `save-adaptation --file <strategy.md> --stage-context-hash <hash>` |
| 故事大纲 | 上一阶段确认后：`generate-story-outline` → `save-story-outline --file <outline.md> --stage-context-hash <hash>` |
| 集纲 | 上两阶段确认后：`generate-episode-outline` → `save-episode-outline --outline-json <episodes.json> --stage-context-hash <hash>`；可读 Markdown 自动同步 |
| 审核阶段产物 | `review-stage --stage adaptation|story_outline|episode_outline` → 按 `stage-review.schema.json` 审核 → `save-stage-review --stage <stage> --file <review.json>` |
| 编剧确认阶段产物 | `confirm-stage --stage <stage> --version vNNN`；只有绑定审核 pass/warning 后可确认 |
| 编剧人工导入阶段产物 | 仅在编剧明确要求时，用对应 save 命令的 `--manual-import --manual-reason "..."`，随后仍需 `confirm-stage --override-reason "人工审核说明"` |
| 写第N集 | `get-episode-context --episode N` → 读上下文包 → `save-draft --episode N --file <draft.txt>` |
| 审核 | `review --episode N` → 读审核包 → `save-review --episode N --file <review.json>`（verdict 由系统按 issues 推导） |
| 定向重写 | `rewrite --episode N` → 读重写包（含一次性 ticket）→ `save-draft --episode N --file <draft2.txt> --rewrite-ticket <ticket>` → 重新审核 |
| 编剧定稿 | `approve --episode N --file <approved.txt>` |
| 修改意见 | `apply-revision --episode N --instruction "..."` |
| 查看/处理修改意见 | `list-revisions`、`approve-revision --revision-id`、`reject-revision --revision-id`、`revoke-revision --revision-id`、`revision-status` |
| 连续性 | `refresh-continuity --dir <project>` |
| 连续性提取（Host Agent） | `extract-continuity --episode N` → `save-continuity-delta --episode N --file <delta.json>` |
| 恢复历史版本 | `activate-version --kind <kind> [--episode N] --version vNNN` |
| 时长预估 | `forecast-duration --dir <project>` |
| 进度 | `status --dir <project>` |
| 导出 | `export --dir <project> [--xml]` |
| 迁移旧项目 | `migrate --legacy-config <旧config> --out-dir <目录>` |
| 生成发布包 | `build-package --out dist/fangcun-next-<version>.zip` |

API 模式：在 `review` / `rewrite` 后加 `--api`，由配置的模型执行；未配置时
必须使用 Host Agent Mode，且不得声称完成了系统模型审核。

## 五层架构

1. **Orchestration**：`SKILL.md` 路由 + `scripts/project_cli.py` 命令面，不含业务规则大全。
2. **Creative Core**：`references/prompts/` 各阶段 Prompt + `references/genres/`、`references/craft/` 按需模块。
3. **Deterministic Runtime**：`scripts/` 下的 Schema 校验、状态版本、原文检索、上下文构建、格式校验、连续性与时长。
4. **Provider Adapter**：`scripts/model_adapter.py`，Host Agent 与 API 共用同一上下文与校验器。
5. **Platform Adapter**：`references/platform-adapters.md` 与迁移层，飞书/OpenClaw 只作为可选 P2 适配，不进入创作核心。

## 最高规则

1. 编剧拥有最终决定权；AI 只提供分析、方案和风险提示。
2. 重大事件、人物、设定和反转必须有原文依据或已确认改编依据；主动偏离必须记录依据。
3. 已确认剧本是已发生剧情的最高事实来源；旧集纲只描述未来计划，冲突时定稿优先且旧版保留历史。
4. 确定性逻辑（文件、版本、状态、锚点、格式、连续性）由程序处理，模型只处理创作判断。
5. Writer、Reviewer、Rewriter 必须消费同一份不可变 `episode_context`（context_hash 校验）。
6. Craft 只按需加载，类型方法只能影响表达，不能改变已确认发生什么。
7. 业务剧本格式、内部 JSON、平台传输格式分离；XML 只是可选适配器。
8. 时长与容量只是预期：口径分离、区间输出、永不阻断。
9. 小范围修改就地处理；是否整体重做由编剧明确决定，系统不得自动回退。
10. 不把单一剧本样本或单一类型流程变成所有题材的硬规则。
11. 改编指引、故事大纲和集纲的 AI 产物保存后只能处于 `needs_writer_confirmation`；审核与编剧确认不可省略，未确认或上游已变化时下游命令硬阻断。
12. 阶段输出必须携带生成时的 `stage_context_hash`；项目配置、上游版本或内容哈希变化后，旧输出拒绝保存。Agent 不得擅自使用人工导入/override 通道。

## 降级与诚实

- 未配置 API 时：Host Agent Mode 直接写作/审核/重写；连续性可通过
  `extract-continuity` + `save-continuity-delta` 由宿主 Agent 提取结构化 delta；
  未提供 delta 时以确定性提取（`extraction_mode: deterministic`）降级并在
  `degraded_episodes` 中显式列出；不允许把格式校验或本地裁决冒充系统模型审核。
- 审核报告必须显式携带 `context_hash`、`draft_hash`、`draft_version`，缺任一拒绝保存，
  不允许自动补齐；草稿绑定生成它的上下文快照，重写只能消费审核报告实际绑定的草稿版本。
- 审核 verdict 只由归一化后的有效 issues 推导（error→blocked / warning→warning / 其余→pass）；
  模型输入的 verdict 只记录为 `model_verdict`；非法 issue（非对象/空 problem/非法 severity）拒绝整份报告。
- 审核的 error 级问题必须有可在绑定 `episode_context` 中验证的结构化证据
  （`evidence_type: source|adaptation`）；任意字符串或不存在的事件/章节/span/quote
  引用拒绝保存，无证据 error 不自动降级；证据的所有字段必须指向同一个摘录。
- 自动重写由系统签发一次性 rewrite ticket 管理（API 与 Host Agent 同一套来源与次数门禁）；
  消耗 ticket 的草稿标记 `origin=automatic_rewrite`，再次自动重写被拒绝，人工保存后可重新获得一次。
- 内部剧本一律为 `default-cn` 业务正文；`<scriptItem>` 只由 export/Renderer 包装，
  旧 XML 导入会先确定性解包再保存。
- 上下文缺少原文证据且无改编依据时硬阻断，让编剧决定，不允许模型自由补写。
- 原文事件的精确 `source_span` 用于证据校验，独立的 `retrieval_span` 用于提供触发—行动—反应—结果上下文；不得把一个孤立原句当成完整事件上下文。
- `must_keep` 和台词锚点必须绑定真实事件或明确改编决策；未解析的自由文本、缺一端的问答/铺垫回收对在集纲保存时即拒绝。

## 安全边界

- 不执行真实飞书写入、不修改线上文档、不使用公司凭据，除非用户明确授权并指定目标。
- 项目目录、`_cache/`、`output/`、`logs/`、密钥、小说原文与内部调研材料不进入发布包。
- 发布包由 `build-package` 生成，内含私密内容模式扫描，命中即拒绝。

## 详细方法

本文件只保留路由与最高规则。详细方法按需加载：

- `references/business-principles.md`：业务原则与事实/指令优先级；
- `references/workflow.md`：流程变体与阶段职责；
- `references/screenplay-format.md`：业务格式唯一标准；
- `references/dialogue-quality.md`：台词最小单位与原文台词策略；
- `references/review-rubric.md`：审核维度、严重度与证据要求；
- `references/genre-router.md` 与 `references/genres/`、`references/craft/`：Craft 路由；
- `references/revision-policy.md`：修改来源、影响分析与定稿后动作；
- `references/platform-adapters.md`：平台能力探测与 P2 适配边界；
- `references/schemas/`：全部机器可读数据契约；
- `references/prompts/`：分层 Prompt（系统底线、Writer、Reviewer、Rewriter、各阶段）。
