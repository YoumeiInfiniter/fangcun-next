# Fangcun Next 第四版修改优化方案

> 目标版本：Fangcun Next 0.3.0（Agent-first）  
> 文档性质：产品决策、实施合同与公开验收基线  
> 开发基线：分支 `codex/fangcun-next-0.2.1-fixes`，commit `535cc90eee919b39953a09d3ddb6a02333e6eb5c`  
> 说明：本文中的“第四版”指第四次产品质量改进方案，不是仓库历史上的 `independent-review-round4` 技术修复轮次。

## 0. 文档优先级与使用方法

开发模型必须完整阅读：

1. `AGENTS.md`；
2. `docs/specs/fangcun-next-design-spec.md`；
3. `docs/governance/development-review-workflow.md`；
4. 本合同；
5. 第三轮真实业务测试报告与反馈：
   - `/Users/mac/Documents/ChatGPT/Fangcun分析/fangcun-next-test-projects/bige-dawang-v021-round3/ROUND3_TEST_REPORT.md`
   - `/Users/mac/Documents/ChatGPT/Fangcun分析/fangcun-next-test-projects/bige-dawang-v021-round3/ROUND3_TEST_FEEDBACK.md`

本合同是当前轮次的产品决定。若其与规格书关于 API 默认地位、单集容量传播或审核时长字段的旧描述冲突，以本合同为准，并同步更新规格书。

第三轮测试项目只用于复现问题、比较修复前后行为，不得把其中的人物、题材、情节、风格要求、表现机制或固定集数写入通用 Skill、Schema、Prompt、代码或测试判断。

开发模型负责实现和开发自测，不能宣布独立验收通过。开发完成后由独立评审模型使用未提前公开的变体复审。

---

## 1. 已确认的产品决策

以下决定不得擅自改变：

1. Fangcun 是通用小说转短剧 Skill，不服务于单一作品或单一题材。
2. 编剧是最终作者，AI 是可控创作助手。
3. 改编指引和故事大纲不做大规模重写；本轮重点仍是集纲到剧本。
4. Agent Mode 是默认、正式生产路径。
5. API Mode 保留为实验性 Provider Adapter，但默认工作流不得依赖它。
6. 未配置 API、API 不可用或 API 审核失败，不得降低状态、证据、版本和人工确认门禁。
7. 常规单集不得因为本轮改造增加模型调用次数。
8. 标准单集最多包含一次 Writer 生成和一次 Reviewer 审核。
9. 自动重写默认关闭；只有编剧明确要求修改时才生成一次 rewrite ticket。
10. 不允许自动审核—重写—复审循环。
11. 内容容量和时长仍是建议，不是创作硬门禁。
12. 容量偏高时必须把选择交给编剧，但“接受当前超时方案”本身就是合法选择。
13. 单集超时不得自动返回改编指引、故事大纲或整套集纲重做。
14. 不使用“每集只能一个事件”“每集必须固定几个动作行”等全题材硬规则。
15. 不把任何项目专属表达机制写成通用规则；项目特殊要求只作为当前项目数据进入上下文。
16. 剧本动作质量关注关键叙事节点是否被演出来，不追求无意义的文字膨胀。
17. 编剧确认的人工版本仍是过去剧情最高事实来源。
18. 本轮不接飞书、OpenClaw 平台写入、Token 统计、主 Bot 管理或公司 Dashboard。

---

## 2. 第三轮暴露的通用问题

### 2.1 局部容量信息存在但没有进入创作闭环

当前 Runtime 已能计算 `episode_density_report`，并将结果写入集纲版本元数据和可读 Markdown，但：

- 阶段 Reviewer 没有收到完整的逐集密度摘要；
- `episode_context` 只包含时长目标，没有本集事件最低/理想时长和压力等级；
- Writer 不知道集纲已接近或超过偏好上限；
- 编剧确认集纲时没有被强制展示统一的高/中压力摘要；
- “仅供参考”在运行中被错误等同于“创作时无需管理”。

### 2.2 `must_keep` 承担了过多职责

现有集纲可能把以下不同内容都塞入 `must_keep`：

