# Fangcun Next v0.3.4 发布说明

- 发布日期：2026-08-10
- 版本：0.3.4（pyproject / `scripts/__init__.py` / release builder / README 统一）
- 来源分支：`codex/fangcun-next-v0.3.4`（基于 main `8da4d61` = v0.3.3）
- 独立验收：unit 143（139+4）/ regression 165 / smoke 4；隐藏变体 46/46

## 本版本修复

### P2-1：批量确认预检补齐容量门禁（原子性）

`confirm_stages` 之前只在确认循环内检查集纲容量决定，缺/非法 `--capacity-decision`
会在前面阶段已写入审计记录后才失败。现在把容量门禁并入统一预检（与
`confirm_stage` 共用同一 `_capacity_gate_for` 规则），预检全部通过才会进入确认
循环——缺/非法容量决定在**任何阶段写入之前**整体拒绝，不再产生"前面已确认、
后面失败"的部分提交。

涉及：`scripts/stage_lifecycle.py`（`_capacity_gate_for`、`confirm_stage`、
`confirm_stages`）、`tests/unit/test_stage_gates.py`（3 项）。

### P2-2：carried 集纲容量决定审计回填

上游内容一字未变（content_hash 相同）触发自动沿用确认时，旧版本已记录的
容量决定现在会回填到新版本（`capacity_decisions.jsonl` 新增一行并标注
`carried_from_version`），按 (新版本, 新 hash) 审计可追溯，不再落空。

涉及：`scripts/stage_lifecycle.py`（`_carry_forward_confirmation`）、
`tests/unit/test_stage_gates.py`（1 项）。

## 已知边界（沿用决策，本轮未扩大）

- 直接改写底层状态文件仍可绕过审计（既有已接受限制）。
