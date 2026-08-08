# fangcun — 小说转短剧剧本改编引擎

基于 AI Agent 的小说转短剧剧本改编工具，提供从原文分析到剧本输出的完整 pipeline。

## 流程

```
事件提取 → 故事骨架 → 审核门控 → 改编策略 → 审核门控 → 剧本编写 → 导出
```

## 特性

- **完整 pipeline**：从章节事件提取到成品剧本，一键贯穿
- **强制审核门控**：骨架和策略阶段产出后自动审核（A/B/C/D 评分），D 级阻塞
- **情绪优先写作**：每个场景必须回答"让观众感受到什么"
- **多平台支持**：Claude Code / Codex / Cursor / OpenCode / Gemini CLI
- **纯标准库 Python**：仅需 `requests` 一个额外依赖

## 快速开始

### 安装

```bash
# Claude Code
cp -r fangcun ~/.claude/skills/

# Codex
ln -s $(pwd)/skills ~/.agents/skills/fangcun
```

### 使用

```
把这本书改成短剧
提取事件
生成骨架
写前10集剧本
看看审核报告
```

## 项目结构

```
fangcun/
├── SKILL.md                  ← 入口技能
├── skills/drama/             ← 短剧剧本引擎
│   ├── SKILL.md
│   ├── prompts/              ← 7 个阶段 prompt
│   └── tools/                ← Python 工具链
│       ├── pipeline.py       ← 主 pipeline
│       ├── agent_tools.py    ← I/O 工具
│       └── lib/api_client.py ← API 客户端
├── agents/                   ← 6 个子代理定义
│   ├── drama-director.md     ← 决策层
│   ├── quality-supervisor.md ← 监督层
│   ├── skeleton-builder.md   ← 执行层
│   ├── adaptation-strategist.md
│   ├── script-writer.md
│   └── event-extractor.md
└── hooks/                    ← 自动激活检测
```

## 运行时要求

- Python 3.10+
- `requests` 库
- 兼容 OpenAI 接口的 LLM API（如 DeepSeek）

## API 配置

API 凭据按以下优先级自动解析：

1. 环境变量：`API_KEY` / `API_BASE_URL`
2. 项目配置：`config.json` 中的 `api_key` / `api_base_url` / `model`
3. OpenClaw：`~/.openclaw/openclaw.json` 中的 `deepseek` 或 `openai-completions` provider

pipeline 启动后会先做 API 连接预检，失败时会在进入耗时阶段前给出配置提示。

## 子代理层级

```
drama-director（决策层，唯一与用户对接）
    ├── quality-supervisor（监督层：A/B/C/D 评分审核）
    └── 执行层：
        ├── event-extractor → 事件表
        ├── skeleton-builder → 故事骨架
        ├── adaptation-strategist → 改编策略
        └── script-writer → 剧本
```

## 许可证

MIT

## Script Draft Quality Gate

The script stage now generates episodes serially into `drafts/`, runs AI review per episode, performs one targeted rewrite for severe issues, and waits for writer confirmation before copying drafts into `scripts/`.

Useful commands:

```bash
python tools/pipeline.py --config {config} --phase script --start 1 --end 5 --batch-size 5
python tools/pipeline.py --config {config} --review-draft --episode 3
python tools/pipeline.py --config {config} --rewrite-draft --episode 3
python tools/pipeline.py --config {config} --confirm-draft-batch
```

Re-running `--phase script` resumes the active draft batch and reviews existing drafts without overwriting manual edits. `--rewrite-draft --episode N` rewrites only the selected episode and archives the previous draft under `drafts/batch_XXX/rewrites/`.

Example requests:

```text
write the first 5 draft episodes
confirm the current draft batch
rewrite draft episode 3
```

## OpenClaw Manual Workflow Requirements

OpenClaw does not rely on SessionStart hooks for this skill. Use `skills/drama/tools/pipeline.py` directly.

Before the first run, collect project intake from the user: `novel_name`, `drama_name`, chapter directory, output directory, episodes, episode duration, chapter range, platform, style, and paywall strategy. The pipeline validates these fields and stops when they are missing.

After AI review, human confirmation is mandatory before the next stage:

```bash
python tools/pipeline.py --config {config} --phase review --review-target skeleton
# send/read reviews/skeleton_review.md, collect human approval
python tools/pipeline.py --config {config} --confirm-review --review-target skeleton

python tools/pipeline.py --config {config} --phase review --review-target adaptation
# send/read reviews/adaptation_review.md, collect human approval
python tools/pipeline.py --config {config} --confirm-review --review-target adaptation
```

Every phase prints output paths. In OpenClaw, send those files to the user when possible; otherwise provide the absolute paths.
