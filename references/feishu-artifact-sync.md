# Fangcun Next Feishu Artifact Sync v0.1

## 定位

这是 Fangcun Next 内部的**最小飞书交付适配层**，属于 Platform Adapter：

- 不改变 Fangcun 的创作流程、阶段门禁、审核与确认规则。
- 不把飞书逻辑写进 Writer/Reviewer/Rewriter Prompt。
- 只在 Fangcun 产物已经落盘之后，负责“本地产物 ↔ 飞书在线文档”的镜像、版本登记、反向同步。

## 触发条件

### 自动触发（默认）

当运行上下文显示当前交互为飞书群聊（例如 `channel=feishu` 且 `chat_type=group`），并且 Fangcun Next 生成了用户需要验收的 Markdown/TXT 产物时，**默认自动启用**本适配，不需要用户额外说“发成飞书文档”。

### 显式触发（兜底）

以下表达用于非默认场景、重发、指定位置或反向同步：

- 用户说“发成飞书文档 / 输出到飞书 / 给我链接”。
- 用户指定飞书输出地址、文件夹或已有文档。
- 用户手动修改飞书文档后，要求“同步回本地 / 用文档覆盖本地”。

## 关键对象

### Artifact

一次 Fangcun 本地产物，例如：

- `artifacts/adaptation_strategy/versions/adaptation_strategy_v001_xxx.md`
- `artifacts/story_outline/versions/story_outline_v001_xxx.md`
- `artifacts/episode_outline_md/versions/episode_outline_md_v001_xxx.md`
- `artifacts/drafts/episode_001/versions/draft_v001_xxx.txt`
- 夜间预跑时的 `outputs/<project>/前三集剧本.md`

### DocumentVersion

某个 Artifact 的一个飞书文档版本。

同一阶段多轮输出时，默认每轮独立文档：

- `v001`：第一次验收版
- `v002`：第二次修改版
- `v003`：定稿版

除非用户明确说“更新这个已有文档”，否则不要覆盖旧文档，避免丢失人工批注和历史版本。

## Registry

默认登记表：`memory/feishu-artifact-sync.json`

```json
{
  "schema": "feishu-artifact-sync.v1",
  "artifacts": [
    {
      "artifact_id": "sha1(project|stage|local_path)",
      "project": "项目名",
      "stage": "前三集剧本",
      "local_path": "project/.../前三集剧本.md",
      "versions": [
        {
          "version": "v001",
          "label": "预跑验收版",
          "doc_token": "Qe7N...",
          "url": "https://feishu.cn/docx/Qe7N...",
          "title": "《项目名》前三集剧本 v001｜预跑验收版",
          "local_sha256": "...",
          "local_bytes": 7307,
          "created_at": "2026-08-11T10:00:00+08:00",
          "updated_at": "2026-08-11T10:00:00+08:00",
          "pulled_from_doc_at": null,
          "backup_path": null
        }
      ]
    }
  ]
}
```

## 输出地址优先级

从高到低：

1. 用户本轮明确指定的 `doc_token` / `folder_token` / wiki parent。
2. Fangcun 项目配置：`<project>/.feishu-output.json`。
3. workspace 默认配置：`memory/feishu-artifact-sync.config.json`。
4. 无配置：创建到 bot 默认空间，并报告“未指定输出文件夹”。

项目配置示例：

```json
{
  "project": "项目名",
  "default_folder_token": "fld_xxx",
  "default_wiki_parent_token": null,
  "stages": {
    "前三集剧本": {
      "mode": "versioned_doc",
      "folder_token": "fld_xxx",
      "title_template": "《{project}》{stage} {version}｜{label}"
    }
  }
}
```

## 本地文件 → 飞书文档

1. 确认本地产物路径、项目名、阶段名、label。
2. 用脚本计算下一版信息：

```bash
skills/fangcun-next/scripts/artifact_sync_registry.py next \
  --registry memory/feishu-artifact-sync.json \
  --local-path <path> \
  --project <project> \
  --stage <stage> \
  --label <label>
```

3. 读取本地文件全文。
4. 创建/写入飞书文档：
   - 新版本：`feishu_doc create` → `feishu_doc write`
   - 指定已有文档：直接 `feishu_doc write`
   - 注意：`feishu_doc create` 的 `content` 参数不生效，必须两步走。
5. `feishu_doc read` 做写后校验。
6. 用脚本登记版本：

```bash
skills/fangcun-next/scripts/artifact_sync_registry.py record \
  --registry memory/feishu-artifact-sync.json \
  --local-path <path> \
  --project <project> \
  --stage <stage> \
  --label <label> \
  --version v001 \
  --doc-token <doc_token> \
  --title <title>
```

7. 回复用户：文档链接 + 版本号 + 权限/校验结果。

## 飞书文档 → 本地文件

1. 用户明确给出文档链接，或说明“同步第 N 版”。
2. 查 registry 定位本地文件；无法定位时先问用户要本地目标路径。
3. `feishu_doc read` 读取飞书正文。
4. 将正文写入临时文件。
5. 用脚本备份并覆盖本地：

```bash
skills/fangcun-next/scripts/artifact_sync_registry.py pull \
  --registry memory/feishu-artifact-sync.json \
  --doc-token <doc_token> \
  --content-file /tmp/feishu_doc_content.md
```

6. `git diff` 自检，无误后 commit。
7. 回复用户：已同步路径 + 备份路径 + commit。

## 写入校验

最低校验：

- 本地文件 SHA256 登记。
- `feishu_doc write` 成功。
- `feishu_doc read` 返回非空，正文包含首个一级标题和关键 label（如“预跑/定稿/审核”）。

严格校验（可选）：

- 将飞书 read 正文规范化换行后，与本地 markdown 规范化文本比对。
- 因飞书 Markdown 渲染可能改变列表/空行，不要求 byte-level 相等；但正文段落不得缺失。

## 失败处理

- 飞书权限 403：不要假装成功；回复用户需要手动授权或换 owner/folder。
- 写后校验不一致：不要交付链接；重新写一次，仍失败则报告。
- 反向同步前无法确定本地目标：先问，不猜。
- 本地和飞书两边都被修改时：不自动合并，先让用户决定以哪边为准。

## v0.1 边界

- 不自动监听所有文件变化；只在 agent 对话触发时同步。
- 不替代 Fangcun 的阶段确认、审核、定稿门禁。
- 复杂表格/图片/多维表格不做 byte-level 镜像；v0.1 以 Markdown/Docx 正文为主。