- 必须发生的剧情；
- 必须保留的原文台词；
- 人物关系或设定边界；
- 项目表达要求；
- 柔性风格提示。

Writer 又被要求落实全部 `must_keep`，于是只能优先完整塞入，缺少压缩、延后和取舍空间。

### 2.3 草稿时长由 Reviewer 猜测

现有 `duration_estimator` 可以确定性计算台词字数、动作行、停顿、转场和预计时长，但 `save-draft` 与 `review` 没有把结果绑定到当前草稿。Reviewer 可以输出一个未经计算的秒数并成功保存，导致报告与 Runtime 计算互相矛盾。

### 2.4 动作行已有文字要求，但缺少执行合同

现有 Writer Prompt 已要求动作具体、可拍、有主体和可见结果；Reviewer 也有 shootability 维度。问题在于：

- 集纲没有指出哪些关键节点必须视觉化；
- Writer 面临事件、台词、因果和时长冲突时，动作表现优先级最低；
- 关键转折被概述时经常只判 warning；
- 动作描写不足不会进入有边界的定向修复；
- 没有区分“关键过程没演出来”和“纯审美上还能更细”。

### 2.5 API Mode 目前不是可靠生产路径

当前 API 链存在输出截断、Schema 未真实注入、阶段证据不足、模型自行构造证据坐标失败和重复重试等问题。本轮不投入完整 API 重构，但必须做到：

- 默认不调用；
- 不被正常工作流自动选择；
- 使用时明确标记 experimental；
- 截断、空输出、非法 JSON 和门禁失败必须诚实停止；
- 不允许静默转成“API 审核成功”。

---

## 3. 目标架构

```text
Host Agent（默认正式路径）
    │
    ├── 读取精简 Skill 与按需 reference
    ├── 消费不可变 stage_context / episode_context
    ├── Writer：一次生成
    └── Reviewer：一次同源审核
             │
             ▼
Deterministic Runtime
    ├── 状态、版本、哈希与人工确认
    ├── 原文证据与连续性
    ├── 集纲局部容量报告
    ├── 草稿确定性时长指标
    ├── 格式、Schema 与审核保存门禁
    └── 编剧覆盖记录

Experimental API Adapter（非默认、非依赖）
    └── 只能复用同一上下文与保存门禁，不能拥有旁路
```

核心系统不得根据宿主是 Codex、OpenClaw 或其他 Agent 改变数据契约。宿主只负责理解用户、调用 CLI、生成内容和展示结果。

---

## 4. 标准与快速使用模式

### 4.1 标准模式（默认）

单集流程固定为：

```text
构建或复用 episode_context
→ Writer 生成一版剧本
→ 本地格式与 draft_metrics 校验
→ Reviewer 对同一上下文和草稿审核一次
→ 展示剧本、确定性时长、审核问题和编剧选项
→ 停止并等待编剧
```

约束：

- 不自动重写；
- 不自动复审；
- warning 不自动触发模型调用；
- 编剧明确要求修改后，才执行一次 Rewriter；
- 重写后是否复审由编剧决定或按项目明确策略执行一次，禁止循环。

### 4.2 快速草稿模式（可选）

流程：

```text
构建或复用 episode_context
→ Writer 生成一版剧本
→ 本地格式与 draft_metrics 校验
→ 标记为 unreviewed_draft
→ 展示并停止
```

快速草稿不得被标记为审核通过、定稿或连续性事实。编剧随后可要求执行标准审核。

### 4.3 模式记录

每版草稿至少记录：

- `generation_mode`: `host_agent` 或 `experimental_api`；
- `workflow_mode`: `standard` 或 `quick_draft`；
- `context_hash`；
- `draft_hash`；
- `draft_version`；
- 是否已执行语义审核。

---

## 5. 集纲合同 V2：通用、柔性、向后兼容

### 5.1 设计原则

- 不用一个固定事件数约束所有题材；
- 不把项目规则伪装成剧情必保留项；
- 不新增一次独立的 Beat Plan 模型调用；
- V2 字段在原有集纲生成调用中一次产出；
- 老项目继续可读；迁移不得改写历史版本。

