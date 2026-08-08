---
name: drama
description: |
  小说转短剧剧本引擎。流程：原文+改编idea→改编指引→新故事大纲→集纲→剧本。
  触发方式：「写剧本」「改编短剧」「小说转剧本」「帮我写剧本」
allowed-tools: Bash(python *)
---

# fangcun-drama：短剧剧本引擎

## 🚫 飞书平台铁律

**禁止以任何形式开启话题（Thread）。** 所有消息——包括产出物、审核报告、进度通知、确认询问——必须直接发送在主对话中。话题模式下智能体无法获取上文导致上下文断裂，任何回复都无法接续之前的讨论。此为硬性规则，所有 agent 均须遵守。

## 三步走核心流程

```
改编指引 → 审核 → 🔴门控 → 故事大纲 → 审核 → 🔴门控 → 集纲 → 审核 → 🔴门控 → 剧本编写 → 导出
```

**子技能分工**：
| 阶段 | 调用技能 | 技能目录 |
|------|---------|---------|
| 改编指引生成 | `fangcun-adaptation` | `skills/adaptation/` |
| 各阶段审核 | `fangcun-supervision` | `skills/supervision/` |
| 故事大纲/集纲/剧本/导出 | `fangcun-drama`（本技能） | `skills/drama/` |

⚠️ **不可跳步**。每个阶段产出独立文件，业务组长可按需单独审核（如只看集纲、只看故事大纲）。同时沉淀为过程资产——改编指引可复用于同类项目，故事大纲可做投流素材参考，集纲可做分镜依据。

**核心逻辑**：
- 改编指引 = 柔性提示（守住底线：自洽 + 不碰红线 + 合乎时代）
- 故事大纲 = 基于改编指引 → 设计新故事的全剧蓝图，**锁定所有创作决策**（人物关系、故事逻辑、矛盾体系、关键剧情——在此阶段全部敲定，不再返工）
- 集纲 = 基于大纲的创作决策 → 做**节奏拆解**（每集的情绪变化、付费节点、钩子设计、删减决策。不重新讨论人物关系和故事逻辑，只做落地编排）
- 剧本 = 最终写出每一句台词

⚠️ **改编哲学**：系统守住底线，编剧驱动创作。爽虐反转等创意决策以编剧指令为主，系统不越位。

**整体大节点**：原文+改编idea → 改编指引 → 新故事大纲 → 集纲 → 剧本全文

### 各级产出物的关系

| 层级 | 产出物 | 核心问题 | 粒度 | 基于什么 | 编剧看什么 |
|------|--------|----------|------|----------|-----------|
| 1 | **改编指引** | 用户的改编idea会导致什么？有什么需要注意？ | 提示（柔性） | 原文事件表 + 用户idea | 改编方向和风险提示 |
| 2 | **故事大纲** | 改编后新故事讲什么？人物关系怎么调？ | 宏观蓝图 + 创作决策 | 改编指引 + 事件表 | **人物关系、故事逻辑、矛盾体系 → 全部在此敲定** |
| 3 | **集纲** | 每集情绪怎么走？付费点卡哪？ | 节奏拆解 | 故事大纲（不重新讨论创作决策） | **节奏、情绪变化、付费节点、集末钩子** |
| 4 | **剧本** | 每一句台词 | 场次/对白 | 集纲 + 上下文 | 完整对白 |

**渐进逻辑**：改编指引（提示）→ 故事大纲（蓝图，锁定所有创作决策）→ 集纲（节奏落地，不重新讨论人物和逻辑）→ 剧本（产出）。
每一步都是上一步的细化，不重新发明。

### 分场 / 分集结构铁律

- **分场只按三项判断：同一时间、同一地点、同一内外关系**。三项一致的连续戏，原则上合并为同一场；三项任一发生变化，才拆成新场。不得按“戏剧关系/情绪功能/信息功能变化”单独拆场；这些变化应在同一场内用动作行、镜头切换或子区域标注承接。
- 体育馆比赛现场、宴会厅、战场、会议厅等大场景可统一为一个大场景，但必须在动作行标注子区域：如「△看台上」「△解说席」「△对站台」「△后台」。
- 1.5-2分钟单集要控制戏量均衡，避免一集空泛、一集塞多个大事件；确需长短差异时必须在分集说明中写明取舍原因。
- 本地门禁：`python3 skills/fangcun/skills/drama/tools/story_structure_guardrails.py <story_skeleton_or_script.md>`。

### ⚠️ 大纲与集纲的分工铁律

**大纲阶段锁定**（不可在集纲阶段返工）：
- 人物关系调整
- 故事逻辑链
- 核心矛盾体系
- 角色身份/性格/弧线

