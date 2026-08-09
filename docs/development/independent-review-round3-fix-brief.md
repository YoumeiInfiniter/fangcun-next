# Fangcun Next 第三轮技术收敛修复合同

> 基线日期：2026-08-09
> 分支：`feature/fangcun-next-rebuild`
> 起点：`f3b5eea7c6d76a1d3ee98a1044c75c792f885116`
> 目标：关闭第二轮测试未覆盖的确定性漏洞，使 Fangcun Next 达到本地内容质量测试前的技术候选标准。

## 1. 权限、优先级与必读文件

开发前完整读取：

1. `AGENTS.md`；
2. `docs/governance/development-review-workflow.md`；
3. `docs/specs/fangcun-next-design-spec.md`；
4. `docs/development/independent-review-round1-fix-brief.md`；
5. `docs/development/fix-handoff-round1.md`；
6. `docs/development/independent-review-round2-fix-brief.md`；
7. `docs/development/fix-handoff-round2.md`；
8. 本合同。

优先级：

1. 用户当前明确决定；
2. 设计规格书；
3. 本合同；
4. 前两轮合同中未被本轮覆盖的要求；
5. 开发交接中的实现自述。

从指定起点后新增 commit，不重写历史，不合并 `main`。开发交接不是验收证明。

## 2. 当前证据与结论

第二轮现有测试已经被独立复现：

- unit：112/112；
- regression：78/78；
- smoke：4/4；
- Round 1：22/22；
- Round 2：50/50；
- 旧版基线：38 项中 31 通过、4 失败、3 报错，未出现新增失败。

但独立临时项目反例仍确认：

1. `manifest` 与 `active_versions` 可以形成版本/路径双重事实源；
2. rewrite ticket 可重复签发，省略 ticket 可伪装 manual；
3. continuity delta 可从 A 定稿移植到 B 定稿；
4. 合法丰富 continuity 字段被静默丢弃；
5. 审核 quote 与声称 span 可以互不对应；
6. setup/payoff 只有一端仍可被当作完整配对；
7. source event span 的方向、边界和坐标基础不可靠；
8. approve 复用旧内容时可把新 revision 错标 applied；
9. `pass + issues=[]` 仍可进入 rewrite；
10. continuity 中的 `writer_overrides` 可能保留陈旧状态。

另外，`tests/regression/test_round2_bypass.py` 的 R2-24 与第二轮合同明确要求相反：它把“已签发 ticket 后省略 ticket 保存”断言为 manual。本轮必须修正该测试方向并记录原因。

当前仍为技术红灯。

## 3. 本轮通用原则

- 修复确定性数据链，不用 Prompt 警告代替门禁；
- 建立单一事实源和单一可信 resolver，禁止消费者自行拼接版本与路径；
- 保存时校验不能替代消费时再校验；
- 非法、冲突、缺失或篡改状态必须阻断并报错，不能静默继续；
- 安全身份使用完整绑定，文件名缩写不得成为真实身份；
- 修复必须适用于随机项目、路径、内容和操作顺序；
- 外部案例可以被看见和修复，但不得被弱化；独立评审仍会使用隐藏变体。

## 4. R3-P0-1：活动 artifact 单一可信解析

### 已确认问题

`active_artifact_path` 信任 `active_versions.path`，`active_version_id` 优先信任 manifest。二者可分别指向不同对象；path 还可逃逸到项目外。context 能读取外部未登记内容，同时声称使用 manifest 中的版本。

### 必须保证

- 建立所有消费者共用的 active artifact resolver；
- kind、episode、version、path、content hash 来自同一 manifest 版本记录；
- `active_versions` 只能作为可验证索引或兼容缓存，不能覆盖事实源；
- 路径必须位于当前 `project_dir`，拒绝绝对路径、`..`、符号链接逃逸和跨项目引用；
- 文件必须存在，消费时重算 hash 并匹配版本记录；
- manifest 与索引不一致时阻断，或从唯一事实源确定性重建，不能混合取值；
- context、review、rewrite、approve、continuity、历史恢复等路径统一使用 resolver。

