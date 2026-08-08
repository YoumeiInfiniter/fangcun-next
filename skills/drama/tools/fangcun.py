#!/usr/bin/env python3
"""
方寸短剧引擎 · 一键启动器

用法：
  python fangcun.py init "项目名"          # 初始化新项目
  python fangcun.py run 项目名             # 跑全流程
  python fangcun.py run 项目名 --phase script --start 1 --end 10  # 只跑剧本
  python fangcun.py sync 项目名            # 同步到飞书
  python fangcun.py status 项目名          # 查看进度
  python fangcun.py report 项目名          # 生成质量报告

首次使用：
  python fangcun.py setup                  # 检查依赖和环境
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from project_ownership_guard import assert_config_binding, current_bot_id, current_feishu_account, ProjectOwnershipError
except Exception:
    assert_config_binding = None
    current_bot_id = lambda: os.environ.get("OPENCLAW_AGENT_ID", "")
    current_feishu_account = lambda default="": os.environ.get("FANGCUN_FEISHU_ACCOUNT") or os.environ.get("OPENCLAW_AGENT_ID") or default
    ProjectOwnershipError = RuntimeError

try:
    from runtime_paths import print_runtime_paths, resolve_runtime_paths
except Exception:
    print_runtime_paths = None
    resolve_runtime_paths = None

RUNTIME_PATHS = resolve_runtime_paths(__file__) if resolve_runtime_paths else None
THIS_DIR = (RUNTIME_PATHS.tools_dir if RUNTIME_PATHS else Path(__file__).resolve().parent)  # .../skills/fangcun/skills/drama/tools
DRAMA_DIR = (RUNTIME_PATHS.drama_dir if RUNTIME_PATHS else THIS_DIR.parent)                  # .../skills/fangcun/skills/drama
SKILL_DIR = (RUNTIME_PATHS.skill_dir if RUNTIME_PATHS else DRAMA_DIR.parents[1])
WORKSPACE_DIR = (RUNTIME_PATHS.workspace_dir if RUNTIME_PATHS else Path.cwd().resolve())
PROMPTS_DIR = DRAMA_DIR / "prompts"
PIPELINE = THIS_DIR / "pipeline.py"
TOOLS_DIR = THIS_DIR
PROJECTS_DIR = (RUNTIME_PATHS.projects_dir if RUNTIME_PATHS else Path(os.environ.get("FANGCUN_PROJECTS", WORKSPACE_DIR / "projects"))).resolve()

# ─── 项目绑定/复用 ───────────────────────────────────────────────────────────


def normalize_chat_id(chat_id: str) -> str:
    """Normalize Feishu chat ids so `chat:oc_xxx` and `oc_xxx` compare equal."""
    return str(chat_id or "").strip().replace("chat:", "", 1)


def current_chat_id_from_env() -> str:
    """Best-effort current Feishu group chat id from OpenClaw/Fangcun env."""
    return (
        os.environ.get("FANGCUN_FEISHU_CHAT_ID")
        or os.environ.get("OPENCLAW_CHAT_ID")
        or os.environ.get("FEISHU_CHAT_ID")
        or ""
    )


def iter_project_config_paths(projects_dir: Path):
    """Yield official Fangcun project configs only.

    The only supported project config path is:
    projects/<project_slug>/drama/config.json
    """
    yield from projects_dir.glob("*/drama/config.json")


def iter_legacy_config_paths(projects_dir: Path):
    """Yield legacy standalone CLI configs for warning/migration only."""
    yield from projects_dir.glob("*/config.json")


def _config_matches_chat_id(config: dict, target_chat_id: str) -> bool:
    candidates = [
        config.get("chat_id"),
        config.get("feishu_chat_id"),
        config.get("group_chat_id"),
    ]
    return any(normalize_chat_id(item) == target_chat_id for item in candidates if item)


def find_existing_project_by_chat_id(projects_dir: Path, chat_id: str):
    """Find an official project bound to the same Feishu chat_id.

    Only projects/<project_slug>/drama/config.json is a formal Fangcun project
    entry. Legacy projects/<project_slug>/config.json is deliberately excluded
    to avoid mixing old CLI output dirs with project-mode output dirs.
    """
    target = normalize_chat_id(chat_id)
    if not target or not projects_dir.exists():
        return None, None
    for config_path in iter_project_config_paths(projects_dir):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _config_matches_chat_id(config, target):
            return config_path, config
    return None, None


def find_legacy_project_by_chat_id(projects_dir: Path, chat_id: str):
    """Detect legacy standalone CLI project configs; never use them as output roots."""
    target = normalize_chat_id(chat_id)
    if not target or not projects_dir.exists():
        return None, None
    for config_path in iter_legacy_config_paths(projects_dir):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _config_matches_chat_id(config, target):
            return config_path, config
    return None, None


def official_config_path(project_name: str) -> Path:
    return PROJECTS_DIR / project_name / "drama" / "config.json"


def legacy_config_path(project_name: str) -> Path:
    return PROJECTS_DIR / project_name / "config.json"


def load_official_project_config(project_name: str):
    config_path = official_config_path(project_name)
    if config_path.exists():
        try:
            return config_path, json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return config_path, {}
    legacy_path = legacy_config_path(project_name)
    if legacy_path.exists():
        print(f"❌ 检测到旧 Fangcun CLI 项目结构: {legacy_path}")
        print(f"   请迁移到正式路径后再继续: {config_path}")
        return None, None
    print(f"❌ 项目不存在: {project_name}")
    print(f"   正式配置路径应为: {config_path}")
    return None, None


def update_group_name_snapshot(config: dict, current_group_name: str) -> bool:
    """Record group rename metadata without changing locked project routing.

    `feishu_group_name` is treated as the first-init folder-name snapshot and is
    not overwritten by later group renames. New names only update
    `current_group_name` and `group_name_aliases`.
    """
    changed = False
    current = (current_group_name or "").strip()
    initial = (
        config.get("feishu_group_name")
        or config.get("initial_group_name")
        or config.get("group_name")
        or config.get("chat_name")
        or config.get("drama_name")
        or current
    )
    if initial and not config.get("feishu_group_name"):
        config["feishu_group_name"] = initial
        changed = True
    aliases = config.get("group_name_aliases")
    if not isinstance(aliases, list):
        aliases = []
        changed = True
    for name in [initial, config.get("current_group_name"), current]:
        if name and name not in aliases:
            aliases.append(name)
            changed = True
    if aliases != config.get("group_name_aliases"):
        config["group_name_aliases"] = aliases
        changed = True
    if current and config.get("current_group_name") != current:
        config["current_group_name"] = current
        changed = True
    return changed


# ─── 项目模板 ───────────────────────────────────────────────────────────────

PROJECT_TEMPLATE = {
    "novel_name": "",
    "novel_source": "",
    "drama_name": "",
    "output_dir": "",
    "project": {
        "episodes": 80,
        "episode_duration": 2,
        "chapter_range": [1, 100],
        "platform": "竖屏9:16",
        "style": "女频·虐恋·身份反转"
    },
    "adaptation": {
        "gender_swap": [],
        "identity_change": [],
        "world_building": "",
        "deleted_characters": [],
        "added_elements": []
    },
    "paywall": {
        "free_episodes": 5,
        "card_points": [],
        "card_point_logic": "由编剧指定卡点位置"
    }
}


def setup():
    """检查环境依赖。"""
    print("🔍 方寸短剧引擎 · 环境检查\n")
    ok = True

    # Python
    v = sys.version_info
    print(f"  Python: {v.major}.{v.minor}.{v.micro} {'✅' if v >= (3, 10) else '❌ 需要 3.10+'}")
    ok &= v >= (3, 10)

    # Pipeline
    if PIPELINE.exists():
        print(f"  Pipeline: {PIPELINE} ✅")
    else:
        print(f"  Pipeline: ❌ 找不到 {PIPELINE}")
        ok = False

    # Prompts
    prompts = ["script.md", "script_local.md", "skeleton.md", "story_outline.md", "adaptation.md", "writing-methods.md"]
    for p in prompts:
        fp = PROMPTS_DIR / p
        print(f"  Prompt {p}: {'✅' if fp.exists() else '❌ 缺失'}")
        ok &= fp.exists()

    # API (from env or OpenClaw config)
    api_key = os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    print(f"  API Key: {'✅ 已找到' if api_key else '⚠️ 未设置（OpenClaw 环境下自动发现）'}")

    # Feishu (available when running under OpenClaw)
    print(f"\n  📝 飞书同步：{'✅ OpenClaw 环境下可用' if os.environ.get('OPENCLAW_CONFIG') else '⚠️ 需要 OpenClaw 环境'}")
    if print_runtime_paths and RUNTIME_PATHS:
        print_runtime_paths(RUNTIME_PATHS)
    else:
        print(f"  📂 项目目录：{PROJECTS_DIR}")
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    if ok:
        print("\n✅ 环境就绪，可以开始使用")
    else:
        print("\n❌ 请修复上述问题后重试")
    return ok


def init_project(name: str, **kwargs):
    """初始化新项目。

    Minimal anti-rename guard: when a current Feishu chat_id is available, reuse
    the existing project config bound to that chat_id instead of creating a new
    folder from the latest group name.
    """
    chat_id = kwargs.get("chat_id") or current_chat_id_from_env()
    group_name = kwargs.get("group_name") or name
    existing_config_path, existing_config = find_existing_project_by_chat_id(PROJECTS_DIR, chat_id)
    if existing_config_path and existing_config is not None:
        if update_group_name_snapshot(existing_config, group_name):
            existing_config_path.write_text(json.dumps(existing_config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"🔒 已按 chat_id 复用现有项目，不创建新目录: {normalize_chat_id(chat_id)}")
        print(f"   配置文件: {existing_config_path}")
        print(f"   output_dir: {existing_config.get('output_dir') or '(未设置)'}")
        return str(existing_config_path)

    legacy_config, _legacy = find_legacy_project_by_chat_id(PROJECTS_DIR, chat_id)
    if legacy_config:
        print(f"❌ 检测到同 chat_id 的旧 Fangcun CLI 项目结构: {legacy_config}")
        print("   旧结构只作为 legacy 检测，不作为正式项目入口。")
        print(f"   请迁移到: {legacy_config.parent / 'drama' / 'config.json'}")
        return None

    slug = name.strip().replace(" ", "_").replace("·", "_")
    project_dir = PROJECTS_DIR / slug
    drama_dir = project_dir / "drama"
    output_dir = drama_dir / "output"
    drama_dir.mkdir(parents=True, exist_ok=True)

    config_path = drama_dir / "config.json"

    if config_path.exists():
        print(f"⚠️  项目已存在: {project_dir}")
        print(f"   配置文件: {config_path}")
        return str(config_path)

    config = json.loads(json.dumps(PROJECT_TEMPLATE))
    config["novel_name"] = kwargs.get("novel", "")
    config["drama_name"] = name
    config["output_dir"] = str(output_dir.resolve())
    config["project_slug"] = slug
    config["project_workspace"] = str(project_dir.resolve())
    config["runtime_workspace"] = str(WORKSPACE_DIR)
    config["runtime_skill_dir"] = str(SKILL_DIR)
    config["runtime_projects_dir"] = str(PROJECTS_DIR)
    config["bot_id"] = current_bot_id()
    config["feishu_account"] = current_feishu_account(current_bot_id())
    if chat_id:
        config["chat_id"] = normalize_chat_id(chat_id)
    config["feishu_group_name"] = group_name
    config["current_group_name"] = group_name
    config["group_name_aliases"] = [group_name]
    config["project"]["episodes"] = kwargs.get("episodes", 80)
    config["project"]["episode_duration"] = kwargs.get("duration", 2)
    config["project"]["platform"] = kwargs.get("platform", "竖屏9:16")
    config["project"]["style"] = kwargs.get("style", "女频·虐恋·身份反转")
    config["project"]["chapter_range"] = kwargs.get("chapters", [1, 100])
    config["adaptation"]["gender_swap"] = kwargs.get("gender_swap", [])
    config["adaptation"]["identity_change"] = kwargs.get("identity_change", [])
    config["adaptation"]["world_building"] = kwargs.get("world_building", "")
    config["paywall"]["free_episodes"] = kwargs.get("free_episodes", 5)
    config["paywall"]["card_points"] = kwargs.get("card_points", [])

    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"✅ 项目已创建: {name}")
    print(f"   目录: {project_dir}")
    print(f"   配置: {config_path}")
    print(f"\n💡 下一步:")
    print(f"   1. 编辑 {config_path} 填入小说来源和改编细节")
    print(f"   2. python fangcun.py run {slug}")
    return str(config_path)


def run_pipeline(project_name: str, **kwargs):
    """运行 pipeline。"""
    config_path, _config = load_official_project_config(project_name)
    if not config_path:
        print(f"   请先运行: python fangcun.py init {project_name}")
        return False
    if assert_config_binding:
        try:
            assert_config_binding(_config, config_path=config_path)
        except ProjectOwnershipError as exc:
            print(str(exc))
            return False

    phase = kwargs.get("phase", "all")
    start = kwargs.get("start")
    end = kwargs.get("end")
    batch_size = kwargs.get("batch_size", 3)
    skip_review = kwargs.get("skip_review", False)
    workers = kwargs.get("workers", 5)

    cmd = [
        "python3", str(PIPELINE),
        "--config", str(config_path),
        "--phase", phase,
    ]
    if start and end:
        cmd += ["--start", str(start), "--end", str(end)]
    if batch_size:
        cmd += ["--batch-size", str(batch_size)]
    if skip_review:
        cmd.append("--skip-draft-review")
    if workers:
        cmd += ["--workers", str(workers)]

    print(f"🚀 启动 Pipeline: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(TOOLS_DIR))
    return result.returncode == 0


def sync_feishu(project_name: str, **kwargs):
    """同步项目到飞书文档。"""
    config_path, _config = load_official_project_config(project_name)
    if not config_path:
        return None
    if assert_config_binding:
        try:
            assert_config_binding(_config, config_path=config_path)
        except ProjectOwnershipError as exc:
            print(str(exc))
            return None

    # Generate manifest
    sync_tool = TOOLS_DIR / "build_feishu_project.py"
    if not sync_tool.exists():
        print(f"❌ 找不到 build_feishu_project.py")
        return None

    cmd = [
        "python3", str(sync_tool),
        "--config", str(config_path),
        "--json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(TOOLS_DIR))
    if result.returncode != 0:
        print(f"❌ Manifest 生成失败: {result.stderr}")
        return None

    try:
        manifest = json.loads(result.stdout.splitlines()[-1])
    except Exception:
        # JSON might be mixed with other output, find the JSON block
        for line in result.stdout.splitlines():
            try:
                manifest = json.loads(line)
                break
            except Exception:
                continue
        else:
            print("❌ 无法解析 manifest")
            return None

    print(f"\n📋 飞书同步 Manifest")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\n💡 在 OpenClaw 环境下，Agent 会自动执行 feishu_doc 调用。")
    print(f"   非 OpenClaw 环境请手动上传上述文件。")
    return manifest


def show_status(project_name: str):
    """查看项目进度。"""
    config_path, config = load_official_project_config(project_name)
    if not config_path:
        return
    output_dir = Path(config.get("output_dir") or (config_path.parent / "output"))
    state_path = output_dir / "state.json"

    if not state_path.exists():
        print(f"📊 {project_name}: 尚未运行")
        return

    state = json.loads(state_path.read_text(encoding="utf-8"))
    phases = state.get("phases", {})

    print(f"\n📊 {project_name} · 进度\n")
    emoji = {"done": "✅", "running": "🔄", "failed": "❌", "pending": "⏳"}

    phase_order = ["event", "adaptation", "story_outline", "skeleton", "review", "script"]
    for p in phase_order:
        info = phases.get(p, {})
        status = info.get("status", "pending")
        e = emoji.get(status, "❓")
        started = info.get("started", "")[:16]
        finished = info.get("finished", "")[:16]

        extra = ""
        if status == "done" and finished:
            extra = f" ({finished})"
        elif status == "failed":
            extra = f" — {info.get('error', '?')}"

        print(f"  {e} {p:20s}{extra}")

    # Script batches
    batches = state.get("script_batches", {})
    confirmed = batches.get("confirmed", [])
    if confirmed:
        print(f"\n  📝 剧本批次: {len(confirmed)} 批已完成")
        for b in confirmed:
            eps = b.get("episodes", [])
            print(f"     {b['batch_id']}: EP{min(eps)}-{max(eps)}")


def generate_report(project_name: str):
    """生成质量报告。"""
    config_path, config = load_official_project_config(project_name)
    if not config_path:
        return
    project_dir = config_path.parent
    output_dir = Path(config.get("output_dir") or (project_dir / "output"))
    scripts_dir = output_dir / "scripts"
    cache_dir = project_dir / "_cache"

    if not scripts_dir.exists() or not list(scripts_dir.glob("ep_*.txt")):
        print(f"❌ 未找到剧本文件")
        return

    print(f"\n📈 {project_name} · 质量报告\n")
    print(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Episode stats
    episodes = sorted(scripts_dir.glob("ep_*.txt"))
    total_chars = 0
    ep_stats = []

    for ep_path in episodes:
        content = ep_path.read_text(encoding="utf-8")
        pure_chars = len(content)  # rough count
        total_chars += pure_chars

        # Count hooks/emotional markers
        has_tension = any(kw in content for kw in ["错过", "试探", "秘密", "选择", "站队", "骗", "瞒", "信任"])
        has_world_detail = any(kw in content for kw in ["陛下", "朕", "皇", "士族", "朝堂", "后宫", "侍君", "宗法"])
        has_cliffhanger = content.rstrip().endswith("---") or "下集" in content[-200:] or "？" in content[-100:]

        # Count △ markers (stage directions) and dialogues
        delta_count = content.count("△")
        dialogue_lines = len([l for l in content.split("\n") if "：" in l and not l.startswith("#") and not l.startswith("△") and not l.startswith("-")])

        ep_stats.append({
            "num": int(ep_path.stem.split("_")[1]),
            "chars": pure_chars,
            "tension": has_tension,
            "world": has_world_detail,
            "hook": has_cliffhanger,
            "deltas": delta_count,
            "dialogues": dialogue_lines,
        })

    print(f"\n  一、整体")
    print(f"     集数: {len(episodes)}")
    print(f"     总字数: {total_chars} (平均 {total_chars // len(episodes)}/集)")

    # 字数分布
    char_min = min(s["chars"] for s in ep_stats)
    char_max = max(s["chars"] for s in ep_stats)
    print(f"     字数: {char_min}-{char_max}/集")

    # 质量指标
    tension_eps = [s["num"] for s in ep_stats if s["tension"]]
    world_eps = [s["num"] for s in ep_stats if s["world"]]
    hook_eps = [s["num"] for s in ep_stats if s["hook"]]
    print(f"\n  二、质量指标")
    print(f"     感情张力覆盖: {len(tension_eps)}/{len(episodes)} 集")
    if tension_eps:
        print(f"     覆盖集: EP{','.join(map(str, tension_eps))}")
    print(f"     世界观细节: {len(world_eps)}/{len(episodes)} 集")
    if world_eps:
        print(f"     覆盖集: EP{','.join(map(str, world_eps))}")
    print(f"     集末钩子: {len(hook_eps)}/{len(episodes)} 集")

    # 付费点检查
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        total_eps = config.get("project", {}).get("episodes", 80)
        paywall = config.get("paywall", {})
        card_points = paywall.get("card_points", [])
        if card_points:
            print(f"\n  三、付费点")
            print(f"     设计师卡点: EP{','.join(map(str, card_points))}")
            print(f"     总集数: {total_eps}")
            for cp in card_points:
                if cp > total_eps:
                    print(f"     ⚠️ EP{cp} 超出总集数 {total_eps}")
            if total_eps <= 10:
                print(f"     📌 ≤10集 → 两卡点模式")

    # 输出详细表格
    print(f"\n  四、逐集详情")
    header = f"     {'集':>4s}  {'字数':>5s}  {'△':>3s}  {'对白':>4s}  {'感情张力':>6s}  {'世界观':>5s}  {'钩子':>4s}"
    print(header)
    print(f"     {'-' * len(header)}")
    for s in ep_stats:
        print(f"     EP{s['num']:02d}  {s['chars']:>5d}  {s['deltas']:>3d}  {s['dialogues']:>4d}  "
              f"{'✅' if s['tension'] else '—':>6s}  {'✅' if s['world'] else '—':>5s}  {'✅' if s['hook'] else '—':>4s}")


def main():
    parser = argparse.ArgumentParser(
        description="方寸短剧引擎 · 一键启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  fangcun.py setup                          # 环境检查
  fangcun.py init "女帝·神医归来"          # 初始化项目
  fangcun.py run 女帝_神医归来              # 跑全流程
  fangcun.py run 女帝_神医归来 --start 1 --end 10 --skip-review  # 只跑剧本
  fangcun.py status 女帝_神医归来           # 查看进度
  fangcun.py report 女帝_神医归来           # 质量报告
  fangcun.py sync 女帝_神医归来             # 飞书同步
        """
    )

    sub = parser.add_subparsers(dest="command", help="命令")

    # setup
    sub.add_parser("setup", help="环境检查")

    # init
    p_init = sub.add_parser("init", help="初始化新项目")
    p_init.add_argument("name", help="项目名称")
    p_init.add_argument("--novel", default="", help="原著小说名")
    p_init.add_argument("--episodes", type=int, default=80, help="总集数")
    p_init.add_argument("--duration", type=int, default=2, help="单集时长(分钟)")
    p_init.add_argument("--platform", default="竖屏9:16")
    p_init.add_argument("--style", default="女频·虐恋·身份反转")
    p_init.add_argument("--chapters", type=int, nargs=2, default=[1, 100], metavar=("START", "END"), help="改编章节范围")
    p_init.add_argument("--gender-swap", nargs="*", default=[], help="性别翻转角色")
    p_init.add_argument("--identity-change", nargs="*", default=[], help="身份变更角色")
    p_init.add_argument("--world-building", default="", help="世界观重构描述")
    p_init.add_argument("--free-episodes", type=int, default=5)
    p_init.add_argument("--card-points", type=int, nargs="*", default=[])
    p_init.add_argument("--chat-id", default="", help="飞书群 chat_id；同 chat_id 初始化会复用旧项目目录")
    p_init.add_argument("--group-name", default="", help="当前飞书群名；仅记录展示/alias，不覆盖首次 feishu_group_name")

    # run
    p_run = sub.add_parser("run", help="运行 pipeline")
    p_run.add_argument("project", help="项目名(slug)")
    p_run.add_argument("--phase", default="all", help="阶段")
    p_run.add_argument("--start", type=int, help="起始集")
    p_run.add_argument("--end", type=int, help="结束集")
    p_run.add_argument("--batch-size", type=int, default=3)
    p_run.add_argument("--skip-review", action="store_true")
    p_run.add_argument("--workers", type=int, default=5)

    # status
    p_status = sub.add_parser("status", help="查看进度")
    p_status.add_argument("project", help="项目名(slug)")

    # report
    p_report = sub.add_parser("report", help="质量报告")
    p_report.add_argument("project", help="项目名(slug)")

    # sync
    p_sync = sub.add_parser("sync", help="飞书同步")
    p_sync.add_argument("project", help="项目名(slug)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "setup":
        setup()
    elif args.command == "init":
        init_project(args.name,
                     novel=getattr(args, "novel", ""),
                     episodes=args.episodes,
                     duration=args.duration,
                     platform=args.platform,
                     style=args.style,
                     chapters=args.chapters,
                     gender_swap=args.gender_swap,
                     identity_change=args.identity_change,
                     world_building=args.world_building,
                     free_episodes=args.free_episodes,
                     card_points=args.card_points,
                     chat_id=args.chat_id,
                     group_name=args.group_name or args.name)
    elif args.command == "run":
        run_pipeline(args.project,
                     phase=args.phase,
                     start=args.start,
                     end=args.end,
                     batch_size=args.batch_size,
                     skip_review=args.skip_review,
                     workers=args.workers)
    elif args.command == "status":
        show_status(args.project)
    elif args.command == "report":
        generate_report(args.project)
    elif args.command == "sync":
        sync_feishu(args.project)


if __name__ == "__main__":
    main()
