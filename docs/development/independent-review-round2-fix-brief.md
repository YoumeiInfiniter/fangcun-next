# Fangcun Next 独立复审与第二轮修复合同

> 日期：2026-08-09
> 修复分支：`feature/fangcun-next-rebuild`
> 第二轮起点：`090848f700839d3b087d520a971e2c6d4b402ddd`
> 依据：第一轮修复后的独立只读复审
> 目标：关闭剩余 P0 确定性漏洞，使创作效果测试不再被状态、版本、证据或格式错误污染。

## 目录

1. 权限、基线与优先级
2. 第二轮结论与实施原则
3. 本轮范围
4. R2-S0-1 审核报告完整性与结论门禁
5. R2-S0-2 连续性真正从当前定稿幂等重建
6. R2-S0-3 Host Agent 自动重写来源不可伪装
7. R2-S1-1 内容去重与逻辑版本分离
8. R2-S1-2 原文配对与 must_keep 可追溯性
9. R2-S1-3 修改意见单一状态源与撤销
10. R2-S1-4 episode_context 真正不可变
11. R2-S1-5 业务剧本格式与 XML Adapter 分离
12. 数据契约要求
13. 必须新增的绕过测试
14. 旧测试、测试方法和验证要求
15. 本轮不处理
16. 禁止事项
17. 完成定义
18. 开发完成后的交接要求
19. 下一轮独立复审重点

## 1. 权限、基线与优先级

开发前必须完整阅读：

1. `AGENTS.md`；
2. `docs/specs/fangcun-next-design-spec.md`；
3. `docs/development/independent-review-round1-fix-brief.md`；
4. `docs/development/fix-handoff-round1.md`；
5. 本文档。

优先级：

1. 用户已确认的业务决策；
2. 规格书；
3. 本文档；
4. 第一轮合同中未被本文覆盖的要求；
5. 开发交接文档中的实现自述。

本轮从 `090848f` 开始。不得修改或重写既有 commit 历史；在其后创建新 commit。

开发交接文档不是验收证明。所有“不可绕过”“幂等”“完整”“已修复”都必须由实现、反例测试和实际测试结果共同证明。

## 2. 第二轮结论与实施原则

第一轮新增测试结果属实：

- unit：112/112；
- regression：28/28，其中 Round 1 绕过场景 22/22；
- smoke：4/4；
- 旧版基线：38 项中 31 通过、4 失败、3 报错。

但独立复审另外复现出以下未覆盖路径：

1. 含 `error` 的报告可保存为 `pass`；
2. `start > end` 的无效 source span 可作为证据通过；
3. 保存后的审核文件被篡改，重写仍继续；
4. 替换定稿后，连续性同时保留新旧冲突事实；
5. Host Agent 重写稿会被登记成普通人工稿，可继续自动重写；
6. 同一文本换新上下文仍复用旧版本及旧 meta；
7. 原文只有 payoff、缺 setup 时仍被判定为完整配对；
8. AI 事件摘要可替代真实原文证明 must_keep；
9. 修改意见批准后再驳回，仍进入后续上下文；
10. `complete=false` 的 Host Agent delta 不进入 `degraded_episodes`。

本轮遵循以下原则：

- 修的是确定性数据链，不通过增加 Prompt 警告掩盖；
- 安全消费端必须重新校验，不能只相信保存时校验过；
- 内容对象可以去重，逻辑版本、确认动作和输入绑定不能被去重掉；
- 连续性只来源于当前有效定稿和与该定稿绑定的当前有效 delta；
- Host Agent Mode 与 API Mode 使用同一套 provenance 和次数门禁；
- 业务剧本永远是统一纯文本，XML 只在导出层出现；
- 所有新测试使用临时目录，不依赖已知真实项目产物。

## 3. 本轮范围

本轮必须完成：

- 审核 verdict、结构化证据及审核产物自身完整性；
- 连续性无污染重建、delta 选择和降级状态；
- Host Agent/API 统一的自动重写来源与次数门禁；
- 内容去重与逻辑版本分离、历史恢复接口；
- setup/payoff、must_keep、事件 span 的真实原文追溯；
- revision 当前状态、撤销、pending 传播和 applied 绑定；
- episode_context 不可变快照；
- P0 要求的业务格式与 XML Adapter 分离；
- 第一轮 22 项测试继续全部通过。

