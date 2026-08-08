# 0021 端到端验证：需求确认单

## 验证目标

验证 Fangcun 在完整剧本使用流程中，能把场次标题稳定输出为业务要求格式，并用本地门禁拦截错误格式。

## 测试输入

- 原文：`source/novel_excerpt.md`
- 项目类型：小说转短剧剧本
- 核心缺陷：模型容易把解释性说明 `【第一集第一场】` 当成剧本格式输出，或使用旧格式 `1-1` + `场：地点-时间-内外`。

## 本次验证参数（已显式列出，避免“测试也跳过需求确认”）

- `novel_name`：山海传媒测试原文片段
- `drama_name`：山海传媒
- `source_dir`：`verification/0021_script_format_e2e/source`
- `output_dir`：`verification/0021_script_format_e2e/artifacts`
- `project.episodes`：2 集
- `project.episode_duration`：2 分钟/集
- `project.chapter_range`：测试片段全文
- `project.platform`：竖屏短剧 / 红果风格参考但不复制任何现有作品
- `project.style`：都市奇幻喜剧、快节奏、抓包现场开场
- `project.paywall`：第 2 集末设置付费钩子
- `aspect_ratio`：9:16 竖屏

## 验证不做的事

- 不调用外部付费/站内视频。
- 不把测试项目写入真实业务项目状态。
- 不写 Jingwei 表1，也不写 Token Usage Observer 表2。
- 不用随机默认值直接跑生产 pipeline。

## 通过标准

1. 好样例必须通过 `validate_script()` 的场次格式门禁。
2. 错样例 A：包含 `【第一集第一场】`，必须被判为严重问题。
3. 错样例 B：使用 `1-1` 单独编号 + `场：xxx-日-内` 旧格式，必须被判为严重问题。
4. 验证报告必须保存输入、流程、中间产物和命令结果。
