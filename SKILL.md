---
name: fangcun-next
description: |
  小说转短剧剧本改编引擎（新版，编剧最终作者、AI 可控助手）。
  触发方式：「写剧本」「改编短剧」「小说转剧本」「帮我写剧本」「用fangcun」
  「分析这本书」「继续写」「改一下第N集」。
  在飞书群聊环境下，阶段验收产物落盘后默认输出 FANGCUN_FEISHU_SYNC_EVENT，
  由 Host Agent 创建版本化飞书文档、写入并读回校验、登记 registry 后回链并停等确认；
  「发成飞书文档」「输出到飞书」「同步回本地」「文档版本」为显式兜底触发。
---

# Fangcun Next：小说转短剧 Skill 系统

本 Skill 是 Fangcun 新版，与旧版 `fangcun-v2-dev` 相互独立；旧版运行体系与
旧文档已迁出到只读归档（Git 历史可追溯），不参与本 Skill 运行。设计基线见
源码仓库 `docs/specs/fangcun-next-design-spec.md`（开发用，发布包不含 `docs/`）。
发布包只包含本 SKILL.md、`agents/openai.yaml`、`scripts/`、`references/`、`assets/`
与 `pyproject.toml`，运行所需规则全部位于包内。

## 一句话定位

把小说原文变成可执行的单集创作契约，让 Writer 只执行当前 execution brief，让 Reviewer
和 Rewriter 看到与 Writer 完全相同的原文证据，让编剧确认的每一集成为后续
集数的最高事实来源。类型差异通过按需加载的 Craft 模块实现，不改变已确认剧情。

编剧通过自然语言提出需求、确认或修改；结构化 JSON、版本绑定和 CLI 调用由 Host Agent
代办，不能把 JSON 格式要求转嫁给编剧。

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

## 集纲事件浏览器（编剧对照原文判断故事选取）

事件资产与集纲确认后，可生成一个**纯本地、零模型调用**的可交互 HTML
（约 1–2 秒/本），供编剧打开后对照集纲快速核查“本集用了哪些故事、哪些被裁”，
并直接跳回原小说对应段落：

- 生成：`fangcun event-browser --dir <项目>`，产物固定为 `<项目>/event_browser/index.html`。
- 内容：左侧按章列出**全部已提取事件**（ID＋一句话摘要＋✔第N集选用/✘被裁徽标，
  支持按关键词搜索、按 全部/选用/被裁 筛选）；右侧为原文章节全文，
  点击任意事件（列表或正文高亮处）弹出事件详情（事件/触发/动作/结果/关键原句/
  重要度/建议时长）并滚动高亮原文 span。
- 自动更新：`save-events`、`save-episode-outline`、`confirm-stage`(episode_outline)
  之后会自动重建该 HTML，因此编剧对集纲的任何已保存修改都会立即反映到浏览器。
- 前提与边界：
  - 依赖事件资产（含 `source_span`）与集纲活动版本；事件只覆盖已做事件提取的章节
    （如测试范围前 30 章），未提取章节不会出现在事件表中；
  - 编剧若要把某段**从未提取的原文**加进集纲，需要先对该章做事件提取与坐标定位
    （`stage_events.md` + `locate-span`，每章约一次模型调用），再做集纲修改；
  - HTML 是只读浏览视图，集纲的修改面仍是 `save-episode-outline`（按集 upsert 或
    `--replace` 整表替换），改完系统自动重建浏览器。

## 标准模式与快速草稿模式

- 标准模式（默认）：`get-episode-context` → Writer 一次生成 → `save-draft` →
  Reviewer 一次同源审核 → 展示后停止等待编剧。不自动重写，warning 不触发模型调用。
- 快速草稿模式：`save-draft --workflow-mode quick_draft`，只做本地格式与
  `draft_metrics` 校验并标记 `unreviewed_draft`；不调用 Reviewer、不标记已审核、
  不能直接定稿或更新连续性。编剧之后可要求标准审核。
- 模型调用预算：标准单集最多 Writer 1 + Reviewer 1；快速草稿只有 Writer 1；
  自动重写 0，只有编剧明确要求时签发一次性 rewrite ticket（最多一次）。

## 命令路由

所有命令通过 `scripts/project_cli.py` 执行（也可安装 console script `fangcun`）。
每个命令都基于同一项目目录 `--dir <project>`。