**集纲阶段只做**（在大纲决策基础上落地）：
- 每集情绪曲线
- 付费节点位置和内容
- 集末钩子设计
- 章节删减/压缩决策
- 节奏编排

> 如果编剧在集纲阶段对人物关系或故事逻辑有意见 → 回大纲阶段调整，不边写集纲边改逻辑。

**改编哲学**：系统守住底线（自洽、红灯、时代），编剧驱动创作。改编指引是柔性提示不是硬性规定。

**不跳步原则**：
- 故事大纲通过 → 才能进入集纲
- 集纲通过 → 才能进入改编策略
- 改编策略通过 → 才能写剧本
- 每个门控必须经过人工确认

## 你是 agent，负责：

1. **理解用户意图**（"把这本书改成短剧" → 跑全流程）
2. **组装正确的命令**
3. **强制执行审核门控**：每个阶段完成后**必须**运行 review、**必须**读审核报告、**必须**向用户汇报、**必须**等待确认后才能继续。**发现审核门控被跳过 = 你的严重失职。**
4. **直接写剧本（Agent Mode，默认）**：agent 作为 LLM 直接写剧本，不调外部 API 绕一圈。读 prompts/script.md + 上下文 → 写 → --save-draft 保存 → --validate-draft 校验 → --mark-pass/blocked
5. **检查输出质量**（剧本格式、字数、角色名）
6. **处理错误**
7. **自动同步飞书文档**：每个阶段产出后自动写入飞书 docx（如项目有 Feishu 配置）。没有在线文档链接/附件不得宣布完成。
8. **执行交付门禁**：script 批次确认后必须同步对应批次剧本文档；export 后必须同步完整导出文档；禁止只发卡片摘要。

## Agent Mode（默认）— 剧本编写

Pipeline 默认以 `--mode agent` 运行（默认值，可省略）。在 Agent Mode 下：

- **`--phase event / skeleton / adaptation / review`** 仍调外部 API（这些阶段需要大批量文本处理）
- **`--phase script`** 不调 API，改为提供上下文（骨架、策略、事件、前集）给 agent，agent 自己写
- **`--review-draft / --rewrite-draft`** 不调 API，改为本地校验 + 打印内容，agent 自己判断

### 剧本编写流程（Agent Mode）

```
--phase script --start N --end M
    ↓ 创建批次 + 输出上下文
    ↓
按集循环：
  读 prompts/script.md（剧本格式 prompt 模板）
  读 prompts/writing-methods.md（写作方法论参考）
  根据上下文写剧本
  --save-draft --episode N --file /tmp/ep_N.txt  → 保存草稿
  --validate-draft --episode N                    → 本地校验（字数/△标记）
  agent 自审                                     → 判断质量
  --mark-pass --episode N                         → 通过
  或 --mark-blocked --episode N --reason "..."    → 阻塞
    ↓
--confirm-draft-batch  → 确认批次，提升到 scripts/
--export                → 导出完整剧本
```

### Agent Mode 命令速查

| 命令 | 作用 |
|------|------|
| `--mode agent` | 默认模式，agent 直接写剧本（可省略） |
| `--mode api` | 传统模式，调外部 API 生成剧本（向后兼容） |
| `--phase script --start N --end M` | Agent Mode：创建批次 + 输出所有集上下文到 stdout |
| `--get-context --episode N` | 输出单集完整生成上下文（骨架片段、改编策略、前集、连续性状态） |
| `--save-draft --episode N --file <path>` | 保存 agent 写好的草稿文件到批次目录 |
| `--validate-draft --episode N` | 本地校验（字数、△标记），输出结果 |
| `--review-draft --episode N` | Agent Mode：读取草稿 + 校验 + 打印全部内容（agent 自审用） |
| `--mark-pass --episode N` | 手动标记某集通过审核（写 .pass 标记） |
| `--mark-blocked --episode N --reason "..."` | 手动标记某集阻塞（写 review report） |
| `--confirm-draft-batch` | 确认批次，提升到 scripts/（两模式通用） |

### Agent 写剧本时要遵循的规范

1. **先读 prompts/script.md**——这是剧本格式的 prompt 模板，包含了所有格式要求
2. **用 `--get-context --episode N` 获取上下文**——单集上下文比批量输出更聚焦
3. **格式要求**：
   - 用 `<scriptItem name="...">...</scriptItem>` XML 标签包裹
   - 用 △ 标记场景描述
   - 对话用 `角色（表情/语气/动作）：台词`，VO/OS 用 `角色VO：` / `角色OS：`