## 5. R3-P0-2：rewrite provenance 不可由省略参数绕过

### 已确认问题

同一 reviewed draft 可重复调用 `rewrite` 获得多张 ticket；ticket 已签发后，`save-draft` 省略 ticket 会被登记为 manual，进而重新获得自动重写机会。

### 必须保证

- 相同 episode、context、review、source draft 完整绑定只能有一张有效 issued ticket；
- 重复 `rewrite` 返回同一未消费 ticket，或明确拒绝，不得产生多张可消费凭证；
- ticket 状态至少明确区分 issued、consumed，以及实现所需的 cancelled/expired；
- 已签发 ticket 的绑定范围内，省略 ticket 的 `save-draft` 默认拒绝；
- 真正人工修改使用显式、可审计流程，至少记录 operator、reason、绑定和被取消 ticket；
- “省略参数”不能证明人工身份；
- API Mode 与 Host Agent Mode 使用同一 provenance 和次数规则；
- 自动重写稿没有新的真实人工修改时，不能继续自动重写；
- `pass` 且无 actionable issue 的审核不得签发 ticket；
- 修正 R2-24 的名称、操作和断言，并在 handoff 解释变更。

## 6. R3-P0-3：continuity delta 与当前定稿全绑定

### 已确认问题

`_load_delta` 验证文件 hash，但不验证 pointer、delta 内嵌字段和当前有效定稿是否一致，因此 A 版 delta 可污染 B 版连续性。

### 必须保证

- pointer、delta 文件、当前 approved script 三方绑定 episode、approved version、script hash、delta hash；
- delta 内嵌 episode、draft/approved version、script hash 必须与调用参数和 pointer 一致；
- delta path 必须受目录约束；
- 当前定稿必须通过统一 active resolver 获取；
- 任一不一致时拒绝 delta，并将该集列入 degraded；
- 安全绑定使用完整 hash，不依赖前 8 位；
- 换定稿、恢复旧定稿、跨项目复制和重复 refresh 均不得污染。

## 7. R3-P0-4：continuity rich fields 完整、幂等合并

### 已确认问题

`_delta_complete` 忽略 `character_states`、`relationship_states`、`props`、`locations`；`_merge_delta` 也未完整合并这些合法字段。

### 必须保证

- schema 明确所有支持字段；
- `_delta_complete` 覆盖所有可构成有效增量的字段；
- `_merge_delta` 完整合并角色状态、关系状态、道具、地点及现有合法字段；
- 冲突规则明确且测试；
- 重复 refresh 幂等，不重复事实、状态或 hook；
- 换定稿重建后删除旧定稿贡献，恢复旧定稿可恢复对应贡献；
- 不支持字段应拒绝或明确记录，不能静默丢弃。

## 8. R3-P0-5：审核 quote 必须位于声称 span

### 已确认问题

当前只要求 quote 和 span 同属一个 excerpt，不要求 quote 实际落在 span 内。

### 必须保证

- 同时提供 quote 和 span 时，quote 必须逐字存在于 span 对应的原文切片；
- quote 的完整实际位置必须落在 span 内；
- event、chapter、excerpt hash、span、quote 使用统一坐标基础并指向同一证据；
- “都在同一摘录”不能替代字段关系校验。

## 9. R3-P0-6：setup/payoff 两端真实存在

### 已确认问题

`_pair_span` 会把缺失端折叠到存在端，单端也可能被判完整。

### 必须保证

- `must_preserve_pairing=true` 时 setup 和 payoff 都必须真实存在；
- 两端必须位于规格允许的同一章节或关系范围；
- 缺任一端不能生成完整 pair span；
- coverage ledger 区分 `missing_setup`、`missing_payoff`；
- 单端不能标记 pairing satisfied；
- 相同文本和跨章节情况有明确规则及测试。

## 10. R3-P0-7：source span 统一坐标契约

