# 平台适配层（P2）

## 边界

- Creative Core 只输出标准产物（JSON/Markdown/TXT）；
- Feishu Adapter 负责创建、更新、读回和评论；
- OpenClaw Adapter 负责 Bot 对话和工具调用；
- Token 统计由独立模块处理；
- 飞书字段和文档 Token 不进入 Writer Prompt。

## 能力探测

```json
{
  "can_read_files": true,
  "can_write_files": true,
  "can_read_feishu_docs": false,
  "can_read_comments": false,
  "can_send_attachments": true,
  "can_call_external_llm": true
}
```

核心流程根据能力降级，但不能伪装已经读取无法访问的在线内容。

## 在线修改（P2）

继续生成前如编剧可能在线修改：读取最新在线正文 → 读取相关评论 → 与本地版本 Diff → 生成 revision_request → 编剧确认或按明确指令自动采用 → 更新本地定稿和连续性 → 再生成后续集数。无法读取时必须说明，不得从旧缓存继续并假装已同步。

## 首轮范围

飞书群聊下的产物交付事件流已在 v0.3.6 实现：CLI 输出 `FANGCUN_FEISHU_SYNC_EVENT`，Host Agent 使用一等 `feishu_doc` 工具创建/写入/读回校验版本化文档并登记 registry。飞书评论读回、在线正文修改回流、OpenClaw 子 Bot、Dashboard、Token 统计仍为 P2，只保留接口约定。

