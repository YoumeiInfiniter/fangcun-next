#!/usr/bin/env python3
"""
飞书项目资产树管理工具。

一键为剧本项目创建飞书文档层级，并同步各阶段 pipeline 产出物。

用法：
  python build_feishu_project.py --config config.json          # 生成同步 manifest（默认不直接调用飞书）
  python build_feishu_project.py --config config.json --json   # 输出 manifest JSON（保持兼容）
  python build_feishu_project.py --config config.json --execute # 生成 manifest 并执行飞书 create/new-version
  python build_feishu_project.py --config config.json --phase skeleton  # 仅同步指定阶段（预留）

文档结构（阶段拆分，禁止把全项目塞进一个超长主文档）：
  📄 《项目名》-项目信息-vYYYYMMDD-r1   # dashboard：元信息/rules/链接索引/进度/版本，不放原文正文
  📄 《项目名》-资产Dashboard-vYYYYMMDD-r1 # project_assets.json 的可读资产面板
  📄 《项目名》-改编指引-vYYYYMMDD-r1
  📄 《项目名》-故事大纲-vYYYYMMDD-r1
  📄 《项目名》-集纲-vYYYYMMDD-r1
  📄 《项目名》-审核报告-阶段-vYYYYMMDD-r1
  📄 《项目名》-剧本EP001-005-vYYYYMMDD-r1
  📄 《项目名》-完整导出-vYYYYMMDD-r1

此工具默认作为 manifest 生成器运行，输出需要执行的飞书操作清单。
加 --execute 时会调用同目录 feishu_project_executor.py，通过 OpenClaw 配置中的飞书应用凭据直接执行 docx create/new-version，并在项目输出目录记录 doc_token 状态；资产 Dashboard 只在剧本批次/导出汇总阶段生成，普通阶段不自动生成。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(THIS_DIR / "lib"))

from project_ownership_guard import assert_config_binding, ProjectOwnershipError


def today_version(revision: int = 1) -> str:
    return datetime.now().strftime(f"v%Y%m%d-r{revision}")


def doc_title(project_title: str, task: str, version: str = None) -> str:
    """统一飞书文档命名：《项目名》-子任务-vYYYYMMDD-r<n>。"""
    version = version or today_version()
    clean = (project_title or "未命名项目").strip("《》")
    return f"《{clean}》-{task}-{version}"


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def format_event_for_markdown(raw: str) -> str:
    """事件提取结果常是单行 markdown 表格；转成普通列表，避免飞书表格兼容问题。"""
    text = (raw or "").strip()
    if not text:
        return "（无事件摘要）"
    if text.startswith("|") and text.endswith("|"):
        cells = [c.strip() for c in text.strip("|").split("|")]
        labels = ["章节", "人物", "事件", "戏剧强度", "改编风险", "建议时长", "类型"]
        lines = []
        for idx, cell in enumerate(cells):
            if not cell:
                continue
            label = labels[idx] if idx < len(labels) else f"字段{idx + 1}"
            lines.append(f"- **{label}**：{cell}")
        return "\n".join(lines) if lines else text
    return text


def load_project_rules(config: dict) -> str:
    """读取项目 rules 摘要；不读取/嵌入原文正文。"""
    output_dir = Path(config.get("output_dir", "."))
    candidates = [
        output_dir / "project_rules.md",
        output_dir.parent / "_cache" / "project_rules.md",
    ]
    for path in candidates:
        content = _read_optional(path).strip()
        if content:
            return content[:4000]
    return "（暂无正式项目 rules）"


def group_scripts_by_batch(scripts: dict, batch_size: int = 5) -> dict:
    """将 epNN 脚本按批次合并，避免每集一个飞书文档过碎。"""
    grouped = {}
    if not scripts:
        return grouped
    nums = sorted(int(k.replace("ep", "")) for k in scripts.keys())
    for start in range(nums[0], nums[-1] + 1, batch_size):
        end = min(start + batch_size - 1, nums[-1])
        items = []
        paths = []
        for n in range(start, end + 1):
            key = f"ep{n:02d}"
            item = scripts.get(key)
            if not item:
                continue
            items.append(f"# 第{n}集\n\n{item['content'].strip()}")
            paths.append(item["path"])
        if items:
            grouped[f"EP{start:03d}-{end:03d}"] = {
                "label": f"剧本EP{start:03d}-{end:03d}",
                "path": ",".join(paths),
                "content": "\n\n---\n\n".join(items),
                "start": start,
                "end": end,
            }
    return grouped


def _final_batch_user_confirmed(config: dict) -> tuple[bool, str]:
    """Return whether final delivery may be registered.

    Final delivery now requires two explicit user signals:
    1) the final script batch was accepted;
    2) the user said a project-finish phrase (剧本完结/剧本结束/项目结束).
    Exporting all requested episodes is not project completion.
    """
    output_dir = Path(config.get("output_dir", "."))
    state_path = output_dir / "state.json"
    if not state_path.exists():
        return False, f"state.json 不存在：{state_path}"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"state.json 读取失败：{exc}"
    finished = state.get("project_finished") or {}
    if finished.get("user_confirmed") is not True or finished.get("status") != "confirmed":
        return False, "用户尚未明确说“剧本完结/剧本结束/项目结束”，禁止登记完结"
    expected = int((config.get("project") or {}).get("episodes") or config.get("episodes") or 0)
    if expected <= 0:
        return False, "config 未声明总集数，无法确认最终批次"
    batches = ((state.get("script_batches") or {}).get("confirmed") or [])
    for batch in reversed(batches):
        eps = [int(x) for x in (batch.get("episodes") or [])]
        if eps and max(eps) >= expected:
            if batch.get("user_confirmed") is True:
                return True, f"最终批次 {batch.get('batch_id')} 已确认，且项目完结口令已确认：{finished.get('finish_text', '')}"
            return False, f"最终批次 {batch.get('batch_id')} EP{eps[0]:03d}-EP{eps[-1]:03d} 尚未用户确认"
    return False, "未找到覆盖最终集的已提升剧本批次"


def build_script_full_output(config: dict, scripts: dict) -> Optional[dict]:
    """当全剧脚本已齐且最终批次已获用户确认时，生成机器可识别的完整剧本交付物。"""
    if not scripts:
        return None
    output_dir = Path(config.get("output_dir", "."))
    project = config.get("project", {}) or {}
    expected = int(project.get("episodes") or config.get("episodes") or 0)
    nums = sorted(int(k.replace("ep", "")) for k in scripts.keys())
    if expected <= 0 or len(nums) < expected or nums[:expected] != list(range(1, expected + 1)):
        return None

    title = config.get("drama_name") or config.get("novel_name") or "未命名项目"
    parts = [
        f"# 《{title}》完整剧本 EP001-EP{expected:03d}",
        "",
        "## 最终交付说明",
        "",
        "- doc_kind: script_full",
        "- stable_key: script_full",
        f"- 原著: {config.get('novel_name') or '未指定'}",
        f"- 剧名: 《{title}》",
        f"- 集数: {expected}",
        f"- 单集时长: {project.get('episode_duration', '?')}分钟",
        f"- 平台: {project.get('platform', '未指定')}",
        "",
        "---",
        "",
    ]
    for n in range(1, expected + 1):
        key = f"ep{n:02d}"
        parts.extend([f"# EP{n:03d}", "", scripts[key]["content"].strip(), "", "---", ""])
    content = "\n".join(parts).rstrip() + "\n"
    path = output_dir / f"script_full_ep001_{expected:03d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "label": f"完整剧本EP001-{expected:03d}",
        "path": str(path),
        "content": content,
        "start": 1,
        "end": expected,
    }


def get_cache_dir(config: dict) -> Path:
    """获取 _cache 目录（与 source_io 约定一致：项目根优先，drama/_cache 兜底）。"""
    from source_io import get_cache_dir as resolve_cache
    return resolve_cache(config)


def get_project_outputs(config: dict, include_script_full: bool = False) -> dict:
    """扫描项目产出物，返回待同步文件清单。

    include_script_full 必须只在用户明确确认最后一个剧本批次后由上层传入。
    集数齐全只能说明“可生成完整稿”，不能自动登记为完结交付。
    """
    cache_dir = get_cache_dir(config)
    output_dir = Path(config.get("output_dir", "."))
    project = config.get("project", {})
    outputs = {}

    # 改编指引
    p = cache_dir / "adaptation_strategy.md"
    if p.exists():
        outputs["adaptation"] = {
            "label": "改编指引",
            "path": str(p),
            "content": p.read_text(encoding="utf-8"),
        }

    # 故事大纲
    p = cache_dir / "story_outline.md"
    if p.exists():
        outputs["story_outline"] = {
            "label": "故事大纲",
            "path": str(p),
            "content": p.read_text(encoding="utf-8"),
        }

    # 集纲
    p = cache_dir / "story_skeleton.md"
    if p.exists():
        outputs["skeleton"] = {
            "label": "集纲（逐集分场）",
            "path": str(p),
            "content": p.read_text(encoding="utf-8"),
        }

    # 事件表
    p = cache_dir / "events.json"
    if p.exists():
        events = json.loads(p.read_text(encoding="utf-8"))
        md_lines = ["# 事件表\n"]
        for ev in events:
            ch = ev.get("chapter", ev.get("chapter_index", ev.get("id", "?")))
            summary = format_event_for_markdown(ev.get("summary", ev.get("event", "")))
            ch_title = str(ch)
            if ch_title.startswith("第") and ch_title.endswith("章"):
                heading = ch_title
            else:
                heading = f"第{ch_title}章"
            md_lines.append(f"## {heading}\n\n{summary}\n")
        outputs["events"] = {
            "label": "事件表",
            "path": str(p),
            "content": "\n".join(md_lines),
        }

    # 审核报告
    reviews_dir = output_dir / "reviews"
    if reviews_dir.exists():
        review_files = {}
        for rp in reviews_dir.glob("*_review.md"):
            phase = rp.stem.replace("_review", "")
            review_files[phase] = {
                "label": f"审核报告-{phase}",
                "path": str(rp),
                "content": rp.read_text(encoding="utf-8"),
            }
        if review_files:
            outputs["reviews"] = review_files

    # 剧本
    scripts_dir = output_dir / "scripts"
    if scripts_dir.exists():
        script_files = {}
        try:
            from story_structure_guardrails import validate_script_scene_keys
        except Exception:
            validate_script_scene_keys = None
        for sp in sorted(scripts_dir.glob("ep_*.txt")):
            num = int(sp.stem.split("_")[1])
            content = sp.read_text(encoding="utf-8")
            if validate_script_scene_keys:
                scene_report = validate_script_scene_keys(content)
                if scene_report.get("ok") is False:
                    details = "; ".join(
                        f"{i.get('previous_scene')}→{i.get('current_scene')} scene_key={i.get('scene_key')}"
                        for i in scene_report.get("issues", [])
                    )
                    raise ValueError(f"剧本分场 scene key 门禁未通过，禁止同步飞书：{sp}: {details}")
            script_files[f"ep{num:02d}"] = {
                "label": f"第{num}集",
                "path": str(sp),
                "content": content,
            }
        if script_files:
            outputs["scripts"] = script_files
            if include_script_full:
                script_full = build_script_full_output(config, script_files)
                if script_full:
                    outputs["script_full"] = script_full

    return outputs


def build_project_hub_md(config: dict, outputs: dict) -> str:
    """生成项目总览文档的内容。"""
    project = config.get("project", {})
    drama_name = config.get("drama_name", "")
    novel_name = config.get("novel_name", "")
    title = drama_name or novel_name or "未命名项目"

    lines = [
        f"# {title} - 项目信息",
        "",
        "> 本文档是项目 dashboard，只放元信息、rules、阶段链接索引、进度和版本记录；禁止放原文正文。",
        "",
        f"- 原小说：{novel_name or '未指定'}（仅记录名称/来源标识，不嵌入正文）",
        f"- 改编方向：{project.get('style', '未指定')}",
        f"- 体量：{project.get('episodes', '?')}集 × {project.get('episode_duration', '?')}分钟",
        f"- 平台：{project.get('platform', '未指定')}",
        f"- 付费点：{project.get('paywall', '未指定')}",
        "",
        "## 项目 Rules",
        "",
        load_project_rules(config),
        "",
        "## 阶段文档索引",
        "",
    ]

    phase_order = ["adaptation", "story_outline", "skeleton", "events", "reviews", "scripts"]
    script_batch_size = int(config.get("script_batch_size", 5))
    for phase in phase_order:
        data = outputs.get(phase)
        if not data:
            continue
        if phase == "reviews":
            lines.append("### 审核报告")
            for key, item in data.items():
                lines.append(f"- 📝 {item['label']} ({Path(item['path']).stat().st_size / 1024:.1f}KB)")
        elif phase == "scripts":
            lines.append("### 剧本批次")
            for key, item in sorted(group_scripts_by_batch(data, script_batch_size).items()):
                lines.append(f"- 🎬 {item['label']} ({len(item['content']) / 1024:.1f}KB)")
        else:
            fsize = Path(data["path"]).stat().st_size / 1024
            lines.append(f"- 📄 {data['label']} ({fsize:.1f}KB)")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*此文档由方寸短剧引擎自动维护。*")

    return "\n".join(lines)


def generate_manifest(config_path: str, sync_phase: str = "all", doc_version: str = None, include_script_full: bool = False, generate_script_summary: bool = False) -> dict:
    """
    生成飞书同步 manifest。
    
    返回结构化的操作清单，供 OpenClaw agent 读取后调用 feishu_doc / feishu_wiki 工具执行。
    """
    resolved_config_path = Path(config_path).resolve()
    config = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    config["_config_path"] = str(resolved_config_path)
    drama_name = config.get("drama_name", "")
    novel_name = config.get("novel_name", "")
    title = drama_name or novel_name or "未命名项目"

    if include_script_full:
        allowed, reason = _final_batch_user_confirmed(config)
        if not allowed:
            return {"status": "blocked", "reason": f"最终批次未获用户确认，禁止登记完结：{reason}"}

    outputs = get_project_outputs(config, include_script_full=include_script_full)
    
    if not outputs:
        return {
            "status": "skip",
            "reason": "未找到任何产出物。请先运行 pipeline 生成内容。",
        }

    # 构建 manifest。version=None 表示执行器从 feishu_sync_state.json 自动计算 V1/V2/V3。
    version = doc_version or config.get("doc_version") or None
    display_version = version or "AUTO"
    script_batch_size = int(config.get("script_batch_size", 5))

    manifest = {
        "status": "ready",
        "project_title": title,
        "version": version,
        "display_version": display_version,
        "config_path": str(resolved_config_path),
        "doc_policy": "阶段拆文档；项目信息不放原文；剧本默认5集一档；批次生成不自动生成剧本汇总；只有用户明确要求汇总时才生成；默认新建版本，旧版本永久保留；显式覆盖才 update 当前版本",
        "generate_script_summary": bool(generate_script_summary),
        "steps": [],
    }

    # Step 1: 创建新版本/显式覆盖项目总览文档
    hub_content = build_project_hub_md(config, outputs)
    manifest["steps"].append({
        "action": "feishu_doc",
        "desc": f"创建新版本/显式覆盖项目信息文档（dashboard，不放原文正文）",
        "task": "项目信息",
        "title": doc_title(title, "项目信息", display_version),
        "doc_kind": "project_info",
        "update_policy": "create_new_version_by_default",
        "content": hub_content,
        "content_kb": len(hub_content) / 1024,
    })

    # Step 2-N: 按阶段创建子文档
    phase_keys = ["adaptation", "story_outline", "skeleton", "events"]
    for phase in phase_keys:
        data = outputs.get(phase)
        if not data:
            continue
        manifest["steps"].append({
            "action": "feishu_doc",
            "desc": f"同步 {data['label']}",
            "task": data['label'].replace('（逐集分场）', ''),
            "title": doc_title(title, data['label'].replace('（逐集分场）', ''), display_version),
            "doc_kind": "phase",
            "update_policy": "create_new_version_by_default",
            "content": data["content"],
            "content_kb": len(data["content"]) / 1024,
            "phase": phase,
        })

    # 审核报告
    reviews = outputs.get("reviews")
    if reviews:
        for key, item in reviews.items():
            manifest["steps"].append({
                "action": "feishu_doc",
                "desc": f"同步审核报告: {key}",
                "task": f"审核报告-{key}",
                "title": doc_title(title, f"审核报告-{key}", display_version),
                "doc_kind": "review",
                "update_policy": "create_new_version_by_default",
                "content": item["content"],
                "content_kb": len(item["content"]) / 1024,
                "phase": "review",
            })

    # 剧本：按批次文档同步，默认5集一档。修改单集时只更新所在批次文档/块。
    scripts = outputs.get("scripts")
    if scripts:
        for key, item in sorted(group_scripts_by_batch(scripts, script_batch_size).items()):
            manifest["steps"].append({
                "action": "feishu_doc",
                "desc": f"同步剧本批次: {key}",
                "task": item["label"],
                "title": doc_title(title, item["label"], display_version),
                "content": item["content"],
                "content_kb": len(item["content"]) / 1024,
                "phase": "script",
                "doc_kind": "script_batch",
                "start_episode": item["start"],
                "end_episode": item["end"],
                "update_policy": "create_new_version_by_default; explicit overwrite-current only when user asks to patch current doc",
            })

    # 完整剧本：仅当用户明确确认最后一个剧本批次后，由 --finalize-delivery 显式开启。
    # 集数齐全不能自动登记完结；同一批次可能会因用户不满意产生多个版本。
    script_full = outputs.get("script_full")
    if script_full:
        manifest["steps"].append({
            "action": "feishu_doc",
            "desc": "同步完整剧本最终交付: script_full",
            "task": script_full["label"],
            "title": doc_title(title, script_full["label"], display_version),
            "content": script_full["content"],
            "content_kb": len(script_full["content"]) / 1024,
            "phase": "script_full",
            "doc_kind": "script_full",
            "start_episode": script_full["start"],
            "end_episode": script_full["end"],
            "local_path": script_full["path"],
            "final_delivery": True,
            "update_policy": "final_full_script_delivery; create_new_version_by_default",
        })

    # 可选阶段过滤：不改变 step 结构，只减少 steps。
    if sync_phase and sync_phase != "all":
        aliases = {
            "adaptation_strategy": "adaptation",
            "outline": "story_outline",
            "story": "story_outline",
            "jigang": "skeleton",
            "review": "review",
            "script": "script",
            "scripts": "script",
            "project_info": "project_info",
        }
        wanted = aliases.get(sync_phase, sync_phase)
        manifest["steps"] = [
            s for s in manifest["steps"]
            if s.get("phase") == wanted
            or s.get("doc_kind") == wanted
            or (include_script_full and wanted == "script" and s.get("doc_kind") == "script_full")
        ]

    # Stats
    total_kb = sum(s.get("content_kb", 0) for s in manifest["steps"])
    manifest["summary"] = f"共 {len(manifest['steps'])} 个文档，合计 {total_kb:.0f}KB"

    return manifest


def main():
    import argparse
    parser = argparse.ArgumentParser(description="飞书项目资产树管理")
    parser.add_argument("--config", required=True, help="项目配置文件路径")
    parser.add_argument("--phase", default="all", help="仅同步指定阶段")
    parser.add_argument("--json", action="store_true", help="输出 JSON manifest")
    parser.add_argument("--dry-run", action="store_true", help="仅展示待同步文件，不执行")
    parser.add_argument("--execute", action="store_true", help="生成 manifest 后直接执行飞书 docx 创建新版本/显式覆盖，并写入 feishu_sync_state.json")
    parser.add_argument("--doc-version", help="兼容旧参数：等同 --version-label")
    parser.add_argument("--version-label", help="指定版本号，如 V2 或 v20260716-r2；不传则自动递增")
    parser.add_argument("--new-version", action="store_true", default=True, help="创建新版本（默认行为）")
    parser.add_argument("--overwrite-current", action="store_true", help="危险操作：显式覆盖当前推荐版本")
    parser.add_argument("--major-revision", action="store_true", help="兼容旧参数；不再归档旧文档，默认仍创建新版本")
    parser.add_argument("--account", default=os.environ.get("FANGCUN_FEISHU_ACCOUNT") or os.environ.get("OPENCLAW_AGENT_ID") or "default", help="OpenClaw 飞书账号配置名；默认取 FANGCUN_FEISHU_ACCOUNT / OPENCLAW_AGENT_ID / default")
    parser.add_argument("--grant-member", help="可选：同步后给指定飞书成员授权（如 open_id）")
    parser.add_argument("--grant-member-type", default="openid", choices=["openid", "userid", "unionid", "email", "openchat", "opendepartmentid"], help="授权成员 ID 类型")
    parser.add_argument("--grant-perm", default="full_access", choices=["view", "edit", "full_access"], help="授权权限")
    parser.add_argument("--finalize-delivery", action="store_true", help="仅在用户明确确认最终剧本批次后使用：生成并登记 script_full/final_delivery 完结交付")
    parser.add_argument("--generate-script-summary", action="store_true", help="仅在用户明确要求“汇总/生成剧本汇总”时使用：生成剧本汇总文档；普通批次同步不得使用")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["_config_path"] = str(config_path)
    try:
        assert_config_binding(config, config_path=config_path, account=args.account)
    except ProjectOwnershipError as exc:
        print(str(exc))
        return
    if args.finalize_delivery:
        allowed, reason = _final_batch_user_confirmed(config)
        if not allowed:
            print(f"[BLOCK] 最终批次未获用户确认，禁止登记完结：{reason}")
            return
    outputs = get_project_outputs(config, include_script_full=args.finalize_delivery)

    if not outputs:
        if args.execute:
            from feishu_project_executor import FeishuProjectExecutor, ensure_project_workspace, load_state, save_state, format_workspace_links_for_chat

            manifest = {"status": "ready", "project_title": config.get("drama_name") or config.get("novel_name") or "未命名项目", "steps": []}
            state = load_state(config)
            client = FeishuProjectExecutor(account=args.account)
            workspace = ensure_project_workspace(client, config, manifest, state)
            save_state(config, state)
            print("[INIT] 未找到阶段产出物；已先完成项目初始化（项目文件夹 + 表1 + 表2），未进入改编流程。")
            links = format_workspace_links_for_chat(workspace)
            if links:
                print(links)
            return
        print("[SKIP] 未找到任何产出物。正式流程会先执行项目初始化；如只需初始化，请加 --execute。")
        return

    print(f"\n📂 项目：{config.get('drama_name') or config.get('novel_name')}")
    print(f"   产出物：{len(outputs)} 个阶段\n")

    for phase, data in outputs.items():
        if phase in ("reviews", "scripts"):
            print(f"  📁 {phase}: {len(data)} 个文件")
            for key, item in data.items():
                print(f"     {item['label']} ({len(item['content'])} chars)")
        else:
            print(f"  📄 {data['label']} ({len(data['content'])} chars)")

    doc_version = args.version_label or args.doc_version
    manifest = generate_manifest(args.config, args.phase, doc_version=doc_version, include_script_full=args.finalize_delivery, generate_script_summary=args.generate_script_summary)

    if args.json:
        print(f"\n{json.dumps(manifest, ensure_ascii=False, indent=2)}")

    if args.execute:
        from feishu_project_executor import execute_manifest

        print(f"\n🚀 开始执行飞书同步：{manifest.get('summary', '')}")
        result = execute_manifest(
            manifest,
            config,
            dry_run=args.dry_run,
            account=args.account,
            major_revision=args.major_revision,
            new_version=args.new_version,
            overwrite_current=args.overwrite_current,
            version_label=doc_version,
            grant_member=args.grant_member,
            grant_member_type=args.grant_member_type,
            grant_perm=args.grant_perm,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("links"):
            print("\n📎 飞书文档链接：")
            for item in result["links"]:
                url = item.get("url") or "(dry-run: 尚未创建)"
                print(f"- [{item.get('operation')}] {item.get('title')}: {url}")
        return

    if args.dry_run:
        print("\n💡 [DRY RUN] 以上为待同步文件预览。正式同步请加 --execute 并去掉 --dry-run。")
        print("   默认模式只生成 manifest，不再假设 agent 手动调工具。")
    else:
        print(f"\n📋 Manifest 已生成，{manifest['summary']}")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