### 5.2 新字段

`episode-outline.schema.json` 增加以下可选但推荐字段：

```json
{
  "episode_focus": "观众看完本集最应记住的核心变化；可以涵盖多个相关事件",
  "required_story_beats": [
    {
      "id": "B01",
      "text": "必须发生的剧情变化",
      "event_ids": ["CH001-E01"],
      "adaptation_decision_id": null,
      "priority": "core"
    }
  ],
  "required_quotes": [
    {
      "quote": "需要保留的原句",
      "source_event_id": "CH001-E01",
      "pair_id": null
    }
  ],
  "project_rule_refs": ["PRJ-RULE-001"],
  "optional_beats": [
    {
      "id": "B03",
      "text": "可压缩、删除或延后的内容",
      "event_ids": ["CH001-E03"]
    }
  ],
  "beat_plan": [
    {
      "beat_id": "B01",
      "function": "本 Beat 对本集的作用",
      "event_ids": ["CH001-E01"],
      "priority": "core",
      "presentation": "full",
      "estimated_seconds": [20, 35],
      "entry_state": "进入 Beat 前可见状态",
      "visible_outcome": "Beat 结束时观众可见的变化",
      "required_visual_beats": ["必须在画面或表演中落地的关键动作/反应"]
    }
  ],
  "overflow_options": [
    {
      "beat_id": "B03",
      "allowed_actions": ["compress", "defer", "accept_overflow"]
    }
  ]
}
```

字段语义：

- `episode_focus` 是观众记忆中心，不等于“只能有一个事件”；
- `required_story_beats` 只存不可省略的剧情变化；
- `required_quotes` 只存需保留或需成对保留的台词；
- `project_rule_refs` 只引用当前项目已经确认的规则，不复制规则正文；
- `optional_beats` 为压缩与延后提供安全出口；
- `beat_plan` 是同一次集纲生成的结构，不创建新模型阶段；
- `required_visual_beats` 只标关键动作、反应和局面变化，不要求所有动作都扩写；
- `overflow_options` 只提供选择，不替编剧决定。

### 5.3 项目专属规则

项目配置可新增通用容器：

```json
{
  "project_specific_requirements": [
    {
      "id": "PRJ-RULE-001",
      "text": "由编剧为当前项目明确的特殊表达或内容要求",
      "scope": "project_wide"
    }
  ]
}
```

核心代码只保存、绑定、路由和展示这些规则，不理解或硬编码任何具体表现方式。

### 5.4 旧 `must_keep` 兼容

- 保留对旧 `must_keep` 的读取、证据验证和渲染；
- 新生成集纲不得再把项目规则、柔性风格或关系边界混入 `must_keep`；
- 迁移旧集纲时把无法可靠分类的条目标记为 `legacy_unspecified`，不得凭模型猜测后静默改类；
- 不修改旧版本文件；新结构只进入新逻辑版本；
- Source Retriever 同时支持旧 `must_keep` 和 V2 的 `required_story_beats` / `required_quotes`。

---

## 6. 局部容量闭环

### 6.1 计算

继续复用并扩展 `episode_density_report`：

- 绑定本集活动集纲版本和内容哈希；
- 统计事件最低/理想时长；
- 对比本集建议区间；
- 标记 `low` / `medium` / `high`；
- 输出置信度和计算依据；
- 明确 `advisory_only: true`。

不得只用事件数量判断容量，不得用固定题材阈值判断。

### 6.2 传播

密度报告必须进入：

1. 集纲 JSON 对应版本元数据；
2. 集纲可读 Markdown；
3. 集纲 Reviewer 上下文中的聚合摘要；
4. 当前 `episode_context.advisory_timing.density_report`；
5. Writer Prompt 的精简本集摘要；
6. Reviewer Prompt 的同一摘要；
7. 编剧确认集纲前的集中风险清单。

Writer/Reviewer 只加载当前集完整报告，不加载全30集全部细节。

### 6.3 集纲确认时的编剧选择

若集纲存在 medium/high：

