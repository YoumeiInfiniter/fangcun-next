# Fangcun Next v0.3.7 质量优先稳定化交接

## 状态

- 分支：`codex/fangcun-next-v0.3.7-quality-stabilization`
- 起始基线：`188d851 test: align v0.3.6 regression fixtures with semantic coverage guard`
- 当前状态：候选实现已完成开发自测，等待独立 Reviewer 复审；未合并 `main`、未推送远程。
- 两份启动合同文档保持原样：`0.3.7-fix-prompt.md`、`quality-gates-v0.3.7-design.md`。

## 已实施

1. 新增版本化、可执行且绑定 `capacity_forecast` / `episode_outline` 哈希的
   `capacity_plan`。medium/high 容量风险的新项目必须由编剧选择具体方案；
   旧 `capacity_decisions` 仅保持读取兼容。
2. 新增 Writer 专用 `episode_execution_brief`。Writer 不再直接消费完整
   `episode_contract`；Reviewer/Rewriter 与 Writer 仍由同一份不可变
   `episode_context` 快照派生。
3. 完全移除 0.3.6 `_contract_semantic_coverage_errors` 及其保存路径；exact
   quote、格式/结构、内部规划标签泄漏由确定性门禁处理，剧情落实交给逐 Beat
   Reviewer。
4. 新增草稿绑定的 `draft_quality`：记录 context/draft 版本与哈希、规则集和
   配置哈希；硬门禁与题材无关，旁白比例、短句、问句、概述动作等只产生
   risk signal。
5. Reviewer 报告增加 core beat 完整覆盖、八项质量维度和系统 risk signal
   完整性；warning 不自动重写，blocked 最多签发一次定向 rewrite ticket。
6. 新增默认三集 provisional batch context。批内草稿、审核和连续性标记为未确认；
   前集草稿变更会使后续临时记录失效，只有批次确认后才进入正式连续性。
7. CLI、Schema、Prompt 路由、发布包、README、工作流和 0.3.7 release notes
   已同步；公开回归夹具已迁移到新容量计划路径。

## 自测证据

使用 `/tmp/fangcun-next-v037-venv`（Python 3.12.13，`requests` 2.34.2）执行：

- unit：154 项，`OK`；
- regression：165 项，`OK`；
- smoke：4 项，`OK`；
- `compileall`：通过；
- 候选包：`/private/tmp/fangcun-next-0.3.7-candidate.zip`，86 个文件，版本
  `0.3.7`；已验证新增模块可从候选包导入，且不含 `tests/`、`docs/`、
  `projects/`、`memory/`、`tools/` 等私有目录。
- 起始提交 `188d851` 的只读基线（解包到临时 `/tmp`，未改当前工作树）：unit
  148、regression 165、smoke 4，均 `OK`。

测试没有调用真实模型/API；缺少 API 配置的路径按降级/诚实报错测试。没有执行
真实飞书写入、线上文档修改、全局部署、远程推送或 `main` 合并。

## 兼容与待复审

- 历史项目、旧草稿和旧容量决定保持可读；旧容量决定不会静默转换成新的
  `capacity_plan`。
- 0.3.7 新项目的 medium/high 容量确认必须提供已批准的 `capacity_plan` 版本，
  不能再用笼统的 `accept_current_plan` 作为新路径。
- 当前结果是开发模型自测，不是独立验收。下一步应由独立 Reviewer 使用隐藏
  题材、不同事件顺序和变体字段复审：Writer brief 隔离、逐 Beat 审核完整性、
  exact/semantic/legacy quote、批内失效传播和质量风险信号边界。
- 已只读复查旧证据目录
  `/Users/mac/Documents/ChatGPT/Fangcun测试/projects-0306/rc-houfu-diy`；其中的
  旧 `accept_current_plan` 记录及 EP8–EP10 草稿/审核未被覆盖，也未作为 0.3.7
  新计划直接复用。
