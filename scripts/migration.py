"""Legacy project migration (spec §28).

Reads legacy configs/artifacts and copies them into the new layout without
deleting or modifying the source. Every mapping is recorded in a migration
report so the writer can audit what was kept, remapped or skipped.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .common import atomic_write_json, ensure_dir, now_iso, slugify
from .schema_validate import ensure_valid
from .state_store import init_project, record_artifact


def _legacy_config_paths(projects_dir: Path) -> list[Path]:
    paths = list(projects_dir.glob("*/drama/config.json"))
    paths += list(projects_dir.glob("*/config.json"))
    return sorted(set(paths))


def map_legacy_config(legacy: dict, project_slug: str) -> dict:
    """Map the legacy config onto the new project-config contract."""
    project = legacy.get("project", {}) or {}
    genre = project.get("style") or legacy.get("style") or ["未指定"]
    if isinstance(genre, str):
        genre = [genre]
    duration_minutes = project.get("episode_duration") or legacy.get("episode_duration")
    minimum_seconds = int(duration_minutes * 60) if isinstance(duration_minutes, (int, float)) else 60
    episodes = project.get("episodes") or legacy.get("episodes")
    mapped = {
        "project_id": slugify(project_slug),
        "novel_name": project.get("source_book") or legacy.get("source_book") or "",
        "drama_name": project.get("drama_name") or project.get("project_name") or legacy.get("project_name") or project_slug,
        "platform": project.get("platform") or legacy.get("platform") or "竖屏短剧",
        "aspect_ratio": project.get("aspect_ratio") or "9:16",
        "genre": genre,
        "initial_episode_count": episodes if isinstance(episodes, int) else None,
        "minimum_episode_seconds": minimum_seconds,
        "minimum_total_seconds": None,
        "reach_original_ending": project.get("reach_original_ending", True),
        "fidelity": project.get("fidelity", "medium"),
        "dialogue_policy": project.get("dialogue_policy", "prefer_original"),
        "review_policy": "advisory_with_writer_confirmation",
        "script_format": "default-cn",
        "writer_has_final_authority": True,
        "legacy_migrated": True,
        "legacy_config": str(legacy.get("config_path", "")),
    }
    ensure_valid(mapped, "project-config.schema.json")
    return mapped


def _legacy_project_root(legacy: dict, config_path: Path) -> Path:
    workspace = legacy.get("project_workspace")
    if workspace:
        root = Path(workspace).resolve()
        if (root / "config.json").exists() or (root / "drama").exists():
            return root
    output_dir = legacy.get("output_dir")
    if output_dir:
        p = Path(output_dir).resolve()
        return p.parent.parent if p.name == "drama" else p.parent
    return config_path.parent.parent if config_path.parent.name == "drama" else config_path.parent


def _normalize_events(legacy_events: Any, config_path: Path) -> list[dict]:
    if isinstance(legacy_events, dict) and "events" in legacy_events:
        legacy_events = legacy_events["events"]
    if not isinstance(legacy_events, list):
        return []
    normalized = []
    for idx, event in enumerate(legacy_events, start=1):
        if not isinstance(event, dict):
            continue
        old_id = event.get("id") or event.get("event_id") or idx
        normalized.append(
            {
                "event_id": f"LEGACY-{old_id}",
                "chapter_id": int(event.get("chapter_index") or event.get("chapter_id") or idx),
                "chapter_title": str(event.get("chapter", "") or ""),
                "event": str(event.get("event", "") or ""),
                "legacy": True,
            }
        )
    return normalized


def mark_legacy_must_keep(outline: dict) -> dict:
    """Mark unclassifiable legacy must_keep entries for a NEW logical version.

    Historical version files are never rewritten.  Strings that cannot be
    reliably classified as story beat / quote / project rule / style hint are
    preserved as text and explicitly tagged legacy_unspecified instead of
    letting the model silently guess a category.
    """
    result = dict(outline)
    entries = list(outline.get("must_keep", []) or [])
    converted = []
    for item in entries:
        if isinstance(item, str):
            converted.append(
                {
                    "text": item,
                    "legacy_classification": "legacy_unspecified",
                }
            )
        else:
            converted.append(item)
    if converted:
        result["must_keep"] = converted
    result["outline_schema_version"] = "v2"
    return result


def migrate_project(legacy_config_path: Path, out_dir: Path) -> dict:
    """Migrate one legacy project into the new layout (copy-only)."""
    legacy_config_path = legacy_config_path.resolve()
    legacy = json.loads(legacy_config_path.read_text(encoding="utf-8"))
    legacy["config_path"] = str(legacy_config_path)
    slug = legacy_config_path.parent.name
    if legacy_config_path.parent.name == "drama":
        slug = legacy_config_path.parent.parent.name

    mapped = map_legacy_config(legacy, slug)
    project_dir = out_dir / mapped["project_id"]
    init_project(project_dir, mapped, source="migration")
    report: dict[str, Any] = {
        "migrated_at": now_iso(),
        "source_config": str(legacy_config_path),
        "target_project_dir": str(project_dir),
        "mapped": [],
        "skipped": [],
        "warnings": [],
    }

    old_root = _legacy_project_root(legacy, legacy_config_path)
    cache = old_root / "_cache" if (old_root / "_cache").exists() else old_root / "drama" / "_cache"

    # source events
    if cache.exists():
        events_src = cache / "events.json"
        if events_src.exists():
            events = _normalize_events(json.loads(events_src.read_text(encoding="utf-8")), legacy_config_path)
            if events:
                target = project_dir / "artifacts" / "source_events" / "events.json"
                ensure_dir(target.parent)
                atomic_write_json(target, events)
                record_artifact(project_dir, "source_events", target, source="migration", status="approved")
                report["mapped"].append({"from": str(events_src), "to": str(target), "type": "source_events", "count": len(events)})
            else:
                report["skipped"].append({"from": str(events_src), "reason": "events.json 无有效事件"})
        else:
            report["skipped"].append({"from": str(cache), "reason": "缺少 events.json"})
    else:
        report["warnings"].append("未找到旧版 _cache 目录，事件资产未迁移")

    # story_skeleton -> episode_outline (copy + legacy note)
    skeleton_candidates = [
        old_root / "story_skeleton.md",
        old_root / "drama" / "story_skeleton.md",
        old_root / "output" / "story_skeleton.md",
    ]
    for candidate in skeleton_candidates:
        if candidate.exists():
            target = project_dir / "artifacts" / "episode_outline" / "episode_outline.md"
            ensure_dir(target.parent)
            text = candidate.read_text(encoding="utf-8")
            target.write_text(
                "<!-- 已从旧版 story_skeleton.md 迁移；尚未解析为 episode-outline JSON，"
                "需要编剧确认后重新生成结构化集纲 -->\n\n" + text,
                encoding="utf-8",
            )
            record_artifact(project_dir, "episode_outline", target, source="migration", status="draft")
            report["mapped"].append({"from": str(candidate), "to": str(target), "type": "episode_outline_md", "status": "needs_structured_outline"})
            break

    # approved scripts
    scripts_src = old_root / "scripts"
    if scripts_src.exists():
        copied = 0
        for src in sorted(scripts_src.glob("ep_*.txt")):
            try:
                episode = int(src.stem.split("_")[1])
            except (IndexError, ValueError):
                report["skipped"].append({"from": str(src), "reason": "文件名无法解析集数"})
                continue
            target = project_dir / "artifacts" / "approved_scripts" / f"ep{episode:03d}.txt"
            ensure_dir(target.parent)
            shutil.copy2(src, target)
            record_artifact(project_dir, "approved_script", target, episode=episode, source="migration", status="approved")
            copied += 1
        report["mapped"].append({"from": str(scripts_src), "to": str(project_dir / "artifacts" / "approved_scripts"), "type": "approved_scripts", "count": copied})

    # legacy continuity
    continuity_src = old_root / "continuity_state.json"
    if not continuity_src.exists():
        continuity_src = old_root / "drama" / "continuity_state.json"
    if continuity_src.exists():
        data = json.loads(continuity_src.read_text(encoding="utf-8"))
        data["legacy_migrated"] = True
        from .state_store import save_continuity

        save_continuity(project_dir, data)
        report["mapped"].append({"from": str(continuity_src), "to": str(project_dir / "state" / "continuity.json"), "type": "continuity_state"})

    report_path = project_dir / "state" / "migration_report.json"
    atomic_write_json(report_path, report)
    (project_dir / "state" / "migration_report.md").write_text(render_migration_report(report), encoding="utf-8")
    return report


def migrate_all(legacy_projects_dir: Path, out_dir: Path) -> list[dict]:
    reports = []
    for config_path in _legacy_config_paths(legacy_projects_dir):
        try:
            reports.append(migrate_project(config_path, out_dir))
        except Exception as exc:
            reports.append({"source_config": str(config_path), "error": str(exc)})
    return reports


def render_migration_report(report: dict) -> str:
    lines = [
        "# 迁移报告",
        "",
        f"- 时间：{report.get('migrated_at')}",
        f"- 源配置：{report.get('source_config')}",
        f"- 目标项目：{report.get('target_project_dir')}",
        "",
        "## 已迁移",
    ]
    for item in report.get("mapped", []):
        lines.append(f"- {item.get('type')}：{item.get('from')} → {item.get('to')}（{item.get('count', '')}）")
    lines.extend(["", "## 跳过", *[f"- {i.get('from')}：{i.get('reason')}" for i in report.get("skipped", [])]])
    lines.extend(["", "## 警告", *[f"- {w}" for w in report.get("warnings", [])]])
    lines.extend(["", "## 说明", "- 迁移只复制，不删除或修改旧文件。", "- 旧 story_skeleton.md 需要编剧确认后重新生成结构化集纲 JSON。"])
    return "\n".join(lines) + "\n"
