# Fangcun Next

Fangcun Next 是新版“小说转短剧剧本”Skill：以编剧为最终作者、AI 为可控创作助手的平台无关系统。本仓库本身就是新版 Skill 的源码与发布源。

> 仓库可见性建议：Private。迁移基线包含公司飞书资源标识、内部生产流程与小说/编剧案例材料；正式发布前使用 `build-package` 生成脱敏发布包，并不要将本仓库设为 Public。

## 开发入口

首次进入仓库按顺序阅读：

1. [`START_HERE.md`](START_HERE.md)
2. [`AGENTS.md`](AGENTS.md)
3. [`docs/specs/fangcun-next-design-spec.md`](docs/specs/fangcun-next-design-spec.md)

## 当前状态

新版核心已实现（见 `SKILL.md` 与 `scripts/`）：

- 数据契约：`references/schemas/`（11 份 JSON Schema）；
- 确定性运行时：原文归档与锚点检索、单集上下文构建、Prompt/Craft 路由、格式校验、连续性、修改请求、时长/容量预估、迁移、发布包；
- CLI：`python3 -m scripts.project_cli <command>`（或安装后 `fangcun`）；
- 测试：`tests/unit/`（新版确定性模块）、`tests/regression/`（EP001）、`tests/smoke/`（多题材）。

旧版代码保留在 `skills/`、`agents/`、`tools/` 与 `docs/legacy/`，作为迁移输入与兼容基线；新版发布包默认排除这些目录。

## 常用命令

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m scripts.project_cli build-package --out dist/fangcun-next-0.2.0.zip
```

完整工作流示例见 `SKILL.md` 的命令路由表。改编指引、故事大纲、集纲均采用“同源输入绑定 → AI 审核 → 编剧确认”门禁；未确认阶段不能进入下游。

## 安全

- 不执行真实飞书写入、不使用公司凭据；
- `projects/`、`_cache/`、`output/`、`logs/`、密钥、小说原文与内部调研不进发布包；
- 发布包生成时自动扫描私密内容，命中即拒绝。
