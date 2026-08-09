# Fangcun Next 第二轮修复交接（Round 2 Fix Handoff）

> 依据：`docs/development/independent-review-round2-fix-brief.md`
> 第二轮起点：`090848f700839d3b087d520a971e2c6d4b402ddd`
> 本轮目标：关闭剩余 P0 确定性漏洞

## 1. 本轮范围

实现合同第 3–18 节：审核 verdict/证据/文件完整性、连续性无污染重建、Host Agent rewrite ticket、逻辑版本与恢复、配对与 must_keep 可追溯、revision 状态机、context 不可变、业务格式与 XML 分离，以及第 13 节 50 条反例测试。未扩展 P1/P2、创作 Prompt 风格、容量算法、打包与 agents 元数据。

## 2. 问题 → 修复 → 测试对照

| 问题 | 修改位置 | 确定性保证 | 测试（round2 编号） |
|---|---|---|---|
| verdict 可被模型覆盖 | project_cli `_derive_verdict` / `_normalize_review_report` | verdict 只由有效 issues 推导；模型 verdict 存 model_verdict；非法 issue 拒绝报告 | 01–02, 10 |
| 无效/拼装 source span | project_cli `_validate_issue_evidence` | span 必须 0<=start<end；所有字段指向同一摘录；event_id 必须是该事件自身摘录 | 03–07 |
| 保存后审核文件被篡改仍可重写 | project_cli `_validate_review_for_consumption` | 消费前重算 content hash、重校验 schema/绑定/证据/verdict | 08–09 |
| 连续性浅拷贝污染/旧事实残留 | continuity_manager `_fresh_continuity` | 每次全新对象；只读当前有效定稿；替换定稿后旧事实消失 | 11–13, 18 |
| delta 按字典序选择/无完整度标记 | continuity_manager pointer + degraded | delta 有逻辑指针（episode+script_hash），只消费当前有效版；complete=false 进 degraded | 15, 17 |
| fact 字段缺失 | continuity-delta/state schema | fact_id/category/fact/evidence_location 必填非空 | 16 |
| 恢复定稿不能恢复事实 | state_store `activate_version` + CLI | 版本恢复校验哈希并触发连续性重建 | 14, 27–29 |
| Host Agent 重写可伪装人工稿 | rewrite_ticket.py + save-draft/rewrite | 系统签发一次性 ticket，全绑定；消费标记 origin=automatic_rewrite；二次自动重写拒绝 | 19–24 |
| 同文本跨上下文复用旧逻辑版本 | state_store `commit_artifact` | 幂等键=内容+输入指纹+来源+父版本；active pointer 指向逻辑版本 | 25–26 |
| 新 revision 被重存旧内容误标 applied | revision_manager + save-draft/approve | 只对显式 revision_ids 且仅新版本 created 时绑定 applied | 30, 42–43 |
| 配对只有一端/事件摘要冒充原文 | source_retriever `_pair_span`/coverage | 两端必须真实存在于同一章；must_keep 只能由原文摘录或有效 adaptation decision 满足；无 span 事件标记 needs_reanchor | 31–37 |
| revision 状态双源/撤销不传播 | revision_manager 事件日志投影 + context_builder | 单一事实源（revisions.jsonl 投影）；approved→rejected/revoked 立即停止传播；applied 撤销保留审计 | 38–41 |
| context 快照含 role/可被篡改 | context_builder | 快照只含语义字段+hash；role/completeness 不入快照；同 hash 路径字节不一致硬阻断；消费端重算 hash | 44–46 |
| legacy XML 进入内部正文 | project-config schema + format_renderer + CLI | 内部一律 default-cn；transport_format 分离；旧 XML 配置/导入确定性迁移与解包；XML 只在导出层 | 47–50 |

## 3. 数据契约变化

### artifact version / active pointer
- active_versions 指针改为 `{version, path}`（兼容旧字符串）；
- 逻辑版本幂等键：content_hash + meta.input_fingerprint/context_hash + source + parent_version；
- 新增 `state/activation_history.jsonl` 记录每次恢复（kind/episode/version/previous/reason/operator/时间）。

### draft meta
- 新增 `origin`（manual|automatic_rewrite）、`rewrite_ticket_id`、`review_version`、`review_hash`、`source_draft_version`、`source_draft_hash`；
- 废弃 `automatic_rewrite` 布尔作为安全边界（保留兼容读取）。

### review report
- verdict 由系统推导；可选 `model_verdict` 保存原始模型结论；
- issue evidence 关系校验升级（span 正序、同一摘录、事件自身摘录、decision 有效）。

