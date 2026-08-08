"""
剧本引擎 — 小说转短剧剧本（Toonflow 原生流程 + 全量优化）

优化项：
  - 按阶段配置模型（model_overrides）
  - 事件提取滑窗上下文（带前2章摘要）
  - 事件提取默认用非推理模型
  - 增量骨架（只生成有事件支撑的集数）
  - 剧本只传当前集相关骨架片段
  - 输出校验层

用法:
  python pipeline.py --config configs/drama_xxx.json                     # 全流程
  python pipeline.py --config configs/drama_xxx.json --phase event       # 仅事件提取
  python pipeline.py --config configs/drama_xxx.json --phase requirements # S0 用户需求文档
  python pipeline.py --config configs/drama_xxx.json --phase skeleton    # S1 故事骨架
  python pipeline.py --config configs/drama_xxx.json --phase adaptation  # S2 改编策略
  python pipeline.py --config configs/drama_xxx.json --phase script --start 1 --end 10  # S3 剧本
  python pipeline.py --config configs/drama_xxx.json --phase review --review-target skeleton  # 审核
  python pipeline.py --config configs/drama_xxx.json --phase export      # 合并导出
"""

import os
import sys
import re
import json

# 修复 Windows GBK 编码问题：强制 stdout/stderr 使用 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加本地工具目录到 path（所有依赖已内聚到本模块下）
_TOOLS_DIR = str(Path(__file__).parent)
_LIB_DIR = str(Path(__file__).parent / "lib")
sys.path.insert(0, _TOOLS_DIR)
sys.path.insert(0, _LIB_DIR)
from lib.api_client import (
    DEFAULT_MODEL,
    call_api,
    get_api_key,
    get_api_key_source,
    get_api_url,
    get_api_url_source,
    get_discovered_model,
    test_api_connection,
)
from source_analysis import (
    load_events, save_events, get_events_text, get_source_chapters, get_source_text,
    load_story_outline, save_story_outline,
    load_skeleton, save_skeleton, load_requirements, save_requirements, load_adaptation, save_adaptation,
    extract_events, build_requirements, build_skeleton, build_adaptation,
    get_cache_dir,
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
# 独立技能 prompts 目录（改编指引、审核）
_SKILLS_BASE = _PROMPTS_DIR.parent.parent  # skills/fangcun/skills/
_ADAPTATION_PROMPTS_DIR = _SKILLS_BASE / "adaptation" / "prompts"
_SUPERVISION_PROMPTS_DIR = _SKILLS_BASE / "supervision" / "prompts"

def load_prompt(name: str) -> str:
    """加载 prompt 文件，按优先级搜索：drama/prompts → adaptation/prompts → supervision/prompts"""
    for search_dir in (_PROMPTS_DIR, _ADAPTATION_PROMPTS_DIR, _SUPERVISION_PROMPTS_DIR):
        p = search_dir / name
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt 文件不存在: {name}（已在 drama/adaptation/supervision prompts 中搜索）")

from state_manager import StateManager
try:
    from drama_observer import record_phase as _obs_record_phase
except Exception:
    def _obs_record_phase(*a, **kw): pass  # graceful fallback
try:
    import sys as _sys
    import os as _os
    _audit_path = str((Path(__file__).resolve().parents[4] / 'ops_observer' / 'scripts'))
    if _audit_path not in _sys.path:
        _sys.path.insert(0, _audit_path)
    from audit_log import log_pipeline_step as _audit_pipeline
except Exception:
    def _audit_pipeline(*a, **kw): pass  # graceful fallback
try:
    from asset_registry import register_asset as _register_asset
except Exception:
    def _register_asset(*a, **kw): return None  # graceful fallback
from script_workflow import (
    format_batch_id,
    get_batch_dir,
    get_draft_path,
    is_review_blocked,
    is_episode_passed,
    mark_episode_passed,
    clear_episode_passed,
    is_batch_pending_confirmation,
    mark_batch_pending,
    clear_batch_pending,
    load_continuity_state,
    load_draft,
    load_review_report,
    promote_batch_to_scripts,
    save_continuity_state,
    save_draft,
    save_review_report,
    save_rewrite_attempt,
    write_batch_summary,
)

from fangcun_guardrails import ensure_output_path, is_machine_identifier, safe_project_display_name, sanitize_user_visible_text
from agent_tools import (
    get_events, get_events_json, save_events,
    get_story_outline, save_story_outline,
    get_skeleton, save_skeleton,
    get_adaptation, save_adaptation,
    get_novel_text, get_novel_chapters,
    get_script_content, save_script, get_all_scripts,
    extract_xml_tag, extract_script_items,
    extract_episode_from_skeleton,
    validate_script, validate_event,
)
from source_io import (
    build_project_rules_context,
    build_project_rules_change_summary,
    get_project_rules_path,
    load_project_rules,
    save_project_rule,
    validate_project_rules_applied,
    extract_rule_candidates_from_chat_text,
    save_project_rule_candidates,
    load_project_rule_candidates,
)


# ─── 模型解析 ───────────────────────────────────────────────────────────────

def get_phase_model(config: dict, phase: str) -> str:
    """按阶段解析模型。

    优先级：model_overrides.{phase} > config.model > OpenClaw 自动发现 > 阶段默认值。

    优化：事件提取默认用非推理模型（避免 MiMo 推理 token 浪费）。
    """
    overrides = config.get("model_overrides", {})
    if phase in overrides:
        return overrides[phase]
    if config.get("model"):
        return config["model"]
    discovered = get_discovered_model()
    if discovered:
        return discovered
    if phase == "event":
        return "deepseek-chat"
    return DEFAULT_MODEL


def get_phase_api(config: dict, phase: str) -> tuple[str, str, str]:
    """返回 (api_key, api_url, model)。"""
    api_key = get_api_key(config)
    api_url = get_api_url(config)
    model = get_phase_model(config, phase)
    return api_key, api_url, model


def _phase_needs_api(phase: str, dry_run: bool = False) -> bool:
    if phase in ("status", "export", "translate"):
        return False
    # dry-run only prints the planned work/context; it must not require or probe external LLM API keys.
    if dry_run:
        return False
    return True


def _preflight_api_check(config: dict, phase: str, dry_run: bool = False) -> bool:
    if not _phase_needs_api(phase, dry_run):
        return True

    model = get_phase_model(config, "skeleton" if phase == "all" else phase)
    print("\n[PREFLIGHT] API 连接预检")
    print(f"[PREFLIGHT] API Key 来源: {get_api_key_source(config)}")
    print(f"[PREFLIGHT] API URL 来源: {get_api_url_source(config)}")
    print(f"[PREFLIGHT] API URL: {get_api_url(config)}")

    result = test_api_connection(config, timeout=10, model=model)
    if result["success"]:
        print(f"[PREFLIGHT] 连接成功 | 模型: {result['model']} | 延迟: {result['latency_ms']}ms")
        return True

    print(f"[PREFLIGHT] 连接失败 | 模型: {result['model']}")
    print(f"[PREFLIGHT] 错误: {result['error']}")
    print("[PREFLIGHT] 请通过以下任一方式配置 API：")
    print("  1. 设置环境变量 API_KEY / API_BASE_URL")
    print("  2. 在 config.json 中添加 api_key / api_base_url / model")
    print("  3. 在 OpenClaw 的 ~/.openclaw/openclaw.json 中配置 deepseek 或 openai-completions provider")
    return False


# ─── 项目配置信息 ───────────────────────────────────────────────────────────

def build_project_info(config: dict) -> str:
    p = config.get("project", {})
    duration = p.get("episode_duration", 2)
    words_per_ep = int(duration * 150)
    ch_range = p.get("chapter_range", [1, 999])
    return f"""【项目配置】
- 集数：{p.get('episodes', '?')}集
- 单集时长：{duration}分钟（约{words_per_ep}字台词）
- 原著范围：第{ch_range[0]}-{ch_range[1]}章
- 平台规格：{p.get('platform', '竖屏9:16')}
- 画幅：{p.get('aspect_ratio', p.get('画幅', '未指定'))}
- 风格定位：{p.get('style', '未指定')}
- 付费策略：{p.get('paywall', '未指定')}"""


def validate_project_intake(config: dict) -> list[str]:
    """Return missing startup fields that the agent must ask the user to fill."""
    issues = []
    required_top = ["novel_name", "drama_name", "output_dir"]
    for key in required_top:
        if not config.get(key):
            issues.append(f"missing {key}: ask the user to provide it before running the workflow.")
    if config.get("drama_name") and is_machine_identifier(config.get("drama_name")):
        issues.append("invalid drama_name: it is a chat/user machine id, ask the user for the real drama/project title before creating outputs.")
    if config.get("novel_name") and is_machine_identifier(config.get("novel_name")):
        issues.append("invalid novel_name: it is a chat/user machine id, ask the user for the real novel title before creating outputs.")
    if config.get("output_dir") and is_machine_identifier(Path(config.get("output_dir")).name):
        issues.append("invalid output_dir: project folder name is a chat/user machine id; recreate under a human project title folder.")
    if not (config.get("source_dir") or config.get("source_chapter_dir")):
        issues.append("missing source_dir: ask the user for the novel chapter directory.")
    project = config.get("project") or {}
    required_project = ["episodes", "episode_duration", "chapter_range", "platform", "style", "paywall", "aspect_ratio"]
    for key in required_project:
        if project.get(key) in (None, "", []):
            issues.append(f"missing project.{key}: ask the user to provide project basics.")
    return issues


def print_project_intake_questions(issues: list[str]):
    if not issues:
        return
    print("[WAIT] Project intake is incomplete. Ask the user for these basics before continuing:")
    for issue in issues:
        print(f"  - {issue}")
    print("Required basics: novel_name, drama_name, source_dir, output_dir, episodes, episode_duration, chapter_range, platform, style, paywall.")


def ensure_project_intake(config: dict) -> bool:
    issues = validate_project_intake(config)
    if issues:
        print_project_intake_questions(issues)
        return False
    return True


def get_phase_output_paths(config: dict, phase: str, review_target: str = None) -> list[Path]:
    output_dir = Path(config["output_dir"])
    cache_dir = get_cache_dir(config)
    if phase == "event":
        return [cache_dir / "events.json"]
    if phase in ("requirements", "s0"):
        return [cache_dir / "requirements.md"]
    if phase == "story_outline":
        return [cache_dir / "story_outline.md"]
    if phase == "skeleton":
        return [cache_dir / "story_skeleton.md"]
    if phase == "adaptation":
        return [cache_dir / "adaptation_strategy.md"]
    if phase == "review":
        targets = [review_target] if review_target and review_target != "all" else ["requirements", "skeleton", "adaptation"]
        return [output_dir / "reviews" / f"{target}_review.md" for target in targets]
    if phase == "script":
        return [output_dir / "drafts"]
    if phase == "export":
        return [output_dir / f"{config.get('drama_name', 'script')}.txt"]
    return []


def print_output_paths(title: str, paths: list[Path]):
    if not paths:
        return
    print(f"{title}:")
    for path in paths:
        print(f"  {path.resolve()}")


def _require_review_report_exists(config: dict, prerequisite_target: str) -> bool:
    """Hard gate: refuse to proceed if the required review report file does not exist.

    This is a file-level guard that cannot be bypassed by deleting state.json.
    It ensures the AI review phase was actually executed before moving on.
    """
    output_dir = Path(config["output_dir"])
    report_path = output_dir / "reviews" / f"{prerequisite_target}_review.md"
    if report_path.exists() and report_path.stat().st_size > 50:
        return True
    print(f"\n{'='*60}")
    print(f"⛔ 硬门控：{prerequisite_target} 审核报告不存在")
    print(f"{'='*60}")
    print(f"  必须先运行 AI 审核才能进入下一阶段：")
    print(f"  python tools/pipeline.py --config {{config}} --phase review --review-target {prerequisite_target}")
    print(f"")
    print(f"  预期文件: {report_path.resolve()}")
    print(f"{'='*60}")
    return False


def ensure_human_review_confirmed(state: StateManager, phase_name: str) -> bool:
    pending = state.get_pending_human_review() if state else None
    if not pending:
        return True
    if pending.get("unlock_phase") != phase_name:
        return True
    print("[WAIT] AI review is complete, but human review confirmation is still required before continuing.")
    print(f"target: {pending.get('target')}")
    print(f"report: {Path(pending.get('report_path', '')).resolve()}")
    print(f"confirm: python tools/pipeline.py --config {{config}} --confirm-review --review-target {pending.get('target')}")
    return False


def phase_confirm_review(config: dict, state: StateManager, target: str, decision: str = "approved", notes: str = ""):
    pending = state.get_pending_human_review()
    if not pending:
        print("no human review is waiting for confirmation")
        return False
    if pending.get("target") != target:
        print(f"[FAIL] pending review target is {pending.get('target')}, not {target}")
        return False
    ok = state.confirm_human_review(target, decision, notes)
    if ok:
        print(f"human review confirmed: {target} -> {pending.get('unlock_phase')}")
    return ok


# ─── 事件提取（优化：滑窗上下文 + 非推理模型 + 增量保存 + 校验）──────────

def phase_event(config: dict, workers: int = 5):
    api_key, api_url, model = get_phase_api(config, "event")
    if not api_key:
        print("[FAIL] 未设置 API_KEY")
        return False
    prompt_text = load_prompt("event_extraction.md")
    cache_dir = get_cache_dir(config)
    print(f"\n{'='*50}")
    print(f"事件提取 | {config.get('novel_name', '')}")
    print(f"输出: {cache_dir}/events.json")
    print(f"{'='*50}")
    events = extract_events(config, api_key, api_url, model, prompt_text, workers)
    if events:
        print_output_paths("event output", get_phase_output_paths(config, "event"))
    return len(events) > 0


def phase_requirements(config: dict, dry_run: bool = False):
    """阶段：S0 用户需求文档生成（AI 根据自然语言/事件表自动整理）。"""
    api_key, api_url, model = get_phase_api(config, "adaptation")
    if dry_run:
        print(f"[DRY-RUN] S0 用户需求文档 | 模型 {model}")
        return True
    if not api_key:
        print("[FAIL] 未设置 API_KEY")
        return False
    system_prompt = load_prompt("requirements.md")
    system_prompt += "\n\n你必须使用如下XML格式写入工作区：\n<requirements>S0用户需求文档</requirements>"
    cache_dir = get_cache_dir(config)
    print(f"\n{'='*50}")
    print(f"S0 用户需求文档 | {config.get('novel_name', '')}")
    print(f"输出: {cache_dir}/requirements.md")
    print(f"{'='*50}")
    result = build_requirements(config, api_key, api_url, model, system_prompt, config.get("novel_name", ""))
    if result is not None:
        print_output_paths("requirements output", get_phase_output_paths(config, "requirements"))
        _obs_record_phase(config, phase="requirements", success=True,
                          char_count=len(result) if isinstance(result, str) else 0)
        _audit_pipeline(config.get('project',{}).get('name') or config.get('novel_name',''),
                        'requirements', 'success', detail='S0用户需求文档生成完成')
    return result is not None


def phase_story_outline(config: dict, dry_run: bool = False):
    """阶段：故事大纲生成（旧版兼容；toonflow 对齐流程默认不再使用）"""
    api_key, api_url, model = get_phase_api(config, "story_outline")
    if not api_key:
        print("[FAIL] 未设置 API_KEY")
        return False
    prompt_text = load_prompt("story_outline.md")
    cache_dir = get_cache_dir(config)

    print(f"\n{'='*50}")
    print(f"阶段：故事大纲（基于改编指引设计新故事）")
    print(f"{'='*50}")

    events_text = get_events_text(config)
    project_info = build_project_info(config)
    project_rules_context = build_project_rules_context(config)
    rules_change_summary = build_project_rules_change_summary(config)

    # 读取改编指引（核心输入）
    adaptation = load_adaptation(config)
    adaptation_context = ""
    if adaptation:
        adaptation_snippet = adaptation[:6000]
        adaptation_context = f"""

## 改编指引（已通过审核，大纲需基于此指引设计新故事）

以下是改编指引中确定的新设定。故事大纲不是梳理原文脉络，而是设计改编后新剧的蓝图：
- 新角色身份/关系必须在故事大纲中体现
- 被删除的角色/情节在大纲中不出现
- 新增的看点在大纲中设计为具体剧情节点

{adaptation_snippet}
"""

    user_prompt = f"""{project_info}

{project_rules_context}

{rules_change_summary}

{adaptation_context}
以下是原著的事件表（参考素材，不是直接复用的底本）：

## 事件表
{events_text}

⚠️ 重要：你设计的是改编后的**新故事**大纲，不是梳理原文。改编指引中的人物变化、世界设定变化都必须在大纲中落实。
⚠️ 项目 Rules 优先于通用改编技法；如某版本规则去掉某技法（例如反差），大纲中不得继续沿用旧规则。
⚠️ 必须严格遵守 story_outline.md 的固定 10 节格式；如需说明项目规则落实情况，只能合并写入第十节「改编方向说明」，不得新增「项目规则落实清单」或任何第 11 节。"""

    if dry_run:
        print("[DRY RUN] 将调用 API 生成故事大纲（prompt 长度: {} chars）".format(len(user_prompt)))
        return True

    print("调用 API 生成故事大纲...")
    try:
        result = call_api(
            api_key, model, user_prompt,
            system_prompt=prompt_text,
            api_url=api_url,
            temperature=0.5,
            max_tokens=8192,
        )
        save_story_outline(config["output_dir"], result)
        outline_path = cache_dir / "story_outline.md"
        print(f"  ✓ 故事大纲已保存 → {outline_path.resolve()}")
        return True
    except Exception as e:
        print(f"  ✗ 故事大纲生成失败: {e}")
        return False


def phase_skeleton(config: dict, dry_run: bool = False):
    api_key, api_url, model = get_phase_api(config, "skeleton")
    if dry_run:
        print(f"[DRY-RUN] 模型 {model}")
        return True
    if not api_key:
        print("[FAIL] 未设置 API_KEY")
        return False
    system_prompt = load_prompt("skeleton.md")
    system_prompt += "\n\n你必须使用如下XML格式写入工作区：\n<storySkeleton>集纲内容</storySkeleton>"
    cache_dir = get_cache_dir(config)
    print(f"\n{'='*50}")
    print(f"S1 故事骨架 | {config.get('novel_name', '')}")
    print(f"输出: {cache_dir}/story_skeleton.md")
    print(f"{'='*50}")
    result = build_skeleton(config, api_key, api_url, model, system_prompt, config.get("novel_name", ""))
    if result is not None:
        print_output_paths("skeleton output", get_phase_output_paths(config, "skeleton"))
        _obs_record_phase(config, phase="skeleton", success=True,
                          char_count=len(result) if isinstance(result, str) else 0)
        _audit_pipeline(config.get('project',{}).get('name') or config.get('novel_name',''),
                        'skeleton', 'success', detail='集纲生成完成')
    return result is not None


def phase_adaptation(config: dict, dry_run: bool = False):
    api_key, api_url, model = get_phase_api(config, "adaptation")
    if dry_run:
        print(f"[DRY-RUN] 模型 {model}")
        return True
    if not api_key:
        print("[FAIL] 未设置 API_KEY")
        return False
    system_prompt = load_prompt("adaptation.md")
    system_prompt += "\n\n你必须使用如下XML格式写入工作区：\n<adaptationStrategy>改编策略内容</adaptationStrategy>"
    cache_dir = get_cache_dir(config)
    print(f"\n{'='*50}")
    print(f"S2 改编策略 | {config.get('novel_name', '')}")
    print(f"输出: {cache_dir}/adaptation_strategy.md")
    print(f"{'='*50}")
    result = build_adaptation(config, api_key, api_url, model, system_prompt, config.get("novel_name", ""))
    if result is not None:
        print_output_paths("adaptation output", get_phase_output_paths(config, "adaptation"))
        _obs_record_phase(config, phase="adaptation", success=True,
                          char_count=len(result) if isinstance(result, str) else 0)
        _audit_pipeline(config.get('project',{}).get('name') or config.get('novel_name',''),
                        'adaptation', 'success', detail='S2改编策略生成完成')
    return result is not None


# Script writing: serial drafts plus per-episode quality gate

def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {
                "verdict": "blocked",
                "summary": "AI review did not return valid JSON",
                "severe_issues": ["review result is not valid JSON"],
                "non_blocking_issues": [],
                "rewrite_instructions": ["rerun review or inspect draft manually"],
            }
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {
                "verdict": "blocked",
                "summary": "AI review JSON could not be parsed",
                "severe_issues": ["review JSON parse failed"],
                "non_blocking_issues": [],
                "rewrite_instructions": ["rerun review or inspect draft manually"],
            }


def _extract_script_content(result: str) -> str:
    """Extract one complete <scriptItem> block while preserving the wrapper.

    The script validator and downstream delivery both require the saved draft to
    keep <scriptItem>...</scriptItem>.  Older code stripped the wrapper after
    parsing, which made API-mode drafts fail the same local validation that the
    agent-mode drafts pass.
    """
    m = re.search(r'<scriptItem\s+name="[^"]*"[^>]*>[\s\S]*?</scriptItem>', result)
    if m:
        return m.group(0).strip()
    return result.strip()


def _get_previous_episode_context(output_dir: str, batch_id: str, ep_num: int) -> str:
    if ep_num <= 1:
        return ""
    draft = load_draft(output_dir, batch_id, ep_num - 1)
    if draft:
        return draft
    return get_script_content(output_dir, [ep_num - 1])


def _get_novel_text_sample(config: dict, ep_num: int) -> str:
    source_dir = config.get("source_dir") or config.get("source_chapter_dir")
    if not source_dir:
        return ""
    project = config.get("project", {})
    novel_text_sample = ""
    events_json = get_events_json(config["output_dir"])
    if events_json:
        chapter_range = project.get("chapter_range", [1, 999])
        chapters_per_ep = max(1, (chapter_range[1] - chapter_range[0] + 1) // project.get("episodes", 20))
        ch_start = chapter_range[0] + (ep_num - 1) * chapters_per_ep
        ch_end = min(ch_start + chapters_per_ep - 1, chapter_range[1])
        for ch in range(ch_start, min(ch_start + 5, ch_end + 1)):
            text = get_novel_text(source_dir, ch)
            if text:
                novel_text_sample += f"\n\n--- Chapter {ch} ---\n{text[:2500]}"
    return novel_text_sample


def build_fidelity_policy(config: dict) -> str:
    """返回贴合度/台词策略/风格锚点指令块；未配置时使用 medium + prefer_original 默认值。"""
    project = config.get("project", {})
    fidelity = project.get("fidelity") or config.get("fidelity") or "medium"
    dialogue = project.get("dialogue_policy") or config.get("dialogue_policy") or "prefer_original"
    anchors = project.get("style_anchors") or config.get("style_anchors") or []
    lines = [
        "## Fidelity Policy（贴合度策略，最高优先级）",
        f"- fidelity: {fidelity}",
        f"- dialogue_policy: {dialogue}",
        "- strict：剧情硬点逐条落实、台词默认原句、禁止无依据原创；",
        "- medium：主干事件与关键台词贴原著，允许为节奏合并删减；",
        "- free：可重组剧情，但核心人设与卖点不破。",
        "- dialogue_policy=prefer_original：优先沿用原著原句，只压缩不换说法。",
    ]
    if anchors:
        lines.append("- style_anchors: " + "、".join(str(a) for a in anchors))
    return "\n".join(lines)


def _build_local_tool_context_mapping() -> str:
    """Explain OpenClaw local-file context without leaking toonflow tool syntax."""
    return """## Fangcun 本地上下文适配
本阶段由 OpenClaw / Python pipeline 直接提供全部上下文；模型只负责输出完整剧本文本，不调用任何外部工具，也不输出工具名或工作台确认语。

已在下方提供的上下文包括：项目配置、S0 用户需求文档、S1 故事骨架、S2 改编策略、已生成剧本摘要、当前集事件表/原文片段、上一集或已确认剧本片段。
若 S0 用户需求文档与通用方法论冲突，以 S0 为准。"""


def build_user_requirements_prefix(config: dict) -> str:
    """Return S0 requirements as a project-level user-task frame.

    Keep the GitHub/toonflow message shape: stable project facts and user task
    material belong in the user message, not in the native system prompt.  S0
    `requirements.md` already owns the format and content, so runtime should not
    invent a second schema.  It only wraps the document with a clear source
    marker and keeps it in the user message, not system.
    """
    requirements = load_requirements(config).strip()
    requirements_content = requirements[:5000] if requirements else "(requirements.md missing; stop and complete S0 before creative generation)"
    return f"""## 用户改编需求（S0 requirements.md，作为用户任务描述传入，非系统指令）

{requirements_content}""".strip()


def build_fixed_user_message_prefix(config: dict, project_info: str = "") -> str:
    """Build the stable user-message prefix for project-specific context.

    Keep native prompts as the system message and inject project brief/rules as
    a fixed prefix of the user message.  This keeps generic writing instructions
    separate from per-project facts, avoids editing prompt files for one project,
    and preserves provider prefix-cache friendliness because the stable project
    block appears before variable episode/script context.
    """
    project_rules_context = build_project_rules_context(config)
    rules_change_summary = build_project_rules_change_summary(config)
    blocks = ["## 固定用户消息前缀｜项目上下文"]
    if project_info:
        blocks.append(project_info.strip())
    blocks.append(build_fidelity_policy(config))
    blocks.append(_build_local_tool_context_mapping())
    blocks.append(f"## Work Title\n{config.get('novel_name', 'Untitled')}")
    blocks.append(build_user_requirements_prefix(config))
    if project_rules_context:
        blocks.append("## Project Rules\n" + project_rules_context)
    if rules_change_summary:
        blocks.append("## Rules Change Summary\n" + rules_change_summary)
    blocks.append("## 固定前缀结束｜以下为本次调用的动态任务上下文")
    return "\n\n".join(blocks).strip()


def build_script_user_prompt(config, project_info, script_list_str, ep_skeleton, adaptation, events_text,
                             prev_script, novel_text_sample, target_words, ep_num,
                             continuity_state, batch_continuity_state):
    format_prompt = '\nYou must write using this XML format:\n<scriptItem name="script title">script content</scriptItem>'
    fixed_prefix = build_fixed_user_message_prefix(config, project_info)
    return f"""{fixed_prefix}

{script_list_str}

## Confirmed Continuity State
{json.dumps(continuity_state, ensure_ascii=False, indent=2)}

## Current Draft Batch Continuity State
{json.dumps(batch_continuity_state, ensure_ascii=False, indent=2)}

## Episode Skeleton
{ep_skeleton}

## Adaptation Strategy
{adaptation}

## Event Table
{events_text[:2000]}

{"## Previous Episode Script" if prev_script else ""}
{prev_script[:3000] if prev_script else ""}

{"## Source Novel Excerpts" if novel_text_sample else ""}
{novel_text_sample[:3000] if novel_text_sample else ""}

Write the complete script for episode {ep_num}. Target length: about {target_words} script characters. {format_prompt}

Output only the complete `<scriptItem>...</scriptItem>` script. Do not add explanations, summaries, tool calls, workbench confirmations, checklists, or any text outside the XML wrapper. Apply project rules inside the actual scenes, actions, dialogue, and synopsis instead of appending a meta checklist."""


def review_script_draft(config, api_key, api_url, model, ep_num, draft_content, ep_skeleton,
                        prev_script, continuity_state, batch_continuity_state):
    system_prompt = load_prompt("script_review.md")
    user_prompt = f"""Review episode {ep_num} draft.

## Episode Skeleton
{ep_skeleton}

## Previous Episode Script
{prev_script[:3000] if prev_script else ""}

## Confirmed Continuity State
{json.dumps(continuity_state, ensure_ascii=False, indent=2)}

## Current Batch Continuity State
{json.dumps(batch_continuity_state, ensure_ascii=False, indent=2)}

## Draft Script
{draft_content}
"""
    result = call_api(api_key, model, user_prompt, system_prompt=system_prompt, api_url=api_url, temperature=0.2, max_tokens=2048)
    report = _parse_json_object(result)
    local_issues = validate_script(draft_content, int(config.get("project", {}).get("episode_duration", 2) * 500))
    severe = [issue for issue in local_issues if issue.startswith("\u4e25\u91cd")]
    warnings = [issue for issue in local_issues if not issue.startswith("\u4e25\u91cd")]
    if severe:
        report.setdefault("severe_issues", []).extend(severe)
        report["verdict"] = "blocked"
    if warnings:
        report.setdefault("non_blocking_issues", []).extend(warnings)
        if report.get("verdict") == "pass":
            report["verdict"] = "warning"
    return report


def _local_draft_review_report(config: dict, ep_num: int, draft_content: str) -> dict:
    """Build a blocking review report from local deterministic script checks."""
    target_words = int(config.get("project", {}).get("episode_duration", 2) * 500)
    issues = validate_script(draft_content, target_words)
    severe = [issue for issue in issues if issue.startswith("严重")]
    warnings = [issue for issue in issues if not issue.startswith("严重")]
    if severe:
        return {
            "verdict": "blocked",
            "summary": f"EP{ep_num} 本地硬门禁未通过，禁止标记 PASS。",
            "severe_issues": severe,
            "non_blocking_issues": warnings,
            "rewrite_instructions": ["重新生成或人工改写本集，确保输出完整剧本文本而不是工具占位/工作台提示。"],
        }
    return {
        "verdict": "passed" if not warnings else "warning",
        "summary": f"EP{ep_num} 本地格式门禁通过；{'存在非阻塞提醒' if warnings else '未发现硬阻塞'}。",
        "severe_issues": [],
        "non_blocking_issues": warnings or ["跳过 AI 复审时仅代表本地格式/门禁通过，仍需编剧人工确认内容质量。"],
    }


def rewrite_script_draft(config, api_key, api_url, model, ep_num, draft_content, review_report,
                         ep_skeleton, prev_script, continuity_state, batch_continuity_state):
    system_prompt = load_prompt("script_rewrite.md")
    user_prompt = f"""Rewrite episode {ep_num} draft based on the review report.

## Review Report
{json.dumps(review_report, ensure_ascii=False, indent=2)}

## Episode Skeleton
{ep_skeleton}

## Previous Episode Script
{prev_script[:3000] if prev_script else ""}

## Continuity State
{json.dumps({"confirmed": continuity_state, "current_batch": batch_continuity_state}, ensure_ascii=False, indent=2)}

## Original Draft
{draft_content}
"""
    result = call_api(api_key, model, user_prompt, system_prompt=system_prompt, api_url=api_url, temperature=0.55, max_tokens=4096)
    return _extract_script_content(result)


def update_continuity_state(config, api_key, api_url, model, ep_num, script_content, current_state):
    system_prompt = load_prompt("continuity_update.md")
    user_prompt = f"""Update continuity state using the approved script for episode {ep_num}.

## Current Continuity State
{json.dumps(current_state, ensure_ascii=False, indent=2)}

## Episode {ep_num} Script
{script_content}
"""
    result = call_api(api_key, model, user_prompt, system_prompt=system_prompt, api_url=api_url, temperature=0.2, max_tokens=2048)
    parsed = _parse_json_object(result)
    if not parsed.get("episodes"):
        parsed = dict(current_state)
    parsed["version"] = 1
    return parsed


def _load_script_system_prompt() -> str:
    """加载剧本编写的系统提示词，包含基础规则和专业技能文件。"""
    system_prompt = load_prompt("script_local.md")

    # 加载 writing-methods
    try:
        writing_methods = load_prompt("writing-methods.md")
        system_prompt += f"\n\n## Writing methods reference only; do not copy into script\n\n{writing_methods}"
    except FileNotFoundError:
        pass

    # 加载所有专业技能文件（craft/）
    craft_dir = _PROMPTS_DIR / "craft"
    if craft_dir.is_dir():
        craft_files = sorted(craft_dir.glob("*.md"))
        if craft_files:
            system_prompt += "\n\n## 🎯 Professional Craft Skills (reference — load only what this episode needs)\n\n"
            system_prompt += "These are your professional writing techniques. Before writing this episode, "
            system_prompt += "decide privately which skills apply, but do not output any skill report, comments, annotations, "
            system_prompt += "checklists, or metadata. The final answer must remain pure `<scriptItem>` script text only.\n\n"
            for cf in craft_files:
                skill_name = cf.stem
                try:
                    content = cf.read_text(encoding="utf-8")
                    system_prompt += f"---\n## Skill: {skill_name}\n{content}\n\n"
                except Exception:
                    pass

    return system_prompt


def _get_active_draft_batch(state: StateManager):
    if state is None:
        print("[FAIL] draft operations require state.json")
        return None
    pending = state.get_pending_script_batch()
    if not pending:
        print("[FAIL] no active draft batch; run --phase script first")
        return None
    return pending


def _episode_in_batch(pending: dict, ep_num: int) -> bool:
    return int(ep_num) in [int(ep) for ep in pending.get("episodes", [])]


def _load_episode_review_context(config: dict, batch_id: str, ep_num: int):
    output_dir = config["output_dir"]
    skeleton = get_skeleton(output_dir)
    if not skeleton:
        raise FileNotFoundError("story_skeleton.md is missing; run --phase skeleton first")
    return {
        "ep_skeleton": extract_episode_from_skeleton(skeleton, ep_num),
        "prev_script": _get_previous_episode_context(output_dir, batch_id, ep_num),
        "continuity_state": load_continuity_state(output_dir),
        "batch_continuity_state": load_continuity_state(output_dir, batch_id),
    }


def _save_episode_review_state(state: StateManager, ep_num: int, report: dict):
    if state is None:
        return
    blocked = is_review_blocked(report)
    state.set_episode_review(ep_num, report.get("verdict", "warning"), blocked, len(report.get("severe_issues", [])))


def _update_batch_continuity(config: dict, api_key: str, api_url: str, model: str,
                             batch_id: str, ep_num: int, script_content: str,
                             batch_continuity_state: dict) -> dict:
    updated = update_continuity_state(config, api_key, api_url, model, ep_num, script_content, batch_continuity_state)
    save_continuity_state(config["output_dir"], updated, batch_id)
    return updated


def _refresh_batch_summary(config: dict, pending: dict):
    if not pending:
        return None
    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    episodes = [int(ep) for ep in pending.get("episodes", [])]
    review_reports = {ep: load_review_report(output_dir, batch_id, ep) for ep in episodes}
    return write_batch_summary(output_dir, batch_id, episodes, review_reports)


def _run_system_review(config: dict, state: StateManager, batch_id: str, ep_num: int, draft_content: str):
    """Agent 模式系统审核：对 agent 写的草稿运行结构化 AI 审核并保存报告。

    返回 report；未配置 API 时返回 None（由 agent 或人工裁决）。
    """
    api_key, api_url, model = get_phase_api(config, "review")
    if not api_key:
        print("[SKIP] 未配置 API 凭据，系统审核跳过；请配置 api_key，或由 agent 用 --mark-pass / --mark-blocked 明确裁决。")
        return None
    ctx = _load_episode_review_context(config, batch_id, ep_num)
    report = review_script_draft(
        config, api_key, api_url, model, ep_num, draft_content,
        ctx["ep_skeleton"], ctx["prev_script"],
        ctx["continuity_state"], ctx["batch_continuity_state"],
    )
    save_review_report(config["output_dir"], batch_id, ep_num, report)
    _save_episode_review_state(state, ep_num, report)
    pending = state.get_pending_script_batch() if state else None
    _refresh_batch_summary(config, pending)
    return report


def _run_system_rewrite(config: dict, state: StateManager, batch_id: str, ep_num: int,
                        draft_content: str, review_report: dict):
    """Agent 模式系统重写：基于审核报告定向重写草稿，并自动复审。

    返回复审 report；未配置 API 时返回 None。
    """
    api_key, api_url, model = get_phase_api(config, "review")
    if not api_key:
        print("[SKIP] 未配置 API 凭据，系统重写跳过；请 agent 自行重写后 --save-draft。")
        return None
    ctx = _load_episode_review_context(config, batch_id, ep_num)
    rewritten = rewrite_script_draft(
        config, api_key, api_url, model, ep_num, draft_content, review_report,
        ctx["ep_skeleton"], ctx["prev_script"],
        ctx["continuity_state"], ctx["batch_continuity_state"],
    )
    attempt = state.mark_episode_rewrite_attempt(ep_num) if state else 1
    save_rewrite_attempt(config["output_dir"], batch_id, ep_num, attempt, rewritten)
    save_draft(config["output_dir"], batch_id, ep_num, rewritten)
    clear_episode_passed(config["output_dir"], batch_id, ep_num)
    return _run_system_review(config, state, batch_id, ep_num, rewritten)


def phase_review_draft(config: dict, state: StateManager, ep_num: int):
    pending = _get_active_draft_batch(state)
    if not pending:
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    draft_content = load_draft(output_dir, batch_id, ep_num)
    if not draft_content:
        print(f"[FAIL] draft not found: {get_draft_path(output_dir, batch_id, ep_num)}")
        return False

    api_key, api_url, model = get_phase_api(config, "script")
    if not api_key:
        print("[FAIL] API_KEY is missing")
        return False
    ctx = _load_episode_review_context(config, batch_id, ep_num)
    report = review_script_draft(
        config, api_key, api_url, model, ep_num, draft_content,
        ctx["ep_skeleton"], ctx["prev_script"],
        ctx["continuity_state"], ctx["batch_continuity_state"],
    )
    _, review_md = save_review_report(output_dir, batch_id, ep_num, report)
    _save_episode_review_state(state, ep_num, report)
    _refresh_batch_summary(config, pending)
    _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本初稿审核")
    if is_review_blocked(report):
        print(f"[BLOCKED] EP{ep_num} draft still has severe issues")
        print(f"draft: {get_draft_path(output_dir, batch_id, ep_num).resolve()}")
        print("choose: manually edit then --review-draft, or run --rewrite-draft --episode N")
        return False

    _update_batch_continuity(config, api_key, api_url, model, batch_id, ep_num, draft_content, ctx["batch_continuity_state"])
    mark_episode_passed(output_dir, batch_id, ep_num)
    print(f"[PASS] EP{ep_num} draft review passed")
    return True


def phase_rewrite_draft(config: dict, state: StateManager, ep_num: int):
    pending = _get_active_draft_batch(state)
    if not pending:
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    draft_content = load_draft(output_dir, batch_id, ep_num)
    if not draft_content:
        print(f"[FAIL] draft not found: {get_draft_path(output_dir, batch_id, ep_num)}")
        return False

    api_key, api_url, model = get_phase_api(config, "script")
    if not api_key:
        print("[FAIL] API_KEY is missing")
        return False
    ctx = _load_episode_review_context(config, batch_id, ep_num)
    report = load_review_report(output_dir, batch_id, ep_num)
    if not is_review_blocked(report):
        report = review_script_draft(
            config, api_key, api_url, model, ep_num, draft_content,
            ctx["ep_skeleton"], ctx["prev_script"],
            ctx["continuity_state"], ctx["batch_continuity_state"],
        )
        save_review_report(output_dir, batch_id, ep_num, report)
        _save_episode_review_state(state, ep_num, report)
        if not is_review_blocked(report):
            _update_batch_continuity(config, api_key, api_url, model, batch_id, ep_num, draft_content, ctx["batch_continuity_state"])
            _refresh_batch_summary(config, pending)
            print(f"[PASS] EP{ep_num} draft already passes review; no rewrite needed")
            return True

    attempt = state.mark_episode_rewrite_attempt(ep_num) if state else 1
    save_rewrite_attempt(output_dir, batch_id, ep_num, attempt, draft_content)
    rewritten = rewrite_script_draft(
        config, api_key, api_url, model, ep_num, draft_content, report,
        ctx["ep_skeleton"], ctx["prev_script"],
        ctx["continuity_state"], ctx["batch_continuity_state"],
    )
    draft_path = save_draft(output_dir, batch_id, ep_num, rewritten)
    report = review_script_draft(
        config, api_key, api_url, model, ep_num, rewritten,
        ctx["ep_skeleton"], ctx["prev_script"],
        ctx["continuity_state"], ctx["batch_continuity_state"],
    )
    _, review_md = save_review_report(output_dir, batch_id, ep_num, report)
    _save_episode_review_state(state, ep_num, report)
    _refresh_batch_summary(config, pending)
    _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本重写后审核 (attempt {attempt})")
    if is_review_blocked(report):
        print(f"[BLOCKED] EP{ep_num} rewrite attempt {attempt} still has severe issues")
        print(f"draft: {draft_path.resolve()}")
        print("choose: manually edit then --review-draft, or run --rewrite-draft --episode N again")
        return False

    _update_batch_continuity(config, api_key, api_url, model, batch_id, ep_num, rewritten, ctx["batch_continuity_state"])
    mark_episode_passed(output_dir, batch_id, ep_num)
    print(f"[PASS] EP{ep_num} rewrite passed")
    print(f"draft: {draft_path.resolve()}")
    return True


def phase_script(config: dict, start: int = 1, end: int = 3, dry_run: bool = False,
                 state: StateManager = None, batch_size: int = None, skip_draft_review: bool = False):
    output_dir = config["output_dir"]
    api_key, api_url, model = get_phase_api(config, "script")
    if not api_key:
        print("[FAIL] API_KEY is missing")
        return False
    current_batch = state.get_pending_script_batch() if state else None
    if state and state.has_pending_script_confirmation():
        pending = state.get_pending_script_batch()
        print("[WAIT] A draft batch is waiting for writer confirmation; cannot generate a new batch.")
        print(f"batch: {pending['batch_id']}")
        print(f"summary: {pending.get('batch_summary_path', '')}")
        print("confirm: python tools/pipeline.py --config {config} --promote-draft-batch")
        return False

    # File-level pending lock: check ALL existing batches for unconfirmed .pending files
    drafts_dir = Path(output_dir) / "drafts"
    if drafts_dir.exists():
        for batch_dir in sorted(drafts_dir.iterdir()):
            if batch_dir.is_dir():
                bid = batch_dir.name
                if is_batch_pending_confirmation(output_dir, bid):
                    print(f"\n{'='*60}")
                    print(f"\u26d4 \u6279\u6b21\u786c\u95e8\u63a7\uff1a{bid} \u5c1a\u672a\u786e\u8ba4")
                    print(f"{'='*60}")
                    print(f"  \u4e0a\u4e00\u6279\u8349\u7a3f\u5fc5\u987b\u7ecf\u4eba\u5de5\u786e\u8ba4\u540e\u624d\u80fd\u7ee7\u7eed\u751f\u6210\u4e0b\u4e00\u6279\u3002")
                    print(f"  \u786e\u8ba4\u547d\u4ee4: python tools/pipeline.py --config {{config}} --promote-draft-batch")
                    print(f"{'='*60}")
                    return False

    skeleton = get_skeleton(output_dir)
    adaptation = get_adaptation(output_dir)
    events_text = get_events(output_dir)
    if not skeleton:
        print("[FAIL] story_skeleton.md is missing; run --phase skeleton first")
        return False
    if not adaptation:
        print("[FAIL] adaptation_strategy.md is missing; run --phase adaptation first")
        return False

    project = config.get("project", {})
    project_info = build_project_info(config)
    duration = project.get("episode_duration", 2)
    target_words = int(duration * 500)  # 500 chars/min includes stage directions + dialogue
    batch_size = int(batch_size or config.get("script_batch_size", 5))
    if batch_size > 10:
        print(f"  \u26a0\ufe0f \u6279\u6b21\u5927\u5c0f\u4e3a{batch_size}\u96c6\uff0c\u751f\u6210+\u5ba1\u6838\u53ef\u80fd\u9700\u8981\u8f83\u957f\u65f6\u95f4\uff08\u9884\u8ba1{batch_size * 2}\u5206\u949f\u4ee5\u4e0a\uff09")
    if current_batch:
        batch_id = current_batch["batch_id"]
        episodes = [int(ep) for ep in current_batch.get("episodes", [])]
    else:
        batch_end = min(end, start + batch_size - 1)
        episodes = list(range(start, batch_end + 1))
        confirmed_batches = []
        if state:
            confirmed_batches = state.state.setdefault("script_batches", {"current": None, "confirmed": []}).setdefault("confirmed", [])
        batch_id = format_batch_id(len(confirmed_batches) + 1)
    if state and not current_batch:
        state.start_script_batch(batch_id, episodes)

    existing_scripts = get_all_scripts(output_dir)
    script_list_str = ""
    if existing_scripts:
        script_list_str = "## Confirmed scripts\n" + ", ".join([f"EP{s['id']}:{s['name']}" for s in existing_scripts])
    print(f"\n{'='*50}")
    print(f"script draft generation | {config.get('novel_name', '')} | EP{episodes[0]}-{episodes[-1]}")
    print(f"model: {model} | target: {target_words} chars/episode | draft batch: {batch_id}")
    print(f"{'='*50}")

    system_prompt = _load_script_system_prompt()
    format_prompt = '\nYou must write using this XML format:\n<scriptItem name="script title">script content</scriptItem>'
    continuity_state = load_continuity_state(output_dir)
    batch_continuity_state = load_continuity_state(output_dir, batch_id)
    review_reports = {}
    t0 = time.time()
    for idx, ep_num in enumerate(episodes, start=1):
        prev_script = _get_previous_episode_context(output_dir, batch_id, ep_num)
        ep_skeleton = extract_episode_from_skeleton(skeleton, ep_num)
        novel_text_sample = _get_novel_text_sample(config, ep_num)
        user_prompt = build_script_user_prompt(config, project_info, script_list_str, ep_skeleton, adaptation, events_text, prev_script, novel_text_sample, target_words, ep_num, continuity_state, batch_continuity_state)
        if dry_run:
            print(f"  [DRY-RUN] EP{ep_num} prompt length: {len(user_prompt)} chars")
            continue
        try:
            existing_draft = load_draft(output_dir, batch_id, ep_num)
            if existing_draft:
                script_content = existing_draft
                draft_path = get_draft_path(output_dir, batch_id, ep_num)
                # Skip review if already passed
                if is_episode_passed(output_dir, batch_id, ep_num):
                    batch_continuity_state = update_continuity_state(config, api_key, api_url, model, ep_num, script_content, batch_continuity_state)
                    save_continuity_state(output_dir, batch_continuity_state, batch_id)
                    print(f"  [{idx}/{len(episodes)}] SKIP EP{ep_num} (already passed) -> {draft_path}")
                    continue
                if skip_draft_review:
                    report = _local_draft_review_report(config, ep_num, script_content)
                    save_review_report(output_dir, batch_id, ep_num, report)
                    blocked = is_review_blocked(report)
                    review_reports[ep_num] = report
                    if state:
                        state.set_episode_review(ep_num, report.get("verdict", "warning"), blocked, len(report.get("severe_issues", [])))
                    if blocked:
                        clear_episode_passed(output_dir, batch_id, ep_num)
                        _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 本地剧本门禁 (batch)")
                        print(f"  [{idx}/{len(episodes)}] BLOCKED EP{ep_num}: local gate failed; paused")
                        print(f"  draft: {draft_path.resolve()}")
                        print("  choose: manually edit then --review-draft, or run --rewrite-draft --episode N")
                        return False
                else:
                    report = review_script_draft(config, api_key, api_url, model, ep_num, script_content, ep_skeleton, prev_script, continuity_state, batch_continuity_state)
                    save_review_report(output_dir, batch_id, ep_num, report)
                    blocked = is_review_blocked(report)
                    review_reports[ep_num] = report
                    if state:
                        state.set_episode_review(ep_num, report.get("verdict", "warning"), blocked, len(report.get("severe_issues", [])))
                    if blocked:
                        _, review_md = save_review_report(output_dir, batch_id, ep_num, report)
                        _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本初稿审核 (batch)")
                        print(f"  [{idx}/{len(episodes)}] BLOCKED EP{ep_num}: existing draft still has severe issues; paused")
                        print(f"  draft: {draft_path.resolve()}")
                        print("  choose: manually edit then --review-draft, or run --rewrite-draft --episode N")
                        return False
                    else:
                        mark_episode_passed(output_dir, batch_id, ep_num)
                        _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本初稿审核")
                batch_continuity_state = update_continuity_state(config, api_key, api_url, model, ep_num, script_content, batch_continuity_state)
                save_continuity_state(output_dir, batch_continuity_state, batch_id)
                print(f"  [{idx}/{len(episodes)}] PASS EP{ep_num} existing draft ({len(script_content)} chars) -> {draft_path}")
                continue

            result = call_api(api_key, model, user_prompt, system_prompt=system_prompt + format_prompt, api_url=api_url, temperature=0.7, max_tokens=4096)
            script_content = _extract_script_content(result)
            severe = _validate_script_before_gate(config, script_content, label=f"EP{ep_num} api-generated draft")
            if severe:
                print(f"  [{idx}/{len(episodes)}] BLOCKED EP{ep_num}: generated draft failed hard format gate before save")
                return False
            draft_path = save_draft(output_dir, batch_id, ep_num, script_content)
            blocked = False
            report = {}
            if skip_draft_review:
                report = _local_draft_review_report(config, ep_num, script_content)
                save_review_report(output_dir, batch_id, ep_num, report)
                blocked = is_review_blocked(report)
            else:
                report = review_script_draft(config, api_key, api_url, model, ep_num, script_content, ep_skeleton, prev_script, continuity_state, batch_continuity_state)
                save_review_report(output_dir, batch_id, ep_num, report)
                if is_review_blocked(report):
                    attempt = state.mark_episode_rewrite_attempt(ep_num) if state else 1
                    save_rewrite_attempt(output_dir, batch_id, ep_num, attempt, script_content)
                    rewritten = rewrite_script_draft(config, api_key, api_url, model, ep_num, script_content, report, ep_skeleton, prev_script, continuity_state, batch_continuity_state)
                    severe = _validate_script_before_gate(config, rewritten, label=f"EP{ep_num} rewritten draft")
                    if severe:
                        print(f"  [{idx}/{len(episodes)}] BLOCKED EP{ep_num}: rewritten draft failed hard format gate before save")
                        return False
                    draft_path = save_draft(output_dir, batch_id, ep_num, rewritten)
                    report = review_script_draft(config, api_key, api_url, model, ep_num, rewritten, ep_skeleton, prev_script, continuity_state, batch_continuity_state)
                    save_review_report(output_dir, batch_id, ep_num, report)
                    script_content = rewritten
                blocked = is_review_blocked(report)
            review_reports[ep_num] = report
            if state:
                state.set_episode_review(ep_num, report.get("verdict", "warning"), blocked, len(report.get("severe_issues", [])))
            if blocked:
                _, review_md = save_review_report(output_dir, batch_id, ep_num, report)
                _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本初稿审核 (batch)")
                print(f"  [{idx}/{len(episodes)}] BLOCKED EP{ep_num}: severe issues remain; paused")
                print(f"  draft: {draft_path.resolve()}")
                print("  choose: manually edit then --review-draft, or run --rewrite-draft --episode N")
                return False
            mark_episode_passed(output_dir, batch_id, ep_num)
            _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本初稿审核")
            batch_continuity_state = update_continuity_state(config, api_key, api_url, model, ep_num, script_content, batch_continuity_state)
            save_continuity_state(output_dir, batch_continuity_state, batch_id)
            print(f"  [{idx}/{len(episodes)}] PASS EP{ep_num} draft ({len(script_content)} chars) -> {draft_path}")
        except Exception as e:
            print(f"  [{idx}/{len(episodes)}] FAIL EP{ep_num} ({e})")
            if state:
                state.episode_failed(ep_num, error=str(e))
                state.save()
            return False
    if dry_run:
        print(f"would write drafts to: {Path(output_dir) / 'drafts' / batch_id}")
        return True
    summary_path = write_batch_summary(output_dir, batch_id, episodes, review_reports)
    mark_batch_pending(output_dir, batch_id)
    if state:
        state.mark_batch_waiting_confirmation(str(summary_path))
    elapsed = time.time() - t0
    # obs: 记录剧本批次用量
    total_chars = sum(
        len(load_draft(output_dir, batch_id, ep) or "")
        for ep in episodes
    )
    _obs_record_phase(config, phase="script", episodes=episodes, elapsed=elapsed,
                      char_count=total_chars, success=True)
    _audit_pipeline(
        config.get('project',{}).get('name') or config.get('novel_name',''),
        'script', 'success',
        detail=f"EP{episodes[0]}-{episodes[-1]} {len(episodes)}集 {total_chars}字 {elapsed:.0f}s",
        duration_ms=int(elapsed*1000),
    )
    print(f"\n{'='*50}")
    print(f"draft batch complete | {batch_id} | EP{episodes[0]}-{episodes[-1]} | {elapsed:.0f}s")
    print(f"draft dir: {(Path(output_dir) / 'drafts' / batch_id).resolve()}")
    print(f"batch summary: {summary_path.resolve()}")
    print("promote internally after writer review: python tools/pipeline.py --config {config} --promote-draft-batch")
    print(f"{'='*50}")
    return True


def phase_confirm_draft_batch(config: dict, state: StateManager):
    pending = state.get_pending_script_batch()
    if not pending:
        print("no draft batch is waiting for confirmation")
        return False
    batch_id = pending["batch_id"]
    episodes = pending["episodes"]
    for ep in episodes:
        draft_content = load_draft(config["output_dir"], batch_id, int(ep))
        if not draft_content:
            print(f"[FAIL] draft not found for EP{int(ep):03d}: {get_draft_path(config['output_dir'], batch_id, int(ep))}")
            return False
        severe = _validate_script_before_gate(config, draft_content, label=f"EP{int(ep)} promote-draft-batch")
        if severe:
            print("  Batch promotion blocked; fix the draft and re-run --validate-draft / --mark-pass first.")
            return False
        if not is_episode_passed(config["output_dir"], batch_id, int(ep)):
            print(f"[BLOCK] EP{int(ep):03d} has no .pass marker; run --validate-draft and --mark-pass before promotion.")
            return False
        report_path = get_batch_dir(config["output_dir"], batch_id) / "reviews" / f"ep_{int(ep):03d}_review.json"
        if not report_path.exists():
            print(f"[BLOCK] EP{int(ep):03d} 无审核报告；请先 --review-draft / --save-draft 触发系统审核，再 --mark-pass。")
            return False
        report = load_review_report(config["output_dir"], batch_id, int(ep))
        if is_review_blocked(report):
            print(f"[BLOCK] EP{int(ep):03d} 审核未通过（blocked）；禁止提升批次。请先 --rewrite-draft 修复。")
            return False
    promoted = promote_batch_to_scripts(config["output_dir"], batch_id, episodes)
    batch_state = load_continuity_state(config["output_dir"], batch_id)
    save_continuity_state(config["output_dir"], batch_state)
    state.confirm_script_batch([str(p) for p in promoted])
    for ep in episodes:
        script_path = Path(config["output_dir"]) / "scripts" / f"ep_{ep:03d}.txt"
        state.episode_completed(ep, chars=len(script_path.read_text(encoding="utf-8")))
    state.save()
    # Clear the file-level pending lock
    clear_batch_pending(config["output_dir"], batch_id)
    print("draft batch internally promoted to scripts/ (not user-confirmed):")
    for path in promoted:
        print(f"  {path.resolve()}")
    return True


PROJECT_FINISH_PHRASES = ("剧本完结", "剧本结束", "项目结束")
EXPORT_FOLLOWUP_PROMPT = "目前你要求的剧集都已经导出。如果未来还需要调整剧本，可以继续告诉我修改意见；如果项目已经结束，请回复：项目结束 / 剧本完结 / 剧本结束。"


def is_project_finish_text(text: str) -> bool:
    return any(phrase in (text or "") for phrase in PROJECT_FINISH_PHRASES)


def phase_confirm_user_batch(config: dict, state: StateManager, message_id: str = "", notes: str = "") -> bool:
    batch = state.confirm_latest_script_batch_by_user(message_id=message_id, notes=notes)
    if not batch:
        print("[FAIL] no promoted script batch found for user confirmation")
        return False
    eps = batch.get("episodes") or []
    print(f"[OK] user confirmed script batch {batch.get('batch_id')} EP{eps[0]:03d}-EP{eps[-1]:03d}")
    print("[WAIT] 批次已确认，但不登记项目完结；用户可继续修改批次。")
    print(EXPORT_FOLLOWUP_PROMPT)
    if message_id:
        print(f"  message_id: {message_id}")
    return True


def phase_confirm_project_finished(config: dict, state: StateManager, message_id: str = "", finish_text: str = "", notes: str = "") -> bool:
    if not is_project_finish_text(finish_text):
        allowed = " / ".join(PROJECT_FINISH_PHRASES)
        print(f"[FAIL] 未检测到项目完结口令；只有用户明确说「{allowed}」才允许登记完结")
        return False
    finished = state.mark_project_finished_by_user(message_id=message_id, finish_text=finish_text, notes=notes)
    print(f"[OK] project finished confirmed by user: {finished.get('finish_text')}")
    if message_id:
        print(f"  message_id: {message_id}")
    return True


# ─── 质量审核 ───────────────────────────────────────────────────────────────

def phase_review(config: dict, target: str = "all", state: StateManager = None):
    output_dir = config["output_dir"]
    api_key, api_url, model = get_phase_api(config, "review")

    if not api_key:
        print("[FAIL] 未设置 API_KEY")
        return False

    project_info = build_project_info(config)
    project_rules_context = build_project_rules_context(config)
    rules_change_summary = build_project_rules_change_summary(config)
    system_prompt = load_prompt("supervision.md")
    reviews_dir = Path(output_dir) / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    results = []

    if target in ("requirements", "all"):
        requirements = load_requirements(config)
        if requirements:
            print(f"\n{'='*50}")
            print(f"审核：S0 用户需求文档")
            print(f"{'='*50}")

            events_text = get_events(output_dir)
            user_prompt = f"""{project_info}

{project_rules_context}

{rules_change_summary}

请审核【S0 用户需求文档】的产出物。
审核维度：是否准确承接用户自然语言需求、项目基础信息是否完整、原著理解是否合理、改编边界是否清楚、待确认项是否明确、是否没有替 S1/S2/S3 提前完成创作。

## S0 用户需求文档
{requirements}

## 事件表
{events_text}"""

            try:
                result = call_api(
                    api_key, model, user_prompt,
                    system_prompt=system_prompt,
                    api_url=api_url,
                    temperature=0.3,
                    max_tokens=4096,
                )
                review_file = reviews_dir / "requirements_review.md"
                review_file.write_text(result, encoding="utf-8")
                results.append(("S0 用户需求文档", result))
                print(f"  ✓ 审核完成 → {review_file.resolve()}")
                if state:
                    state.mark_human_review_required("requirements", str(review_file.resolve()), "skeleton")
                    print("  [WAIT] Human review gate recorded: requirements -> skeleton")
            except Exception as e:
                print(f"  ✗ 审核失败: {e}")

    if target in ("story_outline", "all"):
        outline = load_story_outline(config)
        if outline:
            print(f"\n{'='*50}")
            print(f"审核：故事大纲")
            print(f"{'='*50}")

            events_text = get_events(output_dir)
            user_prompt = f"""{project_info}

{project_rules_context}

{rules_change_summary}

请审核【故事大纲】的产出物。
审核维度：故事核清晰度、受众定位准确度、大结构合理性、核心矛盾强度、关键节点覆盖、情绪曲线设计、卖点矩阵完整度、改编方向说明、项目规则符合性

## 故事大纲
{outline}

## 事件表
{events_text}"""

            try:
                result = call_api(
                    api_key, model, user_prompt,
                    system_prompt=system_prompt,
                    api_url=api_url,
                    temperature=0.3,
                    max_tokens=4096,
                )
                review_file = reviews_dir / "story_outline_review.md"
                review_file.write_text(result, encoding="utf-8")
                results.append(("故事大纲", result))
                print(f"  ✓ 审核完成 → {review_file.resolve()}")
                if state:
                    state.mark_human_review_required("story_outline", str(review_file.resolve()), "skeleton")
                    print("  [WAIT] Human review gate recorded: story_outline -> skeleton")
            except Exception as e:
                print(f"  ✗ 审核失败: {e}")

    if target in ("skeleton", "all"):
        skeleton = get_skeleton(output_dir)
        if skeleton:
            print(f"\n{'='*50}")
            print(f"审核：集纲（逐集分场）")
            print(f"{'='*50}")

            events_text = get_events(output_dir)
            story_outline = get_story_outline(output_dir)
            outline_context = ""
            if story_outline:
                outline_context = f"""

## 故事大纲（改编后的新故事蓝图）
{story_outline[:3000]}
"""

            user_prompt = f"""{project_info}

{project_rules_context}

{rules_change_summary}

请审核【集纲】的产出物。
审核维度：结构完整性、分集与时长、章节全覆盖、付费点分布、重大反转登记、矛盾强度、三大密度结构、心理级爽点/金手指、投放素材、前10%黄金结构、情绪布局、信息差标注、集末钩子、节奏框架、项目规则符合性
{outline_context}
## 集纲
{skeleton}

## 事件表
{events_text}"""

            try:
                result = call_api(
                    api_key, model, user_prompt,
                    system_prompt=system_prompt,
                    api_url=api_url,
                    temperature=0.3,
                    max_tokens=4096,
                )
                review_file = reviews_dir / "skeleton_review.md"
                review_file.write_text(result, encoding="utf-8")
                results.append(("故事骨架", result))
                print(f"  ✓ 审核完成 → {review_file.resolve()}")
                if state:
                    state.mark_human_review_required("skeleton", str(review_file.resolve()), "adaptation")
                    print("  [WAIT] Human review gate recorded: skeleton -> adaptation")
            except Exception as e:
                print(f"  ✗ 审核失败: {e}")

    if target in ("adaptation", "all"):
        adaptation = get_adaptation(output_dir)
        story_outline = get_story_outline(output_dir)
        if adaptation:
            print(f"\n{'='*50}")
            print(f"审核：改编指引")
            print(f"{'='*50}")

            events_text = get_events(output_dir)
            user_prompt = f"""{project_info}

{project_rules_context}

{rules_change_summary}

请审核【改编指引】的产出物。
审核维度：改编方向是否落实用户idea、人物改编是否自洽、删减决策是否合理、世界观重构是否完整、新增看点是否清晰、项目规则符合性

## 改编指引
{adaptation}

## 原文事件表（参考）
{events_text}"""

            try:
                result = call_api(
                    api_key, model, user_prompt,
                    system_prompt=system_prompt,
                    api_url=api_url,
                    temperature=0.3,
                    max_tokens=4096,
                )
                review_file = reviews_dir / "adaptation_review.md"
                review_file.write_text(result, encoding="utf-8")
                results.append(("改编策略", result))
                print(f"  ✓ 审核完成 → {review_file.resolve()}")
                if state:
                    state.mark_human_review_required("adaptation", str(review_file.resolve()), "script")
                    print("  [WAIT] Human review gate recorded: adaptation -> script")
            except Exception as e:
                print(f"  ✗ 审核失败: {e}")

    if results:
        print()
        print(f"{'='*50}")
        print(f"review complete | {len(results)} item(s)")
        print(f"{'='*50}")
        print_output_paths("review report path", get_phase_output_paths(config, "review", target))
        print("Wait for human review confirmation before continuing to the next phase.")
        _obs_record_phase(config, phase=f"review-{target}", success=True)
        _audit_pipeline(
            config.get('project',{}).get('name') or config.get('novel_name',''),
            f'review_{target}', 'success', detail=f'{len(results)} 项审核完成'
        )
    return True


# ─── 审核门控 ───────────────────────────────────────────────────────────────

def parse_review_score(review_text: str) -> dict:
    """从审核报告中解析评分和问题统计。

    Returns:
        {
            "score": "A"|"B"|"C"|"D"|None,
            "severe": int,    # 🔴 严重问题数
            "medium": int,    # 🟡 中等问题数
            "summary": str,   # 总评概要
            "blocked": bool,  # 是否阻塞
        }
    """
    result = {"score": None, "severe": 0, "medium": 0, "summary": "", "blocked": False}

    # 解析评分：支持 **评分**：**D** 或 评分：D 等格式
    m = re.search(r"\*{0,2}评分\*{0,2}[：:]\s*\*{0,2}([ABCD])\*{0,2}", review_text)
    if m:
        result["score"] = m.group(1)

    # 统计严重/中等问题
    result["severe"] = len(re.findall(r"[🔴🛑]\s*严重", review_text))
    result["medium"] = len(re.findall(r"[🟡⚠️]\s*中等", review_text))

    # 提取总评概要
    m = re.search(r"概要\*{0,2}[：:]\s*\*{0,2}(.+?)\*{0,2}", review_text)
    if m:
        result["summary"] = m.group(1).strip()

    # 门控判断
    score = result["score"]
    if score == "D" or result["severe"] >= 1:
        result["blocked"] = True
    elif score == "C" or result["medium"] >= 3:
        result["blocked"] = False  # 警告但不阻塞

    return result


def gate_review(review_text: str, target_name: str) -> tuple[bool, str]:
    """审核门控：检查审核结果，决定是否允许进入下一阶段。

    Returns:
        (proceed: bool, message: str)
        - proceed=True: 可以通过
        - proceed=False: 必须修复后重新审核
    """
    if not review_text or not review_text.strip():
        return True, ""  # 无审核内容，放行

    r = parse_review_score(review_text)

    if r["blocked"]:
        msg = (
            f"\n{'='*60}\n"
            f"⛔ 审核门控：{target_name} 未通过\n"
            f"{'='*60}\n"
            f"  评分: {r['score'] or 'N/A'} | 严重问题: {r['severe']} | 中等问题: {r['medium']}\n"
            f"  概要: {r['summary']}\n"
            f"\n"
            f"  ⚠ 必须先修复上述问题，才能进入下一阶段。\n"
            f"\n"
            f"  修复方式:\n"
            f"    1. 查看审核报告: reviews/{target_name.replace(' ', '_')}_review.md\n"
            f"    2. 根据建议修改后，重新运行:\n"
            f"       --phase skeleton  (重新生成骨架)\n"
            f"       --phase review --review-target skeleton  (重新审核)\n"
            f"    3. 如果确认当前版本可接受，使用 --skip-review-gate 跳过门控\n"
            f"{'='*60}\n"
        )
        return False, msg

    if r["score"] == "C" or r["medium"] >= 3:
        msg = (
            f"\n{'='*60}\n"
            f"⚠️ 审核门控：{target_name} 有改进空间\n"
            f"{'='*60}\n"
            f"  评分: {r['score']} | 中等问题: {r['medium']}\n"
            f"  概要: {r['summary']}\n"
            f"\n"
            f"  建议修复后再继续。如果确认当前版本可用，无需操作。\n"
            f"{'='*60}\n"
        )
        return True, msg  # 警告但不阻塞

    # 通过
    msg = (
        f"\n{'='*60}\n"
        f"✅ 审核门控：{target_name} 通过\n"
        f"  评分: {r['score'] or 'N/A'} | 严重: 0 | 中等: {r['medium']}\n"
        f"{'='*60}\n"
    )
    return True, msg


def load_review(output_dir: str, target: str) -> str:
    """加载审核报告内容。"""
    review_file = Path(output_dir) / "reviews" / f"{target}_review.md"
    if review_file.exists():
        return review_file.read_text(encoding="utf-8")
    return ""


# ─── 资产 / 用量旁路记录 ────────────────────────────────────────────────────

def _project_id(config: dict) -> str:
    if config.get("project_id") or config.get("drama_id"):
        return config.get("project_id") or config.get("drama_id")
    out = Path(config.get("output_dir", "."))
    # Fangcun 默认 output_dir 常是 <project>/drama；归因项目 id 应取项目目录名，
    # 否则多个项目都会写成 project_id=drama，主统计难以聚合。
    return out.parent.name if out.name == "drama" and out.parent.name else out.name


def _project_name(config: dict) -> str:
    return safe_project_display_name(
        config.get("drama_name"),
        config.get("novel_name"),
        config.get("project", {}).get("name"),
        _project_id(config),
    )



def _register_local_asset(config: dict, *, asset_type: str, stage: str, title: str, local_path: Path,
                          source: str = "ai", status: str = "draft", episode_range: str = ""):
    import argparse as _argparse
    try:
        _register_asset(_argparse.Namespace(
            project_dir=config.get("output_dir"),
            project_id=_project_id(config),
            project_name=_project_name(config),
            asset_type=asset_type,
            stage=stage,
            version=config.get("asset_version") or "r1",
            source=source,
            status=status,
            title=title,
            episode_range=episode_range,
            local_path=str(local_path),
            doc_url="",
            doc_token="",
            parent_asset_id="",
            asset_id=f"local_{stage}_{local_path.stem}".replace("/", "_"),
            actor="fangcun-pipeline",
            notes="registered by pipeline",
        ))
    except Exception as exc:
        print(f"[WARN] asset registry skipped: {exc}")


# ─── 合并导出 ───────────────────────────────────────────────────────────────

def phase_export(config: dict):
    output_dir = config["output_dir"]
    drama_name = config.get("drama_name", "剧本")
    scripts = get_all_scripts(output_dir)

    if not scripts:
        print("没有可导出的剧本")
        return False

    parts = [s["content"] for s in scripts]
    export_file = ensure_output_path(output_dir, Path(output_dir) / f"{drama_name}.txt", label="完整剧本导出文件")
    export_file.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
    _register_local_asset(config, asset_type="script_batch", stage="export", title=f"{drama_name}-完整导出", local_path=export_file, status="approved")
    print(f"导出完成: {export_file} ({len(scripts)}集)")
    print(EXPORT_FOLLOWUP_PROMPT)
    return True


def phase_translate(config: dict, target_language: str, style: str = "default", locale: str = "",
                    translated_jsonl: str = "", mode: str = "bilingual") -> bool:
    """Prepare or render dialogue translation for exported script.

    This is a deterministic wrapper around dialogue-translation/tools. It does
    not call external model APIs, so it is safe as an optional export-side phase.
    """
    import subprocess
    output_dir = Path(config["output_dir"])
    drama_name = config.get("drama_name", "剧本")
    script_path = ensure_output_path(output_dir, output_dir / f"{drama_name}.txt", label="待翻译剧本文件")
    if not script_path.exists():
        ok = phase_export(config)
        if not ok or not script_path.exists():
            print("[FAIL] cannot translate: exported script missing")
            return False
    tool = Path(__file__).resolve().parents[2] / "dialogue-translation" / "tools" / "dialogue_translation_job.py"
    workdir = ensure_output_path(output_dir, output_dir / "translations" / f"{target_language}_{style}", label="翻译产物目录")
    cmd = [
        sys.executable, str(tool), str(script_path),
        "--target-language", target_language,
        "--style", style,
        "--workdir", str(workdir),
        "--mode", mode,
    ]
    if locale:
        cmd.extend(["--locale", locale])
    if translated_jsonl:
        cmd.extend(["--translated-jsonl", translated_jsonl])
    subprocess.run(cmd, check=True)
    if translated_jsonl:
        rendered = workdir / f"{script_path.stem}.{target_language}.{style}.{mode}.md"
        if rendered.exists():
            _register_local_asset(config, asset_type="translation", stage="translate", title=f"{drama_name}-{target_language}-{style}", local_path=rendered, status="draft")
    return True


# ─── 主入口 ─────────────────────────────────────────────────────────────────

# ─── Agent Mode: Context & Toolbox Commands ─────────────────────────────────

def build_episode_context(config: dict, state: StateManager, ep_num: int) -> dict:
    """Build full generation context for a single episode.

    Returns a dict with all context pieces needed for script writing.
    """
    output_dir = config["output_dir"]
    skeleton = get_skeleton(output_dir)
    adaptation = get_adaptation(output_dir)
    requirements = load_requirements(config)
    events_text = get_events(output_dir)

    pending = state.get_pending_script_batch() if state else None
    batch_id = pending["batch_id"] if pending else None

    # Auto-detect batch if state has no pending batch
    if not batch_id:
        drafts_dir = Path(output_dir) / "drafts"
        if drafts_dir.exists():
            batches = sorted([d.name for d in drafts_dir.iterdir() if d.is_dir() and d.name.startswith("batch_")])
            if batches:
                batch_id = batches[-1]

    continuity_state = load_continuity_state(output_dir)
    batch_continuity_state = load_continuity_state(output_dir, batch_id) if batch_id else {}
    project_info = build_project_info(config)
    project_rules = load_project_rules(config)
    rules_change_summary = build_project_rules_change_summary(config)
    target_words = int(config.get("project", {}).get("episode_duration", 2) * 500)
    ep_skeleton = extract_episode_from_skeleton(skeleton, ep_num)
    prev_script = _get_previous_episode_context(output_dir, batch_id, ep_num)
    novel_text_sample = _get_novel_text_sample(config, ep_num)

    return {
        "project_info": project_info,
        "novel_name": config.get("novel_name", ""),
        "ep_num": ep_num,
        "target_words": target_words,
        "requirements": requirements,
        "skeleton": skeleton,
        "ep_skeleton": ep_skeleton,
        "adaptation": adaptation,
        "events_text": events_text,
        "prev_script": prev_script,
        "novel_text_sample": novel_text_sample,
        "project_rules": project_rules,
        "rules_change_summary": rules_change_summary,
        "continuity_state": continuity_state,
        "batch_continuity_state": batch_continuity_state,
    }


def print_episode_context(ctx: dict):
    """Print episode context to stdout in a readable format."""
    ep_num = ctx["ep_num"]
    print(f"\n{'─'*60}")
    print(f"## EPISODE {ep_num} CONTEXT")
    print(f"{'─'*60}")
    print(f"\n### Project Info\n{ctx['project_info']}")
    print(f"\n### Target: ~{ctx['target_words']} characters")
    if ctx.get('rules_change_summary'):
        print(f"\n### Rules Change Summary\n{ctx['rules_change_summary']}")
    if ctx.get('project_rules'):
        print(f"\n### Project Rules\n{ctx['project_rules'][:3000]}")
    print(f"\n### Fangcun Local Context Mapping\n{_build_local_tool_context_mapping()}")
    if ctx.get('requirements'):
        print(f"\n### S0 Requirements / Project Brief\n{ctx['requirements'][:3000]}")
    print(f"\n### Episode Skeleton\n{ctx['ep_skeleton']}")
    print(f"\n### Adaptation Strategy\n{ctx['adaptation'][:3000]}")
    print(f"\n### Events\n{ctx['events_text'][:2000]}")
    if ctx["prev_script"]:
        print(f"\n### Previous Episode Script\n{ctx['prev_script'][:2000]}")
    if ctx["novel_text_sample"]:
        print(f"\n### Source Novel Excerpts\n{ctx['novel_text_sample'][:2000]}")
    print(f"\n### Confirmed Continuity State\n{json.dumps(ctx['continuity_state'], ensure_ascii=False, indent=2)}")
    if ctx.get("batch_continuity_state"):
        print(f"\n### Batch Continuity State\n{json.dumps(ctx['batch_continuity_state'], ensure_ascii=False, indent=2)}")


# ─── Agent-Mode Phase Implementations ────────────────────────────────────────

def phase_script_agent(config: dict, start: int, end: int, state: StateManager,
                       batch_size: int = None) -> bool:
    """Agent mode: create batch, prepare context for all episodes, print to stdout.

    Does NOT call any external API. The platform's LLM agent writes the scripts
    directly based on the printed context (works across Claude Code / Codex /
    Cursor / OpenCode / Gemini CLI / OpenClaw).
    """
    output_dir = config["output_dir"]

    # Same gate checks as API mode
    current_batch = state.get_pending_script_batch() if state else None
    if state and state.has_pending_script_confirmation():
        pending = state.get_pending_script_batch()
        print("[WAIT] A draft batch is waiting for writer confirmation; cannot generate a new batch.")
        print(f"batch: {pending['batch_id']}")
        print(f"summary: {pending.get('batch_summary_path', '')}")
        print("confirm: python tools/pipeline.py --config {config} --promote-draft-batch")
        return False

    # File-level pending lock: check ALL existing batches
    drafts_dir = Path(output_dir) / "drafts"
    if drafts_dir.exists():
        for batch_dir in sorted(drafts_dir.iterdir()):
            if batch_dir.is_dir():
                bid = batch_dir.name
                if is_batch_pending_confirmation(output_dir, bid):
                    print(f"\n{'='*60}")
                    print(f"\u26d4 \u6279\u6b21\u786c\u95e8\u63a7\uff1a{bid} \u5c1a\u672a\u786e\u8ba4")
                    print(f"{'='*60}")
                    print(f"  \u4e0a\u4e00\u6279\u8349\u7a3f\u5fc5\u987b\u7ecf\u4eba\u5de5\u786e\u8ba4\u540e\u624d\u80fd\u7ee7\u7eed\u751f\u6210\u4e0b\u4e00\u6279\u3002")
                    print(f"  \u786e\u8ba4\u547d\u4ee4: python tools/pipeline.py --config {{config}} --promote-draft-batch")
                    print(f"{'='*60}")
                    return False

    # Load assets
    skeleton = get_skeleton(output_dir)
    adaptation = get_adaptation(output_dir)
    events_text = get_events(output_dir)
    if not skeleton:
        print("[FAIL] story_skeleton.md is missing; run --phase skeleton first")
        return False
    if not adaptation:
        print("[FAIL] adaptation_strategy.md is missing; run --phase adaptation first")
        return False

    batch_size = int(batch_size or config.get("script_batch_size", 5))

    if current_batch:
        batch_id = current_batch["batch_id"]
        episodes = [int(ep) for ep in current_batch.get("episodes", [])]
    else:
        batch_end = min(end, start + batch_size - 1)
        episodes = list(range(start, batch_end + 1))
        confirmed_batches = []
        if state:
            confirmed_batches = state.state.setdefault("script_batches", {"current": None, "confirmed": []}).setdefault("confirmed", [])
        batch_id = format_batch_id(len(confirmed_batches) + 1)

    if state and not current_batch:
        state.start_script_batch(batch_id, episodes)

    print(f"\n{'='*60}")
    print(f"Agent Mode: Script Context | EP{episodes[0]}-{episodes[-1]} | Batch {batch_id}")
    print(f"{'='*60}")
    print()
    print("## Agent Workflow")
    print(f"  Batch ID: {batch_id}")
    print(f"  Episodes: {episodes}")
    print()
    print("  For each episode, the agent should:")
    print(f"    1. Read prompts/script_local.md for the script-writing prompt template（本地模式标准版；script.md 为旧版 Toonflow 兼容）")
    print(f"    2. (Optional) Get context: --get-context --episode N")
    print(f"    3. Write the complete script based on the context below")
    print(f"    4. Save draft: --save-draft --episode N --file <path>")
    print(f"       （保存时会自动触发系统结构化审核：审核报告 + 问题清单会打印出来）")
    print(f"    5. Read the printed system review result; if blocked, run --rewrite-draft --episode N（系统定向重写）")
    print(f"    6. Confirm and mark: --mark-pass --episode N")
    print(f"       （--mark-pass 会校验审核报告并自动更新连续性状态；严重问题未修复时会被系统拒绝）")
    print(f"       Or if truly blocked: --mark-blocked --episode N --reason \"...\"")
    print()
    print(f"  After all episodes in batch are done:")
    print(f"    Promote batch internally: --promote-draft-batch")
    print()

    # Output per-episode context
    for ep_num in episodes:
        ctx = build_episode_context(config, state, ep_num)
        ep_skeleton = ctx["ep_skeleton"]
        prev_script = ctx["prev_script"]
        novel_sample = ctx["novel_text_sample"]
        continuity = ctx["continuity_state"]
        batch_cont = ctx.get("batch_continuity_state", {})

        print(f"\n{'─'*60}")
        print(f"## EPISODE {ep_num} CONTEXT")
        print(f"{'─'*60}")
        print(f"\n### Project Info\n{ctx['project_info']}")
        print(f"\n### Target: ~{ctx['target_words']} characters")
        print(f"\n### Fidelity Policy\n{build_fidelity_policy(config)}")
        print(f"\n### Fangcun Local Context Mapping\n{_build_local_tool_context_mapping()}")
        if ctx.get('requirements'):
            print(f"\n### S0 Requirements / Project Brief\n{ctx['requirements'][:3000]}")
        if ctx.get('project_rules'):
            print(f"\n### Project Rules\n{ctx['project_rules'][:3000]}")
        print(f"\n### Episode Skeleton\n{ep_skeleton}")
        print(f"\n### Adaptation Strategy\n{adaptation[:3000]}")
        print(f"\n### Events\n{events_text[:2000]}")
        if prev_script:
            print(f"\n### Previous Episode Script\n{prev_script[:2000]}")
        if novel_sample:
            print(f"\n### Source Novel Excerpts\n{novel_sample[:2000]}")
        print(f"\n### Confirmed Continuity State\n{json.dumps(continuity, ensure_ascii=False, indent=2)}")
        if batch_cont:
            print(f"\n### Batch Continuity State\n{json.dumps(batch_cont, ensure_ascii=False, indent=2)}")

    state.mark_batch_waiting_confirmation("")
    state.save()

    print(f"\n{'='*60}")
    print(f"Context ready | Batch {batch_id} | {len(episodes)} episodes")
    print(f"Next: write scripts, save via --save-draft, validate, mark, then --promote-draft-batch")
    print(f"{'='*60}")
    return True


def review_draft_agent(config: dict, state: StateManager, ep_num: int) -> bool:
    """Agent mode: system review first (if API available), else local validation + agent judgement."""
    pending = _get_active_draft_batch(state)
    if not pending:
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    draft_content = load_draft(output_dir, batch_id, ep_num)
    if not draft_content:
        print(f"[FAIL] draft not found: {get_draft_path(output_dir, batch_id, ep_num)}")
        return False

    # 优先系统结构化审核（Agent 模式修复：审核权回到系统）
    api_key, _, _ = get_phase_api(config, "review")
    if api_key:
        report = _run_system_review(config, state, batch_id, ep_num, draft_content)
        if report is not None:
            _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 剧本系统审核")
            if is_review_blocked(report):
                print("建议：运行 --rewrite-draft --episode {}（系统定向重写），或手动修改后重新 --review-draft。".format(ep_num))
            else:
                print("系统审核通过。确认无误后 --mark-pass --episode {}；--mark-pass 会自动更新连续性状态。".format(ep_num))
            return True

    target_words = int(config.get("project", {}).get("episode_duration", 2) * 500)
    issues = validate_script(draft_content, target_words)

    print(f"\n{'='*60}")
    print(f"Agent Mode: Draft Review | EP{ep_num} | Batch {batch_id}")
    print(f"{'='*60}")
    print(f"Draft path: {get_draft_path(output_dir, batch_id, ep_num).resolve()}")
    print(f"Characters: {len(draft_content)} (target: ~{target_words})")
    print(f"\u25b3 markers: {draft_content.count('\u25b3')}")
    print()

    if issues:
        print("## Validation Issues")
        for issue in issues:
            print(f"  - {issue}")
        print()
        print("## Agent Actions")
        print(f"  1. Review the issues above and the draft content below")
        print(f"  2. If acceptable: --mark-pass --episode {ep_num}")
        print(f"  3. If blocked: --mark-blocked --episode {ep_num} --reason \"...\"")
    else:
        print("## Validation: PASS (no local issues found)")
        print()
        print("## Agent Actions")
        print(f"  Still review content for quality, then: --mark-pass --episode {ep_num}")

    print()
    print("## Draft Content")
    print("-" * 40)
    print(draft_content)
    print("-" * 40)
    return True


def rewrite_draft_agent(config: dict, state: StateManager, ep_num: int) -> bool:
    """Agent mode: system targeted rewrite (if API available), else agent rewrites itself."""
    pending = _get_active_draft_batch(state)
    if not pending:
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    draft_path = get_draft_path(output_dir, batch_id, ep_num)
    draft_content = load_draft(output_dir, batch_id, ep_num)

    print(f"\n{'='*60}")
    print(f"Agent Mode: Rewrite | EP{ep_num} | Batch {batch_id}")
    print(f"{'='*60}")
    print()

    api_key, _, _ = get_phase_api(config, "review")
    if api_key and draft_content:
        # 系统定向重写 + 自动复审（Agent 模式修复：重写权收归系统，防"改不收敛"）
        report_path = get_batch_dir(output_dir, batch_id) / "reviews" / f"ep_{ep_num:03d}_review.json"
        report = load_review_report(output_dir, batch_id, ep_num) if report_path.exists() else None
        if report is None:
            print("[AUTO] 未找到审核报告，先运行系统审核…")
            report = _run_system_review(config, state, batch_id, ep_num, draft_content)
        if report is not None:
            print("系统定向重写中（保留有效内容，只修严重问题）…")
            report2 = _run_system_rewrite(config, state, batch_id, ep_num, draft_content, report)
            if report2 is not None:
                _print_draft_review_for_user(report2, batch_id, ep_num, f"EP{ep_num} 重写后复审")
                if is_review_blocked(report2):
                    print("[BLOCKED] 重写后仍有严重问题。请人工介入：修改草稿、调整方向后重新 --rewrite-draft，或 --mark-blocked 说明原因。")
                else:
                    print(f"重写完成并通过系统复审。草稿已更新：{draft_path.resolve()}")
                    print("确认后 --mark-pass --episode {}（自动更新连续性状态）。".format(ep_num))
                return True

    print("未配置 API，请 agent 自行重写：")
    print("## Agent Actions")
    print(f"  1. Read current draft: {draft_path.resolve()}")
    print(f"  2. Read review report: {get_batch_dir(output_dir, batch_id) / 'reviews' / f'ep_{ep_num:03d}_review.md'}")
    print(f"  3. Rewrite the script addressing review issues")
    print(f"  4. Save new draft: --save-draft --episode {ep_num} --file <path>")
    print(f"  5. Re-validate: --validate-draft --episode {ep_num}")
    print(f"  6. Re-review: --review-draft --episode {ep_num}")
    return True


# ─── Agent-Mode Toolbox Commands (mode-agnostic file management) ─────────────

def handle_get_context(config: dict, state: StateManager, ep_num: int) -> bool:
    """Output generation context for a single episode to stdout."""
    output_dir = config["output_dir"]
    skeleton = get_skeleton(output_dir)
    adaptation = get_adaptation(output_dir)
    if not skeleton:
        print("[FAIL] story_skeleton.md is missing; run --phase skeleton first")
        return False
    if not adaptation:
        print("[FAIL] adaptation_strategy.md is missing; run --phase adaptation first")
        return False
    ctx = build_episode_context(config, state, ep_num)
    print_episode_context(ctx)
    return True


def _get_script_target_words(config: dict) -> int:
    return int(config.get("project", {}).get("episode_duration", 2) * 500)


def _validate_script_before_gate(config: dict, content: str, *, label: str) -> list[str]:
    """Run local script validation and print blocking severe issues for hard gates."""
    issues = validate_script(content, _get_script_target_words(config))
    severe = [issue for issue in issues if issue.startswith("严重")]
    if severe:
        print(f"[BLOCK] {label} failed local script format validation:")
        for issue in severe:
            print(f"  - {issue}")
    return severe


def handle_save_draft(config: dict, state: StateManager, ep_num: int, file_path: str) -> bool:
    """Save agent-written script file as a draft in the current batch."""
    pending = state.get_pending_script_batch()
    if not pending:
        print("[FAIL] no active draft batch; run --phase script first")
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    src_path = Path(file_path)
    if not src_path.exists():
        print(f"[FAIL] file not found: {file_path}")
        return False

    content = src_path.read_text(encoding="utf-8")
    severe = _validate_script_before_gate(config, content, label=f"EP{ep_num} save-draft")
    if severe:
        print("  Fix the draft before --save-draft; bad script format must not enter the draft batch.")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    draft_path = save_draft(output_dir, batch_id, ep_num, content)

    # Clear .pass if exists (draft changed, needs re-review)
    clear_episode_passed(output_dir, batch_id, ep_num)

    delta_count = content.count("\u25b3")
    print(f"[SAVED] EP{ep_num} draft -> {draft_path.resolve()}")
    print(f"  Characters: {len(content)} | \u25b3 markers: {delta_count}")

    # Agent 模式系统把关：保存即自动结构化审核（不再依赖 agent 自觉）
    report = _run_system_review(config, state, batch_id, ep_num, content)
    if report is None:
        print("[INFO] 系统审核未运行（未配置 API）。请至少运行 --review-draft 人工审核后再 --mark-pass。")
    else:
        _print_draft_review_for_user(report, batch_id, ep_num, f"EP{ep_num} 系统审核")
        if is_review_blocked(report):
            print("[BLOCKED] EP{} 系统审核未通过。请运行 --rewrite-draft --episode {}（系统定向重写），或修改后重新 --save-draft / --review-draft。".format(ep_num, ep_num))
        else:
            print("[PASS] EP{} 系统审核通过。确认后 --mark-pass --episode {}（通过后系统自动更新连续性状态）。".format(ep_num, ep_num))
    return True


def handle_mark_pass(config: dict, state: StateManager, ep_num: int) -> bool:
    """Mark an episode as passed; system-enforced: review report required, continuity auto-updated."""
    pending = state.get_pending_script_batch()
    if not pending:
        print("[FAIL] no active draft batch")
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]

    # Check draft exists
    draft_content = load_draft(output_dir, batch_id, ep_num)
    if not draft_content:
        print(f"[FAIL] draft not found: {get_draft_path(output_dir, batch_id, ep_num)}")
        print("  Use --save-draft first to save the script, then --mark-pass")
        return False

    severe = _validate_script_before_gate(config, draft_content, label=f"EP{ep_num} mark-pass")
    if severe:
        print("  Fix the draft or use --mark-blocked with an explanation.")
        return False

    rule_issues = validate_project_rules_applied(config, draft_content)
    if rule_issues:
        print("[BLOCK] project rules validation failed before mark-pass:")
        for issue in rule_issues:
            print(f"  - {issue}")
        print("  Fix the draft or use --mark-blocked with an explanation.")
        return False

    # Agent 模式修复：mark-pass 前必须有审核报告，且不得为 blocked
    report_path = get_batch_dir(output_dir, batch_id) / "reviews" / f"ep_{ep_num:03d}_review.json"
    report = load_review_report(output_dir, batch_id, ep_num) if report_path.exists() else None
    if report is None:
        api_key, _, _ = get_phase_api(config, "review")
        if api_key:
            print("[AUTO] 未找到审核报告，先自动运行系统审核…")
            report = _run_system_review(config, state, batch_id, ep_num, draft_content)
        else:
            print("[WARN] 未找到审核报告且未配置 API；将以 agent 裁决方式记录 pass（推荐配置 api_key 启用系统审核）。")
            report = {
                "verdict": "pass",
                "summary": "Agent override pass（未运行系统审核）",
                "severe_issues": [],
                "non_blocking_issues": ["未运行系统审核，建议人工复核台词与原著贴合度。"],
                "continuity_issues": [],
                "format_issues": [],
                "rewrite_instructions": [],
            }
            save_review_report(output_dir, batch_id, ep_num, report)
    if report is not None and is_review_blocked(report):
        print("[BLOCK] 审核报告为 blocked / 含严重问题，禁止 mark-pass。请先 --rewrite-draft 或修改后重新审核。")
        return False

    mark_episode_passed(output_dir, batch_id, ep_num)
    state.set_episode_review(ep_num, "pass", False, 0)
    state.save()
    print(f"[PASS] EP{ep_num} marked as passed in batch {batch_id}")

    # Agent 模式修复：通过后自动更新连续性状态（不再依赖 agent 自觉）
    api_key, api_url, model = get_phase_api(config, "review")
    if api_key:
        try:
            batch_state = load_continuity_state(output_dir, batch_id)
            updated = update_continuity_state(config, api_key, api_url, model, ep_num, draft_content, batch_state)
            save_continuity_state(output_dir, updated, batch_id)
            print(f"[CONTINUITY] EP{ep_num} 连续性状态已自动更新（人物状态/钩子/伏笔）")
        except Exception as exc:
            print(f"[WARN] 连续性状态更新失败：{exc}")
    else:
        print("[WARN] 未配置 API，连续性状态未自动更新（后续集可能缺少人物状态/钩子上下文）")
    return True


def handle_mark_blocked(config: dict, state: StateManager, ep_num: int, reason: str) -> bool:
    """Manually mark an episode as review-blocked and save review report."""
    pending = state.get_pending_script_batch()
    if not pending:
        print("[FAIL] no active draft batch")
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]

    report = {
        "verdict": "blocked",
        "summary": reason,
        "severe_issues": [reason] if reason else ["Manually marked as blocked"],
        "non_blocking_issues": [],
        "continuity_issues": [],
        "format_issues": [],
        "rewrite_instructions": [f"Address: {reason}" if reason else "Agent should rewrite"],
    }
    _, md_path = save_review_report(output_dir, batch_id, ep_num, report)
    state.set_episode_review(ep_num, "blocked", True, 1)
    state.save()
    print(f"[BLOCKED] EP{ep_num} marked as blocked in batch {batch_id}")
    print(f"  Reason: {reason or '(unspecified)'}")
    print(f"  Review: {md_path.resolve()}")
    return True


