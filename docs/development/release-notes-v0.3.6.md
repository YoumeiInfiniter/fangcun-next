# Fangcun Next v0.3.6 Release Notes

## 重点

- 增加飞书群聊下的 Fangcun 产物交付事件流：阶段验收产物落盘后输出 `FANGCUN_FEISHU_SYNC_EVENT`。
- Host Agent / OpenClaw 层消费事件后，用一等 `feishu_doc` 工具创建版本化飞书文档、写入、读回校验、登记 registry，并回链停止等待确认。
- Python runner 只生成事件与 registry 记录命令，不直接调用飞书 Open API。
- 安全边界同步更新：飞书群聊中的 Fangcun 产物交付属于已授权的平台适配；其他未请求线上文档修改仍禁止。

## 变更

- 新增 `scripts/feishu_artifact_delivery.py`。
- `project_cli.py` 在保存 `project_brief`、阶段 Markdown、`episode_outline_md`、`script_draft`、`review_md`、`stage_review_md` 等产物后自动 emit 交付事件。
- 新增审核报告 Markdown 可读版：`review_md` / `stage_review_md`。
- 新增草稿保存时的保守语义覆盖检查，避免必保留剧情点漏写。
- 更新 `SKILL.md`、`README.md` 与 `references/feishu-artifact-sync.md` 的默认飞书交付说明。

## 验证

```bash
PYTHONPATH=. python3 -m unittest discover -s tests/unit -p 'test_project_cli.py' -q
# Ran 11 tests
# OK
```
