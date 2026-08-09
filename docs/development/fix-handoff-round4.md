# Fangcun Next 第四轮修复交接

> 第三轮基线：`144923c6505e68e015acbf371bf50cdcbb37bdcb`
> 第四轮代码提交：`8a361ff882d0b657147739cb2a48ec0c340d7ff9`
> 分支：`codex/fangcun-next-round4`

## 为什么由独立评审者直接修复

前三轮由同一开发模型同时解释合同、实现代码和编写公开测试，出现了多次“指定测试通过，但不变量只修一个入口”的情况。第三轮独立复审先在未改代码时构造了隐藏变体，确认历史版本、delta、pairing、must_keep、审核证据和 ticket 仍可绕过。

第四轮改为：先固定独立失败案例，再由评审者直接修根因；另一个模型如参与，只承担只读复审，不再根据本交接直接补测试或改实现。

## 修复结果

| 范围 | 修复后的不变量 |
|---|---|
| Artifact | 活动/历史读取/历史恢复统一执行项目内相对路径、存在性和内容哈希验证 |
| Delta identity | project instance + episode + current approved version + full script hash + delta hash 全绑定 |
| Delta pointer | pointer 自身字段参与验证；新文件使用完整 hash；旧短 pointer 仅作受验证兼容读取 |
| Rich continuity | 未知顶层/嵌套字段拒绝；notes 可投影但不冒充完整语义提取 |
| Pairing | 事件 key quote 的 setup/payoff 缺端时直接失败并记录原因，不再退化为单句摘录 |
| must_keep | 事件依据必须来自同事件同章节摘录；改编依据必须显式引用 decision id |
| Review evidence | event/chapter 身份不能单独证明 error；quote/span/hash 必须形成可定位证据 |
| Source coordinate | 章节文件保持原始章节切片；事件绑定 coordinate base、chapter hash、excerpt hash，quote/span 错配拒绝 |
| Rewrite audit | ticket 取消必须有 operator/reason；按 context 查找全部 issued ticket，不受写入顺序遮挡 |
| Cross-project | 独立项目实例 ID 阻止同文本、同版本 delta 跨项目复制污染 |

## 第四轮外部案例

新增 `tests/regression/test_round4_external_acceptance.py`，15项。它们在代码修改前全部失败或实际确认绕过，修改后15/15通过。

覆盖历史路径逃逸、相同内容不同逻辑定稿、pointer 篡改、哈希前缀碰撞、跨项目复制、未知 delta 字段、notes 降级、事件配对缺端、must_keep 假来源、自由文本改编授权、event-id-only 审核证据、错误 source span、空理由取消和多 context ticket 顺序。

## 全量验证

```text
unit:       112/112 OK
regression: 133/133 OK
  Round 1: 22
  Round 2: 50
  Round 3: 40
  Round 4: 15
  EP001:    6
smoke:      4/4 OK
旧版基线:   38项中31通过、4失败、3报错（与修复前一致，无新增失败）
```

`skill-creator/quick_validate.py` 因本机没有 PyYAML 无法启动；未联网安装依赖。已用本机 Ruby YAML 对 `SKILL.md` frontmatter 语法、name 和 description 做本地验证，通过。`git diff --check` 和 Python compileall 通过。

## 旧测试的三项契约纠正

1. Round 2 的固定事件 span `end=90` 改为 `89`，因为章节文件现在是未经标题重复/strip 的原始章节切片，真实长度为89；测试意图没有变化。
2. Round 3 篡改测试不再通过安全版 `artifact_version_path` 读取已经被篡改的文件来自我恢复，而是在篡改前保存原始字节；篡改阻断断言没有削弱。
3. adaptation fallback 单元测试改用结构化 decision id，删除“相似自由文本即可授权 must_keep”的旧假设。

## 兼容性

- 未合并或修改旧生产 `fangcun-v2-dev`；旧版基线无新增失败。
- 新项目 manifest 自动获得 `project_instance_id`；旧项目第一次保存新 delta 时确定性补齐。
- 旧短哈希 pointer 不直接信任，只有完整绑定全部匹配才兼容读取。
- 旧事件无 span 时继续 degraded；新事件 span 会自动绑定章节和摘录哈希。
- 旧 XML 导入、内部 default-cn 和可选 XML export 行为由原回归继续覆盖。

## 当前边界

- 本轮只证明确定性技术主链；没有证明真实模型的台词、因果、原著贴合质量。
- 未调用真实模型/API，未执行飞书/OpenClaw 写入。
- continuity delta 的语义抽取质量仍由 Host Agent/模型负责，但错误绑定和跨版本污染已由程序阻断。
- P2 平台集成、正式发布包和大规模旧项目迁移不在本轮。

## 给另一个模型的只读复审提示词

```text
请以独立评审者身份，只读复审 /Users/mac/Documents/ChatGPT/Fangcun分析/fangcun-next 分支 codex/fangcun-next-round4。

第三轮基线：144923c；第四轮代码提交：8a361ff。
必读：
1. docs/development/independent-review-round4-fix-brief.md
2. docs/development/fix-handoff-round4.md
3. docs/specs/fangcun-next-design-spec.md
4. AGENTS.md

请不要根据交接结论直接判定通过。独立构造随机路径、项目、版本、哈希、操作顺序和组合篡改，重点验证：
- 历史与活动 artifact 是否真正共用安全 resolver；
- delta 是否绑定项目实例、当前 logical approved version 和完整 hash；
- pairing、must_keep、审核 evidence 是否仍有替代路径；
- source span 是否从章节归档、事件保存到检索消费使用同一坐标；
- 多 ticket、取消和人工来源是否仍可绕过。

可运行 Round1 22 + Round2 50 + Round3 40 + Round4 15，但不得只依赖测试。全程只读，不修改文件，不合并分支，不联网、不调用 API/飞书。

输出：剩余问题（严重度+文件/行号+复现证据+修复建议）、规格书P0核对、最高风险5文件、是否可进入本地真实内容质量测试。
```