- Agent 一次性汇总数量和高风险集；
- 编剧可以要求调整部分集数；
- 编剧也可以明确接受当前规划；
- 不逐集弹出几十个确认问题；
- 不自动禁止确认；
- `confirm-stage --stage episode_outline` 必须记录本次容量决定，例如：
  - `accept_current_plan`；
  - `changes_recorded`；
  - `not_applicable`（无 medium/high 时由系统推导）。

容量决定必须绑定当前集纲版本与哈希。后续集纲版本变化后应重新展示；已确认版本不得重复提醒同一风险。

### 6.4 剧本阶段的处理

- 若编剧已接受集纲容量，Writer 可以按合同生成，即使预计超出偏好区间；
- Writer 不得因为 `advisory_only` 而忽视压缩与延后选项；
- Writer 应优先完成 core Beat 的完整因果，把 optional Beat 按已确认策略处理；
- 合同自身无法同时满足时，Agent应在生成前说明冲突并询问一次，不得静默删除必保留内容；
- 单集草稿实际超时后只提示，不回滚上游。

---

## 7. 草稿确定性时长指标

### 7.1 `draft_metrics`

`save-draft` 成功校验格式后，必须使用当前 Runtime 计算并保存与草稿绑定的指标：

```json
{
  "episode": 1,
  "context_hash": "...",
  "draft_version": "v001",
  "draft_hash": "...",
  "estimator_version": "v2",
  "dialogue_chars": 0,
  "action_chars": 0,
  "action_lines": 0,
  "scene_count": 0,
  "reaction_count": 0,
  "estimated_seconds": 0,
  "estimated_range": [0, 0],
  "preferred_seconds": [0, 0],
  "deviation": "within|below|above|unknown",
  "blocking": false
}
```

要求：

- 指标绑定 `context_hash + draft_version + draft_hash`；
- 草稿内容变化后旧指标不得用于新版本；
- 指标由 `source=system` 保存；
- 相同草稿重复保存保持幂等；
- 时长始终是估算，报告中显示口径和可校准参数；
- 不宣称估算值等于真实成片时长。

### 7.2 审核使用

- `review` 构建 Reviewer Prompt 时注入当前绑定的 `draft_metrics`；
- Reviewer 不再自行计算或猜测秒数；
- 模型只评价节奏、拥挤位置、可压缩处和压缩风险；
- 最终保存的 `timing_advisory` 必须来自 Runtime；
- 模型返回不同秒数时不得覆盖系统值；
- 为兼容旧审核报告，旧值只有与当前 `draft_metrics` 一致时才能保留，否则明确拒绝或迁移为 `legacy_model_estimate`，不得作为当前事实。

### 7.3 估算器改进边界

本轮可以：

- 保留台词、动作、反应、转场分口径；
- 为动作行中的多个可见 Beat 提供保守估算；
- 允许公司以后配置真实读速和经验参数；
- 为低置信度输出更宽区间。

本轮不得：

- 用一个总字数/分钟值替代所有指标；
- 硬编码未经真实样本校准的公司参数；
- 因估算超时阻止编剧确认；
- 为追求伪精确而引入新的模型调用。

---

## 8. 非台词描写与可拍性

### 8.1 通用质量目标

关键叙事节点应让演员、分镜或画面生成流程知道：

- 谁在行动；
- 对谁或什么行动；
- 身体、位置、道具或表情发生什么可见变化；
- 对方或现场产生什么可见反应；
- 这一拍如何推动下一句台词或下一个 Beat。

不要求每条动作行都很长。动作行应以可见变化为单位，避免把多个独立 Beat 压进一句概述。

### 8.2 通用示例

较弱：

```text
△她很难过。
```

较可执行：

```text
△她抬手按住门把，停了两秒，最终把手收回。
```

示例只说明“抽象情绪”与“可见行为”的区别，不规定镜头、题材、人物或风格。

### 8.3 Writer 调整

Writer 必须优先落实集纲中的 `required_visual_beats`：

- 核心动作结果；
- 关键情绪转折；
- 关系发生变化的可见瞬间；
- 因果链中的必要反应；
- 集末钩子的可见落点。

