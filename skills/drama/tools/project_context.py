#!/usr/bin/env python3
"""Read Fangcun project config and emit stable labels for assets/token events."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _project_id_from_output_dir(output_dir: Path) -> str:
    """Return a stable project id for Fangcun outputs.

    Fangcun projects usually write assets under <project>/drama. Using the last
    path component would collapse every project to project_id=drama, which makes
    attribution impossible to aggregate correctly. Prefer the parent directory in
    that common layout.
    """
    return output_dir.parent.name if output_dir.name == "drama" and output_dir.parent.name else output_dir.name


def labels_from_config(config: dict, config_path: Path) -> dict:
    output_dir = Path(config.get("output_dir") or config_path.parent).resolve()
    title = config.get("drama_name") or config.get("novel_name") or output_dir.name
    return {
        "project_id": config.get("project_id") or config.get("drama_id") or _project_id_from_output_dir(output_dir),
        "project_name": title,
        "org_id": config.get("org_id") or config.get("company_id") or config.get("organization") or "",
        "output_dir": str(output_dir),
        "script_batch_size": int(config.get("script_batch_size", 5)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    path = Path(args.config).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(labels_from_config(config, path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
