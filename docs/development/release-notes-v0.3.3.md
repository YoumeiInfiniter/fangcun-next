# Fangcun Next v0.3.3 发布说明

- 发布日期：2026-08-10
- 版本：0.3.3（pyproject / `scripts/__init__.py` / release builder / README 统一）
- 来源分支：`codex/fangcun-next-v0.3.3`（基于 main `cdfecdf` = v0.3.2）
- 独立验收：unit 139 / regression 165 / smoke 4（v0.3.2 为 129/165/4，新增 10 项 span 定位测试）

## 本版本修复（P2-3：事件提取定位返工）

`locate-span` 不再静默选择错误位置：

- 原文片段重复出现且未显式指定 `--occurrence` 时，返回
  `reason: "ambiguous_occurrence"` + `suggest: "needs_reanchor"`，
  并提示用 `--occurrence N` 或更长/更独特的片段，避免事件锚定到错误坐标
  引发上游 v002 重绑与提取返工；
- 显式 `--occurrence N` 仍可选中第 N 次（唯一文本、找不到、空输入行为不变）；
- 修正 fuzzy 弱匹配下 `matches` 计数（按归一化文本计算，不再用精确计数）；
- `--occurrence` 未传时 CLI 启用歧义保护，函数层 `unique_required=False`
  保持向后兼容。

涉及文件：`scripts/span_locator.py`、`scripts/project_cli.py`、
`references/prompts/stage_events.md`、`SKILL.md`、
`tests/unit/test_span_locator.py`（新增 10 项）。

## 已知边界（沿用 v0.3.2 决策，本轮未扩大）

- `confirm-stages` 预检不包含集纲容量门禁（P2-1）：自然语言工作流中，
  编剧确认与容量决定经由 `confirm-stage`/`confirm-stages` 一次完成，不会
  触发"前面已确认、后面失败"的中间态；按编剧决定本轮不修。
- carried 集纲新版本的容量决定审计追溯为空（P2-2）：同属底层工程审计细节，
  自然语言交互不可达，按编剧决定本轮不修。
- 直接改写底层状态文件仍可绕过审计（既有已接受限制）。