Writer 不得通过增加无功能的走位、表情词或镜头术语机械扩写。动作细节必须服务于因果、人物或节奏。

### 8.4 Reviewer 严重度

- `error`：核心剧情、因果、认知变化或合同要求只被概述，没有实际演出，导致观众无法理解发生过程；
- `warning`：剧情可以理解和拍摄，但关键表演层、可见反应或空间变化过薄；
- `suggestion`：不影响理解与拍摄的纯审美优化。

Reviewer 不得因为动作行较短就自动报错，也不得因为格式含有 `△` 就判定可拍性通过。

### 8.5 Craft 路由

- 可拍性是所有剧本的通用底线，应进入 Writer/Reviewer 核心职责；
- 题材化视听方法仍按需加载；
- 不把任何项目专属表达方法加入 `ALWAYS_MODULES`；
- 不为提高动作质量全量加载所有 Craft。

---

## 9. Agent-first 与 API 实验边界

### 9.1 Host Agent 正式能力

Host Agent 必须能够完成：

- 三个规划阶段的生成、同源审核和等待编剧确认；
- 单集 Writer、Reviewer 和显式 Rewriter；
- 人工版本导入；
- 项目状态与当前产物展示；
- 无外部 API 条件下的完整本地创作流程。

“无 API”不再称为质量降级。只要 Reviewer 实际消费同源上下文并按 Schema 保存，审核来源记录为 `host_agent`，就是正式支持模式。它不等于独立模型审核，交接和 UI 必须如实标注来源。

### 9.2 API Mode

本轮要求：

- 从 `SKILL.md` 默认路径中移除 API 推荐；
- CLI 保留显式 `--api` 接口以兼容和实验；
- 调用前输出 experimental 提示；
- 只有用户明确要求或项目配置明确启用时才允许调用；
- 未明确启用时不得因为检测到 API Key 就自动选择 API；
- 所有 API 输出继续通过与 Host Agent 相同的保存门禁；
- 检查 `finish_reason`、空正文和非法响应，失败时保留错误并停止；
- 不自动重试多轮；
- 不自动回退后冒充 API 审核成功。

本轮不要求：

- 完整阶段分块 API 审核；
- 多模型路由；
- API 批量并行；
- 自动 Schema 修复循环；
- API 成本统计；
- 把 API 恢复为默认生产链。

### 9.3 模式一致性

Host Agent 与 experimental API 必须共用：

- 同一不可变上下文；
- 同一 Prompt 来源；
- 同一 Schema；
- 同一版本与哈希绑定；
- 同一证据验证；
- 同一 verdict 推导；
- 同一人工确认门禁。

不得为了让 API 更容易通过而放宽核心不变量。

---

## 10. OpenClaw 编剧使用体验约束

虽然本轮不开发 OpenClaw Adapter，但核心 Skill 必须为后续接入提供以下行为。

### 10.1 模型调用预算

| 操作 | 标准模式最大模型调用 | 快速草稿最大模型调用 |
|---|---:|---:|
| 生成单集初稿 | 1 | 1 |
| 单集初次审核 | 1 | 0 |
| 本地格式/时长/状态检查 | 0 | 0 |
| 自动重写 | 0 | 0 |
| 自动复审 | 0 | 0 |

编剧明确要求一次重写后可以增加一次 Rewriter 调用。不得由系统自行累计调用。

### 10.2 上下文预算

- 复用已生成的不可变 `episode_context`；
- Writer 与 Reviewer 不重复扫描整本小说；
- 只加载当前集证据、必要依赖和上一集确认事实；
- 密度报告只注入当前集摘要；
- 项目规则使用 ID + 当前适用内容，不复制无关规则；
- `SKILL.md` 保持精简，详细规则按需读取一层 reference；
- 不把测试报告、开发合同或历史 Bug 说明打包进发布 Skill。

### 10.3 交互要求

- 长操作开始时说明当前正在进行的阶段；
- 完成生成后立即展示产物路径、版本和时长摘要；
- 审核完成后展示 verdict、主要问题和编剧选项；
- 需要编剧选择时只问必要问题；
- 集纲容量风险一次汇总，不逐集轰炸；
- 任何阶段等待人工确认时停止当前任务；
- 不因“帮我全部跑完”推断获得跨阶段预授权。

