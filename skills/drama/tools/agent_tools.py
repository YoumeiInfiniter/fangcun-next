"""
文件 I/O 工具层 — 共享产物在 _cache/（源书级），剧本在 output_dir（项目级）。

路径规则：
  events.json / story_skeleton.md / adaptation_strategy.md → _cache/
  scripts/ep_NNN.txt / state.json / reviews/ → output_dir
"""

import json
import re
from pathlib import Path

from fangcun_guardrails import ensure_output_path


def _resolve_cache_dir(output_dir: str) -> Path:
    """从 output_dir 推断 _cache/ 路径（与 source_io 约定一致）。

    Convention: projects/<项目>/_cache（项目根）；drama/_cache 仅作老项目兜底。
    """
    from source_io import resolve_cache_dir_from_output
    return resolve_cache_dir_from_output(Path(output_dir))


def get_events(output_dir: str, chapter_ids: list[int] = None) -> str:
    """读取事件表，返回格式化文本。"""
    cache_dir = _resolve_cache_dir(output_dir)
    events_file = cache_dir / "events.json"
    if not events_file.exists():
        return "事件表不存在，请先执行事件提取（--phase event）"

    events = json.loads(events_file.read_text(encoding="utf-8"))
    if chapter_ids:
        events = [e for e in events if e.get("id") in chapter_ids]
    if not events:
        return "无匹配事件"

    lines = []
    for e in events:
        lines.append(f"第{e.get('chapter_index', e.get('id', '?'))}章，标题:{e.get('chapter', '?')}，事件:{e.get('event', '?')}")
    return "\n".join(lines)


def get_events_json(output_dir: str) -> list[dict]:
    """读取事件表原始 JSON。"""
    cache_dir = _resolve_cache_dir(output_dir)
    events_file = cache_dir / "events.json"
    if not events_file.exists():
        return []
    return json.loads(events_file.read_text(encoding="utf-8"))


def save_events(output_dir: str, events: list[dict]):
    """保存事件表到 _cache/。"""
    cache_dir = _resolve_cache_dir(output_dir)
    events_file = cache_dir / "events.json"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    events_file.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def get_story_outline(output_dir: str) -> str:
    """读取故事大纲。"""
    cache_dir = _resolve_cache_dir(output_dir)
    f = cache_dir / "story_outline.md"
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8")


def save_story_outline(output_dir: str, content: str):
    """保存故事大纲到 _cache/。"""
    cache_dir = _resolve_cache_dir(output_dir)
    f = cache_dir / "story_outline.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def get_skeleton(output_dir: str) -> str:
    """读取故事骨架。"""
    cache_dir = _resolve_cache_dir(output_dir)
    f = cache_dir / "story_skeleton.md"
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8")


def save_skeleton(output_dir: str, content: str):
    """保存故事骨架到 _cache/。"""
    cache_dir = _resolve_cache_dir(output_dir)
    f = cache_dir / "story_skeleton.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def get_adaptation(output_dir: str) -> str:
    """读取改编策略。"""
    cache_dir = _resolve_cache_dir(output_dir)
    f = cache_dir / "adaptation_strategy.md"
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8")


def save_adaptation(output_dir: str, content: str):
    """保存改编策略到 _cache/。"""
    cache_dir = _resolve_cache_dir(output_dir)
    f = cache_dir / "adaptation_strategy.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def get_novel_text(source_dir: str, chapter_index: int) -> str:
    """读取小说章节原文。"""
    source = Path(source_dir)
    for f in sorted(source.glob("第*章*.txt")):
        m = re.search(r"(\d+)", f.name)
        if m and int(m.group(1)) == chapter_index:
            return f.read_text(encoding="utf-8")
    return ""


def get_novel_chapters(source_dir: str) -> list[tuple[int, Path]]:
    """获取所有章节文件列表。"""
    chapters = []
    for f in sorted(Path(source_dir).glob("第*章*.txt")):
        m = re.search(r"(\d+)", f.name)
        if m:
            chapters.append((int(m.group(1)), f))
    return chapters


