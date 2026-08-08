# 工程 SKILL

本文件承接 `SKILL.md` 合并时从 `linqi0717` 分支迁出的工程门禁/流程/校验规则。

合并原则：主 `SKILL.md` 保留 `main` 版本的能力说明和通用规则；本文件专门记录工程执行、飞书流程、项目归属、路径与交付闭环相关硬门禁，供实现脚本、执行器和回归测试引用。

## linqi0717 工程门禁/流程/校验规则

14. **chat_id 复用现有项目目录**：初始化前必须用当前飞书群 `chat_id` 只扫描当前 bot 的正式配置 `projects/*/drama/config.json`；若存在同 `chat_id` 配置，必须复用原 `config.json` / `output_dir` / `project_workspace`，禁止按新群名创建新本地项目目录。`projects/*/config.json` 仅作为旧 Fangcun CLI 结构的 legacy 检测路径，发现后提示迁移，不得作为正式入口继续生成产物。群名变化只更新 `current_group_name` 与 `group_name_aliases`；`feishu_group_name` 作为首次初始化项目文件夹命名快照，不随群名变化覆盖。
15. **跨 owner 输出硬门禁**：项目 `config.json` 必须写入并校验 `bot_id`、`feishu_account`、`chat_id`、`project_slug`、`project_workspace`、`output_dir`。每次 run/sync/execute 正式产出前必须校验：当前 `OPENCLAW_AGENT_ID` 等于 `config.bot_id`；当前飞书账号等于 `config.feishu_account`；`config.json` 位于 `project_workspace/drama/config.json`；所有输出路径位于 `project_workspace/drama/output/`；`feishu_sync_state.json` 属于当前 `project_slug/chat_id/project_workspace`；同步正式产物前 `project_node_token` 必须存在。任一不满足必须停止并提示：`检测到当前 bot、项目目录或飞书账号与项目绑定不一致，本次未生成、未同步任何产物。`
16. **禁止裸飞书文档作为 Fangcun 正式交付**：Fangcun 正式产物禁止直接调用 `feishu_doc.create` / `feishu_doc.write` 游离创建并回贴链接。所有正式产物必须先落本地 `projects/<slug>/drama/output/`，再通过 `build_feishu_project.py --config <project>/drama/config.json --execute --account <当前bot>` 同步，链接必须来自 `execute_manifest()` 返回结果或当前项目 `feishu_sync_state.json` 中已登记的 doc_token。父 agent 在主群回贴任何 Fangcun 文档链接前，必须先运行 `python tools/validate_delivery_link.py --config <project>/drama/config.json --link <doc_url> --account <当前bot>`；若校验失败，禁止回贴该链接，并提示：`检测到游离飞书文档，未进入 Fangcun 项目资产体系。本次不作为正式交付。请先通过 Fangcun 同步执行器导入/重同步。`
17. **命名规范与版本保留**：每个阶段文档标题必须带版本号，如 `《项目名》-故事大纲-V1`、`《项目名》-故事大纲-V2` 或 `《项目名》-故事大纲-vYYYYMMDD-r1`。默认每次新生成都创建新版本文档并永久保留旧版本；不得默认覆盖、清空、删除或自动重命名旧文档。只有用户明确说“覆盖原文档/直接更新当前版本/patch 当前文档”并传 `--overwrite-current` 时，才允许 update 当前推荐版本。
15. **自动执行器闭环**：飞书同步必须优先运行 `python tools/build_feishu_project.py --config <project_slug>/drama/config.json --execute --account <当前bot账号>`，由程序自动初始化项目文件夹、创建两张项目表、create 新版本 docx、保存 `<project_slug>/drama/output/feishu_sync_state.json` 并打印链接；禁止只生成 manifest 后等 agent 手动调工具。

## 落地要求

- 这些规则不得在主流程中丢失；若未来主 `SKILL.md` 重构，应从本文件同步回工程执行器/测试用例。
- 任何正式产物输出前，必须确认项目归属、飞书账号、群 chat_id、项目目录和 output_dir 与配置一致。
- 飞书正式交付必须优先走自动执行器闭环，禁止裸建游离文档作为正式交付。
