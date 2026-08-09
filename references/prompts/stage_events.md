# 原文事件资产阶段

从原文章节提取事件单元，建立可追溯证据，不是创作方案。

每章必须拆为多个独立事件单元（一章多个行动结果就拆多个），每个事件包含：

- event_id（如 CH001-E03）、章节、原文位置 span；
- 事件、触发、动作、结果、必要反应；
- 人物出场、人物认知变化；
- 事件前置依赖、后续回收关系；
- 关键原句（可复用台词及出处）；
- 建议最短/理想呈现时长；
- 主线/支线/过渡；
- 可选改编方式与置信度。

禁止只为每章提取一个事件。关键台词尽量以引号保留原句。

坐标契约：

- 只读取 `source/index.json` 列出的 `source/chapters/chapter_NNN.txt`；
- `source_span` 使用对应章节文件的 Python 字符串坐标，0-based、左闭右开；
- 标题只取 index metadata，不自行向章节正文前追加标题或换行；
- 有 span 时同时输出 `coordinate_base: chapter_file_content` 和位于 span 内的 `source_quote`；
- 不确定准确位置时省略 span，让系统标记 `needs_reanchor`，禁止猜坐标。

输出 source-event.schema.json 兼容 JSON。