def get_script_content(output_dir: str, episode_ids: list[int] = None) -> str:
    """读取已有剧本文本（从 output_dir/scripts/）。"""
    scripts_dir = Path(output_dir) / "scripts"
    if not scripts_dir.exists():
        return ""
    if episode_ids is None:
        files = sorted(scripts_dir.glob("ep_*.txt"))
        if not files:
            return ""
        return files[-1].read_text(encoding="utf-8")
    parts = []
    for ep_id in episode_ids:
        f = scripts_dir / f"ep_{ep_id:03d}.txt"
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def validate_script_scene_key_gate(content: str) -> None:
    """程序级分场门禁：连续场次 scene key 相同则阻断保存/同步。"""
    try:
        from story_structure_guardrails import validate_script_scene_keys
    except Exception:
        try:
            from .story_structure_guardrails import validate_script_scene_keys
        except Exception as exc:
            raise RuntimeError(f"scene key 分场校验器加载失败，禁止保存剧本：{exc}") from exc
    report = validate_script_scene_keys(content)
    if report.get("ok") is False:
        details = []
        for item in report.get("issues", []):
            details.append(
                f"{item.get('previous_scene')}→{item.get('current_scene')} "
                f"scene_key={item.get('scene_key') or item.get('place')}|{item.get('time')}|{item.get('io')} "
                f"line {item.get('previous_line')}->{item.get('current_line')}: {item.get('message')}"
            )
        raise ValueError("剧本分场 scene key 门禁未通过：" + "；".join(details))


def save_script(output_dir: str, episode_num: int, content: str):
    """保存单集剧本到 output_dir/scripts/，并校验不越过项目 output_dir。"""
    validate_script_scene_key_gate(content)
    scripts_dir = ensure_output_path(output_dir, Path(output_dir) / "scripts", label="剧本目录")
    scripts_dir.mkdir(parents=True, exist_ok=True)
    f = ensure_output_path(output_dir, scripts_dir / f"ep_{episode_num:03d}.txt", label="剧本文件")
    f.write_text(content, encoding="utf-8")


def get_all_scripts(output_dir: str) -> list[dict]:
    """获取所有剧本列表。"""
    scripts_dir = Path(output_dir) / "scripts"
    if not scripts_dir.exists():
        return []
    result = []
    for f in sorted(scripts_dir.glob("ep_*.txt")):
        m = re.search(r"ep_(\d+)\.txt", f.name)
        if m:
            result.append({
                "id": int(m.group(1)),
                "name": f.stem,
                "content": f.read_text(encoding="utf-8"),
            })
    return result


# ─── XML 解析 ──────────────────────────────────────────────────────────────

def extract_xml_tag(text: str, tag: str) -> str:
    """从 LLM 输出中提取 XML 标签内容。"""
    pattern = rf"<{tag}[^>]*>([\s\S]*?)</{tag}>"
    m = re.search(pattern, text)
    if m:
        return m.group(1).strip()
    pattern_open = rf"<{tag}[^>]*>"
    m_open = re.search(pattern_open, text)
    if m_open:
        return text[m_open.end():].strip()
    return text.strip()


def extract_script_items(text: str) -> list[dict]:
    """从 LLM 输出中提取所有 <scriptItem> 标签。"""
    items = []
    pattern = r'<scriptItem\s+name="([^"]*)"[^>]*>([\s\S]*?)</scriptItem>'
    for m in re.finditer(pattern, text):
        items.append({"name": m.group(1).strip(), "content": m.group(2).strip()})
    if not items:
        pattern_open = r'<scriptItem\s+name="([^"]*)"[^>]*>'
        m_open = re.search(pattern_open, text)
        if m_open:
            name = m_open.group(1).strip()
            content = text[m_open.end():].strip()
            content = re.sub(r"\s*</scriptItem>\s*$", "", content)
            items.append({"name": name, "content": content})
    return items


# ─── 骨架片段提取 ──────────────────────────────────────────────────────────