### 10.4 性能验收目标

以下用于防止实现退化，不承诺不同模型服务的固定生成时间：

- 新增本地确定性步骤在代表性项目中总耗时应低于 1 秒；
- 标准单集不得新增第三次模型调用；
- 快速草稿不得调用 Reviewer；
- 不调用 API 时不得发生任何外部模型请求；
- 固定 Prompt 与合同新增部分应保持精简，不得把整份全剧容量报告或全项目历史注入单集；
- 测试报告必须分开记录本地 Runtime 耗时、宿主模型耗时和实验 API 耗时；
- 不得把完整回归测试总耗时当成编剧单集等待时间。

---

## 11. 状态、版本与人工决策

### 11.1 不得回归的现有不变量

必须保留 0.2.1 已实现的：

- 不可变版本文件；
- 活动版本单一解析；
- 项目实例、配置、上游版本和内容哈希绑定；
- Writer/Reviewer/Rewriter 同源 `context_hash`；
- `draft_hash` / `draft_version` 审核绑定；
- rewrite ticket 单次消费；
- 证据 quote/span/event 关系验证；
- 人工修改、版本激活和连续性重建；
- 阶段审核后必须等待新的编剧消息；
- 编剧定稿影响后续连续性。

### 11.2 新增决策记录

至少新增或扩展：

- `workflow_mode`；
- `generation_mode`；
- `semantic_review_status`；
- 集纲容量确认决定；
- 草稿 `draft_metrics` 绑定；
- 编剧对时长 warning 的接受记录。

编剧已经明确接受某版本时长后，不得在同一版本上重复阻塞式询问；新草稿若实际指标明显变化，可以提示新的偏差。

---

## 12. 兼容与迁移

### 12.1 旧项目

- 0.2.1 项目必须可继续读取；
- 旧集纲、旧审核、旧草稿和旧定稿不得被原地改写；
- V2 集纲字段采用向后兼容扩展；
- 新生成内容使用 V2；
- 旧 `must_keep` 保持可验证；
- 缺少 `draft_metrics` 的历史草稿在首次审核时可以按当前文件生成绑定指标，但必须标记 `backfilled_by_system`，不能改写旧草稿文件；
- 历史模型时长值保留作记录，但不再作为当前确定性事实。

### 12.2 发布版本

同步更新：

- `pyproject.toml`；
- `scripts/__init__.py`；
- `scripts/release_builder.py` 默认版本；
- 发布清单和 ZIP；
- 必要的 agents 元数据（仅在行为描述变化时）。

发布 Skill 不包含：

- `docs/development/`；
- `docs/research/`；
- 测试项目；
- 小说原文；
- API Key 或本地配置；
- 第三轮测试报告；
- 开发模型交接内容。

---

## 13. 建议修改范围

开发模型必须先检查实际调用链，再决定最终文件，但预计高风险文件包括：

- `SKILL.md`；
- `references/workflow.md`；
- `references/business-principles.md`；
- `references/review-rubric.md`；
- `references/prompts/stage_episode_outline.md`；
- `references/prompts/writer.md`；
- `references/prompts/reviewer.md`；
- `references/schemas/project-config.schema.json`；
- `references/schemas/episode-outline.schema.json`；
- `references/schemas/episode-context.schema.json`；
- `references/schemas/review-report.schema.json`；
- `scripts/stage_lifecycle.py`；
- `scripts/context_builder.py`；
- `scripts/duration_estimator.py`；
- `scripts/prompt_router.py`；
- `scripts/project_cli.py`；
- `scripts/model_adapter.py`（仅实验模式诚实失败所需的最小改动）；
- `scripts/migration.py`；
- 对应 unit / regression / smoke 测试；
- `docs/specs/fangcun-next-design-spec.md`。

不要为了完成本合同重写状态存储核心、连续性核心或发布结构。若必须修改，交接中单独说明原因、风险和新增回归。

---

## 14. 实施顺序

### 阶段 A：基线与范围确认