4. **质量控制**：
   - 写完后立即 `--validate-draft` 检查字数/△标记
   - agent 自审：检查角色名一致性、场景价值、废笔
   - 自审通过后 `--mark-pass`
5. **如阻塞**：`--mark-blocked --episode N --reason "具体问题"`，然后可以重新写并 `--save-draft` 覆盖

## Reference video / existing drama workflow

If the user asks to benchmark an existing short drama, gives only a title, or asks for “视频转剧本”：

- Do not pretend the bot can fetch paywalled/closed-platform episodes from a title alone.
- Ask for an accessible link, uploaded video, transcript, episode synopsis, or a short description of the exact elements to benchmark.
- Use the reference only to extract reusable structure: hook rhythm, paywall pattern, character function, scene density, emotional curve, and visual treatment. Do not copy protected dialogue or distinctive scenes.
- Convert the reference analysis into project-local rules/adaptation notes, then continue the normal Fangcun pipeline with review gates.

## Fresh Feishu document / comment workflow

Before continuing from a Feishu docx that users may have edited online:

- Re-read the latest online document and, when mentioned, its comments before writing the next version.
- Summarize the accepted online edits/comments into project-local `project_rules.md` or a revision checklist.
- State the read timestamp in the task handoff/result summary.
- If the doc cannot be read, stop and ask for permission/link instead of continuing from stale local files.
- When the user requests “标红/显示修改”, deliver a change list and mark changed paragraphs in red/highlight when the channel/doc API supports it; otherwise prefix lines with 【修改】/【新增】/【删除建议】.

## OpenClaw mandatory startup intake

Before running any pipeline phase, the agent must collect and confirm these basics with the user:

- `novel_name`
- `drama_name`
- `source_dir` or `source_chapter_dir`
- `output_dir`
- `project.episodes`
- `project.episode_duration`
- `project.chapter_range`
- `project.platform`
- `project.style`
- `project.paywall`

If any field is missing, stop and ask the user first. The pipeline validates this intake and refuses to continue when required basics are missing.

## Mandatory output reporting

**铁律：能发文件就不要发路径。** 每阶段产出后，agent 必须把实际文件直接发给用户，而不是只告知路径。只有平台不支持文件发送时才降级为打印绝对路径。

| 平台 | 发送方式 |
|------|----------|
| **OpenClaw / Clawdbot（飞书/企微等）** | 用 `send_file` 或等效能力直接发文件到对话 |
| **Claude Code / Codex / Cursor / Gemini CLI** | 打印绝对路径，提示用户打开 |

**每个阶段必须发送/同步的文件与在线文档：**

- event → `events.json` / 事件表文档（可选，不能放原文正文）
- adaptation → `adaptation_strategy.md` / `《项目名》-改编指引-vYYYYMMDD-r1`
- adaptation review → `adaptation_review.md` / `《项目名》-审核报告-改编指引-vYYYYMMDD-r1`
- story_outline → `story_outline.md` / `《项目名》-故事大纲-vYYYYMMDD-r1`
- story_outline review → `story_outline_review.md` / `《项目名》-审核报告-故事大纲-vYYYYMMDD-r1`
- skeleton → `story_skeleton.md` / `《项目名》-集纲-vYYYYMMDD-r1`
- skeleton review → `skeleton_review.md` / `《项目名》-审核报告-集纲-vYYYYMMDD-r1`
- scripts → 默认每 5 集一个批次文档：`《项目名》-剧本EP001-005-vYYYYMMDD-r1`；修改单集只更新所在批次文档/块
- export → `{drama_name}.txt` / `《项目名》-完整导出-vYYYYMMDD-r1`
- project info → `《项目名》-项目信息-vYYYYMMDD-r1`，只放元信息、rules、链接索引、进度和版本记录，禁止放原文正文

**禁止行为**：
- ❌ 只说"文件在 xxx 路径"而不发文件/在线文档链接
- ❌ 只发飞书卡片摘要，不创建在线文档或附件
- ❌ 把原文正文塞进项目信息文档
- ❌ 把全部阶段和全剧本塞进一个超长主文档
- ❌ 修改某一集时全量读取/重写全部剧本，造成无效 token 消耗
- ❌ 等用户问才发
- ❌ 批量打包等最后一起发——每阶段产出即发
- ❌ 事件表直接用 Markdown 表格写飞书 docx，容易出现打开后只有标题/“表格内容”但无正文

### 事件表飞书同步铁律

事件提取结果经常是单行 Markdown 表格：`| 第1章 | 人物 | 事件 | ... |`。飞书 docx 对 markdown 表格/descendant 写入不稳定，**禁止直接把事件表表格写入飞书**。

