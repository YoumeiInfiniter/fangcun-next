# Fangcun Next 独立评审与第一轮修复合同

> 日期：2026-08-09  
> 评审对象：`feature/fangcun-next-rebuild`  
> 评审时 HEAD：`6707f2438e50454d76ae8f547b9243a403e42042`  
> 旧基线：`main@e0d6bda0509ba449d7ab82e87eb49ddbc1430647`  
> 用途：开发模型第一轮修复的唯一交接文档。

## 1. 权限与优先级

开发前必须完整阅读：

1. `AGENTS.md`；
2. `docs/specs/fangcun-next-design-spec.md`；
3. 本文档。

优先级：

1. 用户已确认的业务决策；
2. 规格书；
3. 本文档的缺陷证据与验收合同；
4. 原开发交接文档中的自述。

原开发交接文档不是可信证明。“已实现”、“不可绕过”、“测试通过”都必须通过代码、反例和新增测试重新证明。

## 2. 独立评审总结论

Fangcun Next 的五层架构方向基本正确：

- `SKILL.md + CLI` 编排层；
- `references/prompts + genres/craft` 创作核心；
- `scripts/` 确定性运行时；
- Provider Adapter；
- P2 Platform Adapter 边界。

正向改进包括：

- 原文证据、因果链、人物认知和台词连接已进入通用 Prompt 底线；
- Craft 按题材和本集功能选择，不再全量注入；
- 业务剧本格式、JSON 状态和 XML 传输的概念已分层；
- 时长和容量被定义为建议，不是自动回退门禁；
- `SKILL.md` 只保留路由与高层原则，渐进式拆分方向正确。

但 P0 未通过，当前不得合并 `main`，不得替换生产版，不得先进入真实编剧项目测试。原因是确定性保证仍可绕过，会污染任何创作效果测试。

## 3. 已独立验证的测试基线

评审者已只读运行：

- 新版 unit：112/112 通过；
- regression：6/6 通过；
- smoke：4/4 通过；
- 旧版 38 项：31 通过、4 失败、3 报错；
- 发布 ZIP 可生成，解压后 `python -m scripts.project_cli --help` 可运行。

测试通过不代表 P0 通过。评审者在临时项目中另外复现了测试未覆盖的绕过路径。

## 4. S0-1：上下文、草稿、审核未真正同源绑定

### 4.1 证据

- `scripts/context_builder.py:35-36`：每集只有一个固定上下文路径；
- `scripts/context_builder.py:154-161`：重新生成时覆盖该文件；
- `scripts/project_cli.py:329-347`：草稿不记录 `context_hash` 或 `draft_hash`；
- `scripts/project_cli.py:546-553`：审核报告缺少 `context_hash` 时仍会接受，程序代为填入当前哈希；
- `scripts/project_cli.py:556-572`：重写总是读取当前最新草稿，不验证是否为被审核版本。

### 4.2 已复现路径

1. Writer 使用 H1 上下文生成草稿 v1；
2. 修改集纲后生成 H2，覆盖上下文快照；
3. 提交一份没有 `context_hash` 的审核报告；
4. 系统成功保存，并把 H2 写入报告；
5. 上传草稿 v2；
6. v1 的审核报告可直接用于重写 v2。

### 4.3 必须实现

- `episode_context` 按 `episode + context_hash` 保存不可变快照；
- 可以另设 current pointer，但快照内容不得覆盖；
- 草稿版本记录 `context_hash`、`draft_hash/content_hash`、集纲版本和原文事件版本；
- 审核报告强制绑定 `context_hash + draft_hash + draft_version`；
- 缺任一哈希时拒绝，不得自动补齐；
- 重写只能消费审核报告实际绑定的草稿；
- 重写前同时校验上下文、草稿和审核报告。

## 5. S0-2：版本历史是假历史，微批次集纲会丢失其他集

### 5.1 证据

- `scripts/state_store.py:153-186`：`record_artifact` 只登记路径，不保存内容快照；
- `scripts/project_cli.py:269-291`：集纲永远覆盖同一 `episode_outlines.json`；
- `scripts/project_cli.py:414-426`：审核报告覆盖同一路径；
- `scripts/continuity_manager.py:177-190`：同一集定稿覆盖同一 `epNNN.txt`。