def extract_episode_from_skeleton(skeleton_text: str, ep_num: int) -> str:
    """从骨架中提取指定集的信息。"""
    lines = skeleton_text.split("\n")
    result_sections = []

    story_core = _extract_section(lines, "故事核", "隐线")
    if story_core:
        result_sections.append("### 故事核\n" + story_core)

    hidden_line = _extract_section(lines, "隐线", "人物小传")
    if hidden_line:
        result_sections.append("### 隐线\n" + hidden_line)

    char_section = _extract_section(lines, "人物小传", "三幕结构")
    if char_section:
        result_sections.append("### 人物小传\n" + char_section[:800])

    ep_info = _extract_episode_info(lines, ep_num)
    if ep_info:
        result_sections.append(f"### 第{ep_num}集分集信息\n" + ep_info)

    act_info = _extract_act_for_episode(lines, ep_num)
    if act_info:
        result_sections.append("### 所属幕\n" + act_info)

    return "\n\n".join(result_sections) if result_sections else skeleton_text[:2000]


def _extract_section(lines, start_marker, end_marker):
    result = []
    capturing = False
    for line in lines:
        if start_marker in line and (line.startswith("#") or line.startswith("**")):
            capturing = True
            continue
        if capturing and (end_marker in line and (line.startswith("#") or line.startswith("**"))):
            break
        if capturing:
            result.append(line)
    return "\n".join(result).strip()


def _extract_episode_info(lines, ep_num):
    result = []
    for line in lines:
        if re.match(rf"\|\s*{ep_num}\s*\|", line):
            result.append(line)
            break
    in_detail = False
    for line in lines:
        if re.search(rf"集{ep_num}[（(]|集{ep_num}[:：]|集{ep_num}\s", line) and "详情" in line:
            in_detail = True
            continue
        if in_detail:
            if line.startswith("### 集") or line.startswith("#### "):
                break
            result.append(line)
    return "\n".join(result).strip()


def _extract_act_for_episode(lines, ep_num):
    for line in lines:
        if "第" in line and "幕" in line and "→" in line:
            m = re.search(r"集(\d+)-(\d+)", line)
            if m:
                start_ep, end_ep = int(m.group(1)), int(m.group(2))
                if start_ep <= ep_num <= end_ep:
                    act_lines = [line]
                    idx = lines.index(line) + 1
                    while idx < len(lines):
                        if "第" in lines[idx] and "幕" in lines[idx] and "→" in lines[idx]:
                            break
                        if lines[idx].startswith("### "):
                            break
                        act_lines.append(lines[idx])
                        idx += 1
                    return "\n".join(act_lines).strip()
    return ""


# ─── 输出校验 ──────────────────────────────────────────────────────────────

