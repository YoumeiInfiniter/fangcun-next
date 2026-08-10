# Fangcun Next 0.3.0（Agent-first）开发交接

> 文档性质：开发实施模型的开发自测交接，不等同于独立验收。
> 独立评审模型应从干净工作区复现本文件列出的测试，再运行未公开变体。

## 起点与提交

- 起点：`fa7b5617df0a4276fae3136a1e4f8c1394767e3c`
- 分支：`codex/fangcun-next-v0.3.0-agent-first`
- 新增提交：
  - `b4fabc8` docs: define agent-first default, standard/quick modes and experimental API boundary
  - `77b4cf7` feat: extend episode-outline V2 contract, draft-metrics schema and legacy must_keep migration
  - `3d80eee` feat: propagate per-episode density into context and stage review, support V2 retrieval anchors
  - `ab9d936` feat: bind draft metrics to drafts, enforce system timing advisory and honest experimental API failures
  - `ba8b1b3` test: add v0.3.0 agent-first acceptance and API/metrics regression cases
  - `c2470ac` docs: hand off Fangcun Next 0.3.0 agent-first development
- 最终 HEAD：`c2470ac`（本文件随后只做最终 HEAD 记录提交，工作树干净）。

## 需求到修改文件和测试的映射

| 合同需求 | 主要文件 | 测试 |
|---|---|---|
| Agent Mode 默认正式路径、API 实验化 | `SKILL.md`、`docs/specs/`、`scripts/model_adapter.py`、`scripts/project_cli.py` | `test_default_zero_api_and_experimental_length_fails_honestly`、`test_call_generate_fails_honestly_on_finish_reason_length` |
| 标准/快速草稿模式与模型调用预算 | `SKILL.md`、`references/workflow.md`、`scripts/project_cli.py` | `test_standard_and_quick_modes_record_workflow_and_quick_cannot_approve` |
| 集纲局部容量传播与确认决定 | `scripts/stage_lifecycle.py`、`scripts/context_builder.py`、`scripts/project_cli.py`、`scripts/format_renderer.py` | `test_density_propagates_to_meta_markdown_stage_review_and_accept`、`test_density_aggregate_enters_ai_stage_review_bundle` |
| 集纲合同 V2 与旧 must_keep 兼容 | `references/schemas/episode-outline.schema.json`、`scripts/source_retriever.py`、`scripts/project_cli.py`、`scripts/migration.py` | `test_v2_outline_fields_enter_context_and_old_compat`、`test_mark_legacy_must_keep_never_guesses_category` |
| 草稿确定性时长指标 | `scripts/duration_estimator.py`、`references/schemas/draft-metrics.schema.json`、`scripts/project_cli.py` | `test_draft_metrics_bound_and_deviation_above`、`test_low_density_long_draft_metrics_and_system_timing_advisory` |
| 可拍性闭环与严重度 | `references/prompts/writer.md`、`references/prompts/reviewer.md`、`references/review-rubric.md` | `test_shootability_severity_prompt_and_error_save` |
| 项目规则隔离 | `references/schemas/project-config.schema.json`、`scripts/prompt_router.py` | `test_project_rules_isolated_to_referencing_project` |
| 发布版本 0.3.0 | `pyproject.toml`、`scripts/__init__.py`、`scripts/release_builder.py` | `test_release_builder` |

## 测试结果（开发自测，均未调用真实模型/API）

命令与结果：

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
# Ran 119 tests, OK

.venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
# Ran 163 tests, OK（新增 8 个 0.3.0 公开案例）

.venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
# Ran 4 tests, OK

