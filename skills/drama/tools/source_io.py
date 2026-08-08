"""
源书级 I/O — 共享产物读写（events / skeleton / adaptation / styles / 源文）。

两套引擎共用，路径基于 _cache/。
"""

import json
import re
from datetime import datetime
from pathlib import Path


# ─── 路径解析 ──────────────────────────────────────────────────────────────

def get_cache_dir(config) -> Path:
    """Resolve shared _cache directory.

    Convention: _cache 位于项目根 projects/<项目>/_cache，而不是 drama/_cache。
    优先级：
      1. 显式 source_dir / source_chapter_dir 指向 _cache；
      2. config.project_workspace（正式配置字段）；
      3. 从 output_dir 推断项目根（projects/<项目>/drama/output -> projects/<项目>）；
      4. 老项目兜底：drama/_cache 已存在且项目根 _cache 不存在时使用旧路径。
    """
    for key in ("source_dir", "source_chapter_dir"):
        if config.get(key):
            p = Path(config[key])
            if p.name == "chapters" and p.parent.name == "_cache":
                return p.parent
            if p.name == "_cache":
                return p
    if config.get("project_workspace"):
        return Path(config["project_workspace"]) / "_cache"
    if config.get("output_dir"):
        return resolve_cache_dir_from_output(Path(config["output_dir"]))
    base_dir = config.get("base_dir", ".")
    author = config.get("author", "")
    source_book = config.get("source_book", "")
    return Path(base_dir) / "projects" / author / source_book / "_cache"


def resolve_cache_dir_from_output(output_dir: Path) -> Path:
    """从 output_dir 解析项目根 _cache，带 drama/_cache 旧路径兜底。"""
    p = output_dir
    if "_cache" in p.parts:
        idx = p.parts.index("_cache")
        return Path(*p.parts[: idx + 1])
    if "drama" in p.parts:
        root = Path(*p.parts[: p.parts.index("drama")])
        canonical = root / "_cache"
        legacy = root / "drama" / "_cache"
        if canonical.exists() or not legacy.exists():
            return canonical
        return legacy
    parent = p.parent
    cache = parent / "_cache"
    if cache.exists():
        return cache
    return p


def get_cache_dir_from_path(source_dir: str) -> Path:
    """从源文章节目录推断 _cache/ 路径。"""
    p = Path(source_dir)
    if p.name == "chapters" and p.parent.name == "_cache":
        return p.parent
    return p / "_cache"


# ─── 项目 Rules（项目级隔离；编剧指令优先）───────────────────────────────

def get_project_rules_path(config) -> Path:
    """Return project-local rules file. Rules live under output_dir, not _cache.

    output_dir is project-specific, so rules for one project cannot leak into another
    adaptation project sharing the same source novel cache.
    """
    return Path(config["output_dir"]) / "project_rules.md"


def get_project_rules_json_path(config) -> Path:
    return Path(config["output_dir"]) / "project_rules.json"