本轮不重做改编指引、故事大纲、容量算法、P2 平台能力和创作 Prompt 风格。

## 4. R2-S0-1：审核报告完整性与结论门禁

### 4.1 已复现问题

- `scripts/project_cli.py::_normalize_verdict` 在输入 verdict 可映射时直接返回，忽略 issues 中的 `error`；
- `source_span` 只判断落在摘录边界，没有判断非空、正序和字段类型关系；
- quote、event、chapter、span、excerpt_hash 分别存在即可，不要求属于同一证据对象；
- `cmd_rewrite` 读取审核文件后，不核对 manifest 记录的审核 `content_hash`，不重新执行 Schema、证据和 verdict 校验。

### 4.2 必须实现

#### Verdict 唯一推导规则

保存后的 verdict 只能由归一化后的有效 issues 推导：

```text
存在 error      -> blocked
无 error，有 warning -> warning
仅 suggestion 或无 issue -> pass
```

- 模型输入的 verdict 只可作为原始字段记录，不得覆盖推导结果；
- 可选保存 `model_verdict`，正式 `verdict` 必须是系统推导值；
- 被丢弃、非法或空 problem 的 issue 不得静默消失并让报告变成 pass，应拒绝整个报告或显式列入 normalization errors。

#### Source evidence 关系校验

source evidence 至少满足一个可验证主键，同时所有已提供字段必须相互一致：

- `source_span.start`、`end` 必须是整数，且 `0 <= start < end`；
- span 必须落在指定 chapter 的某一个实际 excerpt 中；
- quote 必须逐字存在于同一个 excerpt，且与 span 对应；
- excerpt_hash 必须是该同一个 excerpt 的哈希；
- event_id 必须存在于当前 context，且其 chapter/span 与证据不冲突；
- chapter_id 必须与 excerpt、event 和 span 一致；
- 不允许用 event A + quote B + hash C 拼装一条证据；
- 只有 event_id、没有任何可定位原文的 span/quote/excerpt 时，不足以证明具体原文问题；
- adaptation evidence 必须引用当前有效 adaptation decision ID。

#### 审核产物消费时再验证

`rewrite` 在消费审核版本前必须：

1. 获取 manifest 中该审核逻辑版本记录；
2. 重新计算审核文件 content hash；
3. 与 manifest 记录一致；
4. 重新校验 review schema；
5. 重新校验 context/draft/review 三方绑定；
6. 重新校验证据关系；
7. 重新推导 verdict。

任一失败都必须阻断。不得把“versions 文件默认不可修改”当作完整性保证。

### 4.3 验收结果

- `error + model verdict pass` 保存后必须是 blocked；
- 反向、零长度、越界、跨 excerpt 拼装的 span 必须拒绝；
- 保存后的 review 文件任意字节变更都必须阻断 rewrite；
- 合法 warning 报告仍可保存并由编剧决定是否处理。

## 5. R2-S0-2：连续性真正从当前定稿幂等重建

### 5.1 已复现问题

`DEFAULT_CONTINUITY.copy()` 是浅复制。facts、knowledge、hooks、states 等嵌套容器会被模块级默认对象污染；换定稿后旧事实仍存在，同进程多项目之间也有串数据风险。

此外：

- 多个同 script hash delta 通过文件名排序选择，不能证明哪一个当前有效；
- `complete=false` 的 host/model delta 不进入 degraded list；
- 全局 extraction mode 会把 host_agent 混写成 model_assisted；
- delta schema 没有强制事实证据位置非空。

### 5.2 必须实现

