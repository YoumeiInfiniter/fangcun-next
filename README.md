# Fangcun Next

Fangcun Next 是新版“小说转短剧剧本”Skill 的独立重构仓库。

> **仓库可见性建议：Private。** 当前迁移基线包含公司飞书资源标识、内部生产流程以及小说/编剧案例材料。仓库未包含真实 API 密钥，但在完成专门的脱敏与版权材料剥离前，不建议设为 Public。

当前仓库处于**设计基线与旧版迁移起点**，不是已经完成的新版本，也不应直接替换生产环境中的 Fangcun。

## 开发入口

无论使用 Codex、Claude Code、Cursor、Gemini CLI、OpenClaw Agent 或其他开发 Agent，首次进入仓库都应按以下顺序阅读：

1. [`START_HERE.md`](START_HERE.md)
2. [`AGENTS.md`](AGENTS.md)
3. [`docs/specs/fangcun-next-design-spec.md`](docs/specs/fangcun-next-design-spec.md)

完整规格书是新版产品和架构的最高设计基线。旧版代码、旧版说明和调研报告用于理解现状、兼容与迁移，不得覆盖已经确认的新设计决策。

## 当前内容

```text
fangcun-next/
├── START_HERE.md                 # 新 Agent 首次接手入口
├── AGENTS.md                     # 仓库级开发约束
├── SKILL.md                      # 旧版 Skill 入口，等待按规格书重构
├── docs/
│   ├── specs/                    # 新版规范性设计
│   ├── research/                 # 问题证据与案例调研，按需读取
│   └── legacy/                   # 旧版说明，兼容和迁移参考
├── skills/                       # 旧版子 Skill 基线
├── agents/                       # 旧版 Agent 定义基线
├── tools/                        # 旧版仓库工具
└── tests/                        # 旧版测试基线
```

## 本地开发环境

当前旧版代码至少需要 Python 3.10；基线验证使用 Python 3.12：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

`.venv/` 和运行缓存已被 Git 忽略。

## 新版首轮重点

- 保留当前反馈较少的改编指引与故事大纲能力；
- 优先重构“集纲 → 剧本 → 审核 → 定向重写 → 编剧定稿 → 后续连续性”；
- 修复偏离原文、台词断裂、因果缺失和剧本不落实集纲的问题；
- 保留内容容量与时长估算，但只作为编剧决策建议；
- 编剧确认的最新剧本成为已发生剧情的最高事实来源；
- 创作核心保持 Agent、模型、OpenClaw 和飞书平台无关。

## 安全边界

- 默认只在本地测试，不执行真实飞书写入；
- 不提交小说原文、项目运行产物、API 密钥或公司凭据；
- 不直接修改或替换生产中的旧 Fangcun；
- 完成规格书中的 P0 验收后，才进入小规模真实项目测试。

旧版基线目前不是全绿状态。具体结果见 `START_HERE.md` 的“旧版测试基线”，开发 Agent 不得把这些既有失败误报为新版修改引入的回归。