必须在 `build_feishu_project.py` 生成飞书内容时转成普通列表字段：

```markdown
## 第001章

- **章节**：第1章
- **人物**：小娇、刘曼
- **事件**：……
- **戏剧强度**：强
- **改编风险**：中
- **建议时长**：40秒
- **类型**：冲突+转折
```

同步后必须读回或抽检确认事件正文存在；如果只剩章节标题/“表格内容”，视为同步失败，必须修复后重刷再继续。

### 飞书文档分配与更新策略

1. 项目信息文档是 dashboard：项目元信息、rules、阶段文档链接索引、进度、版本记录、下一步，不存原文正文。
2. 阶段产物独立成文档：改编指引、故事大纲、集纲、审核报告、完整导出分别命名。
3. 剧本按批次成文档，默认 `script_batch_size=5`，如 EP001-005、EP006-010。
4. 小修：更新原文档；大改：新建 r2，旧文档加 `-archived`。
5. 单集修改：仅读项目 rules + 该集集纲 + 所在批次剧本文档 + 必要前后集；只更新所在批次块，避免全量 token 消耗。
6. 每次同步完成后必须在群里直发：简短说明 + 在线文档链接 + 本地/附件文件名 + 状态。

### 飞书同步自动执行器

阶段产出后不要只生成 manifest，也不要依赖 agent 手动逐个调 `feishu_doc`。必须调用自动执行器闭环：

```bash
python tools/build_feishu_project.py --config <config.json> --execute --account <当前bot账号>
```

执行器会：
- 生成 manifest；
- 直接调用飞书 OpenAPI 创建/更新 docx；
- 把 `doc_token` 映射保存到 `<output_dir>/feishu_sync_state.json`；
- 表1/表2固定模板已沉淀在 `../../references/feishu_project_table_templates.json` 和 `../../references/feishu_project_table_templates.md`；新项目初始化/旧项目修正必须按该 schema 和 `tools/feishu_project_executor.py` 强约束执行；
- 新项目群必须先在知识库 `NNfBwb32SiOhAwkrhRlcYkojnJg` 下创建/复用同名项目文件夹，并在文件夹下创建/复用 `表1:业务产物一览`、`表2：tokens消耗明细表`；表2必须严格按模板 `OIscbOQJQaf7MasVgsGccyrjndc/tblyC8Ee79rJXgCk` 初始化，字段为 `序号 / usage_date / person / bot_id / chat_id / project / model_provider / model / input_tokens / output_tokens / total_tokens / 来源说明`，其中 `来源说明` 必须是最后一列单选字段，选项为 `用户触发`、`自动触发`，禁止出现任何 `费用`、`费用估算`、`成本` 类字段或内容；表1只参考 `NZ8vbVqpbajZqYsZuDjchf5mnvh` 模板，初始化时严格遵循模板字段顺序 `字段/内容/内容链接/来源说明/类型/时间`（`内容链接` 为 URL/链接字段，位于 `内容` 与 `来源说明` 之间）并清理默认/多余列（删 `Single option`/`Date`/`阶段`/`Attachment`/`Attatchment`/`备注`），从第 1 行写入 `编剧`、第 2 行 `BOT ID`、第 3 行 `剧名`，三行 `时间` 字段统一填建表时间；从第 4 行开始在 `字段` 列依次写入固定产物项：小说/剧本原文、改编指引、改编审核、故事大纲、大纲审核、集纲、集纲审核、剧本汇总；固定模板不保留通用「剧本/剧本审核」占位行，剧本分批时由 Jingwei 在「剧本汇总」上方动态插入「剧本EPxxx-yyy / 剧本审核EPxxx-yyy」行；剧本批次/导出汇总阶段若生成资产 Dashboard，飞书文档标题必须使用「剧本汇总」而不是泛称「资产Dashboard」；第 4 行 `类型` 为用户输入，其余产物行 `类型` 为 bot输出，产物行 `来源说明` 为 bot自动抓取；初始化完成后必须把项目文件夹、表1、表2作为可点击链接直接回贴主群，禁止放进代码块/JSON日志块；完成项目目录和建表后，一旦用户发送小说/剧本原文 txt，必须立即用 `tools/archive_source_txt.py --file <txt> --config <project>/drama/config.json --account <当前bot>` 把 txt 内容创建为项目目录下的飞书 docx 链接，并在当前群聊回贴该可点击链接；不需要、也不要把文件链接写入表1；后续所有阶段文档必须落在该项目文件夹下；
- 最终「剧本汇总」必须是所有剧本分批文档的正文合并稿；禁止只把各 batch 链接贴进同一个文档当目录；生成前必须检查每个已登记 `script_batch:EPxxx-yyy` 的 `active_version`，确保汇总覆盖所有最新批次，缺任何最新批次都阻断；批次链接只能留在项目信息/状态索引，不得替代正文合并稿。改编指引、审核、大纲、集纲等非剧本交付物只在各自阶段回贴链接，不塞入最后汇总；
- 后续小修按稳定 key 更新原文档；
- 剧本仍按默认 5 集批次同步；
- 打印在线文档链接清单，agent 必须原样回贴到群主对话。