def validate_script(content: str, target_words: int = 300) -> list[str]:
    """校验剧本输出质量。"""
    issues = []
    stripped = (content or "").strip()
    placeholder_patterns = (
        r"<tool_call\b",
        r"</tool_call>",
        r"剧本已写入",
        r"请在工作台查看",
        r"我会先读取当前工作区",
        r"get_script_content",
        r"get_planData",
        r"get_novel_text",
        r"get_novel_events",
    )
    for pattern in placeholder_patterns:
        if re.search(pattern, stripped, flags=re.IGNORECASE):
            issues.append("严重：输出疑似工具调用占位/工作台占位，不是可交付剧本文本")
            break
    delta_count = stripped.count("△")
    if delta_count == 0:
        issues.append("严重：缺少△场景描述标记")
    elif delta_count < 2:
        issues.append(f"严重：△场景描述偏少（仅{delta_count}处），格式不合格")

    if not re.search(r"<scriptItem\b[^>]*>", content) or not re.search(r"</scriptItem>", content):
        issues.append("严重：缺少 <scriptItem>...</scriptItem> 包裹，剧本输出格式不合格")

    # 分集标题门禁：飞书正文里必须能直接看到固定分集标识，不能只藏在 XML 属性或文件名里。
    # 合法：EP011 / EP011：标题 / 第11集 / 第11集：标题。
    # 非法：作品名 EP011：标题（标识不在行首）、第十一集（非阿拉伯数字）。
    episode_heading_re = re.compile(
        r"^\s*(?:#{1,3}\s*)?(?:EP\s*0*\d+|第\s*\d+\s*集)(?:\s*[:：\-—]\s*\S.*)?\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not episode_heading_re.search(content):
        issues.append("严重：缺少规范分集标识；每集正文必须以『EP001』或『第1集』开头，数字只能用阿拉伯数字；如有集标题，必须写在分集标识之后，如『EP001：集标题』或『第1集：集标题』。")
    if re.search(r"^\s*(?:#{1,3}\s*)?第\s*[一二三四五六七八九十百零〇两]+\s*集", content, flags=re.MULTILINE):
        issues.append("严重：分集标识数字必须使用阿拉伯数字，禁止写『第十五集』这类中文数字形式。")

    # 精修剧本格式校验：场次标题必须是「集-场　地点/场景　时间　内/外」
    # 业务反馈明确：不要写「【第一集第一场】」；方括号只是解释，不是剧本格式。
    scene_heading_re = re.compile(
        r"^\s*\d+[-－]\d+\s+[^\n：:【】]+?\s+(?:日|夜|晨|午|傍晚|清晨|深夜)\s+(?:内|外)\s*$",
        flags=re.MULTILINE,
    )
    scene_headings = scene_heading_re.findall(content)
    if not scene_headings:
        issues.append("严重：缺少规范场次标题；必须写成『1-1　地点/场景　日　内』，不要拆成单独编号+『场：地点-时间-内外』。")
    if re.search(r"【\s*(?:第?[一二三四五六七八九十百0-9]+\s*)?集(?:第?[一二三四五六七八九十百0-9]+\s*)?场\s*】", content):
        issues.append("严重：出现解释性场次标题『【第一集第一场】』；业务格式禁止使用【】说明，必须改为『1-1　地点/场景　日　内』。")
    if re.search(r"^\s*\d+[-－]\d+\s*$", content, flags=re.MULTILINE) or re.search(r"^\s*场[：:].+[-－](日|夜|晨|午|傍晚|清晨|深夜)[-－](内|外)\s*$", content, flags=re.MULTILINE):
        issues.append("严重：仍在使用旧场次格式；场次编号、地点、时间、内外必须合并到同一行，如『1-1　怪力乱神管理局 大会场　日　内』。")
    if len(scene_headings) > 6:
        issues.append(f"警告：单集场次偏多（{len(scene_headings)}场），当前规范建议一集≤6场，优先合并功能相近场景")
    if re.search(r"\*\*[^*\n]{1,12}\*\*[：:]", content):
        issues.append("严重：角色台词仍使用 Markdown 粗体格式，应改为 角色（表情/语气）：台词")
    # 动作/台词混行：只拦截“△林晚：台词”或“△动作。林晚：台词”这类真实台词混排；
    # 不误伤“△大屏弹出文件夹：草图、修改稿”这类道具/列表冒号。
    dialogue_role_names = set(re.findall(r"^\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{0,12})(?:VO|OS)?(?:[（(][^）)]+[）)])?[：:]", content, flags=re.MULTILINE))
    mixed_action_dialogue = []
    for line in content.splitlines():
        if not line.lstrip().startswith("△"):
            continue
        body = line.lstrip()[1:].strip()
        for role in dialogue_role_names:
            if re.match(rf"^{re.escape(role)}(?:VO|OS)?(?:[（(][^）)]+[）)])?[：:]", body):
                mixed_action_dialogue.append(line)
                break
            if re.search(rf"[。！？!?；;]\s*{re.escape(role)}(?:VO|OS)?(?:[（(][^）)]+[）)])?[：:]", body):
                mixed_action_dialogue.append(line)
                break
    if mixed_action_dialogue:
        issues.append("严重：动作行和台词行混在同一行；必须动作另起一行、台词另起一行，不能在△动作后直接接角色台词。")
    dialogue_lines = re.findall(r"^\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{0,12})(?:VO|OS)?[：:]", content, flags=re.MULTILINE)
    expressive_lines = re.findall(r"^\s*[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{0,12}（[^）]+）[：:]", content, flags=re.MULTILINE)
    if len(dialogue_lines) >= 4 and len(expressive_lines) / max(1, len(dialogue_lines)) < 0.35:
        issues.append("警告：台词表情/语气括注偏少，精修格式要求重要台词标注当时表情或语气")
    vo_count = len(re.findall(r"^[^\n：:]{1,12}VO[：:]", content, flags=re.MULTILINE))
    if vo_count >= 3 and not re.search(r"手机特写|屏幕|微信|短信|监控|新闻|闪回|镜头", content):
        issues.append("警告：VO偏多但缺少手机屏幕/闪回/道具/镜头等视听转化，疑似未执行信息降维SOP")

    # 纯内容字数（扣除标题、梗概、分隔线等元数据行）
    pure = re.sub(r'^#.*$', '', content, flags=re.MULTILINE)
    pure = re.sub(r'^[-=]+$', '', pure, flags=re.MULTILINE)
    word_count = len(pure.strip())
    # 严格容差：超2倍或不足50%均为严重
    if word_count > target_words * 2:
        issues.append(f"严重：字数严重偏多 {word_count}字（目标约{target_words}字，上限{target_words * 2}字）")
    elif word_count < target_words * 0.5:
        issues.append(f"严重：字数严重偏少 {word_count}字（目标约{target_words}字，下限{int(target_words * 0.5)}字）")

    # 低级语义错配：媒介/故事类对象不能随手写成“玩”
    bad_media_play = re.findall(r"玩[《\"]([^》\"]+)[》\"]", content)
    for title in bad_media_play:
        if any(key in title for key in ("故事", "童话", "帽", "书", "绘本", "电视", "直播")):
            issues.append(f"严重：原文/常识语义疑似错配：不应写成‘玩《{title}》’，请改为看/听/讲/读/沉浸在等准确动词")

    # 分场/分集结构门禁：检测同时间同地点连续拆场、分集体量严重失衡等。
    try:
        from story_structure_guardrails import validate_text as _validate_story_structure
    except Exception:
        try:
            from .story_structure_guardrails import validate_text as _validate_story_structure
        except Exception:
            _validate_story_structure = None
    if _validate_story_structure:
        structure = _validate_story_structure(content)
        for item in structure.get("issues", []):
            prefix = "严重" if item.get("severity") == "error" else "警告"
            issues.append(f"{prefix}：{item.get('message', item.get('type'))}")

    # 台词风格门禁：检测 AI 腔、口号式、解释性文章腔。
    try:
        from dialogue_style_guardrails import validate_dialogue_style as _validate_dialogue_style
    except Exception:
        try:
            from .dialogue_style_guardrails import validate_dialogue_style as _validate_dialogue_style
        except Exception:
            _validate_dialogue_style = None
    if _validate_dialogue_style:
        style_report = _validate_dialogue_style(content)
        for item in style_report.get("issues", []):
            issues.append(f"警告：{item.get('message', item.get('type'))}")

    # 视听化门禁：动作必须带 △，小说性/心理性/抽象旁白必须转成可拍画面。
    try:
        from cinematic_guardrails import validate_cinematic_action as _validate_cinematic_action
    except Exception:
        try:
            from .cinematic_guardrails import validate_cinematic_action as _validate_cinematic_action
        except Exception:
            _validate_cinematic_action = None
    if _validate_cinematic_action:
        cinematic_report = _validate_cinematic_action(content)
        for item in cinematic_report.get("issues", []):
            prefix = "严重" if item.get("severity") == "error" else "警告"
            issues.append(f"{prefix}：{item.get('message', item.get('type'))}")

    # XML 标签不强制要求
    return issues


def validate_event(event_text: str) -> list[str]:
    """校验事件提取结果。"""
    issues = []
    if not event_text or not event_text.strip():
        issues.append("严重：事件为空")
        return issues
    if event_text.startswith("[提取失败"):
        issues.append(f"严重：{event_text}")
        return issues
    if "|" not in event_text:
        issues.append("警告：事件格式异常")
    if len(event_text) < 20:
        issues.append(f"警告：事件描述过短（{len(event_text)}字）")
    return issues
