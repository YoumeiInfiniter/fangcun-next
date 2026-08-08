"""
源书级分析：事件提取 + 故事骨架 + 改编策略生成。

产物存放在 _cache/，供 fangcun-novel 和 fangcun-drama 共用。
"""

import json
import re
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 确保 fangcun-analyze/tools 在 path 中（兼容直接调用和被其他 engine 导入）
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
_LIB_DIR = str(Path(__file__).resolve().parent / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from source_io import (
    get_cache_dir, get_source_chapters, get_source_text,
    load_events, save_events, get_events_text,
    load_story_outline, save_story_outline,
    load_skeleton, save_skeleton,
    load_requirements, save_requirements,
    load_adaptation, save_adaptation,
    build_project_rules_context,
)


# ─── 事件提取 ──────────────────────────────────────────────────────────────

def extract_events(config, api_key, api_url, model, prompt_text, workers=5):
    """批量提取事件（带滑窗上下文 + 增量保存）。"""
    from lib.api_client import call_api

    chapters = get_source_chapters(config)
    if not chapters:
        print("[FAIL] 没有找到章节文件")
        return []

    existing = {e["id"]: e for e in load_events(config) if e.get("event")}
    chapters_to_do = [(n, f) for n, f in chapters if n not in existing]

    if len(chapters_to_do) < len(chapters):
        print(f"  已有 {len(chapters) - len(chapters_to_do)} 章事件，跳过")

    if not chapters_to_do:
        print(f"  全部 {len(chapters)} 章事件已有")
        return list(existing.values())

    print(f"  事件提取 | {len(chapters_to_do)} 章待处理 | 并行: {workers} | 模型: {model}")

    t0 = time.time()
    done = 0
    total = len(chapters_to_do)
    results = dict(existing)
    fail_count = 0

    def extract_one(ch_num, ch_file):
        chapter_text = ch_file.read_text(encoding="utf-8")
        prev_context = ""
        prev_ids = sorted([k for k in existing.keys() if k < ch_num], reverse=True)[:2]
        if prev_ids:
            prev_events = [existing[pid]["event"] for pid in prev_ids if existing[pid].get("event")]
            if prev_events:
                prev_context = "前几章事件摘要（供参考）：\n" + "\n".join(prev_events) + "\n\n"

        user_prompt = (
            f"{prev_context}"
            f"请根据以下小说章节数：{ch_num}"
            f"小说章节名称：{ch_file.stem}"
            f"、小说章节内容生成事件摘要：\n"
            f"{chapter_text[:4000]}"
        )
        try:
            result = call_api(api_key, model, user_prompt, system_prompt=prompt_text,
                              api_url=api_url, temperature=0.3, max_tokens=2048)
            result = result.strip()
            return {"id": ch_num, "chapter_index": ch_num, "chapter": ch_file.stem, "event": result}, "ok"
        except Exception as e:
            return None, str(e)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(extract_one, n, f): n for n, f in chapters_to_do}
        for future in as_completed(futures):
            ch_num = futures[future]
            result, status = future.result()
            done += 1
            if result:
                results[ch_num] = result
                existing[ch_num] = result
                print(f"    [{done}/{total}] V 第{ch_num}章")
            else:
                fail_count += 1
                results[ch_num] = {"id": ch_num, "chapter_index": ch_num, "chapter": "", "event": ""}
                print(f"    [{done}/{total}] X 第{ch_num}章 ({status})")
            save_events(config, [results[k] for k in sorted(results.keys())])

    elapsed = time.time() - t0
    ok = sum(1 for v in results.values() if v.get("event"))
    print(f"  完成 | {ok}章成功 / {fail_count}章失败 | {elapsed:.0f}s")
    return [results[k] for k in sorted(results.keys())]



