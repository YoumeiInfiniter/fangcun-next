# 「不贴合原著 / 乱编」与「台词简陋」根因分析与已落地修改

> 日期：2026-08-07  
> 范围：V2 开发副本 `fangcun-v2-dev/`（从当前发布包复制后修改）  
> 验证：单元测试对比原版 = 完全一致（4 failures + 3 errors 均为原包既有问题），无新增失败；代码冒烟验证通过

---

## 1. 根因（带证据）

### 1.1 为什么"老爱自己乱编"

| # | 根因 | 证据 |
|---|---|---|
| 1 | **信息链逐级失真**：原文 → 事件表（每章只留 30-60 字摘要）→ 集纲 → 剧本，对话细节在第一级就被丢弃 | `event_extraction.md` 明确要求"核心事件 30-60 字""对话密集章节关注对话推动了什么结果，而非复述对话内容" |
| 2 | **剧本阶段几乎接触不到原文**：上下文里只有 `novel_text_sample`（最多 3 章 × 2000 字），且依赖本地 `第X章*.txt` 拆章 + 按集数平均映射章节 | `pipeline.py _get_novel_text_sample()`；案例 2 用户问"为何要给出原小说？" |
| 3 | **prompt 无"优先使用原著台词"指令**，通篇是情绪/密度/节奏/反转方法论，默认就在再创作 | `script.md` / `script_local.md` 全文无一条"台词优先沿用原著原句" |
| 4 | **审核不查"无依据原创"** | `script_review.md` 阻塞条件 10 条里没有"新增原著不存在的情节"这一条 |
| 5 | **Agent 模式上下文还漏了 Project Rules** | `phase_script_agent()` 打印上下文时没有输出 `project_rules`（bug） |

### 1.2 为什么"台词简陋"

| # | 根因 | 证据 |
|---|---|---|
| 1 | **"短、密、紧"是最高优先级**：宁可砍场删镜，台词量冲突时以短密紧为准 | `script_local.md` 约束第 2 条 |
| 2 | **负向约束多、正向样本少**：单句 ≤20 字、单次 ≤50 字、删废笔，但没有"台词要有信息/情绪/性格"的硬标准 | `script_local.md` 台词创作规范 |
| 3 | **没有风格锚点机制**：编剧给的参考剧本无法注入 | 案例 4"你没有学习参考我给出的剧本文件的格式" |
| 4 | **审核不查台词质量**：阻塞条件里台词只有"角色名错/口吻崩坏" | `script_review.md` |

---

## 2. 本次已落地修改（fangcun-v2-dev）

### 2.1 提示词

| 文件 | 修改 |
|---|---|
| `skills/drama/prompts/script_local.md` | ① 新增「原著优先与贴合度」最高优先级章节（事实源、台词优先原句、fidelity strict/medium/free、禁止无依据原创、编剧修订优先）；② "短密紧"改为"信息密度优先于篇幅"；③ 台词创作规范重写为"台词三问"；④ 单句 ≤20 字改为软约束；⑤ 新增「原著台词 → 短剧版压缩示例」 |
| `skills/drama/prompts/script.md` | 同上：基础规则新增原著优先与贴合度；策略型对话新增台词三问、信息优先于长度、压缩示例 |
| `skills/drama/prompts/script_review.md` | 新增 3 条阻塞条件：无依据原创、必保留项缺失/语义改变、台词质量不达标；非阻塞增加"可更贴原著" |
| `skills/drama/prompts/script_rewrite.md` | 新增原著优先原则 + 机械台词换回原著台词的替换示例 |
| `skills/drama/prompts/skeleton.md` | 每集必须登记**原著锚点**：对应章节、必保留事件、关键台词候选（含出处）、禁止新增项 |
| `skills/drama/prompts/event_extraction.md` | 事件表「核心事件」字段允许以引号保留可复用原句（金句/名场面/关键称呼），作为剧本台词素材 |

### 2.2 代码

| 位置 | 修改 |
|---|---|
| `pipeline.py _get_novel_text_sample()` | 支持 `source_chapter_dir` 兜底；采样扩大到 5 章 × 2500 字；源目录缺失时优雅返回空 |
| `pipeline.py build_fidelity_policy()` | 新增：从 config 读取 fidelity / dialogue_policy / style_anchors，生成贴合度策略块（默认 medium + prefer_original） |
| `pipeline.py build_fixed_user_message_prefix()` | API 模式固定前缀注入 Fidelity Policy |
| `pipeline.py phase_script_agent()` | Agent 模式每集上下文补充输出 Fidelity Policy + Project Rules（修复漏打 bug） |