### rewrite provenance（新增）
- `state/rewrite_tickets.jsonl`：ticket_id/episode/context_hash/review_version/review_hash/source_draft_version/source_draft_hash/status（issued|consumed）/时间；每次 `rewrite` 签发，`save-draft --rewrite-ticket` 消费一次。

### continuity
- 新增 delta 当前有效指针 `current_EP<NNN>_<script_hash8>.json`（绑定 episode/approved_version/script_hash/delta_path/delta_content_hash）；
- continuity 每集 `episode_extraction`（mode/complete/script_hash/draft_version）；`degraded_episodes` 包含 deterministic、无 delta、complete=false、校验失败；
- 全局 `extraction_mode` 支持 deterministic|host_agent|model_assisted|mixed；
- facts 必填 fact_id/category/fact/evidence_location。

### revision
- 单一事实源为 `state/revisions.jsonl` 事件日志，当前状态=按 revision_id 投影最后事件；`writer_overrides.jsonl` 仅为派生流；
- 状态迁移：pending→approved/rejected、approved→applied/revoked、applied→revoked；revoke-revision 命令；
- applied 只通过显式 `--apply-revision <id>` 绑定到新版本。

### source event / episode outline / source evidence
- key_quotes 支持 pair_id/setup/payoff；
- must_keep 支持对象 `{text, event_id, adaptation_decision_id}`；adaptation_basis 支持 `{id, text}`；
- coverage 事件条目新增 degraded/degraded_reason（needs_reanchor）；
- 配对要求两端真实存在于同一章；must_keep 只能由原文摘录或有效 adaptation decision 证明。

### project config
- `script_format` 仅允许 `default-cn`；新增 `transport_format`（plain|legacy-scriptitem）；
- `load_config` 对旧 `script_format=legacy-scriptitem` 自动迁移为 default-cn + transport legacy-scriptitem。

### episode context
- 快照只含语义字段 + context_hash（role/completeness/context_file 不再写入）；
- 快照文件名使用完整 context_hash；同 hash 路径字节不一致硬阻断；移除无效 .sha256 sidecar；
- `current_EP<NNN>.json` 只负责选择指针。

## 4. 旧状态迁移说明

- 第一轮产生的 manifest/active_versions 兼容读取（字符串 path 指针）；draft meta 无 origin 时按 manual 处理；
- 旧 review（无 evidence 或旧字符串证据）无法通过新门禁，需重新 save-review；
- 旧 continuity 无 episode_extraction/degraded 时，refresh 重建后补齐；旧 delta 文件（无指针）不再被消费，需重新 save-continuity-delta；
- 旧 revisions 只有 approved/pending 状态的可在新状态机下继续迁移（reject/revoke 追加事件）；旧 writer_overrides 不作为真相；
- `script_format=legacy-scriptitem` 的旧配置在 load_config 时自动迁移；旧 XML 剧本通过 save-draft/approve 导入时自动解包为业务正文；
- 旧 context 快照（8 位前缀命名）可通过 find_context_snapshot 读取，但新建快照使用完整 hash。

## 5. 测试结果

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'        # 112 OK
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'   # 78 OK（round1 22 + round2 50 + EP001 6）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'        # 4 OK
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'  # 旧基线 38：31/4F/3E 无新增失败
```

本轮不调用真实模型/API；全部测试使用临时目录。

## 6. 已知限制（诚实清单）

- must_keep/证据仍以文本匹配与结构化引用为准，模型语义质量不在本轮；
- delta 事实语义正确性由宿主 Agent/模型负责，系统只保证绑定、校验与重建；
- 旧版 38 项 4F/3E 未修（旧基线）；
- 合同第 15 节排除项全部未处理（容量算法、动态时长、agents 元数据、pip 打包、发布 ZIP 引用、迁移器完善、P2 平台能力）；
- 真实编剧效果指标与创作 Prompt 调优未进行。

## 7. 独立评审者应优先尝试的绕过路径

1. 篡改已保存 review/context/draft/delta 版本文件后消费；
2. 用合法但相互不一致的 evidence 字段拼装（event A + quote B + hash C）；
3. 同一进程交替刷新两个项目；替换/恢复同一集不同定稿；
4. Host Agent 连续两次自动重写；跨集/跨上下文复用或重复消费 ticket；
5. 同文本跨 context 保存；只保留 setup 或 payoff；事件摘要冒充原文；
6. revision 经过 approved/applied/rejected/revoked 组合；
7. legacy 配置下检查内部版本是否混入 XML。

## 8. Commit

- 起点：`090848f`
- 本轮提交：`975c898`（主修复）、`3f8ccab`、`pending`