轻量大改版本，不强制重命名旧飞书标题，只做状态归档 + 新建/激活 r2：

```bash
python tools/build_feishu_project.py --config <config.json> --execute --major-revision --account <当前bot账号>
```

预览但不写飞书时使用：

```bash
python tools/build_feishu_project.py --config <config.json> --execute --dry-run
```

## Mandatory human review confirmation

AI review does not unlock the next stage by itself. After `--phase review`, the workflow enters a pending human-review state. The agent must read the review report, send or show it to the user, summarize issues, collect human approval or revision instructions, and only then run:

```bash
python tools/pipeline.py --config {config} --confirm-review --review-target story_outline
python tools/pipeline.py --config {config} --confirm-review --review-target skeleton
python tools/pipeline.py --config {config} --confirm-review --review-target adaptation
```

Without this confirmation, the pipeline blocks at each review gate.

## 工具路径

本 skill 的 Python 工具位于本 SKILL.md 同级目录的 `tools/` 下。执行命令时请先 `cd` 到 skill 目录，或替换为平台对应的安装路径。
- **Claude Code / Clawdbot / Codex**: `python tools/pipeline.py`
- 命令中统一使用相对路径 `python tools/pipeline.py`，agent 需根据平台自动解析

## 流程

```
event → story_outline → review → 🔴门控 → adaptation → review → 🔴门控 → skeleton → review → 🔴门控 → script → export
```

**系统定位**：改编指引是柔性提示（守住底线），编剧驱动创作（爽虐反转）。

**审核门控（Review Gate）**：每个创作阶段产出后立即审核。审核报告会给出评分（A/B/C/D）和问题清单。

- 🔴 **D 评分 或 ≥1个严重问题** → **阻塞**，必须修复后重新审核才能进入下一阶段
- 🟡 **C 评分 或 ≥3个中等问题** → **警告**，建议修复但可继续
- 🟢 **A/B 评分 且 无严重问题** → **通过**，自动进入下一阶段

### 改编指引迭代循环

大纲是原文脉络梳理，**方向性决策**。

```
story_outline → review → 用户查看审核报告
                              ├─ 通过(A/B) → 进入改编策略
                              ├─ 有问题 → 用户提修改意见 → 重新生成
                              └─ 循环直到用户满意
```

### 故事大纲迭代循环

策略是**核心创作决策**（删什么/怎么改/视觉化），变动空间大。

```
adaptation → review → 用户查看审核报告
                           ├─ 通过(A/B) → 进入骨架(集纲)
                           ├─ 有问题 → 用户提修改意见 → 重新策略
                           └─ 循环直到用户满意
```

### 骨架迭代修复循环

骨架是改编策略的**逐集落地**，审核以快速核对为主。

```
skeleton → review → 用户查看审核报告
                         ├─ 通过(A/B) → 进入剧本
                         ├─ 小问题 → agent 直接修复
                         └─ 严重问题 → 汇报用户确认后修复
```

```bash
# ⚠️ 不推荐：--phase all 会自动跑完全程，不会在门控处暂停
# python tools/pipeline.py --config {config}

# ✅ 推荐：分步执行，每阶段后手动审核
# 阶段0: 事件提取
python tools/pipeline.py --config {config} --phase event

# 阶段1: 故事大纲（梳理原文脉络）
python tools/pipeline.py --config {config} --phase story_outline
python tools/pipeline.py --config {config} --phase review --review-target story_outline
# → 用户确认方向后进入改编策略

# 阶段2: 改编策略（决定怎么改）
python tools/pipeline.py --config {config} --phase adaptation
python tools/pipeline.py --config {config} --phase review --review-target adaptation
# → 读 reviews/adaptation_review.md → 汇报用户 → 用户提修改意见 → 循环迭代

# 阶段3: 骨架/集纲（改编后的逐集落地）
python tools/pipeline.py --config {config} --phase skeleton
python tools/pipeline.py --config {config} --phase review --review-target skeleton
# → A/B 直接继续 / C级 agent 自修 / D级才需要用户介入

# 阶段4: 剧本编写（用户确认骨架后："开始写剧本"）
python tools/pipeline.py --config {config} --phase script --start 1 --end 10

# 阶段5: 导出
python tools/pipeline.py --config {config} --phase export

# 跳过门控（仅当用户确认审核结果可接受时使用）
python tools/pipeline.py --config {config} --skip-review-gate

# 断点续传
python tools/pipeline.py --config {config} --phase resume

# 查看进度
python tools/pipeline.py --config {config} --phase status
```