### 2.3 使用方式（配置示例）

```json
{
  "project": {
    "fidelity": "strict",
    "dialogue_policy": "prefer_original",
    "style_anchors": ["飞书文档：参考剧本《满级婴语》", "已确认集 EP1"],
    "batch_size": 5
  }
}
```

- `fidelity: strict`：剧情硬点逐条落实、台词默认原句、禁止无依据原创（适合案例 3/4 这类项目）；
- `fidelity: medium`：主干贴原著、允许节奏性合并删减（默认）；
- `fidelity: free`：可重组剧情但核心人设卖点不破；
- `dialogue_policy: prefer_original`：台词优先沿用原著原句，只压缩不换说法。

---

## 2.4 Agent 模式重大漏洞修复（2026-08-07 追加）

背景：Agent 模式（默认）此前绕过系统质量闭环——没有结构化审核、没有自动重写、连续性状态不更新。现已按"Agent 负责写、系统负责把关"修复：

| 漏洞 | 修复前 | 修复后 |
|---|---|---|
| 结构化审核缺失 | 保存草稿后只有本地格式校验，内容靠 agent 自觉 | `--save-draft` 保存后**自动触发系统结构化审核**（script_review.md），打印判定与问题清单 |
| 审核门禁可绕过 | `--mark-pass` 直接写 .pass | `--mark-pass` 必须已有审核报告且非 blocked，否则拒绝；未配置 API 时降级为 agent 裁决并记录警告 |
| 连续性状态不更新 | Agent 模式下 continuity 永远为空 | `--mark-pass` 通过后**自动调用连续性更新**并落盘（人物状态/钩子/伏笔） |
| 重写靠自觉 | `--rewrite-draft` 只打印提示 | 配置 API 时执行**系统定向重写 + 自动复审**（script_rewrite.md），仍不过则暂停等人工 |
| 批次提升无质量证据 | 有 .pass 即可提升 | 提升前要求每集有审核报告且非 blocked |
| 双提示词漂移 | Agent 模式读 script.md（Toonflow 版） | Agent 模式改读 script_local.md（与 API 模式同一份），script.md 降级为兼容 |

**运行要求变化**：Agent 模式现在需要 API 凭据来执行系统审核/重写/连续性更新（复用 config 的 `api_key`，可用 `model_overrides.review` 单独指定审核模型）。未配置 API 时功能降级：审核靠 agent 裁决、连续性不更新，并打印明确警告。

**验证**：单元测试与修改前完全一致（4F/3E 均为原包既有问题）；功能冒烟通过——① save 自动审核 + mark_pass 自动连续性 + 批次提升；② blocked 审核下 mark_pass 与提升均被拒绝。

---

## 3. 验证结果

1. 单元测试：V2 与原始包完全一致（4 failures + 3 errors 全部为原包既有问题，与本修改无关；其中一个 error 是 bundled Python 缺 `requests`，已安装后恢复为可运行状态）。
2. 代码冒烟：`build_fidelity_policy`、`_get_novel_text_sample`（含 fallback）、`build_fixed_user_message_prefix`、7 个核心 prompt 加载全部通过。
3. 测试依赖：`python3 -m pip install requests`（方寸本来就要求 requests）。

---

## 4. 本次没做（依赖后续架构工作的部分）

1. **批次集纲契约 JSON**：本次只是让集纲 prompt 登记"原著锚点"，但机器可读契约（contract JSON）还是架构层工作（见《AI主导版流程设计》第 4 节）；
2. **风格锚点自动提取**：本次支持配置 `style_anchors` 并在上下文中声明，但"从参考剧本提取风格档案并注入 few-shot"尚未实现；
3. **人工修订回灌 / 批注读取**：未在本轮实现；
4. **原著摘录从飞书 docx 自动读取**：本次优化了本地章节采样，但原文在飞书 docx 时仍需要导出为本地章节或走协作层。

---

## 5. 下一步验证建议

用「王妈」案例做 5 集最小闭环实验，验证条件：

1. 把小说拆成 `第X章.txt`（或提供章节目录）；
2. 配置 `fidelity: strict` + `dialogue_policy: prefer_original`；
3. 上传参考剧本《满级婴语》到项目（style_anchors）；
4. 出 5 集剧本后对照三个指标：**新增情节是否有事件表依据**、**台词是否可溯源到原著原句**、**编剧修改量占比**。

指标建议：无依据原创集数 = 0；关键台词溯源率 ≥ 60%；编剧修改量 ≤ 30%（当前案例实际接近 100%）。
