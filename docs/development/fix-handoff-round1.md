# Fangcun Next 第一轮修复交接（Round 1 Fix Handoff）

> 依据：`docs/development/independent-review-round1-fix-brief.md`（独立评审第一轮修复合同）
> 修复前 HEAD：`6707f2438e50454d76ae8f547b9243a403e42042`
> 修复后 HEAD：见文末 Commit 一节

## 1. 本轮范围

只处理合同第 4–9 节（S0-1、S0-2、S0-3、S1-1、S1-2、S1-3）与第 10 节 22 项绕过测试。
未扩展 P1 容量算法、动态时长、格式 profile、pip 打包、agents/openai.yaml、迁移器完善与 P2 平台能力。

## 2. 问题 → 修复 → 测试对照

| 问题 | 修改位置 | 新的确定性保证 | 对应测试 |
|---|---|---|---|
| S0-1 上下文/草稿/审核未同源绑定 | `context_builder.py`（不可变快照+pointer）、`state_store.py`、`project_cli.py`（草稿 meta、审核三哈希、重写绑定） | 快照按 `episode+context_hash` 独立保存；草稿记录 context_hash/draft_hash/集纲版本/事件版本；审核必须显式携带三哈希且与草稿绑定一致；重写只消费审核绑定的草稿版本；篡改快照哈希校验失败 | `test_round1_bypass.py` 01–05 |
| S0-2 版本历史是假历史 | `state_store.py` commit_artifact、CLI 全部产物保存改为不可变版本 | 每次修改写独立文件；manifest 记录 content_hash/status/source/created_at/parent_version/supersedes；相同内容幂等；两版定稿/审核可分别读取 | bypass 10–12 |
| S0-2 微批次集纲丢集 | `project_cli.py cmd_save_episode_outline` | 按集 upsert/merge，未出现集数保留；`--replace` 显式整表替换；输出新增/修改/未变/删除报告 | bypass 08–09 |
| S0-3 Host Agent 定稿无法形成语义连续性 | `continuity_manager.py`、`project_cli.py`（extract-continuity/save-continuity-delta）、`continuity-delta.schema.json` | 宿主 Agent 可提取结构化 delta（facts 带 fact_id/category/集数/定稿版本/剧本哈希/证据位置/状态）；每集记录 extraction mode 与完整度；降级集列入 degraded_episodes；从定稿+delta 幂等重建 | bypass 13 |
| S0-3 修改当前定稿集无当前定稿 | `context_builder.py` | episode 已有定稿时，context 注入 current_approved_script | bypass 14 |
| S1-1 检索漏锚点/拆散配对 | `source_retriever.py` 重写 | coverage ledger 逐项记录 requested/resolved/included/omitted；直接 event/chapter 锚点必须有摘录；setup/payoff 不可拆分；长章节强制摘录；预算不足自动提升后仍失败才报错；每段摘录带 excerpt_hash | bypass 15–17；unit test_source_retriever |
| S1-2 修改意见不进入后续创作 | `revision_manager.py`、`project_cli.py`（list/approve/reject/status/apply-revision）、`context_builder.py` | pending 在继续创作前显式提示；approve 进入上下文；reject 不进入；显式 affects_future=false 覆盖关键词推测；applied 记录草稿/定稿版本 | bypass 18–21 |
| S1-3 证据门禁只验证字符串非空 | `project_cli.py` 证据校验、`review-report.schema.json`、reviewer prompt、SKILL.md、review-rubric.md | error 必须携带可在绑定 context 中验证的结构化 evidence；quote/event_id/chapter/span/excerpt_hash/adaptation_decision_id 逐项验证；任意字符串拒绝；无证据 error 不自动降级；verdict 按最终有效 issues 重算 | bypass 06–07 |
| 自动重写无限循环 | `project_cli.py`（草稿 meta automatic_rewrite） | 自动重写产物再次自动重写被拒绝；人工修改后解除限制 | bypass 22 |

## 3. 数据契约变化

### artifact version（manifest.json 内）

每个版本新增/保证字段：`version`、`path`、`content_hash`、`status`、`source`、`created_at`、`parent_version`、`supersedes`、可选 `meta`。

### draft metadata（manifest `script_draft:<ep>` 的 version.meta）

