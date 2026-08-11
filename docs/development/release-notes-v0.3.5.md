# Fangcun Next v0.3.5 发布说明

- 发布日期：2026-08-11
- 版本：0.3.5（pyproject / `scripts/__init__.py` / release builder / README / START_HERE 统一）
- 来源分支：`main`（基于 `e640ef9` = v0.3.4 之后）
- 独立验收：unit 147 / smoke 4，无回归

## 本版本新增：转场桥接机制

删除/压缩中间事件或节拍后，剧本可能出现前后不连贯、切换生硬。本版本新增三层机制：

1. **Writer 补桥义务**（`references/prompts/writer.md`）
   - 执行集纲删除/压缩/合并后，必须用过渡动作行 / OS 承接句 / △转场把前后接上；
   - 补桥依据优先级：还原原文衔接 → 服从事件依赖链与人物认知状态 → 无原文的有限过桥
     （不新增剧情、不改动机、不改事件结果）；
   - 交付"转场桥接说明"时标注依据类型 `source`（还原原文）或 `adaptation`（有限补足）。

2. **Runtime 跳切检测**（`scripts/script_validator.py` + `save-draft`）
   - 相邻场景地点/时间跳变 + 上一场景以台词收尾 + 下一场景以台词开场 + 无转场标识
     → 输出 advisory `scene_jump_needs_bridge` 提示（不阻断保存）；
   - 语义级生硬（如场景跳变但动作收尾）不在此规则覆盖内，由 Writer 补桥义务
     与 Reviewer transition 维度兜底。

3. **Review transition 维度**（`references/schemas/review-report.schema.json`、
   `references/review-rubric.md`、`references/prompts/reviewer.md`）
   - category 新增 `transition`；
   - 压缩后无桥导致观感跳切 → warning；补桥断裂因果或改变事件结果 → error。

## 已知边界（沿用决策）

- 确定性跳切检测只覆盖"台词接台词 + 地点/时间跳变 + 无转场"的强模式；
  语义级生硬依赖 Writer 义务与 Reviewer 把关，不保证 100% 拦截。