- 用函数每次创建全新的 continuity 初始对象，禁止浅复制共享嵌套结构；
- rebuild 只读取每集当前有效 `approved_script`；
- 每个 delta 必须绑定 episode、approved version、script hash 和 delta content hash；
- delta 必须有逻辑版本和 current pointer，不能靠哈希文件名字典序选择；
- 同一 approved script 可有多版 delta，但只能有一个当前有效版；
- 替换定稿后，旧定稿绑定 delta 自动失效但保留历史；
- 从所有当前有效定稿 + 当前有效 delta 重建，结果不得依赖上一次 continuity 内容；
- `complete=false`、无 delta、delta 校验失败都进入 `degraded_episodes`；
- 每集 extraction 明确记录 `deterministic | host_agent | model_assisted`；
- 全局 mode 支持 `deterministic | host_agent | model_assisted | mixed`，不得误报；
- fact 的 `fact_id`、`category`、`fact`、`evidence_location` 必须非空；
- evidence_location 至少能指向当前定稿中的场次、台词或动作位置；本轮不要求程序判断事实语义是否正确，但不得接受空证据；
- 重复 refresh 不增加重复事实、知识、钩子或 override。

### 5.3 必须证明

- 定稿 A 的旧事实在定稿 B 生效后不再进入当前 continuity；
- 项目 A 的事实绝不进入项目 B；
- 重复 refresh 的业务内容完全一致；
- 恢复旧定稿版本后，可重建回旧定稿对应事实；
- 不完整 delta 明确降级。

## 6. R2-S0-3：Host Agent 自动重写来源不可伪装

### 6.1 已复现问题

API rewrite 直接调用 `cmd_save_draft(... automatic_rewrite=True)`，Host Agent rewrite 只输出 Prompt，再让 Agent 执行普通 `save-draft`。因此 Host Agent 自动重写稿会被记录为人工稿，可继续自动重写。

### 6.2 必须实现

实现系统签发的一次性 rewrite provenance。可以命名为 rewrite ticket，但必须具备等价语义：

```json
{
  "ticket_id": "...",
  "episode": 1,
  "context_hash": "...",
  "review_version": "v001",
  "review_hash": "...",
  "source_draft_version": "v001",
  "source_draft_hash": "...",
  "status": "issued | consumed | expired",
  "created_at": "..."
}
```

要求：

- 每次 `rewrite` 先签发 ticket；
- API Mode 保存结果时自动消费 ticket；
- Host Agent Mode 的重写包必须显示 ticket ID，保存重写稿必须显式提交该 ticket；
- ticket 只能消费一次；
- ticket 与 episode/context/review/source draft 全绑定；
- ticket 不得用于保存其他集、其他上下文或其他审核的草稿；
- 消费成功的草稿 meta 标记 `origin=automatic_rewrite` 和 parent bindings；
- 对 automatic rewrite 产物再次调用自动 rewrite 必须阻断；
- 编剧明确人工修改后保存的新版本可再次获得一次自动重写机会；
- “人工修改”不能仅由调用者声明。至少必须是没有消费 rewrite ticket 的显式 writer/manual 来源，并记录来源；
- 隐藏的 `--automatic-rewrite` 布尔参数不得继续作为核心安全边界。

## 7. R2-S1-1：内容去重与逻辑版本分离

### 7.1 已复现问题

`commit_artifact` 只按正文 content hash 幂等。同一文本在 H1 和 H2 上下文下保存，第二次复用旧逻辑版本和 H1 meta。

### 7.2 必须实现

区分：

- content object：相同字节可以只存一份；
- logical artifact version：一次具有独立输入、来源、确认或父版本语义的记录。

逻辑版本的幂等身份至少考虑：

- kind、episode；
- content_hash；
- context_hash 或 input fingerprint；
- source/origin；
- parent/supersedes；
- 对该 kind 有意义的绑定 meta。

要求：

- 同内容 + 同输入 + 同来源重复执行：幂等；
- 同内容 + 不同 context：新逻辑版本；
- 同内容 + 新的编剧确认动作：可形成新确认记录或明确复用并记录确认事件，不能丢审计语义；
- draft 的 context/draft hash 和输入版本不可复用错误；
- 版本号不能用简单 `len + 1` 在并发或恢复后制造冲突；本轮至少要防止重复 ID 和 manifest 不一致；
- active pointer 必须指向逻辑版本，而不是只存路径。

### 7.3 恢复接口

提供确定性接口，例如：