`context_hash`、`draft_hash`、`episode_outline_version`、`source_events_version`、`automatic_rewrite`。

### review-report.schema.json

- 顶层新增必填：`context_hash`、`draft_hash`、`draft_version`；
- issue 新增 `evidence` 对象：`evidence_type`（source|adaptation）、`event_id`、`chapter_id`、`source_span`、`excerpt_hash`、`quote`、`adaptation_decision_id`。

### episode-context

新增：`context_versions`（episode_outline_version/source_events_version）、`current_approved_script`、`pending_revisions`；快照按 hash 独立文件 + `current_EP<NNN>.json` pointer。

### continuity-state

新增：`episode_extraction`（每集 mode/complete/script_hash/draft_version）、`degraded_episodes`；facts 记录 `fact_id`/`category`/`episode`/`draft_version`/`script_hash`/`evidence_location`/`status`/`recorded_at`。

### 新增 continuity-delta.schema.json

Host Agent / 模型结构化连续性提取契约（facts/character_knowledge/open_hooks/resolved_hooks/future_overrides）。

### source_evidence

- 每段摘录新增 `excerpt_hash`；
- 新增 `coverage` ledger（event/chapter/dependency/dialogue_anchor/must_keep/fallback 逐项状态）。

### 旧运行状态迁移说明

旧布局（artifacts/<kind>/<file>.json、单一路径）仍可被 active pointer 读取；但旧草稿缺少 meta、旧审核缺少三哈希，无法通过新门禁。迁移方式：重新 `save-draft`（自动生成 meta）并重新 `save-review`，或由工具标注 legacy 状态。项目 `projects/gaoleng-tonggan` 已按新契约重建上下文与草稿并通过真实 DeepSeek 审核（v005）。

## 4. 测试结果

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'        # 112 OK
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'   # 28 OK（含 22 项绕过测试）
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'        # 4 OK
PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'  # 旧基线 38：31/4F/3E（未修改旧代码）
```

真实模型验证（DeepSeek deepseek-v4-flash，项目 `projects/gaoleng-tonggan`）：
`check-api` OK；EP1 新契约下 `review --api` 成功保存审核报告 v005（warning，7 问题），结构化证据通过摘录校验。

## 5. 已知限制（本轮后仍存在）

- `must_keep` 与证据 quote 验证仍以原文文本匹配为准，模型输出的组合式引用需经归一化剥离前缀；跨模型仍需提示词约束；
- 连续性 delta 的语义质量依赖宿主 Agent/模型，系统只保证结构化、绑定与重建，不保证事实正确性；
- 旧版 38 项测试 4F/3E 未修（属旧基线）；
- P1/P2 与合同第 15 节“后续评审者已知的中等问题”全部未处理；
- 真实项目仍存在待编剧裁决项（EP2 时间线等），不属于本轮。

## 6. 独立评审者应尝试的绕过路径

1. 提交缺 context_hash / draft_hash / draft_version 的审核报告；
2. 用 H2 上下文审核 H1 草稿；用 v1 审核重写 v2；
3. 篡改上下文快照后继续 review/rewrite；
4. 证据填任意字符串、不存在的 event_id、不在摘录的 quote；
5. 单集/小批集纲保存后检查其他集是否消失；两版定稿/审核是否可分别读取；相同内容重复保存是否产生重复版本；
6. Host Agent 模式下通过 save-continuity-delta 让 EP1 事实进入 EP3 上下文；
7. pending revision 是否被显式提示；approve/reject 是否影响上下文；显式 affects_future=false 是否覆盖关键词；
8. 自动重写产物是否可无限重写。

## 7. 高风险文件（复审重点）

- `scripts/project_cli.py`（审核/重写绑定与证据校验）
- `scripts/context_builder.py`（快照/pointer/版本绑定）
- `scripts/state_store.py`（不可变版本与幂等）
- `scripts/source_retriever.py`（coverage ledger 与配对保护）
- `scripts/continuity_manager.py`（delta 生命周期与重建）
- `scripts/revision_manager.py`（状态机与 applied 记录）

## 8. Commit

- 修复前：`6707f24`（评审基线）
- 本轮提交：`eb59553`（Round1 fix 主提交）、`<handoff-commit>`（本交接文档提交）