### 已确认问题

source event 可接受反向 span；retriever 会 clamp/snap 非法值；ingest 又在正文前增加标题并执行 `strip`，可能让事件坐标与保存后的章节文本错位。

### 必须保证

- 定义唯一、可文档化的章节正文坐标系统；
- 标题作为 metadata，或用显式 offset 做统一转换，不能无声明改变正文坐标；
- `strip`、换行处理等规范化不得静默破坏 span；
- source event 语义校验满足整数且 `0 <= start < end <= chapter_text_length`；
- 非法 span 拒绝或标记 `needs_reanchor`，不能 snap 成另一个事件范围；
- coverage 的 resolved 必须表示摘录真实覆盖事件；
- 长标题、前导空白和多段换行场景保持坐标一致。

## 11. R3-P0-8：revision applied 必须绑定本次真实新版本

### 已确认问题

`save-draft` 已检查 `created`，但 `cmd_approve` 无条件调用 `mark_revisions_applied`。复用旧定稿时，新 revision 可被绑定到早已存在的版本。

### 必须保证

- `apply_approved_script` 返回完整 commit result；
- 只有本次真实创建的新逻辑版本才能自动绑定 revision；
- 早于 revision 的旧版本不能证明意见已落实；
- 重试幂等，不重复 applied；
- applied 绑定明确记录 kind、episode、version 和所需指纹；
- 若允许人工确认“既有版本已包含意见”，必须是独立、显式、可审计动作。

## 12. R3-S1-1：无问题的 pass review 不得重写

- `pass + issues=[]` 拒绝 rewrite，不签发 ticket；
- warning 是否可重写按规格书执行，但必须存在合法 actionable issue；
- blocked 必须存在合法 error；
- 自由润色走人工修改流程，不滥用审核重写通道。

## 13. R3-S1-2：revision 当前投影是 writer override 唯一事实源

- continuity 与 episode context 均从 `revisions.jsonl` 当前状态投影构建；
- append-only 派生日志仅供审计；
- rejected/revoked 不再作为有效未来指令；
- applied 的未来作用按 `affects_future` 和规格书决定；
- refresh 后同一 revision 不得出现互相冲突的多个当前状态。

## 14. 必须新增的公开外部验收文件

新增 `tests/regression/test_round3_external_acceptance.py`。测试使用随机临时目录和动态内容，不依赖真实项目。

### A. 活动版本

1. 索引 path 指向项目外文件、manifest 仍为 v001：context 必须拒绝，不能读取外部内容。
2. 索引 version/path 与 manifest 交叉组合：必须拒绝或可信重建，不能返回混合对象。
3. 篡改活动 artifact 内容但不更新 hash：任意消费者必须拒绝。
4. 使用 `..`、绝对路径或符号链接逃逸：必须拒绝。

### B. rewrite provenance

1. 同一 reviewed draft 连续两次 rewrite：不能产生两张可分别消费的 ticket。
2. ticket 已签发后省略 ticket 保存：默认拒绝，不能标 manual。
3. 显式取消后保存人工稿：有审计，旧 ticket 失效。
4. consumed ticket 二次消费：拒绝。
5. 自动重写稿在没有真实人工修改时再次自动 rewrite：拒绝。
6. `pass + issues=[]` rewrite：拒绝且不签发 ticket。
7. 修正 R2-24，并明确这是纠正反向测试，不是削弱测试。

### C. delta 绑定

1. A delta 经伪造 pointer 移植到 B 定稿：拒绝，B 不含 A 事实。
2. pointer 的 episode/version/script hash 任一项与 delta 不一致：拒绝。
3. delta path 指向目录外或其他项目：拒绝。
4. 模拟短哈希前缀相同：仍按完整 hash 区分。
5. 恢复 A 时只能消费与 A 完整绑定的有效 delta。

### D. rich continuity

