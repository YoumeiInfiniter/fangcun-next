# Fangcun Next 开发接手入口

## 1. 当前状态

本仓库已经完成 Fangcun Next 的独立核心重构。新版运行入口是根目录 `SKILL.md`、`scripts/`、`references/`、`assets/` 与 `agents/openai.yaml`；旧版运行体系已迁出到只读归档目录（见 `docs/development/release-notes-v0.3.2.md`），不进入默认发布包。

当前处于本地技术验收与小规模质量测试阶段：

- 改编指引、故事大纲、集纲具备输入哈希绑定、AI 审核和编剧确认状态机；
- 集纲到剧本具备锚点检索、同源审核、版本、重写凭证和连续性闭环；
- 容量/时长为编剧决策辅助，不是自动回退门禁；
- 仍不得直接接入生产 OpenClaw 或执行真实飞书操作；通过真实案例后再进入 P2 平台适配。

## 2. 首次接手必须执行

1. 完整阅读根目录 `AGENTS.md`；
2. 完整阅读 `docs/specs/fangcun-next-design-spec.md`；
3. 检查当前仓库结构、入口、测试和实际运行路径；
4. 对照规格书列出保留、重构、废弃和新增模块；
5. 先运行新版 unit、round1–round5 regression、smoke 和发布包验证；
6. 修改必须优先修复可复现问题，不提前堆叠飞书、Token 统计或主 Bot 管理功能。

若规格书较长，应分段读取直到文件末尾，不能只依赖开头摘要或搜索片段。

## 3. 建议发送给开发 Agent 的首条消息

```text
这是 Fangcun Next 的独立开发仓库。

请先完整阅读 START_HERE.md、AGENTS.md 和
docs/specs/fangcun-next-design-spec.md，将规格书视为新版产品与架构基线。

旧版代码用于分析、兼容和迁移；docs/research 只提供问题证据，
不能把某个案例的具体写法升级为所有题材的硬规则。

开始编码前先输出：
1. 对新版目标和不可改变决策的理解；
2. 当前代码与规格书的主要差距；
3. 保留、重构、废弃和新增模块；
4. 分阶段开发计划；
5. 第一阶段修改文件清单；
6. 测试、迁移与回退方案。

首轮只实施规格书 P0：集纲到剧本的质量闭环。
不要执行飞书写入，不要修改生产版本。
```

## 4. 文档优先级

发生冲突时按以下顺序处理：

1. 当前用户明确要求；
2. `docs/specs/fangcun-next-design-spec.md`；
3. `AGENTS.md`；
4. 已通过的新版自动化测试和数据 Schema；
5. 旧版归档（只读）与旧版 `SKILL.md`（Git 历史）；
6. `docs/research/` 中的调研证据；
7. 旧版运行体系的历史说明（已归档，按需经 Git 历史追溯）。

不能静默解决规格书内部的真实业务冲突。发现冲突时，应给出文件位置、两种解释及影响，并请求业务方决定。

## 5. 研究材料的读取时机

- 分析 EP001 台词、因果和格式问题时，读取 `docs/research/ep001-three-way-diagnosis.md`；
- 分析生产效率和编剧使用方式时，读取 `docs/research/current-problems-and-production-impact.md`；
- 需要验证问题是否跨案例存在时，读取 `docs/research/four-case-root-cause-analysis.md`；
- 分析旧架构与污染来源时，读取 `docs/research/legacy-architecture-analysis.md`；
- 设计审核、重写和质量门禁时，读取 `docs/research/quality-root-causes-and-options.md`。

研究材料按需读取，不需要在每次任务中全量注入。

## 6. 测试基线

当前测试基线（2026-08-10 独立验收复现）：

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
```

- unit 129 / regression 165 / smoke 4 全绿；隐藏变体 43/43 通过（时长容差、确认继承与批量确认、locate-span 边界）；
- 旧版 38 项测试基线随旧运行时一并迁出归档，由 Git 历史追溯；
- 发布包构建：`build-package --out dist/fangcun-next-0.3.2.zip`。

既有失败基线不再作为活动仓库测试入口；新增或修改必须保持 unit/regression/smoke 无新增失败。