```text
activate-version --kind KIND [--episode N] --version vNNN
```

要求：

- 校验版本存在、文件哈希有效；
- 更新 manifest 和 active pointer；
- 记录操作者、时间、原因和 previous active；
- 恢复 approved_script 后自动或明确触发 continuity rebuild；
- 不删除较新版本；
- 支持读取和恢复两版定稿、审核、集纲等关键产物。

## 8. R2-S1-2：原文配对与 must_keep 可追溯性

### 8.1 必须修复的配对规则

- dialogue anchor 同时声明 setup/payoff 时，两者必须都存在；
- 只有 setup 或只有 payoff 时，coverage 必须 omitted，不得用找到的一端替代两端；
- 两端必须来自同一章或明确允许的连续原文范围；
- 选取的 excerpt 必须完整包含两端；
- 低预算时提升必要预算或阻断，不得拆散；
- source event 中 `must_preserve_pairing` 必须有可执行的配对结构，不能只是未被消费的布尔字段；
- 如现有 key_quote schema 无法表达 pair，应扩展 `pair_id`/`setup`/`payoff` 或等价结构，并兼容旧字段。

### 8.2 must_keep 追溯规则

以下任一成立才算 included：

1. must_keep 绑定的 source event 有有效 chapter + source span，且对应 raw excerpt 实际覆盖该 span；
2. 有真实 quote，逐字存在于 included excerpt；
3. 引用当前有效 adaptation decision ID。

以下不得单独作为证明：

- AI 生成的 event 摘要；
- event/result/actions 中出现相同字符串；
- requested chapter ID 但没有实际 excerpt；
- 无 source span 的事件对象；
- 自由文本 adaptation basis。

事件资产 schema 应要求可追溯定位；对 legacy event 无 span 的情况必须显式标记 degraded/needs_reanchor，不得假装完整。

## 9. R2-S1-3：修改意见单一状态源与撤销

### 9.1 已复现问题

`revisions.jsonl` 修改当前状态，`writer_overrides.jsonl` 另存 approved/applied 副本。reject 不写撤销记录，context 仍读到旧 approved override。

### 9.2 必须实现

- revision 当前状态必须有单一事实源；
- 推荐由 revision event log 投影当前状态，或让 context 直接读取 revisions 当前状态；
- writer_overrides 如保留，只能是可重建派生物，不能成为独立真相；
- 定义合法状态迁移，不允许任意往返而不留历史；
- approved 后撤销必须立即从后续上下文移除；
- applied 后如编剧撤销，记录 revoked/superseded 或等价状态，并明确已应用版本是否需要新修改；不得静默继续传播；
- pending revision 若 `affects_future=true` 或 scope 指向未来，在生成后续集时也必须提示；
- 保存任意新草稿不得自动宣称所有 approved revisions 已执行；applied 必须绑定明确 revision IDs 和目标版本；
- 重新保存旧内容或幂等复用旧版本，不得把新 revision 标记 applied；
- `affects_future=false` 继续覆盖关键词推测。

## 10. R2-S1-4：episode_context 真正不可变

### 10.1 当前风险

context hash 只覆盖 body，但 role、completeness 等字段随后写入同一 hash 路径；不同 role 重新构建时可能覆盖同名文件。`.sha256` sidecar 写入后也没有成为消费校验的一部分。

### 10.2 必须实现

- 明确哪些字段属于不可变 episode context，哪些是 prompt 渲染的瞬时 role；
- role 不应改变共享 context，也不应写回同一快照；
- context_hash 覆盖全部语义字段；
- 相同 hash 路径已存在时，只有字节完全一致才可复用；否则硬阻断 hash/path collision；
- 快照文件被合法 JSON 方式修改也必须校验失败；
- current pointer 只负责选择，不改变历史快照；
- Writer、Reviewer、Rewriter 读取同一快照；role-specific bundle 单独生成；
- context 文件名应避免仅依赖过短哈希前缀造成路径碰撞，至少在碰撞时验证完整 hash；
- 消费端以 context 内重算 hash 为主；sidecar 如保留必须实际验证，否则删除无效复杂度。

## 11. R2-S1-5：业务剧本格式与 XML Adapter 分离

