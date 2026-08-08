# Craft 路由

## 选择依据

- 项目题材（配置 genre）；
- 当前集戏剧功能（集纲 episode_function）；
- 编剧指令；
- 审核指出的具体问题；
- 当前集是否需要压缩或扩展（operation）。

## 固定底线模块（每集都加载）

`source-fidelity`、`causality`、`knowledge-state`、`screenplay-format`。

## 按需模块

- 题材：comedy / romance / revenge / suspense / family / male-progression / urban-ability / brainhole；
- 功能：hook / reversal / satisfaction / abuse / expand / compress / audiovisual；
- 操作：compress-without-breaking-causality → compress；expand → expand；hook → hook；等等。

路由由 `scripts/prompt_router.py` 确定性计算，禁止全量注入；类型模块只能影响“怎么表达”，不能改变“已经确认发生什么”。