| 用户说 | 命令 |
|--------|------|
| 初始化项目 | `fangcun init --dir <project> --config <config.json>` |
| 发来原始需求 | `init --brief "..."` 后 `generate-requirements` → `save-requirements` |
| 发来小说文件 | `ingest-source --dir <project> --file <novel.txt>` |
| 提取事件 | 读取 `source/index.json` 及其章节文件，按 `references/prompts/stage_events.md` 生成 JSON；定位原文片段坐标用 `locate-span --dir <project> --chapter <N> --text "<原文片段>" [--fuzzy]` 半自动计算（禁止手工数坐标；片段重复出现时须用 `--occurrence N` 指定第几次，工具不会静默选错位置），再执行 `save-events --dir <project> --file <events.json>` |
| 编剧一次性确认多个阶段产物（上游重绑批量确认） | 在编剧明确确认后，`confirm-stages --stages adaptation,story_outline,episode_outline --operator <实际确认人> --confirmation-ref <消息或评论引用> [--override-reason ...]`；已确认且内容 hash 未变的阶段会自动沿用旧确认并跳过 |
| 容量预估与取舍 | `estimate-capacity --dir <project>` → `generate-capacity-plan --dir <project>` → 编剧选择后 `save-capacity-plan --plan-json <file> --operator <实际确认人> --confirmation-ref <确认引用>` |
| 改编指引 | `generate-adaptation`（记录输出的 `stage_context_hash`）→ `save-adaptation --file <strategy.md> --stage-context-hash <hash>` |
| 故事大纲 | 上一阶段确认后：`generate-story-outline` → `save-story-outline --file <outline.md> --stage-context-hash <hash>` |
| 集纲 | 上两阶段确认后：`generate-episode-outline` → `save-episode-outline --outline-json <episodes.json> --stage-context-hash <hash>`；可读 Markdown 自动同步 |
| 审核阶段产物 | `review-stage --stage adaptation|story_outline|episode_outline [--api]` → Host Agent 时按 `stage-review.schema.json` 审核并执行 `save-stage-review`；API 时由同一保存门禁落盘 |
| 编剧确认阶段产物 | **必须先停止并等待编剧在后续消息明确确认**，再执行 `confirm-stage --stage <stage> --version vNNN --operator <实际确认人> --confirmation-ref <消息或评论引用>`；集纲 medium/high 容量风险必须先绑定已确认的 `capacity_plan`，再提供 `--capacity-plan-version vNNN` |
| 编剧人工导入阶段产物 | 仅在编剧明确要求时，用对应 save 命令的 `--manual-import --manual-reason "..."`；后续仍需新的明确确认消息和可审计 confirmation_ref |
| 写第N集（标准） | `get-episode-context --episode N` → 读上下文包 → `save-draft --episode N --file <draft.txt>` |
| 启动临时批次 | `start-batch --start-episode N [--size 3]`；后续集可读未确认临时上下文，不能写入正式连续性 |
| 批次状态与确认 | `batch-status`；编剧明确确认后 `confirm-batch --operator <实际确认人> --confirmation-ref <确认引用>` |
| 快速草稿 | 同一上下文 → `save-draft --episode N --file <draft.txt> --workflow-mode quick_draft` |
| 审核 | `review --episode N` → 读审核包 → `save-review --episode N --file <review.json>`（Host Agent 代办 JSON；系统综合 issues、beat/dimension/quote 检查和确定性门禁推导 verdict） |
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
| 集纲事件浏览器 | `event-browser --dir <project>`（编剧对照集纲与原文：左侧全事件表 ✔选用/✘被裁、可搜索/筛选；点事件右侧跳转并高亮原文 span；`save-events` / `save-episode-outline` / `confirm-stage(episode_outline)` 后自动重建，也可手动重跑） |
| 迁移旧项目 | `migrate --legacy-config <旧config> --out-dir <目录>` |
| 生成发布包 | `build-package --out dist/fangcun-next-<version>.zip` |

API 模式（实验性）：只有用户明确要求或项目配置明确启用时，才可在
`review-stage` / `review` / `rewrite` 后加 `--api`。默认工作流完全不调用 API；
未配置或未明确启用时不得因为检测到 Key 就自动选择 API。调用前会输出实验性提示，
`finish_reason=length`、空正文或非法 JSON 会诚实失败，不自动重试、不静默降级、
不得伪装成系统审核成功。Host Agent Mode 是默认正式路径，审核来源如实记录为
`host_agent`。

## 五层架构

1. **Orchestration**：`SKILL.md` 路由 + `scripts/project_cli.py` 命令面，不含业务规则大全。
2. **Creative Core**：`references/prompts/` 各阶段 Prompt + `references/genres/`、`references/craft/` 按需模块。
3. **Deterministic Runtime**：`scripts/` 下的 Schema 校验、状态版本、原文检索、上下文构建、格式校验、连续性与时长。
4. **Provider Adapter**：`scripts/model_adapter.py`，Host Agent 与 API 共用同一上下文与校验器。
5. **Platform Adapter**：`references/platform-adapters.md`、`references/feishu-artifact-sync.md` 与迁移层，飞书/OpenClaw 只作为可选适配，不进入创作核心。在飞书群聊环境下，阶段 Markdown/TXT 产物落盘后会稳定打印 `FANGCUN_FEISHU_SYNC_EVENT:` 交付事件，由 Host Agent 用一等 `feishu_doc` 工具完成在线文档创建、读回校验与登记。

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
13. `save-stage-review` 后必须结束当前任务并展示产物与审核结论；只有编剧在后续消息明确确认该版本时才能调用 `confirm-stage`。任务目标、批量运行要求、Agent 自填 `operator=writer` 或推测的“预授权”都不构成确认。
14. 在飞书群聊中，`project_brief`、`adaptation_strategy`、`story_outline`、`episode_outline_md`、`script_draft`、`review_md`、`stage_review_md` 等用户验收产物保存后，Host Agent 必须响应 `FANGCUN_FEISHU_SYNC_EVENT`：创建版本化飞书文档、写入并读回校验，成功后登记 registry、回复链接并停止等待确认；403/写入失败/读回不一致不得假装成功。