def load_project_rules(config) -> str:
    """Load project-local playwright/producer rules plus optional config rules."""
    parts = []
    cfg_rules = (config.get("project") or {}).get("rules") or config.get("project_rules") or []
    if isinstance(cfg_rules, str):
        cfg_rules = [cfg_rules]
    cfg_rules = [str(r).strip() for r in cfg_rules if str(r).strip()]
    if cfg_rules:
        parts.append("## config rules\n" + "\n".join(f"- {r}" for r in cfg_rules))
    path = get_project_rules_path(config)
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def save_project_rule(config, rule: str, source: str = "user", stage: str = "global") -> Path:
    """Append one project rule and keep a JSON audit trail with versioning."""
    rule = (rule or "").strip()
    if not rule:
        raise ValueError("rule is empty")
    out = Path(config["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    path = get_project_rules_path(config)
    json_path = get_project_rules_json_path(config)

    data = {"rules_version": 0, "entries": []}
    if json_path.exists():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                data = {"rules_version": len(loaded), "entries": loaded}
            elif isinstance(loaded, dict):
                data = {"rules_version": int(loaded.get("rules_version", 0)), "entries": list(loaded.get("entries", []))}
        except Exception:
            data = {"rules_version": 0, "entries": []}

    next_version = int(data.get("rules_version", 0)) + 1
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"version": next_version, "timestamp": timestamp, "stage": stage, "source": source, "rule": rule}
    data["rules_version"] = next_version
    data.setdefault("entries", []).append(entry)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if not path.exists():
        path.write_text(
            "# Project Rules\n\n"
            "> 项目级规则，只对本 output_dir 项目生效；不会写入源书 _cache，也不会影响其他项目。\n\n"
            "## Precedence\n\n"
            "1. 平台红线/合规规则是硬约束，不能被覆盖。\n"
            "2. 编剧/业务负责人写入的项目 rules 优先于通用改编方法论。\n"
            "3. 通用爽点、反差、反转等只是可选技法；项目 rules 否定时必须关闭。\n\n"
            "## Rules\n\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- [v{next_version} | {timestamp}] ({stage}/{source}) {rule}\n")
    return path


def build_project_rules_change_summary(config) -> str:
    json_path = get_project_rules_json_path(config)
    if not json_path.exists():
        return ""
    try:
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if isinstance(loaded, list):
        entries = loaded
        version = len(entries)
    else:
        entries = list(loaded.get("entries", []))
        version = int(loaded.get("rules_version", len(entries)))
    if not entries:
        return ""
    recent = entries[-3:]
    lines = [f"【项目规则变更提醒｜v{version}】"]
    for item in recent:
        lines.append(f"- v{item.get('version', '?')}: {item.get('rule', '')}")
    lines.append("从当前版本起，后续改编指引、故事大纲、集纲、剧本、审核必须按上述规则执行；如与通用技法冲突，以项目规则为准。")
    return "\n".join(lines)


def build_project_rules_context(config) -> str:
    rules = load_project_rules(config)
    if not rules:
        return ""
    summary = build_project_rules_change_summary(config)
    return f"""
## 项目 Rules（本项目独立生效；编剧要求优先）

以下规则来自本项目的编剧/业务要求，存放在 output_dir/project_rules.md，只对当前项目生效，禁止影响其他项目。

优先级：
1. 平台红线/合规硬规则不可被覆盖。
2. 项目 Rules 优先于通用改编方法论、爽点模板、反差/反转技法。
3. 如果项目 Rules 否定某技法（如“不要反差”），后续改编指引、故事大纲、集纲、剧本均不得继续设计该技法。
4. 每次产出末尾必须写“项目规则落实清单”，逐条说明遵守/冲突/需人工确认。

{summary}

{rules}
""".strip()


def extract_negative_rule_terms(rules_text: str) -> list[str]:
    """Extract simple terms from negation rules for violation checking.

    Also emits de-prefixed sub-terms: '强反转堆叠' -> '反转'; '身份反差' -> '反差'.
    """
    terms: list[str] = []
    seen: set[str] = set()

    def _add(t: str):
        t = t.strip()
        if t and len(t) >= 2 and t not in seen:
            terms.append(t)
            seen.add(t)

    for line in (rules_text or "").splitlines():
        line = re.sub(r"^[-*]\s*", "", line).strip()
        m = re.search(r"(?:不要|禁止|避免|不准|不能|不需要)\s*([^，。；;、\n]{1,20})", line)
        if m:
            term = m.group(1).strip(" ：:，。；;,.!！?？）)")
            # Drop vague tails
            term = re.sub(r"(这个|这些|设计|桥段|元素|规则|手法|堆叠)$", "", term).strip()
            if term:
                _add(term)
                # Also add de-prefixed sub-term (e.g. "强反转"->"反转"; "身份反差"->"反差")
                sub = re.sub(r"^[强大小多少部分]", "", term).strip()
                if sub and sub != term:
                    _add(sub)
    return terms
def detect_current_project_from_chat_text(chat_text: str) -> str:
    """Best-effort detect current drama/project title from recent chat text.

    Heuristics only: prefer explicit markers like 《剧名》 / 项目《XXX》 / 剧本《XXX》.
    """
    text = chat_text or ""
    patterns = [
        r"《([^》]{2,40})》",
        r"项目[：:\s]*([A-Za-z0-9\u4e00-\u9fa5·《》_-]{2,40})",
        r"剧本[：:\s]*([A-Za-z0-9\u4e00-\u9fa5·《》_-]{2,40})",
        r"剧名[：:\s]*([A-Za-z0-9\u4e00-\u9fa5·《》_-]{2,40})",
    ]
    counts: dict[str, int] = {}
    for pat in patterns:
        for m in re.finditer(pat, text):
            name = m.group(1).strip().strip("《》")
            if 2 <= len(name) <= 40:
                counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))[0][0]