### 5.2 已复现路径

- 先保存 EP1、EP2 集纲，再单独保存 EP1，EP2 立即消失；
- manifest 显示多个版本，但所有版本指向同一个已覆盖文件；
- 同一集上传两版定稿后，两条历史都只能读到最新内容。

### 5.3 必须实现

- 每次修改保存真正独立的不可变内容文件；
- manifest 每个版本记录 `version`、`path`、`content_hash`、`status`、`source`、`created_at`、`parent_version/supersedes`；
- `active_versions` 只负责当前指针；
- 旧内容必须能独立读取和恢复；
- 相同内容和相同输入重复保存应幂等，不制造重复版本；
- 适用于 source events、容量预估、改编指引、故事大纲、集纲、草稿、审核、定稿、时长预估。

### 5.4 微批次集纲合同

- 默认按 `episode` 做 upsert/merge；
- 未出现在本次输入的集数必须保留；
- 支持完整集纲、单集、任意小批次、新增少量集数和修改已有集数；
- 默认不允许静默删除集数；
- 如需整表替换，必须使用单独的显式 replace 选项；
- 每次记录新增、修改、未变和删除集数。

## 6. S0-3：Host Agent Mode 下定稿不能形成语义连续性

### 6.1 证据

- `scripts/continuity_manager.py:45-66`：确定性提取只包含人物、地点和候选末句；
- `scripts/continuity_manager.py:130-168`：无独立 API 时 `facts`、人物认知、关系等不会产生；
- `tests/unit/test_continuity_manager.py:86-91`：测试明确接受无 API 时 `facts == []`；
- `scripts/context_builder.py:117-142`：只读取上一集定稿，更早的人工修改必须依赖 continuity 传递。

### 6.2 生产影响

EP1 人工改掉系统规则后，EP2 可能通过上一集全文知道，但 EP3 及以后不会继承该事实。

### 6.3 必须实现

- API Mode 可继续用模型生成结构化 continuity delta；
- Host Agent Mode 必须提供连续性提取 Prompt 包、保存 CLI 和校验器；
- 宿主 Agent 根据编剧定稿输出结构化 delta，不要求另配独立 API；
- 每条事实记录 `fact_id`、类别、集数、定稿版本、剧本哈希、证据位置、状态和时间；
- 覆盖已发生事件、人物认知、人物状态、关系、道具、地点、伏笔、钩子和 future override；
- 可从所有当前有效定稿幂等重建；
- 每集分别记录 extraction mode 和完整性；
- 某集提取失败时明确报告降级，不得宣称全部成功；
- 修改当前已定稿集时，当前定稿必须进入修改上下文。

## 7. S1-1：原文检索会漏显式锚点并拆散成对台词

### 7.1 证据

- `scripts/source_retriever.py:128-171`：超预算事件会选中单条能放下的引文，不保证 setup/payoff 共存；
- `scripts/source_retriever.py:247-269`：明确长章节只在小于单章预算时加入原文摘录；
- `scripts/source_retriever.py:274-297`：已进入 `chapter_ids` 的章节可能被关键词检索跳过；
- `scripts/source_retriever.py:331-350`：总预算超限时直接丢弃整段摘录；
- `scripts/source_retriever.py:373-382`：完整性不核对每个直接锚点是否真实进入原文摘录。

### 7.2 已复现路径

- `chapter_ids` 显示第 1、2 章，但 `raw_excerpts` 只有第 1 章，完整性仍通过；
- `must_preserve_pairing` 的 setup/payoff 在小预算下只保留一句。

### 7.3 必须实现

- 为 source event、source chapter、dependency、must keep、dialogue anchor 和 key quote 建立 coverage ledger；
- 每个记录标记 requested、resolved、included、omitted 和 omission reason；
- 每个直接 event/chapter anchor 至少有一段真实原文；
- requested chapter 与 included chapter 分开记录；
- setup/payoff 和 `must_preserve_pairing` 作为不可拆分单元；
- 预算不足时提升必要证据预算，或显式阻断/报告，不得静默拆散；
- 完整性逐项验证 coverage ledger；
- must keep 必须追溯到原文 event/span 或已确认 adaptation basis。

