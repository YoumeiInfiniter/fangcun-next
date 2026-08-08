# Fangcun 飞书项目表模板（强约束）

本文件沉淀 2026-07-16 已校准的表1/表2模板。新项目初始化、旧项目修正、代码变更时均以同目录 `feishu_project_table_templates.json` 为机器可读 schema，以本文为人工规则说明。

## 表1：业务产物一览

参考模板：<https://m9cfu49348.feishu.cn/base/NZ8vbVqpbajZqYsZuDjchf5mnvh?table=tblacd7rgShbaNBl&view=vewHS5ZPEB>

### 字段

只保留：

1. `字段` Text
2. `内容` Text
3. `内容链接` URL/链接（必须位于 `内容` 与 `来源说明` 之间）
4. `来源说明` Text
5. `类型` SingleSelect：`项目信息` / `用户输入` / `bot输出`
6. `时间` DateTime：`yyyy/MM/dd HH:mm`

必须删除：`Single option`、`Date`、`阶段`、`Attachment`、`Attatchment`、`备注`。

### 初始化行

| 行 | 来源说明 | 字段 | 内容 | 内容链接 | 类型 | 时间 |
|---|---|---|---|---|---|---|
| 1 | 用户手动填写姓名 | 编剧 | 请填写编剧姓名 | 空 | 项目信息 | 建表时间 |
| 2 | bot自动抓取 | BOT ID | 当前 bot/account id | 空 | 项目信息 | 建表时间 |
| 3 | bot自动抓取 | chat_id | 飞书群 chat_id | 空 | 项目信息 | 建表时间 |
| 4 | bot自动抓取 | 剧名 | 项目名称 | 空 | 项目信息 | 建表时间 |
| 5 | bot自动抓取 | 小说/剧本原文 | 空 | 收到用户 txt 后填项目目录下原文 docx 链接 | 用户输入 | 文件创建时间 |
| 6 | bot自动抓取 | 改编指引 | 空 | 文件链接 | bot输出 | 文件创建时间 |
| 7 | bot自动抓取 | 改编审核 | 空 | 文件链接 | bot输出 | 文件创建时间 |
| 8 | bot自动抓取 | 故事大纲 | 空 | 文件链接 | bot输出 | 文件创建时间 |
| 9 | bot自动抓取 | 大纲审核 | 空 | 文件链接 | bot输出 | 文件创建时间 |
| 10 | bot自动抓取 | 集纲 | 空 | 文件链接 | bot输出 | 文件创建时间 |
| 11 | bot自动抓取 | 集纲审核 | 空 | 文件链接 | bot输出 | 文件创建时间 |
| 12 | bot自动抓取 | 剧本汇总 | 空 | 文件链接 | bot输出 | 文件创建时间 |

说明：固定模板不保留通用 `剧本` / `剧本审核` 占位行。剧本分批时，Jingwei 在 `剧本汇总` 行上方动态插入 `剧本EPxxx-yyy` / `剧本审核EPxxx-yyy` 行；每行只放当前批次最新版本。

### 小说 txt 归档

项目目录和表1/表2完成后，用户发送小说/剧本原文 txt 时：

1. 立即把 txt 内容创建为项目目录下的飞书 docx 链接。
2. 不得把原文正文塞进项目信息 dashboard。
3. Fangcun 不直接写表1文件链接；表1由 Jingwei 按同一项目目录扫描后幂等贴入 `内容` / `内容链接` 字段。
4. 在当前群聊直接回贴该可点击链接给用户；后续也可从项目目录查看。
5. 推荐执行：`skills/drama/tools/archive_source_txt.py --file <txt> --config <project>/drama/config.json --account <当前bot>`。

## 表2：tokens消耗明细表

参考模板：<https://m9cfu49348.feishu.cn/base/OIscbOQJQaf7MasVgsGccyrjndc?table=tblyC8Ee79rJXgCk&view=vewfNlNv1I>

### 字段

必须严格一模一样，只保留以下 12 列：

1. `序号` Text（主字段）
2. `usage_date` DateTime：`yyyy-MM-dd`
3. `person` Text
4. `bot_id` Text
5. `chat_id` Text
6. `project` Text
7. `model_provider` Text
8. `model` Text
9. `input_tokens` Number：`0`
10. `output_tokens` Number：`0`
11. `total_tokens` Number：`0`
12. `来源说明` SingleSelect：`用户触发` / `自动触发`（必须位于最后一列）

禁止出现任何费用相关字段或内容，包括：`费用`、`费用估算`、`成本`。

旧字段映射：

- `Text` → `序号`
- `Date` → `usage_date`
- `项目名称` → `project`
- `模型` → `model`
- `输入tokens` → `input_tokens`
- `输出tokens` → `output_tokens`
- `总tokens` → `total_tokens`

必须删除：`Single option`、`Attachment`、`Attatchment`、`skill`、`阶段`、`费用`、`费用估算`、`成本`、`调用时间`、`备注`。
