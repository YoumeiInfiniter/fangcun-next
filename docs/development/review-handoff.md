# Fangcun Next 重构评审交接包

> 用途：给独立评审 Agent/模型（新会话）使用。评审者应先读本文件、规格书与 AGENTS.md，再按需读代码。评审只读，不修改文件、不合并分支。

## 1. 评审范围

- 仓库：`/Users/mac/Documents/ChatGPT/Fangcun分析/fangcun-next`
- 分支：`feature/fangcun-next-rebuild`（`main` 仅为旧基线初始 commit，未动）
- 重构目标：把旧 Fangcun 重做为“编剧为最终作者、AI 为可控助手”的跨 Agent 小说转短剧 Skill；唯一设计基线是 `docs/specs/fangcun-next-design-spec.md`
- 本次实现范围：P0（集纲→剧本质量闭环）+ P1（容量预估）；P2（飞书/OpenClaw/Dashboard/Token 统计）仅留接口

## 2. 关键设计决策

1. **五层架构**：Orchestration（SKILL.md + CLI）→ Creative Core（references/prompts + genres/craft）→ Deterministic Runtime（scripts/）→ Provider Adapter（model_adapter）→ Platform Adapter（P2）。
2. **不可变 `episode_context`**：Writer/Reviewer/Rewriter 消费同一 JSON 快照，`context_hash` 绑定；保存审核报告时校验哈希，防止换证据集。
3. **锚点驱动检索**：集纲事件 ID → 章节 → 关键词 → 依赖 → 回退；句子边界吸附、引用完整、setup/payoff 不拆；禁止平均分配章节。
4. **Craft 按需路由**：题材 + 本集功能 + 操作三个维度选择模块，固定 4 个底线模块，禁止全量注入。
5. **确定性职责边界**：文件/版本/状态/锚点/格式/连续性由程序处理；模型只做创作判断。格式校验不冒充内容审核。
6. **证据门禁**：审核 error 必须有 source_evidence 或 adaptation_basis，缺证据自动降级 warning 并注明；无集纲/无证据且无改编依据时硬阻断。
7. **定稿优先**：已确认剧本是已发生事实最高来源；连续性可从定稿幂等重建；无 API 时明确 `deterministic` 降级，不伪造系统审核。
8. **业务格式唯一**：default-cn；XML 仅是可选 Renderer 适配；时长口径分离、仅提示。
9. **迁移只复制**：旧项目迁移不删除/修改源文件，输出迁移报告。
10. **发布包白名单**：排除旧代码/测试/项目产物/私密内容，命中密钥模式即拒绝构建。

## 3. 文件地图

```text
SKILL.md                        新版入口（113 行，路由+最高规则）
scripts/
  common.py                     路径/原子写入/哈希/围栏剥离
  schema_validate.py            自研轻量 JSON Schema 校验（stdlib）
  state_store.py                manifest + active_versions + config.local 合并
  source_ingest.py              拆章/归档/索引
  source_retriever.py           锚点检索与截断
  context_builder.py            不可变上下文 + 完整性检查
  prompt_router.py              七层 Prompt + Craft 路由
  script_validator.py           格式校验 + 结构化解析
  format_renderer.py            业务格式 ↔ XML
  duration_estimator.py         时长口径分离
  revision_manager.py           修改请求/影响分析
  continuity_manager.py         定稿→连续性（deterministic/model_assisted）
  model_adapter.py              Host Agent / API 双模式
  capacity_estimator.py         容量预估（仅提示）
  migration.py                  旧项目迁移
  release_builder.py            干净发布包
  project_cli.py                全部命令面（约 780 行，建议重点审）
references/
  schemas/                      9 份 JSON Schema
  prompts/                      分层 Prompt（system_base/writer/reviewer/rewriter/各阶段）
  genres/ + craft/              按需模块
  business-principles.md 等     规则文档
assets/screenplay-templates/    格式模板
tests/unit|regression|smoke/    106 项新版测试
docs/development/handoff-report.md  开发交接报告
```

旧版代码保留在 `skills/`、`agents/`、`tools/`、`docs/legacy/`，未修改。

## 4. 测试结果（2026-08-09，Python 3.12，无 API 的新版测试；真实模型验证用 DeepSeek）

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'        # 112 OK
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'   # 6 OK
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'        # 4 OK
PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'  # 旧基线 38：31 通过/4 失败/3 报错（未修，属旧基线）
```

真实模型验证：DeepSeek deepseek-v4-flash 完成 EP001 审核/重写/复审闭环（buggy→blocked→重写→pass）；真实小说前 3 章 3 集全流程测试通过（详见项目内 test-report.md）。

## 5. 已知限制与诚实清单

1. `must_keep` 原文依据检查是**确定性子串匹配**，描述性表述会误报警告（不阻断，不影响流程）；语义级检查需模型，未实现。
2. 真实模型审核存在**误报案例**：曾把“谢淮舟雷击前已明白自己听得见系统”判为认知错误（原文支持雷击前明白），已记录待编剧裁决。
3. 审核报告归一化依赖**模型输出映射表**（verdict/category 别名），未知类别落到 `other`；映射表需要随新模型调优。
4. `deepseek-v4-flash` 对该中转的 `max_tokens` 行为异常（正文为空），已通过 `max_completion_tokens` + 关闭思考规避；换模型/端点需复测。
5. 旧版 38 项测试的 4 失败/3 报错未修（过时测试与真实缺陷并存），新版用独立测试覆盖其真实缺陷场景。
6. P2 全部未实现：飞书同步/评论读回/OpenClaw 子 Bot/Dashboard/Token 统计。
7. `agents/openai.yaml` 仅为适配声明，未接入具体宿主插件。
8. 事件提取、改编指引、故事大纲、集纲的**生成**目前走 Host Agent Mode（Agent 直接写），CLI 只有审核/重写支持 `--api`；若要在 OpenClaw 上全自动生成上游产物，需要补模型生成命令（规划中）。

## 6. 建议评审重点（高风险文件）

- `scripts/context_builder.py`：上下文契约、哈希与完整性；检查是否有可绕过路径；
- `scripts/source_retriever.py`：检索顺序、截断、引用完整性；检查边界用例；
- `scripts/prompt_router.py`：Prompt 分层与 Craft 路由；检查是否可能全量注入；
- `scripts/continuity_manager.py`：定稿事实提取与重建；检查幂等性与降级诚实性；
- `scripts/project_cli.py`：命令面、审核证据门禁、模型输出归一化；
- `scripts/release_builder.py`：发布白名单与私密扫描；
- `scripts/schema_validate.py`：自研校验器覆盖范围（不支持 if/then 等 draft-07 特性）。

## 7. 验证命令（评审者可自行运行）

```bash
cd /Users/mac/Documents/ChatGPT/Fangcun分析/fangcun-next
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m scripts.project_cli build-package --out /tmp/review-pkg.zip
PYTHONPATH="$PWD" .venv/bin/python -m scripts.project_cli --help
```

## 8. 给评审 Agent 的输出要求

建议输出：问题清单（严重度 + 文件/行号证据 + 修复建议）、规格书 P0/P1 验收逐项核对、风险最高的 5 个文件、与旧版兼容性结论。全程只读。