## 8. S1-2：修改意见默认不会进入后续创作

### 8.1 证据

- `SKILL.md:53`：“修改意见”路由到 `apply-revision`；
- `scripts/revision_manager.py:48-73`：创建后默认为 pending；
- `scripts/context_builder.py:46-60`：上下文跳过 pending；
- `scripts/project_cli.py:861-869`：CLI 只有创建时 `--auto-approve`，没有后续 approve/reject/list/apply 命令；
- `scripts/context_builder.py:117-121`：修改当前集时不读取当前定稿。

### 8.2 必须实现

- 提供 `list-revisions`、`approve-revision`、`reject-revision`、`apply-revision`、`revision-status`；
- 明确的编剧直接指令可在确认来源后 approved；
- 模型推测或不明确评论保持 pending；
- 继续创作前必须显式提示 pending，不得静默忽略；
- 支持显式 `affects_future=true/false` 和 scope；
- 关键词只是影响建议，不是最终决定；
- 编剧选择高于自动分析；
- approved revision 进入对应集上下文；
- applied 后记录应用到的草稿/定稿版本；
- 修改当前已定稿集时基于当前定稿，不得从集纲重生。

## 9. S1-3：审核证据门禁只验证字符串非空

### 9.1 证据

- `scripts/project_cli.py:414-421`：任意非空 `source_evidence` 或 `adaptation_basis` 即通过；
- `scripts/project_cli.py:508-543`：无证据 error 会在归一化阶段自动降为 warning；
- `SKILL.md:90`：文档却宣称无证据 error 拒绝保存。

### 9.2 已复现路径

`"source_evidence": "任意字符串"` 可以作为 error 证据成功保存。

### 9.3 必须实现

证据改为结构化引用，至少支持：

```json
{
  "evidence_type": "source | adaptation",
  "event_id": "CH001-E03",
  "chapter_id": 1,
  "source_span": {"start": 10, "end": 80},
  "excerpt_hash": "...",
  "quote": "...",
  "adaptation_decision_id": "..."
}
```

程序必须验证：

- 证据属于报告绑定的 episode context；
- event ID、chapter、span 真实存在；
- quote 与当前原文摘录一致；
- excerpt hash 一致；
- adaptation basis 属于当前有效改编决策；
- 任意字符串或不存在引用不得通过；
- 无证据 error 的处理在 SKILL、Prompt、Schema、代码和测试中完全一致；
- verdict 根据归一化后的有效 issue 重新计算。

## 10. 本轮必须新增的绕过测试

至少覆盖：

1. 缺 `context_hash` 的审核报告被拒绝；
2. 缺 `draft_hash` 的审核报告被拒绝；
3. H1 草稿不能用 H2 上下文审核；
4. v1 审核不能用于重写 v2 草稿；
5. 篡改上下文快照后哈希校验失败；
6. 任意证据字符串被拒绝；
7. 不存在的 event ID/span 被拒绝；
8. 单集集纲更新不删除其他集；
9. 小批集纲更新不删除批次外集数；
10. 两版定稿可分别读取和恢复；
11. 两版审核报告可分别读取；
12. 相同内容重复保存不产生重复版本；
13. Host Agent Mode 下 EP1 人工定稿事实能进入 EP3 上下文；
14. 当前已定稿 EP1 的修改上下文包含 EP1 当前定稿；
15. 明确长章节锚点必须有实际原文摘录；
16. setup/payoff 在低预算下不能拆散；
17. completeness 识别“chapter IDs 有值但原文摘录缺失”；
18. pending revision 在继续创作前被显式提示；
19. approve revision 后指令进入上下文；
20. reject revision 后指令不进入上下文；
21. `affects_future=false` 可覆盖关键词推测；
22. 自动重写次数有限，人工修改版本数不受限。

不得通过删除旧测试、放宽断言、把 error 改成 warning 或仅修改 fixture 制造通过。

## 11. 本轮不处理

- P1 容量预估算法优化；
- 动态总时长预测；
- 格式 profile 扩展；
- pip 资源打包、`agents/openai.yaml` 和跨 Agent 元数据修复；
- 旧项目迁移器完善；
- P2 飞书、OpenClaw、Dashboard、Token 统计；
- 改编指引和故事大纲能力重做。

