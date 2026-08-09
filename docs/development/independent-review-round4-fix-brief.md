# Fangcun Next 第四轮确定性收敛合同

> 修复基线：`144923c6505e68e015acbf371bf50cdcbb37bdcb`
> 开发分支：`codex/fangcun-next-round4`
> 来源：第三轮独立复审的隐藏变体，先复现失败再修改实现。

## 目标

关闭第三轮公共测试未覆盖的确定性绕过，使技术主链达到本地内容质量测试候选标准。本轮不调整台词风格、题材 Craft、容量算法或平台集成。

## 必须成立的不变量

1. 活动和历史 artifact 共用同一项目内路径、存在性与内容哈希验证；历史读取和恢复不能绕过 resolver。
2. continuity delta 必须同时绑定项目实例、集数、当前 approved logical version、完整 script hash 与 delta hash。
3. pointer 自身字段必须参与验证；文件身份不得依赖前八位哈希。
4. delta schema 支持的字段必须投影，不支持字段必须拒绝；备注可保留，但备注本身不能冒充完整连续性提取。
5. 事件级 `must_preserve_pairing` 缺 setup/payoff 任一端时不得退化成普通摘录。
6. 绑定事件的 `must_keep` 只能由该事件同章摘录满足；改编依据必须使用显式 decision id。
7. source error 不能只靠 event/chapter 身份成立，必须有 quote、span 或 excerpt hash 等定位证据。
8. 章节文件是唯一坐标面，保存原始章节切片；事件绑定坐标基准、章节哈希和 span 摘录哈希。
9. ticket 取消必须有非空 operator/reason；按 context 查找 ticket 时不能被其他绑定遮挡。
10. 跨项目复制 delta、相同文本不同逻辑定稿、短哈希前缀碰撞均不得污染连续性。

## 外部验收

`tests/regression/test_round4_external_acceptance.py` 共 15 项，覆盖：

- 历史路径逃逸；
- 相同内容不同 logical version 的旧 delta；
- pointer 字段篡改；
- 短哈希前缀碰撞；
- 顶层和嵌套未知 delta 字段；
- 跨项目 delta；
- notes 投影但保持 degraded；
- 事件级 pairing 缺端；
- 无关摘录冒充 must_keep；
- 自由文本冒充 adaptation decision；
- event-id-only 审核证据；
- quote/span 坐标错配；
- 空理由取消 ticket；
- 多 context ticket 查找顺序。

这些测试在修复前全部失败或确认绕过。不得删除、反转或用固定项目名、路径、哈希进行特判。

## 兼容原则

- 不修改或合并旧 `fangcun-v2-dev`；
- 旧版基线不得新增失败；
- 旧短哈希 delta pointer 只允许在完整项目/version/hash/instance 校验通过时兼容读取；
- 老事件缺精确 span 时允许 degraded，不允许伪造精确证据；
- 旧 XML/业务正文 Adapter 行为保持不变。

## 验收命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/regression -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" .venv/bin/python -m unittest discover -s tests/smoke -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/skills/drama/tools" .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

全程本地运行，不调用真实 API，不执行飞书或 OpenClaw 写入。