### 11.1 当前 P0 缺口

项目配置允许 `script_format=legacy-scriptitem`，随后 validator 要求 Writer 直接产出 XML。这与规格书“业务剧本唯一标准、XML 仅为 Adapter”冲突。

### 11.2 必须实现

- Writer、save-draft、review、rewrite、approve 的内部正文一律使用 `default-cn` 业务格式；
- `<scriptItem>` 不得进入内部 script_draft/approved_script 内容；
- XML 只由 `format_renderer` 在 export/平台适配时包装；
- 配置将业务格式与传输格式分离，例如：

```json
{
  "script_format": "default-cn",
  "transport_format": "plain | legacy-scriptitem"
}
```

- 旧项目 `script_format=legacy-scriptitem` 需要兼容迁移为业务 `default-cn` + transport `legacy-scriptitem`；
- 导入旧 XML 剧本时先确定性解包为业务正文，再保存；
- 导出 XML 时标签外无注释，内部正文保持业务标准；
- 不在 Writer Prompt 中要求维护 XML。

## 12. 数据契约要求

本轮至少需要审查或更新：

- artifact version record；
- active version pointer；
- draft meta；
- review report 与 review version meta；
- rewrite provenance/ticket；
- continuity delta；
- continuity state；
- revision request/current state；
- source event；
- source evidence coverage；
- project config 的业务/传输格式字段；
- episode context snapshot。

每项修改必须在交接文档中列出：

- 新字段；
- 必填/可选；
- 谁创建；
- 谁验证；
- 谁消费；
- 旧状态如何迁移或为何必须重建。

禁止只改 Python 而不同步 Schema、Prompt、SKILL 和测试；也禁止只改 Schema 而消费端不验证。

## 13. 必须新增的绕过测试

除第一轮 22 项外，至少新增以下测试；测试名必须能追溯到编号。

### 审核完整性

1. `verdict=pass` 且存在 error，保存后必须 blocked；
2. `verdict=pass` 且存在 warning，保存后必须 warning；
3. 反向 span（start > end）拒绝；
4. 零长度 span（start == end）拒绝；
5. 越界 span 拒绝；
6. event A + quote B 的跨证据拼装拒绝；
7. quote 与 excerpt_hash 指向不同 excerpt 时拒绝；
8. review 保存后篡改 summary/issue 任一字节，rewrite 拒绝；
9. review manifest content_hash 被篡改或文件缺失，rewrite 拒绝；
10. 非对象 issue、空 problem、非法 severity 不得静默变 pass。

### 连续性

11. 定稿 A 换成定稿 B 后，A 独有事实从当前 continuity 消失；
12. 两个项目在同一 Python 进程刷新，事实不串项目；
13. 对相同当前定稿重复 refresh，不产生重复 facts/knowledge/hooks；
14. 恢复定稿 A 后，可恢复 A 的连续性事实；
15. host_agent 空 delta 标记 complete=false 且进入 degraded_episodes；
16. fact 缺 fact_id/category/evidence_location 时拒绝；
17. 多版 delta 只消费显式当前有效版，不按文件名字典序选择；
18. mixed extraction 模式报告准确。

### 重写来源

19. Host Agent rewrite ticket 保存的草稿被标记 automatic rewrite；
20. 同一 ticket 第二次消费拒绝；
21. ticket 用于其他 episode/context/review/draft 时拒绝；
22. automatic rewrite 草稿再次自动 rewrite 拒绝；
23. 人工新版本不受总版本数限制，并可重新获得一次 rewrite；
24. 单纯声明 `--automatic-rewrite=false` 或省略参数不能把已签发重写冒充人工稿。

### 逻辑版本

25. 同内容 + 同 context + 同来源重复保存幂等；
26. 同内容 + 不同 context 产生不同逻辑版本和正确 meta；
27. 两版可读取，activate v1 后 active pointer 指向 v1；
28. 恢复不存在或哈希损坏版本时拒绝；
29. 恢复 approved_script 后连续性与该版本一致；
30. 新 revision 不能通过重存旧内容被标记 applied。

### 原文证据

