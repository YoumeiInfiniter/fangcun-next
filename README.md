# Fangcun Next

Fangcun Next 是新版“小说转短剧剧本”Skill：以编剧为最终作者、AI 为可控创作助手的平台无关系统。本仓库本身就是新版 Skill 的源码与发布源。

> 发布安全：正式部署请优先使用 GitHub Release 中由 `build-package` 生成并经过内容扫描的 Skill ZIP。小说原文、项目产物、密钥、本地配置与内部调研材料不得提交到仓库或发布包。

## 最新稳定版

当前正式版本为 **Fangcun Next 0.3.7**：

- [v0.3.7 Release 与发布说明](https://github.com/YoumeiInfiniter/fangcun-next/releases/tag/v0.3.7)
- [直接下载可部署 Skill ZIP](https://github.com/YoumeiInfiniter/fangcun-next/releases/download/v0.3.7/fangcun-next-0.3.7-skill.zip)
- SHA-256：`203d75061d025ed923979ae0d0ac5e0595b066a7597de1bdbad4473b10cd3271`

压缩包顶层目录为 `fangcun-next/`。新安装可直接解压到 `~/.codex/skills/`；升级时应先备份旧的
`~/.codex/skills/fangcun-next/`，再解压新包，避免旧文件残留。需要 CLI 时，在 Python 3.10+
虚拟环境中执行：

```bash
python -m pip install -e ~/.codex/skills/fangcun-next
fangcun --version
```

GitHub 自动生成的 “Source code” 压缩包是仓库快照，不是部署包；请使用 Release 附件
`fangcun-next-0.3.7-skill.zip`。

## 开发入口

首次进入仓库按顺序阅读：

1. [`START_HERE.md`](START_HERE.md)
2. [`AGENTS.md`](AGENTS.md)
3. [`docs/specs/fangcun-next-design-spec.md`](docs/specs/fangcun-next-design-spec.md)

## 当前状态

新版核心已实现（见 `SKILL.md` 与 `scripts/`，当前正式版本 0.3.7）：

- 数据契约：`references/schemas/`（14 份 JSON Schema）；
- 确定性运行时：原文归档与锚点检索、版本化容量取舍、单集执行 brief、草稿质量信号、逐 Beat 审核门禁、临时批次连续性、Prompt/Craft 路由、格式校验、连续性、修改请求、时长预估、迁移、发布包；
- CLI：`python3 -m scripts.project_cli <command>`（或安装后 `fangcun`）；
- 测试：`tests/unit/`（新版确定性模块）、`tests/regression/`（EP001 + 公开案例 + v0.3.7 隐藏变体回归）、`tests/smoke/`（多题材）。
- v0.3.7 发布验证：unit 155、regression 170、smoke 4，全部通过；正式 Skill ZIP 已完成全新解压、editable install、Schema、Prompt 与初始化验证。
- 流程：Host Agent Mode 为默认正式路径；标准单集 Writer 1 + Reviewer 1，快速草稿
  `--workflow-mode quick_draft` 只有 Writer 1；API Mode 为显式实验性路径。
- 飞书群聊交付：阶段验收产物落盘后默认输出 `FANGCUN_FEISHU_SYNC_EVENT`，由 Host Agent 使用一等 `feishu_doc` 工具创建版本化飞书文档、写入并读回校验、登记 registry 后回链并停止等待确认。

旧版运行体系（`skills/`、`tools/`、旧 `agents/*.md`、`tests/drama/`、`docs/legacy|superpowers` 等）已迁出到只读归档目录，不参与新版运行；迁移兼容层（`scripts/migration.py`、legacy-scriptitem XML 适配、legacy delta 回退、`legacy_unspecified` 字段）仍保留在 `scripts/` 与 `assets/` 中。发布包只包含正式 Skill 内容。

## 常用命令

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m scripts.project_cli build-package --out dist/fangcun-next-0.3.7.zip
```

完整工作流示例见 `SKILL.md` 的命令路由表。编剧只需用自然语言提出需求、确认或修改，Host Agent
代办结构化 JSON/CLI；改编指引、故事大纲、集纲均采用“同源输入绑定 → AI 审核 → 编剧确认”门禁，
单集 Reviewer 还必须逐 beat、逐维度、逐条 required quote 输出可保存检查；未确认或 stale 阶段不能进入下游。

## 安全

- 飞书群聊中的 Fangcun 产物交付属于已授权的平台适配；当 CLI 输出有效 `FANGCUN_FEISHU_SYNC_EVENT` 时，Host Agent 可用 `feishu_doc` 创建/写入/读回校验版本化文档并登记 registry；除此之外，不执行未请求的线上文档修改、不使用公司凭据、不向未指定目标写入；
- `projects/`、`_cache/`、`output/`、`logs/`、密钥、小说原文与内部调研不进发布包；
- 发布包生成时自动扫描私密内容，命中即拒绝。
