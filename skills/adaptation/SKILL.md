---
name: adaptation
description: |
  短剧改编指引生成技能。基于原文事件表和用户改编idea，生成改编蓝图（不是"怎么删"，而是"改成什么样"）。
  输入：原文事件表 (events.json) + 用户改编idea
  输出：改编指引 (adaptation_strategy.md)
  被 drama 技能在第一轮调用。
allowed-tools: Bash(python *)
---

# fangcun-adaptation：改编指引生成

独立技能，可由 drama 管线调用，也可单独使用。

## 核心任务

```
原文事件表 + 用户改编idea → 改编指引
```

## 输入

- **原文事件表** (`events.json`)：从原文提取的事件序列
- **用户改编idea**：从项目配置的 `adaptation_idea` 或 `style` 字段读取
  - 如"女主变女帝，男主变落难士族公子""性别互换""视角切换"

## 产出

- `adaptation_strategy.md`：改编指引文件，包含：
  - 核心改编设定（新身份、新世界观）
  - 人物改编表
  - 删减决策
  - 世界观重构
  - 改编原则

## 调用方式

**drama 管线内部调用**：
```bash
python tools/pipeline.py --config configs/drama_xxx.json --phase adaptation
```

**单独调用**（在项目目录下）：
```bash
python /path/to/drama/tools/pipeline.py --config configs/drama_xxx.json --phase adaptation --skip-review-gate
```

## 注意

改编指引是**第一轮创作产出**，为后续的故事大纲和集纲提供蓝图。
不越权执行其他阶段。