31. setup 缺失、仅 payoff 存在时 dialogue anchor omitted；
32. payoff 缺失、仅 setup 存在时 dialogue anchor omitted；
33. 两端都存在时低预算仍完整保留或明确阻断；
34. `must_preserve_pairing` 的事件台词配对真正不可拆；
35. 只在 event 摘要出现、原文不存在的 must_keep 不得通过；
36. event 缺有效 span 且无 adaptation decision 时标记 degraded/阻断；
37. must_keep 绑定 adaptation decision 时必须验证有效 decision ID。

### 修改意见与上下文

38. pending -> approved -> rejected 后不进入当前及后续上下文；
39. applied revision 撤销后不继续传播，并保留审计记录；
40. EP1 的 future-scoped pending revision 在生成 EP2/EP3 时提示；
41. `affects_future=false` 继续覆盖“下一集/后续”等关键词；
42. 保存未执行 revision 的普通草稿不能自动标记 applied；
43. 只对明确 revision IDs 执行 applied 绑定。

### Context 与格式

44. writer/reviewer/rewriter 生成 bundle 不改变 context 快照字节；
45. 合法 JSON 篡改 context 任一语义字段，消费时拒绝；
46. 同 hash 路径已有不同字节时拒绝覆盖；
47. legacy 配置下 Writer 仍只保存 default-cn 业务正文；
48. XML 导出由 renderer 包装，内部定稿不含 `<scriptItem>`；
49. 旧 XML 导入后保存为纯业务正文；
50. XML 标签外内容继续拒绝。

不得把多个要求塞进一个只有浅断言的测试来虚报覆盖。可合理合并测试 setup，但每条绕过必须有独立断言和失败信息。

## 14. 旧测试、测试方法和验证要求

必须运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

要求：

- 第一轮 22 项绕过测试全部保留并通过；
- 不修改旧测试以适配错误行为；
- 新测试必须驱动真实 CLI/模块，不只测试复制出来的辅助函数；
- 文件篡改、跨项目、恢复版本、Host Agent ticket 必须使用临时项目真实复现；
- 不调用真实飞书；
- 本轮不要求调用真实模型/API；如调用必须单独说明，不得把模型输出当确定性证明；
- 测试前后报告 `git status --short --branch`；
- 测试不得在仓库留下 projects、缓存、rewrite 临时稿、dist 或密钥。

## 15. 本轮不处理

- 容量预估固定“+10 集”的算法；
- `minimum_total_seconds` 的容量压力整合；
- 基于剩余剧情的动态总时长预测；
- 真实编剧效果测试和创作 Prompt 调优；
- `agents/openai.yaml` 标准化；
- pip 资源打包；
- 发布 ZIP 引用清理；
- 迁移器完整迁移原著、旧 continuity 和全部旧剧本；
- 飞书、OpenClaw、Dashboard、Token 统计；
- 旧版 38 项中的既有 4F/3E。

格式与 XML 分离虽然此前列为中等问题，但它直接对应规格书 P0，本轮必须处理；不得继续延期。

## 16. 禁止事项

- 不合并 `main`；
- 不修改 `fangcun-v2-dev`；
- 不修改旧版 `skills/drama`、旧 agents 或旧 tools；
- 不执行真实飞书写入；
- 不提交 API 密钥、原著、projects、缓存、日志、dist 或真实项目产物；
- 不通过 Prompt 声明替代哈希、状态、版本、ticket 和证据关系校验；
- 不把所有版本文件设为操作系统只读来代替消费端哈希校验；
- 不把所有相同文本强制制造重复物理文件；允许内容存储去重，但逻辑版本必须正确；
- 不删除第一轮测试；
- 不进入 P1/P2 功能扩张；
- 不以“测试数量增加”代替逐项反例证明。

## 17. 完成定义

只有同时满足以下条件才能宣称第二轮完成：