def _build_local_tool_context_mapping() -> str:
    """Fangcun 对 toonflow 原生工具名的外层适配说明。

    保持 S1/S2/S3 system prompt 原生不变；工具语义在 user prompt 的上下文装配层说明。
    """
    return """## Fangcun 本地上下文适配
本阶段使用 GitHub/toonflow 原生 S1/S2/S3 prompt；其中提到的工具由 Fangcun pipeline 预装配为以下上下文：
- get_planData → 项目配置、S0 用户需求文档、上游阶段产物。
- get_novel_events(ids) → 下方原文事件表或事件片段。
- get_novel_text → 当前阶段可用原文/章节摘要。
- get_script_content(ids) → S3 阶段的上一集/已确认剧本片段。
若 S0 用户需求文档与通用方法论冲突，以 S0 为准。"""


def _build_project_info(config: dict) -> str:
    """构建项目配置信息字符串（供骨架和策略 prompt 使用）。"""
    p = config.get("project", {})
    if not p:
        return ""
    duration = p.get("episode_duration", 2)
    words_per_ep = int(duration * 150)
    ch_range = p.get("chapter_range", [1, 999])
    return f"""【项目配置】
- 集数：{p.get("episodes", "?")}集
- 单集时长：{duration}分钟（约{words_per_ep}字台词）
- 原著范围：第{ch_range[0]}-{ch_range[1]}章
- 平台规格：{p.get("platform", "竖屏9:16")}
- 风格定位：{p.get("style", "未指定")}
- 付费策略：{p.get("paywall", "未指定")}"""


# ─── S0 用户需求文档 ───────────────────────────────────────────────────────

def build_requirements(config, api_key, api_url, model, system_prompt, novel_name=""):
    """生成 S0 用户需求文档（AI 根据自然语言/项目配置/事件表自动整理）。"""
    from lib.api_client import call_api

    events_text = get_events_text(config)
    project_info = _build_project_info(config)
    project_rules_context = build_project_rules_context(config)
    project = config.get("project", {})
    user_idea = project.get("adaptation_idea") or project.get("style") or config.get("style") or "按原著改编为短剧"

    user_prompt = f"""## 作品名称
{novel_name or config.get('source_book', '未命名')}

{project_info}

## 用户自然语言需求 / 改编 idea
{user_idea}

{project_rules_context}

## 原文事件表（供 AI 初步理解原著，不要求用户填表）
{events_text[:12000]}

请自动生成 S0 用户改编需求文档。用户不需要填写结构化表格；你需要基于以上信息先给出可执行的项目 brief，并把不确定项放入「待用户确认」。"""

    print(f"  S0 用户需求文档 | 模型: {model}")
    t0 = time.time()
    try:
        result = call_api(api_key, model, user_prompt, system_prompt=system_prompt,
                          api_url=api_url, temperature=0.3, max_tokens=6144)
    except Exception as e:
        print(f"[FAIL] API 调用失败: {e}")
        return None

    m = re.search(r"<requirements[^>]*>([\s\S]*?)</requirements>", result)
    content = m.group(1).strip() if m else result.strip()
    save_requirements(config, content)
    elapsed = time.time() - t0
    print(f"  完成 | {len(content)}字 | {elapsed:.0f}s")
    return content


# ─── 故事骨架 ──────────────────────────────────────────────────────────────