.venv/bin/python -m unittest discover -s tests/drama -p 'test_*.py'
# Ran 38 tests, FAILED (failures=4, errors=3)
```

旧版 drama 基线在改动前已存在 4 failures / 3 errors，本轮未新增失败；其余新版测试全部通过。

默认零 API 验证：`test_default_zero_api_and_experimental_length_fails_honestly` 在存在
`FANGCUN_API_KEY` 时运行默认 Host Agent 流程，`requests.post` 未被调用；显式
`review --api` 在模型截断时失败且不保存审核报告。

模型调用预算验证：

- 标准模式：Writer 1 + Reviewer 1（`save-draft` + `review/save-review`）；
- 快速草稿：Writer 1，不生成 Reviewer 调用、不标记已审核、不能直接定稿；
- warning 不触发自动重写；自动重写只能由编剧显式 `rewrite` 签发一次性 ticket。

本地性能（代表性单集，Python 3.12 / Apple Silicon）：

- `save-draft` 本地确定性步骤（格式校验 + 上下文哈希 + `draft_metrics` 绑定）：
  约 `0.0064s`，远低于 1 秒预算；
- 单集 Prompt 只含当前集容量摘要，不包含全剧 density 明细或完整历史产物。

## API 与平台写入

- 是否调用真实外部 API：否；
- 是否执行飞书或 OpenClaw 写入：否；
- 是否修改第三轮测试项目原文/产物：否；
- 是否修改已安装 Skill `~/.codex/skills/fangcun-next`：否；
- 是否合并 `main`：否。

## 与 0.2.1 的兼容变化

- 老项目继续可读：旧 `must_keep` 字符串、无 V2 字段、无 `draft_metrics` 的草稿均可
  读取；旧 `must_keep` 保存为新的逻辑版本时标记 `legacy_unspecified`，历史版本文件
  不原地改写；
- `save-draft` 新增必需元数据：`workflow_mode`、`generation_mode`、
  `semantic_review_status`，并新增 `draft_metrics` 产物；
- `confirm-stage --stage episode_outline` 在 medium/high 容量时新增
  `--capacity-decision` 必选参数；无风险时自动记录 `not_applicable`；
- `review` 最终 `timing_advisory` 由 Runtime 覆盖为 `draft_metrics` 值，模型估计只
  保留为 `legacy_model_estimate`；
- `model_adapter` 检查 `finish_reason=length`，截断结果不再被当作完整结果。

## 已知限制

- 可拍性仍是语义判断，由 Prompt 与审核严重度规则约束，确定性 Runtime 不代替模型
  判断“是否演出关键过程”；
- `review-stage` 对人工导入且无 `stage_context_hash` 的旧阶段产物仍要求
  `confirm-stage --override-reason`，不能生成标准阶段审核包；
- 快速草稿不能直接 `approve`，需要先执行标准审核；这是有意保护，不是缺陷；
- 容量/时长仍是建议，`density_report` 只影响展示与编剧决定记录；
- 编剧确认与 `confirmation_ref` 的可审计性依赖宿主平台传递真实用户/消息引用，
  纯本地 CLI 不能加密证明调用者身份。

## 风险最高的 5 个文件

1. `scripts/project_cli.py`：CLI 入口集中了草稿指标、审核覆盖、容量决定与快速模式；
2. `scripts/stage_lifecycle.py`：阶段门禁与集纲容量决定；
3. `scripts/source_retriever.py`：V2 锚点覆盖和不可拆台词对；
4. `scripts/context_builder.py`：`episode_context` 哈希与密度传播；
5. `references/schemas/episode-outline.schema.json`：V2 可选字段的向后兼容边界。

## 发布包

- 路径：`dist/fangcun-next-0.3.0.zip`
- SHA256：`b68d055d9c6fe385652f3a3b045f6b7696696211065afe3bb397af47a05f49a3`
- 清单：`dist/release_manifest.json`（74 个文件，版本 0.3.0）
- 发布包不包含 `docs/development/`、`docs/research/`、测试项目、小说原文、密钥或本地配置。

## 给独立评审模型的简短只读复审提示词

```text
你是 Fangcun Next 0.3.0 独立评审模型，只读复审。
从干净工作区 checkout codex/fangcun-next-v0.3.0-agent-first 的最终 HEAD，
不修改代码、不合并 main、不调用真实 API、不执行平台写入。
请复现 docs/development/fix-handoff-v0.3.0-agent-first.md 中的 unit/regression/smoke，
然后重点构造隐藏变体：
1. 修改项目名、临时目录、事件 ID、章节坐标、集纲版本顺序；
2. 篡改或缺失 draft_metrics / density_reports / capacity_decisions；
3. 尝试绕过 quick_draft 未审核定稿、模型覆盖 timing_advisory、API 截断继续保存；
4. 检查 V2 required_story_beats/required_quotes 的锚点覆盖与旧 must_keep 兼容；
5. 检查默认流程在存在 API Key 时是否发生任何网络请求。
给出可复现问题与红灯/黄灯结论，不要替开发模型宣布验收通过。
```
