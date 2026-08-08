"""drama_observer.py — 剧本任务用量观测埋点（零侵入）

在 pipeline.py 各 phase 末尾调用 record_phase()，自动写入
ops_observer SQLite 数据库并（可选）同步到飞书多维表格。

Usage in pipeline.py:
    from drama_observer import record_phase, record_call

    # 单次 API 调用（call_api 之后）
    content, usage = call_api(..., return_usage=True)
    record_call(config, phase="script", ep_num=1, usage=usage, latency_ms=1200)

    # 整批 phase 完成时
    record_phase(config, phase="script", episodes=[1,2,3], elapsed=45.3,
                 total_tokens=12000, estimated_cost=0.09)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# ops_observer 相对本文件在 skills/fangcun/skills/drama/tools/，
# 往上找到 workspace 根目录
_HERE = Path(__file__).resolve().parent
_WORKSPACE = None
for _p in [_HERE, _HERE.parent, _HERE.parent.parent, _HERE.parent.parent.parent,
           _HERE.parent.parent.parent.parent, _HERE.parent.parent.parent.parent.parent]:
    if (_p / "ops_observer" / "data").exists() or (_p / "ops_observer" / "scripts" / "observer.py").exists():
        _WORKSPACE = _p
        break

_OBSERVER_CLI = _WORKSPACE / "ops_observer" / "scripts" / "observer.py" if _WORKSPACE else None
_DB_PATH = _WORKSPACE / "ops_observer" / "data" / "observer.db" if _WORKSPACE else None

# 模型定价表（USD/1M tokens，blended）
_PRICING_PATH = _WORKSPACE / "ops_observer" / "config_pricing.json" if _WORKSPACE else None
_PRICING: dict[str, float] = {}


def _load_pricing() -> dict[str, float]:
    global _PRICING
    if _PRICING:
        return _PRICING
    if _PRICING_PATH and _PRICING_PATH.exists():
        try:
            raw = json.loads(_PRICING_PATH.read_text(encoding="utf-8"))
            _PRICING = {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            pass
    return _PRICING


def estimate_cost(model: str, total_tokens: int) -> float:
    pricing = _load_pricing()
    for key, rate in pricing.items():
        if key.lower() in (model or "").lower():
            return total_tokens * rate / 1_000_000
    return total_tokens * 5.0 / 1_000_000


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection | None:
    if not _DB_PATH:
        return None
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _ensure_drama_table() -> None:
    conn = _connect()
    if not conn:
        return
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drama_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    project_name TEXT,
                    phase TEXT NOT NULL,
                    episodes TEXT,
                    ep_start INTEGER,
                    ep_end INTEGER,
                    ep_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    estimated_cost REAL DEFAULT 0,
                    latency_ms INTEGER,
                    model TEXT,
                    success INTEGER DEFAULT 1,
                    error_reason TEXT,
                    char_count INTEGER DEFAULT 0,
                    metadata_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drama_created ON drama_tasks(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drama_project ON drama_tasks(project_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drama_phase ON drama_tasks(phase)")
    except Exception:
        pass
    finally:
        conn.close()


def record_phase(
    config: dict,
    phase: str,
    episodes: list[int] | None = None,
    elapsed: float = 0,
    total_tokens: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost: float | None = None,
    model: str | None = None,
    success: bool = True,
    error_reason: str | None = None,
    char_count: int = 0,
    metadata: dict | None = None,
) -> None:
    """在 phase 完成时记录一条汇总记录。"""
    _ensure_drama_table()
    conn = _connect()
    if not conn:
        return

    project_name = config.get("project", {}).get("name") or config.get("novel_name") or "unknown"
    if not model:
        model = config.get("model") or config.get("project", {}).get("model") or "unknown"

    if estimated_cost is None and total_tokens:
        estimated_cost = estimate_cost(model, total_tokens)
    elif estimated_cost is None:
        estimated_cost = 0.0

    ep_start = min(episodes) if episodes else None
    ep_end = max(episodes) if episodes else None
    ep_count = len(episodes) if episodes else 0
    episodes_str = json.dumps(episodes, ensure_ascii=False) if episodes else None
    latency_ms = int(elapsed * 1000) if elapsed else None

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO drama_tasks
                (created_at, project_name, phase, episodes, ep_start, ep_end, ep_count,
                 total_tokens, input_tokens, output_tokens, estimated_cost, latency_ms,
                 model, success, error_reason, char_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(), project_name, phase, episodes_str, ep_start, ep_end, ep_count,
                    total_tokens or 0, input_tokens or 0, output_tokens or 0,
                    estimated_cost, latency_ms, model,
                    1 if success else 0, error_reason, char_count or 0,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        print(f"  [obs] {phase} | {project_name} | tokens={total_tokens} cost=${estimated_cost:.4f} time={elapsed:.0f}s")
    except Exception as e:
        print(f"  [obs] warn: {e}", file=sys.stderr)
    finally:
        conn.close()


def record_call(
    config: dict,
    phase: str,
    usage: dict,
    ep_num: int | None = None,
    latency_ms: int = 0,
    char_count: int = 0,
    model: str | None = None,
) -> dict:
    """记录单次 API 调用的 usage，返回 usage dict（方便链式调用）。

    usage 格式（OpenAI-compatible）:
        {"prompt_tokens": 500, "completion_tokens": 1000, "total_tokens": 1500}
    """
    _ensure_drama_table()
    conn = _connect()
    if not conn:
        return usage or {}

    project_name = config.get("project", {}).get("name") or config.get("novel_name") or "unknown"
    if not model:
        model = config.get("model") or config.get("project", {}).get("model") or "unknown"

    input_tokens = (usage or {}).get("prompt_tokens", 0) or (usage or {}).get("input_tokens", 0)
    output_tokens = (usage or {}).get("completion_tokens", 0) or (usage or {}).get("output_tokens", 0)
    total_tokens = (usage or {}).get("total_tokens", 0) or (input_tokens + output_tokens)
    estimated_cost = estimate_cost(model, total_tokens)

    episodes = [ep_num] if ep_num is not None else None
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO drama_tasks
                (created_at, project_name, phase, episodes, ep_start, ep_end, ep_count,
                 total_tokens, input_tokens, output_tokens, estimated_cost, latency_ms,
                 model, success, char_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    _now_iso(), project_name, phase,
                    json.dumps(episodes, ensure_ascii=False) if episodes else None,
                    ep_num, ep_num, 1 if ep_num is not None else 0,
                    total_tokens, input_tokens, output_tokens, estimated_cost,
                    latency_ms, model, char_count or 0,
                    json.dumps({"usage": usage}, ensure_ascii=False),
                ),
            )
    except Exception as e:
        print(f"  [obs] warn: {e}", file=sys.stderr)
    finally:
        conn.close()

    return usage or {}


def drama_daily_summary(project_name: str | None = None, date: str | None = None) -> dict:
    """返回今日（或指定日期）剧本任务统计摘要。"""
    _ensure_drama_table()
    conn = _connect()
    if not conn:
        return {}

    day = date or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    start = f"{day}T00:00:00"
    end_date = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    end = f"{end_date}T00:00:00"

    where = "created_at >= ? AND created_at < ?"
    params: list = [start, end]
    if project_name:
        where += " AND project_name = ?"
        params.append(project_name)

    try:
        row = conn.execute(
            f"SELECT COUNT(*) calls, COALESCE(SUM(total_tokens),0) tokens, "
            f"COALESCE(SUM(estimated_cost),0) cost, COALESCE(SUM(ep_count),0) eps, "
            f"COALESCE(SUM(char_count),0) chars FROM drama_tasks WHERE {where}",
            params
        ).fetchone()
        phases = conn.execute(
            f"SELECT phase, COUNT(*) c, COALESCE(SUM(total_tokens),0) t FROM drama_tasks WHERE {where} GROUP BY phase",
            params
        ).fetchall()
        return {
            "date": day,
            "project": project_name or "all",
            "calls": row["calls"],
            "total_tokens": row["tokens"],
            "estimated_cost_usd": row["cost"],
            "episodes_processed": row["eps"],
            "total_chars": row["chars"],
            "by_phase": {r["phase"]: {"calls": r["c"], "tokens": r["t"]} for r in phases},
        }
    except Exception:
        return {}
    finally:
        conn.close()
