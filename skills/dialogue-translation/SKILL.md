---
name: fangcun-dialogue-translation
description: 中文剧本台词翻译与风格改写。触发：台词翻译、剧本翻译、翻成英文/西语/泰语、黑帮口语、话剧风格、斯文古典。
---

# 台词翻译与风格改写

## 目标

将中文剧本中的台词部分翻译成指定语种，并支持风格控制，同时尽量保留剧本结构。

## 核心规则

1. 不要整篇粗暴翻译；优先识别台词行。
2. 保留场次标题、动作描写、空行、Markdown 结构。
3. 人名保持一致；如需本地化，必须生成术语/人名表。
4. 可输出：
   - 只替换台词版
   - 中外双语对照版
   - 台词抽取表
5. 翻译必须保留人物关系、情绪强度和短剧节奏。
6. **海外文化背景门禁**：当目标地区/受众为海外、欧美、美国、英语区等，禁止保留明显中国制度和称呼词（如「刘队长」「张局长」「派出所」「公安」「民警」「刑警队」「户口本」），必须替换成目标地区自然表达，并建立术语/人名表。

## 支持风格

见 `prompts/style_profiles.md`。

常用：

- default：自然影视口语
- theatrical：话剧风格
- gangster：黑帮口语
- classical_polite：斯文古典
- localized_slang：目标地区本土口语

## 工具

```bash
python3 tools/extract_dialogue.py input.md --out dialogue.jsonl
python3 tools/render_dialogue_translation.py input.md dialogue_translated.jsonl --mode bilingual --out output.md
python3 tools/dialogue_translation_job.py input.md --target-language English --style gangster --workdir ./translate_job
```

也可从 drama pipeline 侧调用：

```bash
python3 tools/pipeline.py --config config.json --phase translate \
  --target-language English \
  --translation-style gangster

# 模型翻译好 JSONL 后回填：
python3 tools/pipeline.py --config config.json --phase translate \
  --target-language English \
  --translation-style gangster \
  --translated-jsonl output/translations/English_gangster/translated.jsonl \
  --translation-mode bilingual
```

## 推荐流程

1. `extract_dialogue.py` 抽取台词行。
2. 使用 `prompts/dialogue_translation.md` 让模型逐条翻译 JSONL。
3. `render_dialogue_translation.py` 回填剧本。
4. 输出飞书文档或附件链接。

## 交付归属

台词翻译与风格改写属于公司版方寸的统一交付能力，不再按版本档位拆分。
