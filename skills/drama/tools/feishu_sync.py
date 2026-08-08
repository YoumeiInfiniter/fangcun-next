"""
飞书文档自动同步工具

用法：
  python feishu_sync.py --config config.json --phase story_outline
  python feishu_sync.py --config config.json --phase skeleton
  python feishu_sync.py --config config.json --phase adaptation
  python feishu_sync.py --config config.json --phase review --review-target skeleton
  python feishu_sync.py --config config.json --phase script --start 1 --end 10
  python feishu_sync.py --config config.json --phase export

此工具将 pipeline 各阶段产物自动写入飞书文档。
需要 feishu_doc 工具权限（OpenClaw 飞书集成）。
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

_TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(_TOOLS_DIR))
sys.path.insert(0, str(_TOOLS_DIR / "lib"))

from source_analysis import load_events, load_skeleton, load_adaptation, get_cache_dir


def _resolve_path(config: dict, subdir: str, filename: str) -> Optional[Path]:
    """Resolve file path for a pipeline output."""
    output_dir = Path(config["output_dir"])
    path = output_dir / subdir / filename
    if path.exists():
        return path
    return None


def get_output_files(config: dict, phase: str, **kwargs) -> list[tuple[str, Path, str]]:
    """
    Get output files for a phase.
    Returns list of (label, path, doc_section_title).
    """
    output_dir = Path(config["output_dir"])
    cache_dir = get_cache_dir(config)
    files = []

    if phase == "event":
        path = cache_dir / "events.json"
        if path.exists():
            events = json.loads(path.read_text(encoding="utf-8"))
            # Convert to readable Markdown
            md = _events_to_md(events)
            # Save as events.md alongside
            md_path = cache_dir / "events.md"
            md_path.write_text(md, encoding="utf-8")
            files.append(("事件表", md_path, "事件表"))

    elif phase == "story_outline":
        path = cache_dir / "story_outline.md"
        if path.exists():
            files.append(("故事大纲", path, "故事大纲"))

    elif phase == "skeleton":
        path = cache_dir / "story_skeleton.md"
        if path.exists():
            files.append(("故事骨架(集纲)", path, "故事骨架(集纲)"))

    elif phase == "adaptation":
        path = cache_dir / "adaptation_strategy.md"
        if path.exists():
            files.append(("改编策略", path, "改编策略"))

    elif phase == "review":
        target = kwargs.get("review_target", "all")
        review_dir = output_dir / "reviews"
        targets = [target] if target != "all" else ["story_outline", "skeleton", "adaptation"]
        for t in targets:
            path = review_dir / f"{t}_review.md"
            if path.exists():
                files.append((f"审核报告-{t}", path, f"审核报告：{t}"))

    elif phase == "script":
        start = kwargs.get("start", 1)
        end = kwargs.get("end", 100)
        scripts_dir = output_dir / "scripts"
        for ep in range(start, end + 1):
            path = scripts_dir / f"ep_{ep:03d}.txt"
            if path.exists():
                files.append((f"第{ep}集剧本", path, f"第{ep}集"))

    elif phase == "export":
        drama_name = config.get("drama_name", "script")
        path = output_dir / f"{drama_name}.txt"
        if path.exists():
            files.append(("完整剧本", path, f"{drama_name} 完整剧本"))

    return files


def _events_to_md(events: list) -> str:
    """Convert events JSON to readable Markdown."""
    md_lines = ["# 事件表\n"]
    for ev in events:
        ch = ev.get("chapter", "?")
        summary = ev.get("summary", "")
        event_type = ev.get("type", "")
        md_lines.append(f"## 第{ch}章")
        if event_type:
            md_lines.append(f"- 类型：{event_type}")
        if summary:
            md_lines.append(f"- {summary}")
        md_lines.append("")
    return "\n".join(md_lines)


def generate_sync_manifest(config: dict, phase: str, **kwargs) -> dict:
    """
    Generate a sync manifest that describes what needs to be synced to Feishu.
    The agent (on OpenClaw) reads this manifest and calls feishu_doc tools accordingly.

    Returns:
        {
            "action": "create_or_update",
            "title": "项目名-阶段",
            "files": [...],
            "instructions": "step-by-step instructions for the agent"
        }
    """
    files = get_output_files(config, phase, **kwargs)
    if not files:
        return {
            "action": "skip",
            "reason": f"No output files found for phase: {phase}",
            "files": []
        }

    drama_name = config.get("drama_name", "")
    novel_name = config.get("novel_name", "")
    project_title = drama_name or novel_name or "未命名项目"

    phase_labels = {
        "event": "事件表",
        "story_outline": "故事大纲",
        "skeleton": "集纲",
        "adaptation": "改编策略",
        "review": "审核报告",
        "script": "剧本",
        "export": "完整剧本"
    }

    phase_label = phase_labels.get(phase, phase)

    # Generate instructions for the OpenClaw agent
    instructions = f"""
飞书文档同步 - {project_title} - {phase_label}

需要创建/更新飞书文档，包含以下内容：
"""
    for label, path, section in files:
        size_kb = path.stat().st_size / 1024
        instructions += f"\n- **{label}** ({path.name}, {size_kb:.1f}KB)"

    return {
        "action": "create_or_update",
        "title": f"{project_title}-{phase_label}",
        "project_title": project_title,
        "phase": phase,
        "phase_label": phase_label,
        "files": [
            {
                "label": label,
                "path": str(path.resolve()),
                "section": section,
                "size_kb": round(path.stat().st_size / 1024, 1)
            }
            for label, path, section in files
        ],
        "instructions": instructions.strip()
    }


def print_manifest_for_agent(config: dict, phase: str, **kwargs):
    """
    Print sync manifest as JSON to stdout.
    The OpenClaw agent reads this and performs the feishu_doc operations.
    """
    manifest = generate_sync_manifest(config, phase, **kwargs)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    import argparse
    parser = argparse.ArgumentParser(description="飞书文档同步工具")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--phase", required=True,
                        choices=["event", "story_outline", "skeleton", "adaptation", "review", "script", "export", "all"],
                        help="同步阶段")
    parser.add_argument("--review-target", default="all", help="审核目标")
    parser.add_argument("--start", type=int, default=1, help="剧本起始集")
    parser.add_argument("--end", type=int, default=100, help="剧本结束集")
    parser.add_argument("--json", action="store_true", help="输出 JSON manifest 供 agent 消费")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))

    if args.json:
        manifest = print_manifest_for_agent(config, args.phase,
                                            review_target=args.review_target,
                                            start=args.start, end=args.end)
        return manifest

    # Human-readable output
    files = get_output_files(config, args.phase,
                             review_target=args.review_target,
                             start=args.start, end=args.end)
    if not files:
        print(f"[SKIP] No files found for phase: {args.phase}")
        return

    print(f"\n📁 待同步文件 ({len(files)}个):")
    for label, path, section in files:
        size_kb = path.stat().st_size / 1024
        print(f"  • {label}: {path.name} ({size_kb:.1f}KB)")

    print(f"\n💡 提示：在 OpenClaw 环境下，Agent 会自动调用 feishu_doc 工具同步。")
    print(f"   非 OpenClaw 环境请手动上传上述文件。")


if __name__ == "__main__":
    main()
