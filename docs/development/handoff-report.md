# Fangcun Next v0.1 开发交接报告

> 日期：2026-08-09；分支：`feature/fangcun-next-rebuild`
> 本文件是开发过程摘要，正式交付要求以最终消息为准。

## 完成的模块

### P0 集纲→剧本质量闭环

- 数据契约：`references/schemas/` 9 份 JSON Schema（project-config / source-event / episode-outline / episode-context / continuity-state / revision-request / review-report / capacity-forecast / project-manifest）；
- `scripts/schema_validate.py`：零第三方依赖的轻量校验；
- `scripts/state_store.py`：manifest + active_versions + 版本历史 + 幂等初始化；
- `scripts/source_ingest.py`：标题式拆章、原文归档、禁止平均分配；
- `scripts/source_retriever.py`：事件 ID → 章节 → 关键词 → 依赖 → 回退；句子边界吸附、引用完整、setup/payoff 不拆；
- `scripts/context_builder.py`：不可变 `episode_context` + context_hash + 完整性检查（无集纲/无证据硬阻断）；
- `scripts/prompt_router.py`：七层 Prompt 组装 + Craft 按需路由；
- `scripts/script_validator.py`：确定性格式校验 + 结构化解析；
- `scripts/format_renderer.py`：业务格式 ↔ XML 适配器；
- `scripts/revision_manager.py`：修改请求标准化与影响分析；
- `scripts/continuity_manager.py`：定稿 → 确定性/模型辅助提取，幂等重建；
- `scripts/duration_estimator.py`：口径分离、区间、永不阻断；
- `scripts/model_adapter.py`：Host Agent / API 双模式；
- `scripts/project_cli.py`：规格书 §21 全部命令面；
- `scripts/migration.py`、`scripts/release_builder.py`。

### P1

- `scripts/capacity_estimator.py`：区间/方案/置信度/假设，仅提示。

## 主要架构变化（vs 旧版）

| 维度 | 旧版 | 新版 |
|---|---|---|
| 原文证据 | 剧本阶段几乎接触不到原文；按章节平均采样 | 集纲锚点检索，事件/摘录/原句带 span 注入上下文 |
| 上下文 | Writer/Reviewer/Rewriter 各自拼装 | 同一不可变 episode_context，context_hash 校验 |
| Craft | 全量注入写作方法 | 按题材+功能+操作按需加载 |
| 格式 | 多份剧本格式并存，XML 与业务格式混用 | 唯一业务格式 default-cn，XML 仅适配器 |
| 时长 | 单一“每分钟字数” | 台词/动作/反应/转场分口径，仅提示 |
| 连续性 | 不更新或依赖 API | 定稿→确定性提取，无 API 明确降级 |
| 审核 | 格式校验冒充内容审核；审核看不到原文 | 同源审核，error 必须有证据，缺证据拒绝保存 |
| 飞书 | 创作核心直接耦合表结构/交付门禁 | 移出 Creative Core，仅保留 P2 适配接口 |

## 兼容与迁移

- 旧版代码保留在 `skills/`、`agents/`、`tools/`、`docs/legacy/`，未修改；
- 旧根 `SKILL.md` 归档至 `docs/legacy/root-docs/SKILL-v2.md`，新版入口重写；
- `migration.py` 支持旧 config / events.json / story_skeleton.md / scripts/ / continuity_state.json → 新版布局，只复制不删除，输出迁移报告；
- 旧版 `story_skeleton.md` 迁移后标记“需要编剧确认后重新生成结构化集纲 JSON”，不伪造已解析状态。

## 实际测试

环境：Python 3.12.13，本地 `.venv`，未调用真实模型 API，未执行飞书操作。

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
# Ran 96 tests OK
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
# Ran 6 tests OK
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
# Ran 4 tests OK
PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
# Ran 38 tests: 31 pass / 4 fail / 3 error（与 START_HERE 基线一致，未改动旧代码）
```

EP001 回归：buggy 版至少 4 项通用检查失败，fixed 版 6 项全部通过。

发布包：`build-package` 生成 `dist/fangcun-next-0.1.0.zip`（65 个文件），含私密内容扫描；解压后 CLI 可独立运行。

## 与规格书仍有差距的项目

1. 已用 DeepSeek（deepseek-v4-flash）完成 EP001 审核/重写小规模验证：buggy 草稿被判 blocked（7 个带原文证据的问题）→ 模型定向重写 v2 → 复审 pass。编剧真实评估（修改次数/人工重写比例指标）仍未做；
2. 人物声音卡尚未提供自动提取，仅有配置口子；
3. 飞书正文/评论读回、OpenClaw 子 Bot、Dashboard、Token 统计为 P2，未实现（符合规格书优先级）；
4. 旧版 38 项测试的 4 失败/3 报错未修复——它们属于旧版基线（过时测试与真实缺陷并存），新版已通过独立测试覆盖其真实缺陷场景；
5. `agents/openai.yaml` 为声明文件，未接入具体宿主插件打包。

## 建议 Review 的高风险文件

- `scripts/context_builder.py`：上下文契约核心，哈希与完整性逻辑；
- `scripts/source_retriever.py`：检索顺序、截断与引用完整性；
- `scripts/prompt_router.py`：Prompt 分层与 Craft 路由；
- `scripts/continuity_manager.py`：定稿事实提取与重建；
- `scripts/project_cli.py`：命令面与审核证据门禁；
- `scripts/release_builder.py`：发布包白名单与私密扫描。