1. 确认分支、HEAD 和工作树；
2. 运行当前 unit、regression、smoke 和旧版基线；
3. 记录修复前测试数量；
4. 只读复现第三轮的容量、时长和审核来源问题；
5. 不调用真实 API。

### 阶段 B：Agent-first 与流程瘦身

1. 更新规格书和 Skill 默认路径；
2. 增加标准/快速草稿模式；
3. 删除默认 API 推荐和自动选择；
4. 明确审核来源；
5. 禁止自动重写循环。

### 阶段 C：局部容量传播

1. 扩展 density report 绑定；
2. 注入 stage review 与 episode context；
3. 在集纲确认前输出聚合摘要；
4. 记录编剧容量决定；
5. 保证 accept overflow 可继续。

### 阶段 D：集纲合同 V2

1. 扩展 Schema；
2. 更新集纲 Prompt 与 Renderer；
3. 更新证据检索；
4. 增加旧 `must_keep` 兼容；
5. 保证不增加独立模型阶段。

### 阶段 E：草稿指标与审核

1. 生成绑定 `draft_metrics`；
2. 注入 Reviewer；
3. 由 Runtime 生成最终 timing advisory；
4. 修复旧审核兼容；
5. 阻止模型时长覆盖系统指标。

### 阶段 F：可拍性闭环

1. 集纲增加关键视觉 Beat；
2. 更新 Writer/Reviewer 通用规则；
3. 调整 shootability 严重度；
4. 验证不产生机械动作膨胀；
5. 运行多类型测试。

### 阶段 G：API 最小隔离与发布

1. 增加 experimental 标记；
2. 检测截断和空输出；
3. 确认默认流程零 API；
4. 完整回归；
5. 版本升级并构建发布包；
6. 生成开发交接。

---

## 15. 公开开发验收案例

开发模型必须为以下通用行为增加测试，但独立评审仍会改变路径、内容、顺序和数据形态。

### A. 局部容量不能丢失

构造三个通用事件，其最低时长之和高于单集建议上限：

- 保存集纲成功；
- density 为 high；
- 集纲可读版、stage review context 和 episode context 均能读取同一结果；
- 编剧选择 `accept_current_plan` 后可以进入剧本；
- 不得自动回滚上游。

### B. 低事件容量但草稿实际超时

构造 density 为 low 的集纲，再保存一份台词明显较长的合法剧本：

- `draft_metrics` 必须判定 above；
- Reviewer Prompt 必须包含真实指标；
- 最终审核不得保存模型猜测的不同秒数；
- 时长仍为 warning，不阻止编剧定稿。

### C. 可拍性关键缺失

构造一个关键关系/因果变化只写成抽象概述的剧本：

- Reviewer 必须识别核心过程没有演出；
- 若影响因果或合同落实，严重度为 error；
- 不能因存在动作符号而通过。

### D. 简洁但合格的动作

构造动作行很短、但主体、动作和可见结果完整的剧本：

- 不得仅因行短或动作字数少报错；
- 不得为了达到固定比例机械扩写。

### E. 项目规则隔离

在项目 A 配置一个特殊表达要求，项目 B 不配置：

- 项目 A 的 episode context 能引用该要求；
- 项目 B 的 Prompt、Schema 默认值和输出中不得出现项目 A 内容；
- 不得按项目名、人物名或固定文本硬编码。

### F. 标准与快速模式

- 标准模式生成一次 Writer 包和一次 Reviewer 包；
- 快速模式不生成 Reviewer 调用，不得标记已审核；
- 两种模式均执行本地格式与 draft metrics；
- 快速草稿不能直接更新连续性。

### G. 默认零 API

在环境中存在 API Key 的情况下运行默认 Host Agent 流程：

- 不得发生网络请求；
- 不得自动选择 API；
- 产物来源正确标记 `host_agent`。

显式实验 API 返回 `finish_reason=length`：

- 必须明确失败；
- 不保存审核报告；
- 不自动重试；
- 不伪装成 Host Agent 或 API 审核成功。

### H. 旧项目兼容

加载只有旧 `must_keep`、没有 V2 字段和 `draft_metrics` 的项目：

