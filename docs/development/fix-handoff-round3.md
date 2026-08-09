# Fangcun Next 第三轮技术收敛交接（Round 3 Fix Handoff）

> 依据：`docs/development/independent-review-round3-fix-brief.md`
> 起点：`f3b5eea`；本轮起始 HEAD：`c6fc5c5`
> 目标：关闭第二轮测试未覆盖的确定性漏洞，达到本地内容质量测试前的技术候选标准（由独立评审放行，本交接不作验收结论）

## 1. 问题 → 修改 → 不变量 → 测试对照

| 问题 | 修改文件 | 通用不变量 | 外部验收测试 |
|---|---|---|---|
| R3-P0-1 manifest/索引双事实源、路径逃逸、内容篡改 | `scripts/state_store.py`（`resolve_active`/`_validated_version_path`） | manifest 为唯一事实源；索引不一致阻断；路径必须在项目内；消费时重算 content hash | a1–a4 |
| R3-P0-2 rewrite ticket 可重复签发/省略参数伪装 manual | `scripts/rewrite_ticket.py`（同绑定唯一 issued、cancelled 状态、latest 投影）、`scripts/project_cli.py`（save-draft 省略 ticket 拒绝、--manual-edit 显式人工流程） | 同一绑定只有一张有效 ticket；省略 ticket 默认拒绝；人工修改必须显式并审计 | b1–b6 |
| R3-P0-3 delta 可从 A 定稿移植到 B | `scripts/continuity_manager.py`（delta 内嵌字段校验、pointer 路径约束、完整 hash） | pointer/delta/当前定稿三方绑定 episode+version+script hash+delta hash；不一致拒绝并 degraded | c1–c5 |
| R3-P0-4 rich fields 被静默丢弃 | `scripts/continuity_manager.py`（`_delta_complete`/`_merge_delta` 覆盖 character_states/relationship_states/props/locations） | 所有合法 delta 字段完整合并；重复 refresh 幂等；换/恢复定稿正确切换 | d1–d4 |
| R3-P0-5 quote 与 span 互不对应 | `scripts/project_cli.py`（`_validate_issue_evidence` span 切片校验） | quote 必须逐字位于 span 对应原文切片；全部字段指向同一摘录 | e1–e4 |
| R3-P0-6 setup/payoff 单端被当完整 | `scripts/source_retriever.py`（`_pair_span` 严格两端、missing_setup/missing_payoff 记录） | 配对两端必须真实存在于同一章；缺一端不得 satisfied | f1–f4 |
| R3-P0-7 source span 方向/边界/坐标不可靠 | `scripts/source_ingest.py`（coordinate_base 声明）、`scripts/project_cli.py`（save-events 反向/零长拒绝）、`scripts/source_retriever.py`（越界 needs_reanchor，不 snap 成其他范围） | 坐标基础=章节文件内容；0<=start<end<=章节长度；非法 span 拒绝或 needs_reanchor | g1–g5 |
| R3-P0-8 approve 复用旧内容误标 applied | `scripts/continuity_manager.py`（apply_approved_script 返回 commit result）、`scripts/project_cli.py`（仅 created 时绑定） | applied 只绑定本次真实创建的新逻辑版本；幂等复用不绑定；显式 revision_ids | h1–h4 |
| R3-S1-1 pass+空 issues 可重写 | `scripts/project_cli.py`（`_validate_review_for_consumption` actionable 规则） | pass 且无 actionable issue 拒绝 rewrite 且不签发 ticket；blocked 必须有 error；warning 必须有 actionable issue | b6 |
| R3-S1-2 continuity writer_overrides 陈旧 | `scripts/continuity_manager.py`（从 revision 当前投影构建） | revisions.jsonl 投影是唯一事实源；rejected/revoked 不再传播；多次状态变化只保留最新投影 | i1–i2 |
| 组合生命周期与篡改阻断 | 上述全部 + CLI | 任意审查/草稿/上下文/定稿/delta 篡改都在对应安全消费者处阻断 | j1–j2 |

## 2. R2-24 修改前后差异

- 修改前：`test_r2_24_omitting_ticket_is_manual_not_automatic` 断言“已签发 ticket 后省略 ticket 保存 = manual”（与第二轮合同相反，属于反向测试）。
- 修改后：`test_r2_24_omitting_ticket_cannot_pretend_manual` 断言省略 ticket 保存被拒绝；显式 `--manual-edit` 流程可保存为 manual，并记录 manual_edits.jsonl 审计、取消已签发 ticket。
- 这是纠正测试方向而非弱化；第一轮 test_22 与第二轮 test_23 的人工保存步骤同步改为显式 `--manual-edit`。

## 3. 测试结果（真实命令与数量）

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
# Ran 112 tests, OK
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
# Ran 118 tests, OK（Round1 22 + Round2 50（含修正后 R2-24）+ Round3 40 + EP001 6）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
# Ran 4 tests, OK
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
# Ran 38 tests：31 通过 / 4 失败 / 3 报错（旧版基线，无新增失败）
```

- 未调用真实模型/API；未执行飞书或任何平台写入；全部测试使用随机临时目录。
- 测试前后 `git status --short --branch`：工作树干净（除本交接提交前的新文件）。

## 4. 兼容性

- 旧 active_versions 字符串路径索引兼容读取（缺失/旧格式时从 manifest 重建或按新格式写入）；
- 旧 draft meta 无 origin 按 manual 处理；
- 旧 review 无新字段需重建；旧 delta 无 pointer 不再消费；
- 旧 `script_format=legacy-scriptitem` 配置与旧 XML 剧本按第二轮规则自动迁移/解包；
- 旧 revisions 状态可继续迁移（事件日志投影），旧 writer_overrides 不作为事实源。

## 5. 已知限制

- delta 事实语义正确性由宿主 Agent/模型负责；
- must_keep/quote 以文本与结构化引用为准，模型语义质量不在本轮；
- 合同第 17 节排除项未处理（创作质量、容量/时长算法、P2、agents 元数据、pip/ZIP 发布、大规模迁移）；
- 旧版 38 项 4F/3E 未修；
- 本轮为开发自测，不构成独立验收或技术放行。

## 6. 最高风险文件

- `scripts/state_store.py`（resolver 与路径/哈希校验）
- `scripts/project_cli.py`（审核消费再验证、ticket 流程、证据 span 校验）
- `scripts/rewrite_ticket.py`（ticket 状态投影与取消）
- `scripts/continuity_manager.py`（delta 绑定与 rich fields 合并）
- `scripts/source_retriever.py`（配对与 span 坐标）

## 7. Commit

- 起点：`f3b5eea`（问题复现基线）；当前轮起始：`c6fc5c5`
- 本轮提交：`a36eb3b`、`3fa918f`、`cd2612e`
- 最终 HEAD：见交付消息

