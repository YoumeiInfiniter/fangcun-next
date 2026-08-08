# Installing fangcun — 通用安装指南

fangcun 是一个跨平台的 AI Agent 技能，提供小说转短剧剧本改编引擎。

## 目录结构

```
fangcun/
├── SKILL.md              ← 入口技能
├── skills/
│   └── drama/            ← 短剧剧本引擎
│       ├── SKILL.md
│       ├── prompts/
│       └── tools/        ← Python 工具
├── agents/               ← 子代理定义
├── references/
│   └── platform-tools.md ← 跨平台工具映射
└── INSTALL.md            ← 本文件
```

## 平台安装方式

| 平台 | 安装方式 | 详见 |
|------|---------|------|
| **Claude Code** | `/plugin` 安装或放入 `~/.claude/skills/` | `.claude-plugin/plugin.json` |
| **Codex** | symlink 到 `~/.agents/skills/fangcun` | `.codex/INSTALL.md` |
| **Cursor** | `/add-plugin` 安装 | `.cursor-plugin/plugin.json` |
| **OpenCode** | 添加 plugin 到 `opencode.json` | `.opencode/INSTALL.md` |
| **Gemini CLI** | `gemini-extension.json` + GEMINI.md | `GEMINI.md` |

## 运行时要求

- Python 3.10+
- `requests` 库（HTTP 请求），其余为标准库
- Shell 执行能力
- 文件读写能力
- API：兼容 OpenAI 接口格式的 LLM API（如 DeepSeek）

## API 凭据解析

fangcun 会按顺序读取：

1. 环境变量 `API_KEY` / `API_BASE_URL`
2. 配置文件中的 `api_key` / `api_base_url`
3. OpenClaw 的 `~/.openclaw/openclaw.json`，优先 `models.providers.deepseek`，其次任一 `api=openai-completions` 的 provider

如果需要指定模型，在配置文件里设置 `model` 或 `model_overrides`；否则会优先使用 OpenClaw provider 中的第一个模型。
