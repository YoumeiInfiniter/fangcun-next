---
name: supervision
description: |
  短剧剧本质控审核技能。独立于创作管线，可审核任意阶段的产出物。
  输入：目标阶段的产出文件 + 审核维度配置
  输出：审核报告（A/B/C/D 评分 + 问题清单）
  被 drama 技能在每个阶段产出后调用。
allowed-tools: Bash(python *)
---

# fangcun-supervision：质控审核

独立技能，可由 drama 管线调用，也可单独审核任意一个阶段的产出。

## 核心任务

```
阶段产出物 + 审核维度 → 审核报告（评分 + 问题清单）
```

## 调用方式

**drama 管线内部调用**：
```bash
python tools/pipeline.py --config configs/drama_xxx.json --phase review --review-target adaptation|story_outline|skeleton|script
```

**单独审核某个产出**：
```bash
# 直接传入要审核的文件和阶段
python tools/pipeline.py --config configs/drama_xxx.json --phase review --review-target skeleton
```

## 审核维度（按阶段）

| 阶段 | 审核维度 |
|------|---------|
| 改编指引 | 改编方向落实、人物改编自洽、删减合理、世界观完整 |
| 故事大纲 | 结构完整、核心矛盾、卖点矩阵、情绪曲线、与指引一致 |
| 集纲 | 分集与时长、付费点分布、矛盾强度、密度结构、节奏框架 |
| 剧本 | 合规审核6大类 + **平台过审红线**（见 `references/platform_guidelines.md`）|

## 平台过审红线

剧本审核时同步检查平台过审红线（来源：短剧创作者中心内容创作建议）。
红线不阻断创作流程，仅以 ⚠️ 标记提示编剧自查。

**自动同步**：
```bash
# 检查是否有更新（轻量，只查元数据，不需要飞书认证）
python scripts/fetch_guidelines.py --check

# 拉取最新指南（全量同步正文，需要飞书凭证）
python scripts/fetch_guidelines.py
```

脚本自动从飞书凭据获取 tenant_access_token，调用文档 API 拉取完整正文。
凭据来源（按优先级）：`FEISHU_APP_ID` / `FEISHU_APP_SECRET` 环境变量 → `~/.openclaw/openclaw.json`。

平台指南更新频繁，建议每次批量出剧本前 `--check` 一次。

缓存文件：
- `references/guidelines_real.md`：真人版完整指南正文（含同步时间戳）
- `references/guidelines_animation.md`：动画版完整指南正文（含同步时间戳）
- `references/platform_guidelines.md`：七大类红线速查表（人工提炼）

## 门控规则

- 🔴 D 评分 / ≥1 严重问题 → 阻塞，必须修复
- 🟡 C 评分 / ≥3 中等问题 → 警告，建议修复
- 🟢 A/B 评分 / 无严重问题 → 通过

## 产出文件

- `_review/{phase}_review.md`：审核报告