1. 仅含 `character_states` 的 delta 有效并合并。
2. 仅含 `relationship_states`、`props` 或 `locations` 时不得丢失。
3. 连续两次 refresh 结果幂等，不重复追加。
4. A 切 B 后 A 的丰富字段消失，恢复 A 后正确恢复。

### E. 审核证据

1. quote 在摘录后部、span 指向前部：拒绝。
2. quote 只有部分落在 span：拒绝。
3. event/chapter/hash 正确但 quote 不在 span：拒绝。
4. 合法 quote 完整位于 span：通过，避免过度阻断。

### F. setup/payoff

1. 只有 setup：不得 satisfied。
2. 只有 payoff：不得 satisfied。
3. 两端都存在于合法范围：生成覆盖两端的 span。
4. 两端位于不允许拼接的章节：不得 satisfied。

### G. source span

1. `start=50,end=10`：拒绝或 needs_reanchor。
2. `start=end`：拒绝或 needs_reanchor。
3. end 超过正文：拒绝或 needs_reanchor。
4. 长标题时事件摘录包含目标正文，而非仅标题。
5. 前导空白和多段换行时保持统一坐标。

### H. revision applied

1. v001 已存在后创建 revision，再 approve 相同内容：不得 applied。
2. 实际创建 v002 后，显式 revision 才绑定 v002。
3. 相同命令重试不重复 applied。
4. 其他 episode 的 revision 不得绑定。

### I. writer override 投影

1. approved 后进入未来上下文，随后 rejected/revoked 后从 continuity 和下一集 context 消失。
2. 多次状态变化后只保留当前有效投影。

### J. 组合生命周期

1. 临时项目完整执行原文、事件、集纲、context、草稿、blocked review、rewrite、ticket、复审、approve、delta、refresh、下一集 context。
2. 分别篡改 review、draft、context、approved script、delta 后，后续安全消费者在正确位置阻断。

## 15. 测试政策

1. 上述案例属于独立评审者提供的公开外部案例，不得删除、跳过、弱化或反转。
2. 唯一已授权改变既有测试方向的是 R2-24；必须改成“省略 ticket 不能伪装 manual”。
3. 可以增加实现级测试，但不能替代外部案例。
4. 禁止识别固定测试名、项目名、路径、ID、哈希或夹具内容。
5. 独立评审会另外运行未公开的路径、顺序、跨项目、篡改、中断、恢复和边界变体。
6. 开发自测通过不能表述为独立验收通过或技术封板。

## 16. 必须运行的测试

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

分别报告 unit、Round 1、Round 2、Round 3、EP001、smoke 和旧版基线。说明 R2-24 修正后的统计，不调用真实模型/API，不执行飞书操作。

## 17. 本轮不处理

- 台词、因果和原著贴合等创作质量调优；
- Writer Prompt 和题材 Craft 扩展；
- 容量与动态时长算法；
- 飞书、OpenClaw、Token 统计和 Bot 管理；
- agents 元数据、pip、ZIP 正式发布；
- 大规模旧项目迁移和 P2 运营能力。

除非修复本轮问题不可避免，不扩展范围。

## 18. 完成定义与交接

第三轮开发完成要求：

1. 本合同问题均由确定性实现修复；
2. Round 3 外部案例全部通过；
3. unit、Round 1、修正后的 Round 2、EP001、regression、smoke 无新增失败；
4. 旧版基线无新增失败；
5. 工作区干净，修改全部提交在当前分支，未合并 `main`；
6. 没有真实 API、飞书或线上操作；
7. 剩余限制诚实记录。

完成后创建 `docs/development/fix-handoff-round3.md`，至少包含：

- 起点、全部新增 commit、最终 HEAD；
- 问题到修改文件、不变量和测试编号的映射；
- R2-24 修改前后差异；
- 精确测试命令、数量、通过、失败和跳过；
- API/平台操作声明；
- 旧版兼容性变化；
- 剩余限制和最高风险文件；
- 给独立评审模型的简短只读复审提示词。

不得把“开发测试全部通过”写成“独立验收通过”。
