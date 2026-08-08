# 方寸编剧 Agent 后续需求 Roadmap

来源：2026-07-08 群聊同步的编剧 Agent 后续需求。

## 当前落地状态

- 资产管理 MVP：已新增 `skills/drama/tools/asset_registry.py`，支持 `project_assets.json` 和 dashboard markdown。
- token 标签 MVP：已新增 `skills/drama/tools/token_usage_event.py`，支持项目/组织/人/模型/阶段维度 JSONL 事件。
- 台词翻译 MVP：已新增 `skills/dialogue-translation/` 子 skill，支持台词抽取、翻译 prompt、双语/替换回填。

## 总体判断

三个需求可以支持，建议按依赖关系拆成三条能力线：

1. **文本资产管理 / 业务通路**：大纲、集纲、剧本等 AI 输出要自动沉淀为项目资产。
2. **项目维度 token/成本统计**：按日期、组织、项目、人、模型维度统计用量。
3. **台词翻译与风格改写**：中文剧本台词翻译成指定语种，并支持风格控制。

优先级建议：

```text
P0 输出资产管理
P1 token/成本统计
P1 台词翻译与风格改写
```

原因：输出资产管理是后续业务流程连续管理的底座；token 统计最好能挂到项目/阶段/用户/产出物；台词翻译相对独立，可以并行做成子 skill。

---

## 1. 输出资产管理 / 业务通路

### 背景

后续要做业务流程连续管理：

- 先把 AI 输出管理起来
- 再规范人工修改版本上传、管理
- 最终形成项目维度文本资产库

涉及阶段：

```text
改编指引 → 大纲 → 集纲 → 剧本批次 → 审核报告 → 人工修订版
```

### 推荐设计

每个剧本项目生成一个「项目资产 dashboard」，再配一张「文本资产表」。

#### A. 项目资产 dashboard（飞书文档）

用于人看：

- 项目基本信息
- 当前阶段
- 阶段产出链接
- 剧本批次链接
- 审核报告链接
- 人工修订版链接
- 版本记录
- 下一步动作

#### B. 文本资产表（飞书多维表格）

用于机器统计和流程管理。

建议字段：

| 字段 | 说明 |
| --- | --- |
| project_id | 项目唯一 ID |
| project_name | 项目名 |
| asset_type | adaptation / outline / skeleton / script_batch / review / human_revision |
| stage | 当前阶段 |
| episode_range | EP001-005 等 |
| version | r1/r2/... |
| source | ai / human / imported |
| status | draft / reviewing / approved / archived |
| doc_url | 飞书文档链接 |
| doc_token | 飞书 doc token |
| created_by | 创建人/agent |
| updated_by | 修改人/agent |
| created_at | 创建时间 |
| updated_at | 更新时间 |
| parent_asset_id | 上一版本或来源资产 |
| notes | 备注 |

### 与现有能力关系

当前 `build_feishu_project.py` 已经能自动 create/update docx 并维护 `feishu_sync_state.json`，可作为 P0 基础。

下一步应做：

1. 抽象 `asset_registry`：每次同步飞书文档时登记资产。
2. 生成或更新项目 dashboard。
3. 可选同步到飞书多维表格。
4. 人工上传版本作为 `source=human` 新资产进入 registry。

### MVP

先不强依赖飞书多维表格，MVP 可做成本地 + dashboard：

```text
project_assets.json + 飞书项目 dashboard
```

等流程稳定后，再同步到 Bitable。

---

## 2. 日期/组织/项目/人/模型维度 token 统计

### 目标

支持日维度输出，后续可做自动化看板。

维度：

- 日期
- 组织/公司
- 项目
- 人/agent
- 模型
- 阶段/任务类型

### 是否依赖需求 1

不完全依赖，但强烈建议和需求 1 对齐。

- 如果先做统计：可以基于 OpenClaw session usage + 手动 project 标签统计。
- 如果先做资产管理：可以把 token 成本绑定到 project_id / asset_id / stage，更准。

### 推荐数据结构

| 字段 | 说明 |
| --- | --- |
| date | 日期 |
| org_id | 组织/公司 |
| project_id | 项目 |
| project_name | 项目名 |
| user_id | 用户 |
| agent_id | agent |
| model | 模型 |
| task_type | outline/script/review/translation/sync 等 |
| stage | 阶段 |
| asset_id | 关联文本资产 |
| input_tokens | 输入 token |
| output_tokens | 输出 token |
| total_tokens | 总 token |
| estimated_cost | 估算成本 |
| success | 是否成功 |

### 与现有能力关系

当前 workspace 已有 `ops_observer`：

- `observer.py`
- `harvest_sessions.py`
- `token_stats.py`
- `sync_feishu.py`

下一步不是重写，而是补齐 project/org/person 标签来源。

### MVP

1. 每次 fangcun pipeline 运行时写入 `project_id / stage / task_type`。
2. `ops_observer` 采集 session token 时关联这些标签。
3. 日报输出按 date/project/model 聚合。
4. 后续再扩展到组织/人维度看板。

---

## 3. 中文剧本台词翻译 + 风格改写

### 需求

将中文剧本中的「台词部分」翻译成指定语种，并支持风格控制：

- 话剧风格
- 黑帮口语
- 斯文古典
- 本土化口语
- 平台/地区适配

### 关键点

不要整篇粗暴翻译。应保留剧本结构，只翻译台词：

- 场次标题保留或可选翻译
- 动作描写可选翻译
- 人名保持一致或做本地化映射
- 台词翻译需保留人物口吻
- 支持中外双语对照输出

### 推荐子 skill

新增子能力：

```text
skills/fangcun/skills/dialogue-translation/
```

建议包含：

```text
SKILL.md
prompts/dialogue_translation.md
prompts/style_profiles.md
tools/extract_dialogue.py
tools/translate_dialogue.py
```

### 输入

- 中文剧本 markdown/txt
- 目标语种：English / Spanish / Arabic / Thai 等
- 风格：默认/话剧/黑帮口语/斯文古典/本土口语
- 输出格式：
  - 只替换台词版
  - 中外双语对照版
  - 术语/人名表

### MVP

先不做复杂 NLP，直接按剧本格式解析：

```text
角色名：台词
角色名: 台词
```

识别台词行后逐段翻译，保留非台词内容。

### 交付归属建议

台词翻译子 skill 纳入公司版方寸统一交付；风格库、术语表、人名本地化、公司私有风格模板按客户私有分支隔离维护，不再做版本档位分层。

---

## 推荐实施顺序

### Phase 1：资产管理 MVP

- `project_assets.json`
- dashboard 更新
- 阶段产出登记

### Phase 2：token 标签打通

- pipeline 写入 project/stage/task 标签
- observer 聚合项目维度
- 日报/看板同步

### Phase 3：台词翻译子 skill MVP

- 台词行识别
- 指定语种翻译 prompt
- 风格参数
- 双语输出

### Phase 4：公司私有分支隔离

- dialogue-translation 纳入统一交付
- 企业客户私有风格模板放到 `company/<name>` 分支

---

## 风险与注意

1. 飞书交付不要只发卡片，必须有文档/表格链接。
2. 群聊禁止 Thread，所有链接直接贴主群。
3. Bitable 写入中文长文本时不要手敲 unicode 转义，尽量本地文件/JSON/Python API 流程。
4. 资产表不要存原文全文，只存链接、状态、版本和摘要。
5. token 统计是估算，不能替代供应商账单。