def build_skeleton(config, api_key, api_url, model, system_prompt, novel_name=""):
    """生成 S1 故事骨架。

    对齐 toonflow：S1 基于 S0 用户需求文档 + 事件表建立全剧骨架事实源。
    """
    from lib.api_client import call_api

    events_text = get_events_text(config)
    if "不存在" in events_text or "为空" in events_text:
        print("[FAIL] 事件表不存在，请先提取事件")
        return None

    total_ch = len(get_source_chapters(config))
    valid_events = [e for e in load_events(config) if e.get("event")]

    # 读取 S0 用户需求文档（核心输入——项目 brief）。旧 story_outline 仅作为兼容参考。
    requirements = load_requirements(config)
    context_blocks = ""
    if requirements:
        context_blocks = f"""

## S0 用户需求文档（项目 brief，最高项目输入）

{requirements[:8000]}
"""

    story_outline = load_story_outline(config)
    if story_outline:
        context_blocks += f"""

## 旧版故事大纲（兼容参考，不作为新事实源）

{story_outline[:3000]}
"""

    incremental_note = ""
    if len(valid_events) < total_ch:
        incremental_note = f"""

⚠️ 增量模式：当前只有 {len(valid_events)}/{total_ch} 章事件数据。
只为有事件支撑的章节规划，未覆盖部分标注"待补充"。"""

    project_info = _build_project_info(config)
    project_rules_context = build_project_rules_context(config)
    user_prompt = f"""## 作品名称
{novel_name or config.get('source_book', '未命名')}

{project_info}

{project_rules_context}

{_build_local_tool_context_mapping()}
{context_blocks}
## 原文事件表（参考）
{events_text}
{incremental_note}

请根据 S0 用户需求文档和原文事件表，生成 toonflow S1 故事骨架。
⚠️ S1 是全剧结构事实源：人物小传、三幕结构、分集决策、删减决策、付费卡点和反转登记都应在此稳定下来。
⚠️ 后续 S2/S3 会消费本骨架，不应在后续阶段重开事实源。"""

    print(f"  S1 故事骨架 | {len(valid_events)} 章事件 | 模型: {model}")
    t0 = time.time()

    try:
        result = call_api(api_key, model, user_prompt, system_prompt=system_prompt,
                          api_url=api_url, temperature=0.7, max_tokens=16384)
    except Exception as e:
        print(f"[FAIL] API 调用失败: {e}")
        return None

    m = re.search(r"<storySkeleton[^>]*>([\s\S]*?)</storySkeleton>", result)
    content = m.group(1).strip() if m else result.strip()

    save_skeleton(config, content)
    elapsed = time.time() - t0
    print(f"  完成 | {len(content)}字 | {elapsed:.0f}s")
    return content


# ─── 改编策略 ──────────────────────────────────────────────────────────────

def build_adaptation(config, api_key, api_url, model, system_prompt, novel_name=""):
    """生成 S2 改编策略（对齐 toonflow：基于事件表和 S1 骨架制定策略）。"""
    from lib.api_client import call_api

    events_text = get_events_text(config)

    project_info = _build_project_info(config)
    project_rules_context = build_project_rules_context(config)
    requirements = load_requirements(config)
    skeleton = load_skeleton(config)

    user_prompt = f"""## 作品名称
{novel_name or config.get('source_book', '未命名')}

{project_info}

{project_rules_context}

{_build_local_tool_context_mapping()}

## S0 用户需求文档
{requirements[:8000] if requirements else '（S0 尚未生成；请尽量基于项目配置和事件表制定策略）'}

## S1 故事骨架
{skeleton[:10000] if skeleton else '（S1 骨架尚未生成；建议先运行 --phase skeleton）'}

## 原文事件表
{events_text[:12000]}

请根据原文事件表和 S1 故事骨架，生成 toonflow S2 改编策略。所有改编决策必须服务于 S1 确立的故事核和主角弧线，不得推翻 S1 事实源。"""

    print(f"  S2 改编策略 | 模型: {model}")
    t0 = time.time()

    try:
        result = call_api(api_key, model, user_prompt, system_prompt=system_prompt,
                          api_url=api_url, temperature=0.7, max_tokens=6144)
    except Exception as e:
        print(f"[FAIL] API 调用失败: {e}")
        return None

    m = re.search(r"<adaptationStrategy[^>]*>([\s\S]*?)</adaptationStrategy>", result)
    content = m.group(1).strip() if m else result.strip()

    save_adaptation(config, content)
    elapsed = time.time() - t0
    print(f"  完成 | {len(content)}字 | {elapsed:.0f}s")
    return content