def handle_validate_draft(config: dict, state: StateManager, ep_num: int) -> bool:
    """Run local validation only on a draft and print results."""
    pending = state.get_pending_script_batch()
    if not pending:
        print("[FAIL] no active draft batch")
        return False
    if not _episode_in_batch(pending, ep_num):
        print(f"[FAIL] EP{ep_num} is not in current draft batch {pending['batch_id']}")
        return False

    output_dir = config["output_dir"]
    batch_id = pending["batch_id"]
    draft_content = load_draft(output_dir, batch_id, ep_num)
    if not draft_content:
        print(f"[FAIL] draft not found: {get_draft_path(output_dir, batch_id, ep_num)}")
        return False

    target_words = int(config.get("project", {}).get("episode_duration", 2) * 500)
    issues = validate_script(draft_content, target_words)
    issues.extend(validate_project_rules_applied(config, draft_content))

    print(f"\n{'='*60}")
    print(f"Draft Validation | EP{ep_num} | Batch {batch_id}")
    print(f"{'='*60}")
    print(f"Characters: {len(draft_content)} (target: ~{target_words})")
    print(f"\u25b3 markers: {draft_content.count('\u25b3')}")
    if issues:
        print(f"Issues: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("Validation: PASS (no local issues)")
    return True


def handle_extract_project_rules_from_text(config: dict, text_file: str, source: str = "chat_export") -> bool:
    path = Path(text_file)
    if not path.exists():
        print(f"[FAIL] text file not found: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    candidates = extract_rule_candidates_from_chat_text(text)
    save_path = save_project_rule_candidates(config, candidates, source=source)
    print(f"[OK] extracted {len(candidates)} candidate rules -> {save_path.resolve()}")
    for i, item in enumerate(candidates, 1):
        print(f"{i}. [{item.get('kind')}/{item.get('confidence')}] {item.get('rule')}")
        print(f"   evidence: {item.get('evidence')}")
    return True


def handle_confirm_rule_candidates(config: dict, selection: str, rule_source: str, rule_stage: str) -> bool:
    payload = load_project_rule_candidates(config)
    candidates = list(payload.get("candidates", []))
    if not candidates:
        print("[FAIL] no candidate rules found; run --extract-project-rules-from-text first")
        return False
    selection = (selection or "").strip().lower()
    picked = []
    if selection == "all":
        picked = candidates
    elif selection in {"hard", "only-hard", "硬规则", "只采纳硬规则"}:
        picked = [c for c in candidates if c.get("kind") == "hard"]
    else:
        try:
            idxs = [int(x.strip()) for x in selection.split(",") if x.strip()]
        except Exception:
            print("[FAIL] --confirm-rule-candidates expects 'all', 'hard', or comma-separated indexes like 1,2,4")
            return False
        for idx in idxs:
            if 1 <= idx <= len(candidates):
                picked.append(candidates[idx - 1])
    if not picked:
        print("[FAIL] no candidates selected")
        return False
    for item in picked:
        save_project_rule(config, item.get("rule", ""), source=rule_source or item.get("kind", "chat_extract"), stage=rule_stage)
    print(f"[OK] confirmed {len(picked)} candidate rules into project rules")
    print(build_project_rules_change_summary(config))
    return True


def main():
    parser = argparse.ArgumentParser(description="剧本引擎 — 小说转短剧剧本")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--mode", default="agent", choices=["agent", "api"],
                        help="agent=LLM agent 直接写剧本（默认，跨平台通用）, api=调外部 LLM API")
    parser.add_argument("--phase", default="all",
                        choices=["all", "resume", "event", "requirements", "s0", "story_outline", "skeleton", "adaptation", "adaptation_strategy", "script", "review", "export", "translate", "status"],
                        help="执行阶段（requirements/s0=S0用户需求文档，adaptation=S2改编策略，resume=断点续传，status=查看进度）")
    parser.add_argument("--start", type=int, default=1, help="剧本起始集")
    parser.add_argument("--end", type=int, default=3, help="剧本结束集")
    parser.add_argument("--workers", type=int, default=5, help="事件提取并行数")
    parser.add_argument("--review-target", default="all", choices=["requirements", "story_outline", "skeleton", "adaptation", "all"],
                        help="审核目标")
    parser.add_argument("--dry-run", action="store_true", help="只分析不执行")
    parser.add_argument("--skip-review-gate", action="store_true", help="跳过审核门控（不推荐）")
    parser.add_argument("--confirm-draft-batch", action="store_true", help="legacy alias: internally promote current draft batch to scripts/; NOT user confirmation")
    parser.add_argument("--promote-draft-batch", action="store_true", help="internally promote current reviewed draft batch to scripts/; NOT user confirmation")
    parser.add_argument("--confirm-user-batch", action="store_true", help="mark latest promoted script batch as explicitly confirmed by user; does NOT finish project")
    parser.add_argument("--confirm-project-finished", action="store_true", help="mark project finished only after explicit finish phrases: 剧本完结/剧本结束/项目结束")
    parser.add_argument("--finish-text", default="", help="original user text for --confirm-project-finished")
    parser.add_argument("--user-message-id", default="", help="message_id for user confirmation audit")
    parser.add_argument("--confirm-review", action="store_true", help="confirm current AI review after human approval")
    parser.add_argument("--review-decision", default="approved", help="human review decision when using --confirm-review")
    parser.add_argument("--review-notes", default="", help="human review notes when using --confirm-review")
    parser.add_argument("--review-draft", action="store_true", help="review one draft episode")
    parser.add_argument("--rewrite-draft", action="store_true", help="rewrite one draft episode")
    parser.add_argument("--episode", type=int, help="episode number for draft operations")
    parser.add_argument("--batch-size", type=int, help="draft batch size for this script run")
    parser.add_argument("--skip-draft-review", action="store_true", help="Skip per-episode AI review during draft generation (batch mode)")
    # Agent-mode / toolbox commands
    parser.add_argument("--get-context", action="store_true", help="output generation context for one episode to stdout")
    parser.add_argument("--save-draft", action="store_true", help="save agent-written script file as a draft")
    parser.add_argument("--file", help="file path for --save-draft")
    parser.add_argument("--mark-pass", action="store_true", help="manually mark episode as review-passed")
    parser.add_argument("--mark-blocked", action="store_true", help="manually mark episode as review-blocked")
    parser.add_argument("--reason", default="", help="reason for --mark-blocked")
    parser.add_argument("--validate-draft", action="store_true", help="run local validation only (chars, △ markers) on a draft")
    parser.add_argument("--add-project-rule", help="append one project rule for the current project")
    parser.add_argument("--rule-source", default="user", help="source label for --add-project-rule")
    parser.add_argument("--rule-stage", default="global", help="stage label for --add-project-rule")
    parser.add_argument("--show-project-rules", action="store_true", help="print current project rules and version summary")
    parser.add_argument("--extract-project-rules-from-text", help="extract candidate project rules from a chat/export text file")
    parser.add_argument("--confirm-rule-candidates", help="confirm candidate rule indexes (e.g. 1,2,4) or 'all'")
    parser.add_argument("--target-language", default="English", help="target language for --phase translate")
    parser.add_argument("--translation-style", default="default", help="style profile for --phase translate")
    parser.add_argument("--translation-locale", default="", help="locale/audience for --phase translate")
    parser.add_argument("--translated-jsonl", default="", help="translated JSONL for rendering in --phase translate")
    parser.add_argument("--translation-mode", default="bilingual", choices=["bilingual", "replace"], help="render mode for --phase translate")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    output_dir = config["output_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 加载状态
    state = StateManager(output_dir)
    state.load()

    print(f"\n{'#'*50}")
    print(f"剧本引擎 | {config.get('novel_name', '')} → {config.get('drama_name', '')}")
    print(f"阶段: {args.phase} | 模式: {args.mode}")
    print(f"{'#'*50}")

    # ─── Toolbox commands (mode-agnostic file management, handled first) ────

    if args.get_context:
        if args.episode is None:
            print("[FAIL] --episode N is required for --get-context")
            sys.exit(1)
        ok = handle_get_context(config, state, args.episode)
        if not ok:
            sys.exit(1)
        return

    if args.save_draft:
        if args.episode is None or not args.file:
            print("[FAIL] --episode N and --file <path> are required for --save-draft")
            sys.exit(1)
        ok = handle_save_draft(config, state, args.episode, args.file)
        if not ok:
            sys.exit(1)
        return

    if args.mark_pass:
        if args.episode is None:
            print("[FAIL] --episode N is required for --mark-pass")
            sys.exit(1)
        ok = handle_mark_pass(config, state, args.episode)
        if not ok:
            sys.exit(1)
        return

    if args.mark_blocked:
        if args.episode is None:
            print("[FAIL] --episode N is required for --mark-blocked")
            sys.exit(1)
        ok = handle_mark_blocked(config, state, args.episode, args.reason)
        if not ok:
            sys.exit(1)
        return

    if args.validate_draft:
        if args.episode is None:
            print("[FAIL] --episode N is required for --validate-draft")
            sys.exit(1)
        ok = handle_validate_draft(config, state, args.episode)
        if not ok:
            sys.exit(1)
        return

    if args.add_project_rule:
        path = save_project_rule(config, args.add_project_rule, args.rule_source, args.rule_stage)
        print(f"[OK] project rule saved -> {path.resolve()}")
        print(build_project_rules_change_summary(config))
        return

    if args.show_project_rules:
        print(build_project_rules_change_summary(config) or "【项目规则变更提醒】当前尚无版本化规则")
        print()
        print(load_project_rules(config) or "(no project rules)")
        print(f"path: {get_project_rules_path(config).resolve()}")
        payload = load_project_rule_candidates(config)
        if payload.get("candidates"):
            print()
            print("【候选规则】")
            for i, item in enumerate(payload.get("candidates", []), 1):
                print(f"{i}. [{item.get('kind')}/{item.get('confidence')}] {item.get('rule')}")
        return

    if args.extract_project_rules_from_text:
        ok = handle_extract_project_rules_from_text(config, args.extract_project_rules_from_text, source="chat_export")
        if not ok:
            sys.exit(1)
        return

    if args.confirm_rule_candidates:
        ok = handle_confirm_rule_candidates(config, args.confirm_rule_candidates, args.rule_source, args.rule_stage)
        if not ok:
            sys.exit(1)
        return

    # ─── Confirmation commands ──────────────────────────────────────────────

    # --status: 查看进度
    if args.confirm_draft_batch or args.promote_draft_batch:
        phase_confirm_draft_batch(config, state)
        return

    if args.confirm_user_batch:
        ok = phase_confirm_user_batch(config, state, message_id=args.user_message_id, notes=args.review_notes)
        if not ok:
            sys.exit(1)
        return

    if args.confirm_project_finished:
        ok = phase_confirm_project_finished(config, state, message_id=args.user_message_id, finish_text=args.finish_text, notes=args.review_notes)
        if not ok:
            sys.exit(1)
        return

    if args.confirm_review:
        ok = phase_confirm_review(config, state, args.review_target, args.review_decision, args.review_notes)
        if not ok:
            sys.exit(1)
        return

    # ─── Draft review/rewrite ─────────────────────────────────────────────

    if args.review_draft or args.rewrite_draft:
        if args.episode is None:
            print("[FAIL] --episode N is required for draft review/rewrite")
            sys.exit(1)
        if args.review_draft and args.rewrite_draft:
            print("[FAIL] choose only one: --review-draft or --rewrite-draft")
            sys.exit(1)

        if args.mode == "agent":
            if args.review_draft:
                ok = review_draft_agent(config, state, args.episode)
            else:
                ok = rewrite_draft_agent(config, state, args.episode)
        else:
            ok = phase_review_draft(config, state, args.episode) if args.review_draft else phase_rewrite_draft(config, state, args.episode)
        if not ok:
            sys.exit(1)
        return

    if args.phase == "status":
        state.print_status()
        return

    if not ensure_project_intake(config):
        sys.exit(1)

    # --resume: 断点续传
    if args.phase == "resume":
        resume_phase = state.get_resume_phase()
        if resume_phase is None:
            print("全部完成，无需续传")
            state.print_status()
            return
        if resume_phase == "human_review_confirmation":
            pending = state.get_pending_human_review()
            print("断点续传: 等待人工审核确认")
            print(f"target: {pending.get('target')}")
            print(f"report: {Path(pending.get('report_path', '')).resolve()}")
            print(f"confirm: python tools/pipeline.py --config {{config}} --confirm-review --review-target {pending.get('target')}")
            return
        print(f"断点续传: 从 {resume_phase} 阶段继续")
        args.phase = resume_phase
        # resume 时 script 默认续写到 config 中的集数
        if resume_phase == "script":
            project = config.get("project", {})
            args.end = project.get("episodes", args.end)

    # Preflight API check (skip for agent-mode script phase which doesn't use API)
    if not (args.mode == "agent" and args.phase == "script"):
        if not _preflight_api_check(config, args.phase, args.dry_run):
            sys.exit(1)

    # 执行
    if args.phase == "all":
        _run_all(config, state, args)
    elif args.phase == "event":
        _run_phase(state, "event", lambda: phase_event(config, args.workers), config=config)
    elif args.phase in ("requirements", "s0"):
        _run_phase(state, "requirements", lambda: phase_requirements(config, args.dry_run), config=config)
    elif args.phase in ("adaptation", "adaptation_strategy"):
        if not args.skip_review_gate:
            if not _require_review_report_exists(config, "skeleton"):
                sys.exit(1)
            if not ensure_human_review_confirmed(state, "adaptation"):
                sys.exit(1)
        _run_phase(state, "adaptation", lambda: phase_adaptation(config, args.dry_run), config=config)
    elif args.phase == "story_outline":
        if not args.skip_review_gate:
            if not _require_review_report_exists(config, "adaptation"):
                sys.exit(1)
            if not ensure_human_review_confirmed(state, "story_outline"):
                sys.exit(1)
        _run_phase(state, "story_outline", lambda: phase_story_outline(config, args.dry_run), config=config)
    elif args.phase == "skeleton":
        if not args.skip_review_gate:
            if not _require_review_report_exists(config, "requirements"):
                sys.exit(1)
            if not ensure_human_review_confirmed(state, "skeleton"):
                sys.exit(1)
        _run_phase(state, "skeleton", lambda: phase_skeleton(config, args.dry_run), config=config)
    elif args.phase == "script":
        if not args.skip_review_gate:
            if not _require_review_report_exists(config, "adaptation"):
                sys.exit(1)
            if not ensure_human_review_confirmed(state, "script"):
                sys.exit(1)
        if args.mode == "agent":
            _run_phase(state, "script", lambda: phase_script_agent(config, args.start, args.end, state, args.batch_size), config=config)
        else:
            _run_phase(state, "script", lambda: phase_script(config, args.start, args.end, args.dry_run, state, args.batch_size, getattr(args, 'skip_draft_review', False)), config=config)
    elif args.phase == "review":
        review_phase_name = f"{args.review_target}_review" if args.review_target != "all" else "review"
        _run_phase(state, review_phase_name, lambda: phase_review(config, args.review_target, state), config=config)
    elif args.phase == "export":
        _run_phase(state, "export", lambda: phase_export(config), config=config)
    elif args.phase == "translate":
        translate_phase_name = "translate_render" if args.translated_jsonl else "translate_prepare"
        _run_phase(state, translate_phase_name, lambda: phase_translate(
            config,
            args.target_language,
            args.translation_style,
            args.translation_locale,
            args.translated_jsonl,
            args.translation_mode,
        ), config=config)


def _run_phase(state, phase_name, fn, config: dict = None):
    """包装单个 phase 的执行：自动记录 start/done/failed。"""
    if state.is_phase_done(phase_name):
        print(f"  {phase_name} 已完成，跳过（用 --phase {phase_name} 强制重跑）")
        return True
    state.phase_start(phase_name)
    try:
        result = fn()
        if result:
            state.phase_done(phase_name)
        else:
            state.phase_failed(phase_name, "返回失败")
        return result
    except Exception as e:
        state.phase_failed(phase_name, str(e))
        raise


def _print_draft_review_for_user(report: dict, batch_id: str, ep_num: int, label: str = ""):
    """Print draft review report so the user can see it in-channel."""
    if not report:
        return
    verdict = report.get("verdict", "?")
    severe = report.get("severe_issues", [])
    non_blocking = report.get("non_blocking_issues", [])
    summary = report.get("summary", "")
    rewrite = report.get("rewrite_instructions", [])
    print(f"\n{'='*60}")
    print(f"📄 剧本审核报告 {label} | Batch {batch_id} | EP{ep_num} | 判定: {verdict}")
    print(f"{'='*60}")
    if severe:
        print(f"\n🔴 严重问题 ({len(severe)}):")
        for i, issue in enumerate(severe, 1):
            print(f"  {i}. {issue}")
    if non_blocking:
        print(f"\n🟡 建议改进 ({len(non_blocking)}):")
        for i, issue in enumerate(non_blocking, 1):
            print(f"  {i}. {issue}")
    if summary:
        print(f"\n📝 总评: {summary}")
    if rewrite:
        print(f"\n✏️ 修改建议:")
        for i, instr in enumerate(rewrite, 1):
            print(f"  {i}. {instr}")
    print(f"{'='*60}\n")


def _print_review_for_user(output_dir: str, target: str, review_text: str, target_name: str):
    """Print the full review report so that it reaches the user via OpenClaw stdout.

    When the pipeline is invoked through OpenClaw (e.g. feishu channel), stdout is
    relayed to the user.  This function prints the review content in a clearly
    delimited block so the user can read it without opening the file manually.
    """
    review_file = Path(output_dir) / "reviews" / f"{target}_review.md"
    print(f"\n{'='*60}")
    print(f"📄 审核报告: {target_name}")
    print(f"   文件: {review_file.resolve()}")
    print(f"{'='*60}")
    if review_text:
        # Print full content; OpenClaw exec output is emitted to the channel
        print(review_text)
    else:
        print("(审核报告为空)")
    print(f"{'='*60}\n")


def _run_all(config, state, args):
    """全流程执行：event → S0 requirements → S1 skeleton → S2 adaptation → S3 script → export。

    对齐 GitHub/toonflow 主干：S0 负责用户需求文档；S1 是结构事实源；S2 基于 S1 做改编策略；S3 基于 S1/S2 写剧本。
    """
    output_dir = config["output_dir"]
    skip_gate = getattr(args, "skip_review_gate", False)

    # Phase 1: 事件提取
    if not _run_phase(state, "event", lambda: phase_event(config, args.workers), config=config):
        print("\n⛔ 事件提取失败，流程终止。")
        return

    # Phase 2: S0 用户需求文档 → 审核 → 门控
    if not _run_phase(state, "requirements", lambda: phase_requirements(config, args.dry_run), config=config):
        print("\n⛔ S0 用户需求文档生成失败，流程终止。")
        return

    if not _run_phase(state, "requirements_review", lambda: phase_review(config, "requirements", state), config=config):
        print("\n⛔ S0 用户需求文档审核失败，流程终止。")
        return

    if not skip_gate:
        review_text = load_review(output_dir, "requirements")
        proceed, msg = gate_review(review_text, "S0 用户需求文档")
        print(msg)
        _print_review_for_user(output_dir, "requirements", review_text, "S0 用户需求文档")
        print("[WAIT] Human review confirmation is required before S1 skeleton.")
        print("confirm: python tools/pipeline.py --config {config} --confirm-review --review-target requirements")
        state.print_status()
        return

    # Phase 3: S1 故事骨架 → 审核 → 门控
    if not _run_phase(state, "skeleton", lambda: phase_skeleton(config, args.dry_run), config=config):
        print("\n⛔ S1 故事骨架生成失败，流程终止。")
        return

    if not _run_phase(state, "skeleton_review", lambda: phase_review(config, "skeleton", state), config=config):
        print("\n⛔ S1 故事骨架审核失败，流程终止。")
        return

    if not skip_gate:
        review_text = load_review(output_dir, "skeleton")
        proceed, msg = gate_review(review_text, "S1 故事骨架")
        print(msg)
        _print_review_for_user(output_dir, "skeleton", review_text, "S1 故事骨架")
        print("[WAIT] Human review confirmation is required before S2 adaptation strategy.")
        print("confirm: python tools/pipeline.py --config {config} --confirm-review --review-target skeleton")
        state.print_status()
        return

    # Phase 4: S2 改编策略 → 审核 → 门控
    if not _run_phase(state, "adaptation", lambda: phase_adaptation(config, args.dry_run), config=config):
        print("\n⛔ S2 改编策略生成失败，流程终止。")
        return

    if not _run_phase(state, "adaptation_review", lambda: phase_review(config, "adaptation", state), config=config):
        print("\n⛔ S2 改编策略审核失败，流程终止。")
        return

    if not skip_gate:
        review_text = load_review(output_dir, "adaptation")
        proceed, msg = gate_review(review_text, "S2 改编策略")
        print(msg)
        _print_review_for_user(output_dir, "adaptation", review_text, "S2 改编策略")
        print("[WAIT] Human review confirmation is required before S3 script writing.")
        print("confirm: python tools/pipeline.py --config {config} --confirm-review --review-target adaptation")
        state.print_status()
        return

    # Phase 5: S3 剧本编写
    project = config.get("project", {})
    episodes = project.get("episodes", 30)
    script_fn = phase_script_agent if getattr(args, "mode", "agent") == "agent" else phase_script
    if script_fn is phase_script_agent:
        ok = _run_phase(state, "script",
                        lambda: phase_script_agent(config, 1, episodes, state, getattr(args, "batch_size", None)), config=config)
    else:
        ok = _run_phase(state, "script",
                        lambda: phase_script(config, 1, episodes, args.dry_run, state, getattr(args, "batch_size", None)), config=config)
    if not ok:
        print("\n⛔ S3 剧本编写失败。")
        return

    # Phase 6: 导出
    _run_phase(state, "export", lambda: phase_export(config), config=config)
    state.print_status()
    print("\n✅ 全流程完成！")


if __name__ == "__main__":
    main()
