#!/usr/bin/env python3
"""One-command dialogue translation job scaffold.

This tool does the deterministic parts:
1. Extract dialogue from script.
2. Create a model input JSONL and prompt instruction file.
3. Optionally render a translated JSONL back to script.

It does not call a model directly; agent/model can fill translated_jsonl using the
prompt file, then rerun with --translated-jsonl.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PROMPT_PATH = THIS_DIR.parent / "prompts" / "dialogue_translation.md"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare/render dialogue translation job")
    ap.add_argument("script")
    ap.add_argument("--target-language", required=True)
    ap.add_argument("--style", default="default")
    ap.add_argument("--locale", default="")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--translated-jsonl", default="", help="existing model output JSONL to render")
    ap.add_argument("--mode", choices=["bilingual", "replace"], default="bilingual")
    args = ap.parse_args()

    script = Path(args.script).resolve()
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    extracted = workdir / "dialogue_source.jsonl"
    prompt_out = workdir / "translation_prompt.md"
    rendered = workdir / f"{script.stem}.{args.target_language}.{args.style}.{args.mode}.md"

    run(["python3", str(THIS_DIR / "extract_dialogue.py"), str(script), "--out", str(extracted)])

    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (template
        .replace("{{target_language}}", args.target_language)
        .replace("{{style}}", args.style)
        .replace("{{locale}}", args.locale or "未指定"))
    prompt += "\n\n## 待翻译 JSONL\n\n```jsonl\n"
    prompt += extracted.read_text(encoding="utf-8")
    prompt += "```\n"
    prompt_out.write_text(prompt, encoding="utf-8")

    result = {
        "script": str(script),
        "target_language": args.target_language,
        "style": args.style,
        "locale": args.locale,
        "dialogue_source_jsonl": str(extracted),
        "translation_prompt": str(prompt_out),
        "rendered_output": None,
    }

    if args.translated_jsonl:
        run([
            "python3", str(THIS_DIR / "render_dialogue_translation.py"),
            str(script), str(Path(args.translated_jsonl).resolve()),
            "--mode", args.mode,
            "--out", str(rendered),
        ])
        run([
            "python3", str(THIS_DIR / "localization_guardrails.py"),
            str(rendered),
            "--locale", args.locale or args.target_language,
            "--json",
        ])
        result["rendered_output"] = str(rendered)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