## 降级与诚实

- 未配置 API 时：Host Agent Mode 直接写作/审核/重写；连续性可通过
  `extract-continuity` + `save-continuity-delta` 由宿主 Agent 提取结构化 delta；
  未提供 delta 时以确定性提取（`extraction_mode: deterministic`）降级并在
  `degraded_episodes` 中显式列出；不允许把格式校验或本地裁决冒充系统模型审核。
- 审核报告必须显式携带 `context_hash`、`draft_hash`、`draft_version`，缺任一拒绝保存，
  不允许自动补齐；草稿绑定生成它的上下文快照，重写只能消费审核报告实际绑定的草稿版本。
- 审核报告必须按 `review-report.schema.json` 提供逐 beat、八维度、逐 required quote 和
  risk signal 检查；verdict 由归一化 issues 加这些检查和系统确定性门禁综合推导
  （任一 error→blocked / 否则 warning→warning / 其余→pass）。模型输入的 verdict 只记录为
  `model_verdict`；非法 issue（非对象/空 problem/非法 severity）拒绝整份报告。
- 审核的 error 级问题必须有可在绑定 `episode_context` 中验证的结构化证据
  （`evidence_type: source|adaptation`）；任意字符串或不存在的事件/章节/span/quote
  引用拒绝保存，无证据 error 不自动降级；证据的所有字段必须指向同一个摘录。
- 自动重写由系统签发一次性 rewrite ticket 管理（API 与 Host Agent 同一套来源与次数门禁）；
  消耗 ticket 的草稿标记 `origin=automatic_rewrite`，再次自动重写被拒绝，人工保存后可重新获得一次。
- 内部剧本一律为 `default-cn` 业务正文；`<scriptItem>` 只由 export/Renderer 包装，
  旧 XML 导入会先确定性解包再保存。
- 上下文缺少原文证据且无改编依据时硬阻断，让编剧决定，不允许模型自由补写。
- 每版草稿保存时由 Runtime 计算并绑定 `draft_metrics`
  （`context_hash + draft_version + draft_hash`）；Reviewer 不得猜测或覆盖秒数，
  最终 `timing_advisory` 始终来自系统指标。
- 集纲局部容量报告绑定集纲版本/哈希，进入可读 Markdown、阶段审核摘要、
  `episode_context` 与 Writer/Reviewer Prompt；medium/high 必须由编剧选择具体
  `capacity_plan`（集数、时长、保留/压缩/延期/省略事件）后才能确认，旧项目的
  `accept_current_plan` 记录只读兼容且不会伪装成新计划。
- `required_story_beats` / `required_quotes` / `beat_plan` / `project_rule_refs`
  与旧 `must_keep` 分离：剧情必保留、台词必保留、项目规则、可选内容不再混入
  `must_keep`；旧项目保持可读，历史版本不原地改写。
- 原文事件的精确 `source_span` 用于证据校验，独立的 `retrieval_span` 用于提供触发—行动—反应—结果上下文；不得把一个孤立原句当成完整事件上下文。
- `must_keep` 和台词锚点必须绑定真实事件或明确改编决策；未解析的自由文本、缺一端的问答/铺垫回收对在集纲保存时即拒绝。

## 飞书交付适配（可选 P2）

检测到当前交互环境为飞书群聊，且 Fangcun 产物已落盘并需要交付用户验收时，
**默认自动启用**飞书交付适配；无需用户额外说“发成飞书文档”。按需读取
`references/feishu-artifact-sync.md`，用 `scripts/artifact_sync_registry.py`
登记本地文件与飞书文档版本。显式触发词只用于用户主动要求重发、指定地址、
反向同步或非默认场景。该适配只处理产物镜像、版本命名、反向同步，不得改变
阶段门禁、审核结论、编剧确认规则或创作内容。

## 安全边界

- 飞书群聊默认交付属于已授权的平台适配：当 CLI 打印 `FANGCUN_FEISHU_SYNC_EVENT` 时，Host Agent 应使用一等 `feishu_doc` 工具创建/写入/读回校验版本化文档并登记 registry；无需用户再次说“发成飞书文档”。除此之外，不执行未请求的线上文档修改、不使用公司凭据、不向未指定目标写入。
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
- `references/feishu-artifact-sync.md`：飞书群聊阶段产物交付事件、版本化文档、registry 与失败处理；
- `references/schemas/`：全部机器可读数据契约；
- `references/prompts/`：分层 Prompt（系统底线、Writer、Reviewer、Rewriter、各阶段）。