def _is_non_script_rule_discussion(line: str) -> bool:
    line = line or ""
    deny_terms = [
        "一个项目一个群", "项目群", "工作台", "会话隔离", "数据隔离", "进群", "确认当前项目",
        "bug", "已知 bug", "预计改完", "规则框架", "系统级", "全局 skill 规则",
        "fangcun", "skill", "群组结构", "文档", "wiki", "挂载", "权限", "归档", "bot",
    ]
    return any(t.lower() in line.lower() for t in deny_terms)


def extract_rule_candidates_from_chat_text(chat_text: str) -> list[dict]:
    """Best-effort extraction of *current project creative rules* from chat logs.

    Important: this intentionally filters out system/workspace/product discussions,
    bug status, governance, wiki/doc management, etc. Only creative constraints for
    the currently discussed drama project should survive.
    """
    current_project = detect_current_project_from_chat_text(chat_text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (chat_text or "").splitlines()]
    candidates: list[dict] = []
    seen: set[str] = set()
    patterns = [
        (r"(不要[^，。；\n]{2,40})", "hard", 0.9),
        (r"(禁止[^，。；\n]{2,40})", "hard", 0.95),
        (r"(必须[^，。；\n]{2,40})", "hard", 0.85),
        (r"(每集[^，。；\n]{2,40}(?:要|必须)[^，。；\n]{1,20})", "hard", 0.8),
        (r"(建议[^，。；\n]{2,40})", "soft", 0.6),
        (r"(尽量[^，。；\n]{2,40})", "soft", 0.6),
        (r"(先别[^，。；\n]{2,40})", "soft", 0.7),
    ]
    for line in lines:
        if len(line) < 3:
            continue
        if _is_non_script_rule_discussion(line):
            continue
        # If a current project name is detectable, prefer lines that mention it or obvious creative constraints.
        if current_project and (current_project not in line) and not re.search(r"不要|禁止|必须|每集|建议|尽量|先别|女主|男主|反差|反转|哭戏|钩子|人设|节奏|集", line):
            continue
        for pat, kind, conf in patterns:
            for m in re.finditer(pat, line):
                rule = m.group(1).strip(" ：:，。；;,.!！?？")
                rule = re.sub(r"^(我觉得|要不|是不是|感觉|我们项目|这个项目|这一版|当前版本|本群最新的剧本是)", "", rule).strip()
                if len(rule) >= 3 and rule not in seen:
                    candidates.append({
                        "rule": rule,
                        "kind": kind,
                        "confidence": conf,
                        "evidence": line[:200],
                        "project": current_project,
                    })
                    seen.add(rule)
    return candidates


def get_project_rule_candidates_path(config) -> Path:
    return Path(config["output_dir"]) / "project_rule_candidates.json"