## 配置文件

`api_key`、`api_base_url`、`model` 可写在配置文件里；也可以通过环境变量
`API_KEY` / `API_BASE_URL` 提供。部署在 OpenClaw 时，如果
`~/.openclaw/openclaw.json` 中已配置 `deepseek` 或 `openai-completions`
provider，pipeline 会自动发现凭据并在启动阶段做连接预检。

```json
{
  "novel_name": "原著书名",
  "drama_name": "剧本名",
  "source_dir": "projects/作者/书名/_cache/chapters",
  "output_dir": "projects/作者/书名/drama",
  "api_key": "sk-xxx",
  "api_base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "model_overrides": {
    "event": "deepseek-chat"
  },
  "project": {
    "episodes": 30,
    "episode_duration": 2,
    "chapter_range": [1, 153],
    "platform": "竖屏9:16",
    "style": "甜宠喜剧",
    "paywall": "前3集免费，第4集起付费"
  }
}
```

## 输出格式

剧本使用 `<scriptItem>` XML 标签包裹，△ 标记场景描述。

## 剧本结构核心原则（专业编剧规范）

### 1. 四个卡点
卡点为观众付费点，可以理解为网文当中的上架，因此，卡点十分关键，必须牢牢抓住观众情绪。
- 每一个卡点都要在前一个卡点的基础上递进十集
- 一卡为整部剧本最为重要的卡点（最好在第十集进行卡点）
- 卡点位置：约10%/30%/50%/70%/90%

### 2. 多次反转
尽量在剧集中多融入反转内容：
- 基于逻辑人设的有效反转，不能空穴来风
- 不能忽视逻辑
- 反转要有看点，要有强烈的期待感
- 要能抓住观众的眼球

### 3. 期待不断
开篇融入期待感，后续保持期待不断：
- 尽量围绕着期待去展开剧情
- 期待感和主线要互相融合，你中有我，我中有你
- 千万不能让期待感和主线产生分歧

### 4. 主线情绪
剧情围绕主线，不要东一下西一下：
- 尽量少开支线
- 要跟着主线去推动人物
- 以主线作为核心去塑造整体剧情

### 5. 框架写作
短剧的创作，不是空穴来风，头脑风暴，拿笔随手写出来的，而是需要方法论的支持：
- 需要一个框架来作为底层的创作逻辑
- 其余的人物，剧情，亦或者其他细枝末节的东西，只不过在这个框架上去进行填充
- 框架可以简单理解为：爆款短剧的底层逻辑
- 也就是：节奏的安排，爽点的布置，主线的期待
- 将这些点作为框架，再把其余的新东西填充进去

## 质量检查（agent 自动执行）

跑完后 agent 应该：
1. 读 `scripts/ep_001.txt`，检查格式是否正确（△标记、场景标题、台词）
2. **字数统计**：只计纯内容（△描述+对话+OS），不含剧情梗概、场景头、人物行、格式标记
3. 检查角色名是否正确
4. **场景价值判断**：对每个场景问"这个场景对观众有什么用？"，答不出来 = 废笔
5. **废笔检测**：删除过程展示、环境铺垫、无用对话、废话台词
6. 读 `reviews/` 目录，汇报审核评分
7. 如有问题，告诉用户

## 飞书文档自动同步

在 OpenClaw/飞书环境下，每个阶段的产出物应**自动同步到飞书文档**。

### 同步机制

1. **生成 manifest**：运行 `python tools/feishu_sync.py --config {config} --phase {phase} --json` 获取待同步文件清单
2. **创建飞书文档**：Agent 使用 `feishu_doc` 工具创建/更新 docx
3. **写入内容**：将阶段产出物写入飞书 docx

### 命名规范

飞书文档标题：`《{作品名}》-{阶段名}-v{YYYYMMDD}`

| 阶段 | 飞书文档标题 |
|------|------------|
| 故事大纲 | 《作品名》-故事大纲-v20260701 |
| 集纲/骨架 | 《作品名》-集纲-v20260701 |
| 改编策略 | 《作品名》-改编策略-v20260701 |
| 审核报告 | 《作品名》-{阶段}审核报告-v20260701 |
| 剧本(第X-Y集) | 《作品名》-剧本第X-Y集-v20260701 |

