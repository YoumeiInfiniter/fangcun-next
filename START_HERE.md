# Fangcun Next 开发接手入口

## 1. 当前状态

本仓库已经完成 Fangcun Next 的独立核心重构。新版运行入口是根目录 `SKILL.md`、`scripts/`、`references/`；`skills/`、`agents/`、`tools/` 与 `docs/legacy/` 仅是旧版迁移基线，不进入默认发布包。

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
5. 旧版代码与旧版 `SKILL.md`；
6. `docs/research/` 中的调研证据；
7. `docs/legacy/` 中的历史说明。

不能静默解决规格书内部的真实业务冲突。发现冲突时，应给出文件位置、两种解释及影响，并请求业务方决定。

## 5. 研究材料的读取时机

- 分析 EP001 台词、因果和格式问题时，读取 `docs/research/ep001-three-way-diagnosis.md`；
- 分析生产效率和编剧使用方式时，读取 `docs/research/current-problems-and-production-impact.md`；
- 需要验证问题是否跨案例存在时，读取 `docs/research/four-case-root-cause-analysis.md`；
- 分析旧架构与污染来源时，读取 `docs/research/legacy-architecture-analysis.md`；
- 设计审核、重写和质量门禁时，读取 `docs/research/quality-root-causes-and-options.md`。

研究材料按需读取，不需要在每次任务中全量注入。

## 6. 旧版测试基线

验证日期：2026-08-09。

验证环境：Python 3.12，本地 `.venv`，安装 `requirements.txt`；未调用真实模型 API，未执行飞书操作。

执行命令：

```bash
PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m compileall -q skills tools tests
PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

结果：

- Python 编译通过；
- 共运行 38 项测试；
- 31 项通过；
- 4 项失败；
- 3 项报错。

既有失败主要分为：

1. 测试剧本样本重复使用同一场次编号和 scene key，被当前场次门禁拦截；
2. 剧本生成测试样本缺少当前 Validator 要求的规范分集标识；
3. 可移植性测试会把旧代码注释中的 OpenClaw 示例路径判为违规；
4. 旧 Prompt 测试期待一句已经不存在的 Toonflow 确认文案；
5. 一项审核阻断测试读取不到预期的 `episode_reviews["1"]` 状态。

这些问题存在于复制进来的旧版基线中。本次仓库初始化不修复业务代码；开发 Agent 应先把失败分类为“过时测试”“真实缺陷”或“新版将废弃行为”，再根据规格书处理，不能为了全绿简单删除测试。
