# Fangcun Next v0.3.2 发布说明

- 发布日期：2026-08-10
- 版本：0.3.2（pyproject / `scripts/__init__.py` / release builder / README 统一）
- 来源分支：`codex/fangcun-next-v0.3.0-agent-first`
- 合并范围：`276560e..e0a7faa`（4 个提交：±2s→±10s 容差收敛、draft metrics 扩展、Writer/Reviewer 时长规则、上游重绑确认继承 + 批量确认 + span 定位）+ 本轮清理/发布 commit
- 独立验收：unit 129 / regression 165 / smoke 4 全绿；隐藏变体 43/43 通过（时长容差、确认继承/原子性、locate-span 边界）

## 本版本功能

1. 时长建议（P0）：确定性口径（台词 150cpm + 动作行×2.5s + 反应×0.8s + 转场×1.2s），
   ±10s 容差内不判偏差；`advisory_only=true`、`blocking=false`；Writer 仅允许四种压缩
   手段，严禁为时长精简动作/表演描写；Reviewer 不得把超时判为 error。
2. 上游重绑确认继承（P1）：content_hash 完全相同时自动沿用旧确认并记录
   `carried_from` 审计；任一内容 hash/配置/项目实例变化仍强制过期；新增
   `confirm-stages` 批量确认与 `locate-span` 半自动原文坐标定位（0-based 左闭右开，
   找不到返回 `needs_reanchor`）。

## 清理与合并

- 旧版运行体系（`skills/`、`tools/`、`tests/drama/`、旧 `agents/*.md`、
  `memory/user-preferences.md`、飞书模板、`platform-tools.md`、`.cursor-plugin/`、
  `.codex/`、`.opencode/`、`.claude-plugin/`、`hooks/`、`gemini-extension.json`、
  `CLAUDE.md`、`GEMINI.md`）从活动仓库移除；
- `docs/legacy/`、`docs/superpowers/`、`docs/novel-to-drama-skill-intro.html` 与
  历轮修复合同/交接迁出到只读归档：
  `/Users/mac/Documents/ChatGPT/Fangcun分析/fangcun-next-legacy-archive/`；
- 迁移兼容层保留：`scripts/migration.py`、`assets/screenplay-templates/legacy-scriptitem.txt`
  与 legacy-scriptitem XML 适配、`continuity_manager` legacy delta pointer 回退、
  `legacy_unspecified` 旧项目数据兼容字段；
- 发布包仅含 `SKILL.md`、`agents/openai.yaml`、`scripts/`、`references/`、`assets/`、
  `pyproject.toml`。

## 已知边界（不阻塞发布）

- `confirm-stages` 的预检不包含集纲容量门禁，容量决定失败会发生在确认循环内
  （前面阶段审计记录已写）；自然流程下前面阶段通常已确认，状态不回归，建议 0.3.3
  把容量门禁并入预检。
- carried 集纲新版本的容量决定审计追溯为空，建议 0.3.3 回填关联。
- `locate-span` 对重复原句默认选第一次并输出 `matches` 计数，建议 CLI 增加重复告警。
- 直接改写底层状态文件仍可绕过审计（既有已接受限制，本轮未扩大）。