### Agent 行为

每阶段完成后：
1. ✅ 本地文件已保存
2. ✅ 文件已发送到对话（平台支持时）
3. ✅ 同步到飞书 docx（如项目有飞书 wiki 配置）
4. ✅ 飞书文档链接回复到群

## 内容合规建议审核（可选）

在主 Agent 派发审核指令时可附带要求内容合规审核：

```bash
# 正常审核（不含合规检查）
python tools/pipeline.py --config {config} --phase review --review-target skeleton

# Agent 行为：在审核请求中额外要求合规检查
# → supervision Agent 会附带读取 prompts/content_compliance.md
# → 以「内容合规提醒」块附在审核报告末尾
```

**核心原则**：
- ⚠️ 所有合规提醒均为建议，**不做强制拦截**
- 🎨 编剧自主决定是否调整
- 📋 提醒覆盖：价值观红线、暴力尺度、两性关系、社会敏感、未成年人保护、短剧特有合规

## 常见场景

| 用户说 | agent 做 |
|--------|----------|
| "把这本书改成短剧" | **四步走，不跳步**：event → story_outline → 审核 → **确认** → adaptation → 审核 → **确认** → skeleton(集纲) → 审核 → **确认** → script |
| "写前10集剧本" | 确认集纲审核已通过 → 跑 --phase script --start 1 --end 10 |
| "继续写" | 跑 --phase resume |
| "看看审核报告" | 读 `reviews/` 目录 → 汇报评分和问题清单 → **等待用户决策** |
| "骨架有问题，重新生成" | 跑 --phase skeleton（覆盖旧的）→ 跑 --phase review --review-target skeleton → **汇报新评分** |
| "审核过了，继续" | 跑 --phase adaptation（或 --skip-review-gate 继续后续流程） |
| "不用管审核，直接继续" | 跑 --skip-review-gate 跳过门控（不推荐，需确认用户已知风险） |
| "看看剧本质量" | 读 scripts/ → 检查格式/字数/角色名 |

### ⚠️ 禁止使用 --phase all

`--phase all` 会自动跑完 event→story_outline→review→skeleton→review→adaptation→review→script→export 全部流程，**不会在审核门控处停下来等待用户**。除非用户明确要求"全自动跑完不用问我"，否则**禁止**使用 `--phase all`。

正确做法是**逐阶段执行**，每完成一个阶段就在门控处暂停：

```bash
# 阶段0: 事件提取
python tools/pipeline.py --config {config} --phase event

# 🔴 阶段1: 故事大纲（三步走第一步，方向性决策）
python tools/pipeline.py --config {config} --phase story_outline

# 🔴 门控0: 故事大纲审核（必须执行，不可跳过）
python tools/pipeline.py --config {config} --phase review --review-target story_outline
# → agent 读取 reviews/story_outline_review.md
# → 向用户汇报评分和问题清单
# → 等待用户确认后才能继续

# 阶段2: 集纲/骨架（三步走第二步，逐集展开）
python tools/pipeline.py --config {config} --phase skeleton

# 🔴 门控1: 骨架审核（必须执行，不可跳过）
python tools/pipeline.py --config {config} --phase review --review-target skeleton
# → agent 读取 reviews/skeleton_review.md
# → 向用户汇报评分（A/B/C/D）和问题清单
# → 阻塞规则: D 或 ≥1严重 → 必须修复后重跑；C → 建议修复
# → 等待用户确认后才能继续

# 阶段3: 改编策略（仅在用户确认骨架审核通过后执行）
python tools/pipeline.py --config {config} --phase adaptation

# 🔴 门控2: 策略审核（必须执行，不可跳过）
python tools/pipeline.py --config {config} --phase review --review-target adaptation
# → agent 读取 reviews/adaptation_review.md
# → 向用户汇报评分和问题清单
# → 等待用户确认后才能继续

# 阶段3: 剧本编写（仅在用户确认策略审核通过后执行）
python tools/pipeline.py --config {config} --phase script --start 1 --end 10
```

### 📁 文件发送原则（最高优先级）

**铁律：能发文件不要发路径。每阶段产出后必须直接把文件发给用户。**

**汇报顺序**：产出物在前，审核报告在后——让用户先看内容，再看评价。

不同平台的发送方式：

| 平台 | 发送方式 |
|------|----------|
| **OpenClaw / Clawdbot（飞书等）** | **直接发文件到对话**——用 send_file 或等效能力。**禁止只发路径。** |
| **Claude Code / Cursor / Codex / Gemini CLI** | 打印绝对路径告知用户 |