1. 第 4—11 节全部实现；
2. 第 13 节 50 条场景全部有可追溯断言；
3. 第一轮 22 项绕过测试继续通过；
4. unit/regression/smoke 全部通过；
5. 旧版核心文件未修改，旧版基线没有新增失败；
6. review verdict、证据和文件完整性不可从 CLI/文件消费路径绕过；
7. 连续性可在替换和恢复定稿时正确切换，无旧事实或跨项目污染；
8. Host Agent 和 API 自动重写都由系统 provenance 管理；
9. 同内容不同输入生成正确逻辑版本；
10. 历史版本可确定性恢复；
11. setup/payoff 与 must_keep 只能由真实证据满足；
12. revision 撤销后不再传播；
13. context 快照不会因 role 或重新渲染而改变；
14. 内部剧本始终为业务正文，XML 只在 Adapter；
15. Git 工作区没有意外文件；
16. 没有把本轮排除项混入实现。

## 18. 开发完成后的交接要求

创建并提交：

`docs/development/fix-handoff-round2.md`

最终回复和交接文档必须包含以下内容。

### A. Git 状态

- 仓库绝对路径；
- 分支；
- 第二轮起点 `090848f`；
- 第二轮所有 commit hash；
- 最终 HEAD；
- 是否推送；
- 明确未合并 main；
- 最终 git status。

### B. 文件清单

按新增、修改、删除分类；每个文件说明用途。特别说明是否修改 Schema、SKILL、Prompt 和 migration compatibility。

### C. 问题到修复到测试对照

必须逐项覆盖：

- 审核 verdict；
- evidence 关系校验；
- review 文件完整性；
- continuity rebuild；
- delta active version/degraded；
- Host Agent rewrite provenance；
- logical version/idempotency/restore；
- dialogue pairing/must_keep；
- revision revoke/pending/applied；
- context immutability；
- business format/XML adapter。

### D. 数据契约变化

按第 12 节逐项说明字段、创建者、校验者、消费者和迁移策略。

### E. 测试清单

- 第一轮 22 项测试结果；
- 第二轮 50 项测试的测试文件、类、方法和对应编号；
- unit/regression/smoke 总数；
- 旧版基线；
- 独立临时目录反例；
- 是否调用真实 API。

### F. 反例运行证据

至少展示以下修复前后差异：

- error + pass；
- reversed span；
- tampered review；
- 定稿 A -> B；
- 项目 A -> B 隔离；
- Host Agent 二次 rewrite；
- 同文本 H1 -> H2；
- only payoff；
- fake must_keep；
- approved -> rejected；
- incomplete delta；
- legacy XML config。

### G. 兼容性

- 旧 Fangcun Next 状态是否需迁移；
- 第一轮产生的 manifest、draft meta、review、delta、revision 如何处理；
- 旧 XML 剧本如何导入；
- 无法自动迁移的状态如何明确降级或重建。

### H. 未解决问题

列出 P1、P2、模型语义质量、迁移和发布限制。不得宣称整个 Fangcun Next 完成或已达到生产效果指标。

### I. 下一轮独立复审提示词

最终给出一段可直接复制的只读复审提示词，包含：

- 路径、分支、起止 commit；
- 必读本文和 Round 2 handoff；
- 11 类修复；
- 第一轮 22 项 + 第二轮 50 项；
- 要求独立构造反例，不只运行测试；
- P0 逐项核对；
- 只读、不修改、不合并 main；
- 输出剩余问题、严重度、文件/行号、修复建议、P0 表和交接差异。

如任一项未完成，必须明确写“未完成”及原因，不能省略。

## 19. 下一轮独立复审重点

独立评审者应优先尝试：

1. 篡改已保存的 review/context/draft/delta 版本文件；
2. 用合法但相互不一致的 evidence 字段拼装证据；
3. 在同一 Python 进程中交替刷新两个项目；
4. 替换、恢复同一集的不同定稿；
5. 在 Host Agent Mode 中连续执行两次自动重写；
6. 复用、跨集或篡改 rewrite ticket；
7. 同文本跨 context/source/confirmation 保存；
8. 只保留 setup 或 payoff；
9. 让 event 摘要与真实原文冲突；
10. 让 revision 经过 approved/applied/rejected/revoked 组合；
11. 在 legacy 配置下检查内部版本是否仍混入 XML；
12. 检查开发模型是否通过放宽旧断言制造通过。