def save_project_rule_candidates(config, candidates: list[dict], source: str = "chat_extract") -> Path:
    path = get_project_rule_candidates_path(config)
    payload = {
        "source": source,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidates": candidates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_project_rule_candidates(config) -> dict:
    path = get_project_rule_candidates_path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def validate_project_rules_applied(config, content: str) -> list[str]:
    """Best-effort deterministic checks for explicit negative project rules.

    This does not replace AI/human review; it catches obvious violations and forces
    the agent to address them before marking outputs as passed.
    """
    text = content or ""
    rules = load_project_rules(config)
    if not rules:
        return []
    issues = []
    if "项目规则落实清单" not in text:
        issues.append("缺少『项目规则落实清单』：必须逐条说明项目 rules 如何被落实。")

    # For keyword conflict checks, ignore the self-descriptive checklist section to
    # reduce false positives like “已去掉反差设计”.
    body_for_scan = text.split("项目规则落实清单", 1)[0]
    for term in extract_negative_rule_terms(rules):
        if term and term in body_for_scan:
            issues.append(f"项目规则疑似未落实：规则禁止/否定「{term}」，但产出正文中仍出现该词。请人工确认是否违规。")

    try:
        from creative_consistency_guardrails import validate_creative_consistency
    except Exception:
        validate_creative_consistency = None
    if validate_creative_consistency:
        consistency = validate_creative_consistency(text, rules)
        for item in consistency.get("issues", []):
            prefix = "项目规则严重未落实" if item.get("severity") == "error" else "项目规则提醒"
            issues.append(f"{prefix}：{item.get('message', item.get('type'))}")
    return issues


# ─── 源文读取 ──────────────────────────────────────────────────────────────

def _extract_chapter_number(filename: str) -> int | None:
    """从文件名中提取章节号。支持格式：
    - 第1章xxx.txt, 第01章.txt
    - ch_001.txt, ch_01.txt
    - 01_xxx.txt, 1.txt
    - ep_001.txt (忽略，优先匹配 ch_ 和 第*章)
    """
    # 优先匹配 "第N章" 格式
    m = re.search(r"第\s*(\d+)\s*章", filename)
    if m:
        return int(m.group(1))
    # 其次匹配 ch_NNN 格式
    m = re.search(r"ch[_\s]*(\d+)", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 最后匹配任意数字（取第一个数字组）
    m = re.search(r"(\d+)", filename)
    if m:
        return int(m.group(1))
    return None


def get_source_text(config, ch_num: int) -> str:
    """读取源文单章全文。"""
    cache = get_cache_dir(config)
    chapters_dir = _resolve_chapters_dir(config, cache)
    if not chapters_dir:
        return ""
    for f in sorted(chapters_dir.glob("*.txt")):
        n = _extract_chapter_number(f.name)
        if n == ch_num:
            return f.read_text(encoding="utf-8")
    return ""


def _resolve_chapters_dir(config, cache):
    """解析源文章节目录，按优先级：cache/chapters → source_chapter_dir → source_dir。"""
    chapters_dir = cache / "chapters"
    if chapters_dir.exists():
        return chapters_dir
    for key in ("source_chapter_dir", "source_dir"):
        if config.get(key):
            p = Path(config[key])
            if p.exists():
                return p
    return None


def get_source_chapters(config) -> list[tuple[int, Path]]:
    """获取源文章节列表 [(章号, 路径), ...]。支持多种命名格式。"""
    cache = get_cache_dir(config)
    chapters_dir = _resolve_chapters_dir(config, cache)
    if not chapters_dir:
        return []
    chapters = []
    for f in sorted(chapters_dir.glob("*.txt")):
        n = _extract_chapter_number(f.name)
        if n is not None:
            chapters.append((n, f))
    return chapters


def get_total_chapters(config) -> int:
    """获取源文总章数。"""
    return len(get_source_chapters(config))


# ─── 事件表 ────────────────────────────────────────────────────────────────

def load_events(config) -> list[dict]:
    """读取事件表。"""
    f = get_cache_dir(config) / "events.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


def save_events(config, events: list[dict]):
    """保存事件表。"""
    f = get_cache_dir(config) / "events.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def get_events_text(config, chapter_ids=None) -> str:
    """读取事件表，返回格式化文本。"""
    events = load_events(config)
    if chapter_ids:
        events = [e for e in events if e.get("id") in chapter_ids]
    valid = [e for e in events if e.get("event")]
    if not valid:
        return "事件表不存在或为空"
    return "\n".join(
        f"第{e.get('chapter_index', e.get('id', '?'))}章，标题:{e.get('chapter', '?')}，事件:{e.get('event', '?')}"
        for e in valid
    )


def get_chapter_event(config, ch_num: int) -> str:
    """提取指定章节的事件摘要（单行）。"""
    events = load_events(config)
    for e in events:
        if e.get("id") == ch_num or e.get("chapter_index") == ch_num:
            if e.get("event"):
                return f"第{ch_num}章：{e['event']}"
    return ""


# ─── 故事骨架 ──────────────────────────────────────────────────────────────

def load_story_outline(config) -> str:
    """读取故事大纲。"""
    f = get_cache_dir(config) / "story_outline.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def save_story_outline(config, content: str):
    """保存故事大纲。"""
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    f = get_cache_dir(config) / "story_outline.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def load_skeleton(config) -> str:
    """读取故事骨架。"""
    f = get_cache_dir(config) / "story_skeleton.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def save_skeleton(config, content: str):
    """保存故事骨架。"""
    f = get_cache_dir(config) / "story_skeleton.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def get_skeleton_context(config, ch_num: int) -> str:
    """从骨架中提取与指定章节相关的片段（所属幕 + 分集信息）。"""
    skeleton = load_skeleton(config)
    if not skeleton:
        return ""

    lines = skeleton.split("\n")
    result = []

    # 找本章所属幕
    for i, line in enumerate(lines):
        if "第" in line and "幕" in line and "→" in line:
            m = re.search(r"第(\d+)-(\d+)章", line)
            if m:
                start_ch, end_ch = int(m.group(1)), int(m.group(2))
                if start_ch <= ch_num <= end_ch:
                    result.append(f"【所属幕】{line.strip()}")
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if lines[j].startswith("**功能") or lines[j].startswith("**核心问题") or lines[j].startswith("**幕末转折"):
                            result.append(lines[j].strip())
                        if lines[j].startswith("### 第") or lines[j].startswith("## "):
                            break
                    break

    # 找分集信息（模式A：逐集展开）
    for i, line in enumerate(lines):
        if re.search(rf"集\s*{ch_num}\s*[：:]", line) or re.search(rf"### 集{ch_num}", line):
            result.append("【分集信息】")
            for j in range(i, min(i + 10, len(lines))):
                if lines[j].strip():
                    result.append(lines[j].strip())
                if j > i and (lines[j].startswith("### 集") or lines[j].startswith("## ")):
                    break
            break

    # 找分集总览表中的行（模式B）
    for line in lines:
        if re.match(rf"\|\s*{ch_num}\s*\|", line):
            result.append(f"【分集总览】{line.strip()}")
            break

    return "\n".join(result) if result else ""


# ─── S0 用户需求文档 / 改编策略 ────────────────────────────────────────────

def load_requirements(config) -> str:
    """读取 S0 用户需求文档。"""
    f = get_cache_dir(config) / "requirements.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def save_requirements(config, content: str):
    """保存 S0 用户需求文档。"""
    f = get_cache_dir(config) / "requirements.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def load_adaptation(config) -> str:
    """读取 S2 改编策略。"""
    f = get_cache_dir(config) / "adaptation_strategy.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def save_adaptation(config, content: str):
    """保存 S2 改编策略。"""
    f = get_cache_dir(config) / "adaptation_strategy.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def get_adaptation_principles(config) -> str:
    """从改编策略中提取核心原则（前 5 条）。"""
    adaptation = load_adaptation(config)
    if not adaptation:
        return ""

    lines = adaptation.split("\n")
    result = []
    in_principles = False

    for line in lines:
        if "核心改编原则" in line or "改编原则" in line:
            in_principles = True
            continue
        if in_principles:
            if line.startswith("## ") or line.startswith("### "):
                break
            if line.strip():
                result.append(line.strip())
            if len(result) >= 15:
                break

    return "\n".join(result) if result else ""


# ─── 文笔指纹 ──────────────────────────────────────────────────────────────

def load_style_text(config, ch_num: int) -> str:
    """加载文笔指纹（算法锚点 + LLM 分析）。"""
    styles_dir = get_cache_dir(config) / "styles"
    parts = []
    f = styles_dir / f"style_{ch_num:03d}.md"
    if f.exists():
        parts.append(f.read_text(encoding="utf-8"))
    f_llm = styles_dir / f"style_{ch_num:03d}_llm.md"
    if f_llm.exists():
        parts.append(f_llm.read_text(encoding="utf-8"))
    return "\n\n".join(parts) if parts else ""