**每阶段产物必须立即发送，不得拖延到下一阶段：**
- 事件表、骨架、审核报告、改编策略、策略审核报告——每份产出即发送
- 剧本每集单独发送，每批次完成后立即发送
- 合并版最后发送

**反面教材（禁止）**：只告知路径不发送文件（如"📁 文件在 xxx/drama/reviews/..."而不发实际文件）

### agent 审核门控标准操作

当 `--phase review` 完成后，agent **必须**：

1. **先发送产出物，再发送审核报告**（顺序：产出物在前，审核在后）
2. **读取审核报告**：读取 `reviews/{target}_review.md`
2. **发文件给用户**：直接把审核报告文件发送到对话（不要只发路径）
3. **向用户汇报**：
   - 总评分（A/B/C/D）
   - 🔴 严重问题数量和内容
   - 🟡 中等问题数量和内容
   - 是否阻塞进入下一阶段
4. **阻塞时引导用户**：
   - 展示具体问题
   - 告知需修复的文件路径
   - 给出修复建议
   - 等待用户确认修复方向
   - **不要自动继续**，用户必须看过并确认
5. **通过时告知用户**：确认可以进入下一阶段，征求用户同意后继续

### 📁 各阶段产物路径速查

| 阶段 | 产物 | 路径 |
|------|------|------|
| 事件提取 | 事件表 | `{output_dir}/_cache/events.json` |
| 故事大纲 | 故事大纲 | `{output_dir}/_cache/story_outline.md` |
| 大纲审核 | 审核报告 | `{output_dir}/reviews/story_outline_review.md` |
| 骨架生成 | 故事骨架(集纲) | `{output_dir}/_cache/story_skeleton.md` |
| 骨架审核 | 审核报告 | `{output_dir}/reviews/skeleton_review.md` |
| 策略生成 | 改编策略 | `{output_dir}/_cache/adaptation_strategy.md` |
| 策略审核 | 审核报告 | `{output_dir}/reviews/adaptation_review.md` |
| 剧本编写 | 剧本 | `{output_dir}/scripts/ep_{NNN}.txt` |
| 导出 | 完整剧本 | `{output_dir}/export/` |

**每次阶段完成后，agent 必须告知用户产物路径，不得遗漏。**

## Script Draft Quality Gate (cross-platform)

Stage 3 now uses a draft-first workflow for all platforms, with OpenClaw as the primary runtime scenario.

Command:
```bash
python tools/pipeline.py --config {config} --phase script --start 1 --end 10 --batch-size 5
```

### Batch size configuration

`script_batch_size` in config.json controls how many episodes per batch (default: 5). Users may customize this. If set >10, pipeline prints a warning about expected wait time.

### Rules:
1. Each episode is generated serially into `{output_dir}/drafts/batch_XXX/ep_NNN.txt`.
2. Each draft receives an AI review report in JSON and Markdown under `drafts/batch_XXX/reviews/`.
3. Severe issues trigger one targeted AI rewrite.
4. If severe issues remain, the workflow pauses and the current episode must pass before the next episode can be generated.
5. **A batch pauses after `script_batch_size` episodes and writes a `.pending` lock file. The pipeline physically refuses to generate the next batch until the lock is cleared via `--confirm-draft-batch`. This is enforced at the code level and cannot be bypassed by the agent.**
6. No draft is promoted automatically. The writer must confirm with:
   `python tools/pipeline.py --config {config} --confirm-draft-batch`
7. Confirmation copies drafts into `{output_dir}/scripts/` and clears the `.pending` lock.
8. Once an episode passes review, a `.pass` marker is written. Re-running `--phase script` skips re-review of passed episodes.
9. Use `--review-draft --episode N` after manual edits (this clears and re-evaluates the .pass marker), and `--rewrite-draft --episode N` to rewrite only that blocked episode.

### Agent mandatory behavior after each batch:

**The agent MUST do the following after every batch completes:**
1. Send all draft files (ep_NNN.txt) to the user
2. Send the batch_summary.md to the user
3. Send any review reports with issues to the user
4. Wait for user confirmation
5. Only after user says "confirmed" / "继续" / equivalent, run `--confirm-draft-batch`

**Violation of this sequence = agent failure. The pipeline's .pending lock provides a hard backstop, but agents must not attempt to work around it.**

OpenClaw guidance: **always send the files directly to the chat** — never just print paths. Script files, batch_summary.md, and review reports must all be sent as file attachments. Other platforms must at least print absolute paths.