- 可以读取和构建上下文；
- 历史文件不被改写；
- 新草稿生成新指标；
- 新集纲版本使用 V2；
- 活动版本和历史版本仍可分别读取。

### I. 多类型泛化

至少覆盖：

- 对话密集；
- 信息差或悬念；
- 动作推进；
- 后段连续性依赖。

验证 V2 不把所有集数强制成相同事件数量、相同场次数或相同动作密度。

### J. 性能预算

通过 mock/counter 证明：

- 标准单集模型调用预算不超过 Writer 1 + Reviewer 1；
- 快速草稿只包含 Writer 1；
- warning 不触发自动重写；
- 新增本地步骤在代表性夹具上低于 1 秒；
- 单集 Prompt 不包含全剧所有 density 明细或完整历史产物。

---

## 16. 完整测试要求

开发完成必须运行并报告：

1. 新增 unit；
2. 全部现有 unit；
3. 全部 regression；
4. smoke；
5. EP001 回归；
6. 旧版行为基线；
7. 本合同公开案例；
8. 发布包构建和 Skill 验证；
9. 默认零 API 网络调用测试；
10. 代表性本地性能测试。

要求：

- 报告修复前与修复后的测试数量；
- 旧基线已有失败可以保留，但不得新增失败；
- 不得跳过失败后只报告部分绿灯；
- 不调用真实外部 API；
- 不执行飞书或 OpenClaw 写入；
- 不修改第三轮测试项目中的原文和产物；
- 开发模型自写测试通过只算开发自测。

---

## 17. 完成定义

只有同时满足以下条件，本轮开发才能交给独立评审：

- Agent Mode 成为清晰、完整、默认的正式路径；
- 默认流程不调用 API；
- API 明确为实验性且失败诚实；
- 常规标准单集没有新增模型调用；
- 快速草稿模式可用且不会冒充审核稿；
- 集纲局部容量真实进入 Writer 和 Reviewer；
- medium/high 可由编剧一次性接受或调整；
- 超时不自动回退上游；
- 草稿时长由 Runtime 绑定生成；
- 模型不能覆盖确定性时长；
- 集纲合同能区分剧情、台词、项目规则和可选内容；
- 关键可拍性问题进入合同和审核闭环；
- 不存在单案例规则污染；
- 旧项目可以继续读取；
- 0.2.1 的状态、版本、证据和连续性不变量不回归；
- 完整测试无新增失败；
- 发布包为 0.3.0；
- 开发交接诚实列出剩余限制。

---

## 18. 明确不做

本轮不得扩展：

- 完整 API 生产化；
- 阶段 API 分块并行；
- 多模型自动路由；
- Token 成本统计；
- 飞书同步；
- OpenClaw Bot 管理；
- 公司项目 Dashboard；
- 向量数据库或知识图谱；
- 全自动批量生成整本并定稿；
- 自动无限重写；
- 根据单一案例添加全局风格模板；
- 用固定事件数、固定动作数或固定场次数约束所有剧本；
- 对改编指引和故事大纲进行无关重构；
- 修改旧版 `fangcun-v2-dev`；
- 合并 `main` 或写入生产环境。

---

## 19. 开发交付

开发模型应在新分支上实施，建议分支：

```text
codex/fangcun-next-v0.3.0-agent-first
```

建议按独立模块提交，不把全部修改压成一个不可审计 commit。

开发完成新增：

```text
docs/development/fix-handoff-v0.3.0-agent-first.md
```

交接必须包含：

- 起点 commit；
- 全部新增 commit；
- 最终 HEAD；
- 每项需求对应的修改文件和测试；
- 修复前/后测试命令与数量；
- 是否调用真实 API；
- 是否执行平台写入；
- 模型调用预算验证；
- 本地性能结果；
- 与 0.2.1 的兼容变化；
- 已知限制；
- 风险最高的 5 个文件；
- 发布 ZIP 路径和 SHA256；
- 给独立评审模型的简短只读复审提示词。

开发模型不得修改或删除本合同来适配实现。如发现合同内部冲突，应保留现场并说明阻塞，不得自行降低要求。
