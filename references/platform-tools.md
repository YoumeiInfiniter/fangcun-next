# 跨平台工具映射

fangcun 技能中的工具引用在各平台的对应关系。技能主要使用 `Bash(python *)`，即执行 Python 脚本。

## Python 脚本执行

所有 fangcun SKILL.md 中的 pipeline 命令格式为：
```bash
python tools/pipeline.py --config {config} --phase {phase}
```

| 平台 | 执行方式 | 备注 |
|------|---------|------|
| **Claude Code** | `Bash(python *)` | 需 `allowed-tools: Bash(python *)` 声明 |
| **Codex** | 原生 shell | 直接执行 python 命令 |
| **Cursor** | 原生 shell | 直接执行 python 命令 |
| **OpenCode** | 原生 shell | 直接执行 python 命令 |
| **Gemini CLI** | `run_shell_command` | 工具名不同，功能相同 |
| **Copilot CLI** | 原生 shell | 直接执行 python 命令 |
| **自研框架** | cmd/shell executor | 需要 shell 执行能力 |

## 文件操作工具

| 操作 | Claude Code | Codex | OpenCode | Gemini CLI |
|------|-----------|-------|----------|------------|
| 读文件 | `Read` | 原生 file | 原生 file | `read_file` |
| 写文件 | `Write` | 原生 file | 原生 file | `write_file` |
| 编辑文件 | `Edit` | 原生 file | 原生 file | `replace` |
| 搜索内容 | `Grep` | `grep_search` | 原生 grep | `grep_search` |
| 文件匹配 | `Glob` | `glob` | 原生 glob | `glob` |

## 子任务/子代理

| 操作 | Claude Code | Codex | OpenCode | Gemini CLI |
|------|-----------|-------|----------|------------|
| 启动子代理 | `Agent` / `Task` | `spawn_agent` | `@mention` | 不支持（回退到单会话） |
| 任务列表 | `TodoWrite` / `TaskCreate` | `update_plan` | `todowrite` | `write_todos` |

## 技能加载

| 操作 | Claude Code | Codex | OpenCode | Gemini CLI |
|------|-----------|-------|----------|------------|
| 加载技能 | `Skill` 工具 | 原生 skill | 原生 `skill` | `activate_skill` |

## fangcun 特有工具需求

fangcun 技能的核心运行时需求：

1. **Python 3.10+** — 所有 pipeline 脚本
2. **Shell 执行** — 运行 `python tools/pipeline.py`
3. **文件读写** — 读取章节、保存产物

仅此三项。不需要浏览器、不需要网络搜索、不需要子代理。

## `allowed-tools` 等价声明

Claude Code 使用 `allowed-tools` 限制技能可用工具。其他平台的等价配置：

- **Claude Code**: `allowed-tools: Bash(python *)`
- **Codex**: 无需声明（原生支持 shell）
- **Cursor**: 无需声明（原生支持 shell）
- **OpenCode**: 无需声明（原生支持 shell）
- **Gemini CLI**: 无需声明

## 文件交付能力

各平台向用户交付文件内容的能力：

| 平台 | 文件交付方式 | 说明 |
|------|------------|------|
| **Claude Code** | `Read` 工具读取后展示 | agent 用 Read 读取报告文件，内容直接显示在对话中 |
| **Codex** | 告知绝对路径 | 用户手动打开文件 |
| **Cursor** | 告知绝对路径 | 用户可以点击路径在 IDE 中打开 |
| **OpenClaw / Clawdbot** | `send_file` 或消息附件 | 直接把文件发给用户 |
| **OpenCode** | 告知绝对路径 | 用户手动打开 |
| **Gemini CLI** | 告知绝对路径 | 用户手动打开 |

**原则**：能直接发送的平台直接发送；不能发送的平台必须输出完整的绝对路径，让用户能复制后打开。