以上保留为后续轮次，不得在本轮顺手扩张范围。

## 12. 禁止事项

- 不合并 `main`；
- 不修改旧版 `skills/drama`、旧 agents 和旧 tools；
- 不接入飞书或公司凭据；
- 不把确定性保证改成“要求 Agent 记住”；
- 不使用 Prompt 替代版本、哈希、状态和证据验证；
- 不提交 projects、原著文件、API 密钥、测试运行产物、缓存或打包临时文件；
- 不以“现有测试全过”代替新的绕过证明。

## 13. 完成定义

只有同时满足以下条件才能宣称第一轮完成：

1. 第 4–9 节问题逐项修复；
2. 第 10 节绕过测试有可追溯的测试名；
3. 新版 unit/regression/smoke 全部通过；
4. 旧版核心文件没有修改；
5. Git 工作树无意外文件；
6. 每个版本能恢复真实历史内容；
7. 同源审核无法通过 CLI 绕过；
8. 微批次集纲不丢集；
9. Host Agent Mode 定稿事实能传递到隔集上下文；
10. 没有把 P1/P2 混入本轮。

## 14. 开发模型完成后必须返回的交接

最终回复不得只写“已完成”或“测试通过”。

### A. Git 状态

- 仓库绝对路径；
- 当前分支；
- 修复前 commit；
- 修复后 commit；
- 本轮所有 commit hash；
- 是否推送远程；
- 明确说明没有合并 `main`；
- 最终 `git status --short --branch`。

### B. 文件清单

分类列出新增、修改和删除文件，每个文件用一句话说明用途。

### C. 问题→修复→测试对照

```text
| 问题 | 修改位置 | 新的确定性保证 | 对应测试 |
```

必须覆盖：同源绑定、真实版本、微批次集纲、定稿连续性、原文检索、修改意见、审核证据。

### D. 数据契约变化

完整列出 artifact version、draft metadata、review report、episode context、continuity、revision request 和 source evidence coverage 的新增/修改字段，并说明是否需要迁移旧 Fangcun Next 运行状态。

### E. 新增测试

逐项列出测试文件、测试类、测试方法名和它验证的绕过场景。

### F. 实际测试结果

逐条给出完整命令、测试数、通过/失败/跳过数、是否调用真实模型/API、是否只使用临时目录，以及测试前后 Git 状态。

### G. 未解决问题

诚实列出本轮未处理的 P1、P2、创作质量人工判断、降级模式和兼容限制。

### H. 修复交接文档

创建并提交：

`docs/development/fix-handoff-round1.md`

必须包含本轮范围、commit、修改摘要、数据契约、测试结果、已知限制、独立评审者应尝试的绕过路径和高风险文件。

### I. 下一轮独立评审提示词

最终回复末尾生成一段可直接复制给独立评审模型的提示词，包含：

- 仓库路径和分支；
- 修复前后 commit；
- 必读文件；
- 本轮七类修复；
- 要求独立复现所有绕过场景；
- 要求核对 P0；
- 只读、不修改、不合并 `main`；
- 输出剩余问题、严重度、文件/行号和修复建议。

如任一项未完成，不得省略，必须明确写“未完成”及原因。

## 15. 后续评审者已知的中等问题

以下不在第一轮修复，但开发模型不得宣称整个 Fangcun Next 已完成：

- 容量方案的“+10 集”是固定文案，不是内容推导结果；
- `minimum_total_seconds` 没有真正进入容量压力计算；
- 剧本批次后没有基于实际密度重新预测剩余剧情；
- 非连续返回同一地点也可能被 scene key 全局重复误拦；
- `legacy-scriptitem` 配置反向要求 Writer 维护 XML；
- AI 上游产物保存时直接标记 approved，人工确认状态不完整；
- `agents/openai.yaml` 不符合标准 `interface` 结构；
- pip 安装配置只包含 Python `scripts` 包，可丢失 references/assets/SKILL；
- 发布包 `SKILL.md` 引用了包内不存在的 docs/legacy/skills；
- 迁移器不迁移原著章节、不转换旧 continuity Schema，也不规范化旧 XML 剧本；
- 真实模型 3 集报告仍包含人工修复、待裁决集和误报，尚未完成生产效率验收。

