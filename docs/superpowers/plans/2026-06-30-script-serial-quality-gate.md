# Script Serial Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a serial draft-first script generation workflow with per-episode AI quality gates, automatic targeted rewrite for the first blocked draft, and per-batch writer confirmation before promoting drafts into official scripts.

**Architecture:** Keep the feature file-based and CLI-driven so it works across Claude Code, Codex, Cursor, OpenCode, Gemini CLI, and OpenClaw. Add focused workflow helpers for draft paths, review reports, batch state, and continuity state, then have `pipeline.py` orchestrate generation, review, rewrite, confirmation, and resume behavior. Use Python standard library tests only.

**Tech Stack:** Python 3.10+, standard library `unittest`, existing OpenAI-compatible API client, Markdown prompt files, JSON state files.

## Global Constraints

- Primary runtime scenario is OpenClaw, but implementation must remain a generic multi-platform skill group.
- Do not depend on platform-specific message sending, UI, or OpenClaw-only APIs.
- Drafts must not be written to `scripts/` until the writer explicitly confirms the batch.
- No timeout or missing reply may promote drafts automatically.
- The current episode must pass its quality gate before the next episode can be generated.
- The first blocked review triggers one automatic targeted rewrite; further AI rewrites require explicit writer action.
- AI review writes both JSON for automation and Markdown for writer review.
- Use Python standard library tests; do not add external test dependencies.

---

## File Structure

- Create `skills/drama/tools/script_workflow.py`: pure helpers for draft paths, batch ids, review report normalization, Markdown rendering, draft promotion, batch summary, and continuity state file I/O.
- Modify `skills/drama/tools/state_manager.py`: add script-batch state helpers while preserving existing phase and episode APIs.
- Modify `skills/drama/tools/pipeline.py`: integrate draft-first serial script workflow, AI review/rewrite calls, CLI flags, batch stop messages, resume behavior, and confirmation operation.
- Create `skills/drama/prompts/script_review.md`: structured per-episode review prompt.
- Create `skills/drama/prompts/script_rewrite.md`: targeted rewrite prompt.
- Create `skills/drama/prompts/continuity_update.md`: continuity-state update prompt.
- Modify `skills/drama/SKILL.md`: document new script workflow and OpenClaw-friendly manual confirmation.
- Modify `skills/drama/prompts/decision.md`: update stage 3 orchestration rules.
- Modify `agents/script-writer.md`: align execution-layer behavior with draft-first gated writing.
- Create `tests/drama/test_script_workflow.py`: unit tests for pure helper behavior.
- Create `tests/drama/test_state_manager_script_batches.py`: unit tests for pending batch and blocked episode state.
- Create `tests/drama/test_pipeline_script_workflow.py`: orchestration tests using mocked API calls and fixture files.

---

### Task 1: Draft Workflow Helpers

**Files:**
- Create: `skills/drama/tools/script_workflow.py`
- Test: `tests/drama/test_script_workflow.py`

**Interfaces:**
- Produces:
  - `get_drafts_dir(output_dir: str) -> Path`
  - `format_batch_id(batch_num: int) -> str`
  - `get_batch_dir(output_dir: str, batch_id: str) -> Path`
  - `get_draft_path(output_dir: str, batch_id: str, episode_num: int) -> Path`
  - `save_draft(output_dir: str, batch_id: str, episode_num: int, content: str) -> Path`
  - `load_draft(output_dir: str, batch_id: str, episode_num: int) -> str`
  - `save_review_report(output_dir: str, batch_id: str, episode_num: int, report: dict) -> tuple[Path, Path]`
  - `load_review_report(output_dir: str, batch_id: str, episode_num: int) -> dict`
  - `is_review_blocked(report: dict) -> bool`
  - `save_rewrite_attempt(output_dir: str, batch_id: str, episode_num: int, attempt_num: int, content: str) -> Path`
  - `load_continuity_state(output_dir: str, batch_id: str | None = None) -> dict`
  - `save_continuity_state(output_dir: str, state: dict, batch_id: str | None = None) -> Path`
  - `write_batch_summary(output_dir: str, batch_id: str, episodes: list[int], review_reports: dict[int, dict]) -> Path`
  - `promote_batch_to_scripts(output_dir: str, batch_id: str, episodes: list[int]) -> list[Path]`
- Consumes: no project-specific imports other than Python standard library.

- [ ] **Step 1: Write the failing helper tests**

Create `tests/drama/test_script_workflow.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from skills.drama.tools.script_workflow import (
    format_batch_id,
    get_draft_path,
    is_review_blocked,
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


class ScriptWorkflowTests(unittest.TestCase):
    def test_draft_is_saved_under_batch_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_draft(tmp, "batch_001", 3, "EP3 draft")

            self.assertEqual(path, Path(tmp) / "drafts" / "batch_001" / "ep_003.txt")
            self.assertEqual(load_draft(tmp, "batch_001", 3), "EP3 draft")

    def test_review_report_writes_json_and_markdown(self):
        report = {
            "verdict": "blocked",
            "severe_issues": ["缺少集末钩子"],
            "non_blocking_issues": ["对白略直白"],
            "rewrite_instructions": ["补上钩子"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = save_review_report(tmp, "batch_001", 1, report)

            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertTrue(is_review_blocked(load_review_report(tmp, "batch_001", 1)))
            self.assertIn("缺少集末钩子", md_path.read_text(encoding="utf-8"))

    def test_promote_batch_copies_drafts_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_draft(tmp, "batch_001", 1, "EP1")
            promoted = promote_batch_to_scripts(tmp, "batch_001", [1])

            self.assertEqual(promoted, [Path(tmp) / "scripts" / "ep_001.txt"])
            self.assertEqual((Path(tmp) / "scripts" / "ep_001.txt").read_text(encoding="utf-8"), "EP1")
            self.assertEqual(load_draft(tmp, "batch_001", 1), "EP1")

    def test_continuity_state_defaults_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_continuity_state(tmp), {"version": 1, "episodes": []})
            path = save_continuity_state(tmp, {"version": 1, "episodes": [{"id": 1}]})

            self.assertEqual(path, Path(tmp) / "continuity_state.json")
            self.assertEqual(load_continuity_state(tmp)["episodes"], [{"id": 1}])

    def test_batch_local_continuity_state_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_continuity_state(tmp, {"version": 1, "episodes": [{"id": 1}]}, "batch_001")

            self.assertEqual(load_continuity_state(tmp), {"version": 1, "episodes": []})
            self.assertEqual(load_continuity_state(tmp, "batch_001")["episodes"], [{"id": 1}])

    def test_rewrite_attempt_is_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_rewrite_attempt(tmp, "batch_001", 2, 1, "old blocked draft")

            self.assertEqual(path, Path(tmp) / "drafts" / "batch_001" / "rewrites" / "ep_002_attempt_01.txt")
            self.assertEqual(path.read_text(encoding="utf-8"), "old blocked draft")

    def test_batch_summary_lists_reviews_and_actions(self):
        reports = {
            1: {"verdict": "pass", "severe_issues": [], "non_blocking_issues": []},
            2: {"verdict": "warning", "severe_issues": [], "non_blocking_issues": ["节奏略慢"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_batch_summary(tmp, "batch_001", [1, 2], reports)

            text = path.read_text(encoding="utf-8")
            self.assertIn("batch_001", text)
            self.assertIn("ep_001.txt", text)
            self.assertIn("节奏略慢", text)
            self.assertIn("--confirm-draft-batch", text)

    def test_batch_id_format(self):
        self.assertEqual(format_batch_id(7), "batch_007")
        self.assertEqual(get_draft_path("out", "batch_007", 12), Path("out") / "drafts" / "batch_007" / "ep_012.txt")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.drama.test_script_workflow -v
```

Expected: FAIL or ERROR because `skills.drama.tools.script_workflow` does not exist.

- [ ] **Step 3: Implement `script_workflow.py`**

Create `skills/drama/tools/script_workflow.py` with these functions:

```python
"""Draft-first script workflow helpers for fangcun-drama."""

import json
import shutil
from pathlib import Path


def get_drafts_dir(output_dir: str) -> Path:
    return Path(output_dir) / "drafts"


def format_batch_id(batch_num: int) -> str:
    return f"batch_{batch_num:03d}"


def get_batch_dir(output_dir: str, batch_id: str) -> Path:
    return get_drafts_dir(output_dir) / batch_id


def get_draft_path(output_dir: str, batch_id: str, episode_num: int) -> Path:
    return get_batch_dir(output_dir, batch_id) / f"ep_{episode_num:03d}.txt"


def save_draft(output_dir: str, batch_id: str, episode_num: int, content: str) -> Path:
    path = get_draft_path(output_dir, batch_id, episode_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def load_draft(output_dir: str, batch_id: str, episode_num: int) -> str:
    path = get_draft_path(output_dir, batch_id, episode_num)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _review_paths(output_dir: str, batch_id: str, episode_num: int) -> tuple[Path, Path]:
    base = get_batch_dir(output_dir, batch_id) / "reviews"
    return base / f"ep_{episode_num:03d}_review.json", base / f"ep_{episode_num:03d}_review.md"


def normalize_review_report(report: dict) -> dict:
    return {
        "verdict": report.get("verdict", "warning"),
        "severe_issues": list(report.get("severe_issues", [])),
        "non_blocking_issues": list(report.get("non_blocking_issues", [])),
        "continuity_issues": list(report.get("continuity_issues", [])),
        "format_issues": list(report.get("format_issues", [])),
        "rewrite_instructions": list(report.get("rewrite_instructions", [])),
        "summary": report.get("summary", ""),
    }


def review_report_to_markdown(episode_num: int, report: dict) -> str:
    r = normalize_review_report(report)
    lines = [
        f"# EP{episode_num:03d} AI Review",
        "",
        f"- Verdict: {r['verdict']}",
        f"- Summary: {r['summary']}",
        "",
        "## Severe Issues",
        *[f"- {item}" for item in r["severe_issues"]] or ["- None"],
        "",
        "## Non-Blocking Issues",
        *[f"- {item}" for item in r["non_blocking_issues"]] or ["- None"],
        "",
        "## Continuity Issues",
        *[f"- {item}" for item in r["continuity_issues"]] or ["- None"],
        "",
        "## Format Issues",
        *[f"- {item}" for item in r["format_issues"]] or ["- None"],
        "",
        "## Rewrite Instructions",
        *[f"- {item}" for item in r["rewrite_instructions"]] or ["- None"],
        "",
    ]
    return "\n".join(lines)


def save_review_report(output_dir: str, batch_id: str, episode_num: int, report: dict) -> tuple[Path, Path]:
    normalized = normalize_review_report(report)
    json_path, md_path = _review_paths(output_dir, batch_id, episode_num)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(review_report_to_markdown(episode_num, normalized), encoding="utf-8")
    return json_path, md_path


def load_review_report(output_dir: str, batch_id: str, episode_num: int) -> dict:
    json_path, _ = _review_paths(output_dir, batch_id, episode_num)
    if not json_path.exists():
        return normalize_review_report({})
    return normalize_review_report(json.loads(json_path.read_text(encoding="utf-8")))


def is_review_blocked(report: dict) -> bool:
    normalized = normalize_review_report(report)
    return normalized["verdict"] == "blocked" or bool(normalized["severe_issues"])


def save_rewrite_attempt(output_dir: str, batch_id: str, episode_num: int, attempt_num: int, content: str) -> Path:
    path = get_batch_dir(output_dir, batch_id) / "rewrites" / f"ep_{episode_num:03d}_attempt_{attempt_num:02d}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _continuity_path(output_dir: str, batch_id: str | None = None) -> Path:
    if batch_id:
        return get_batch_dir(output_dir, batch_id) / "continuity_state.json"
    return Path(output_dir) / "continuity_state.json"


def load_continuity_state(output_dir: str, batch_id: str | None = None) -> dict:
    path = _continuity_path(output_dir, batch_id)
    if not path.exists():
        return {"version": 1, "episodes": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_continuity_state(output_dir: str, state: dict, batch_id: str | None = None) -> Path:
    path = _continuity_path(output_dir, batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_batch_summary(output_dir: str, batch_id: str, episodes: list[int], review_reports: dict[int, dict]) -> Path:
    path = get_batch_dir(output_dir, batch_id) / "batch_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Draft Batch {batch_id}",
        "",
        "## Episodes",
    ]
    for ep in episodes:
        report = normalize_review_report(review_reports.get(ep, {}))
        lines.append(f"- ep_{ep:03d}.txt: {report['verdict']}")
        for issue in report["severe_issues"] + report["non_blocking_issues"]:
            lines.append(f"  - {issue}")
    lines.extend([
        "",
        "## Writer Actions",
        "- Confirm: `python tools/pipeline.py --config {config} --confirm-draft-batch`",
        "- Rewrite one episode: `python tools/pipeline.py --config {config} --rewrite-draft --episode N`",
        "- Review edited draft: `python tools/pipeline.py --config {config} --review-draft --episode N`",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def promote_batch_to_scripts(output_dir: str, batch_id: str, episodes: list[int]) -> list[Path]:
    scripts_dir = Path(output_dir) / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    promoted = []
    for episode_num in episodes:
        source = get_draft_path(output_dir, batch_id, episode_num)
        target = scripts_dir / f"ep_{episode_num:03d}.txt"
        shutil.copyfile(source, target)
        promoted.append(target)
    return promoted
```

- [ ] **Step 4: Run helper tests to verify pass**

Run:

```bash
python -m unittest tests.drama.test_script_workflow -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add skills/drama/tools/script_workflow.py tests/drama/test_script_workflow.py
git commit -m "feat: add script draft workflow helpers"
```

---

### Task 2: Script Batch State

**Files:**
- Modify: `skills/drama/tools/state_manager.py`
- Test: `tests/drama/test_state_manager_script_batches.py`

**Interfaces:**
- Consumes:
  - `StateManager.load()`
  - `StateManager.save()`
- Produces:
  - `StateManager.start_script_batch(batch_id: str, episodes: list[int]) -> None`
  - `StateManager.set_episode_review(episode_num: int, verdict: str, blocked: bool, severe_count: int) -> None`
  - `StateManager.mark_episode_rewrite_attempt(episode_num: int) -> int`
  - `StateManager.mark_batch_waiting_confirmation(batch_summary_path: str) -> None`
  - `StateManager.confirm_script_batch(promoted_paths: list[str]) -> None`
  - `StateManager.get_pending_script_batch() -> dict | None`
  - `StateManager.has_pending_script_confirmation() -> bool`

- [ ] **Step 1: Write failing state tests**

Create `tests/drama/test_state_manager_script_batches.py`:

```python
import tempfile
import unittest

from skills.drama.tools.state_manager import StateManager


class ScriptBatchStateTests(unittest.TestCase):
    def test_start_script_batch_records_pending_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1, 2])

            pending = state.get_pending_script_batch()
            self.assertEqual(pending["batch_id"], "batch_001")
            self.assertEqual(pending["episodes"], [1, 2])
            self.assertFalse(pending["awaiting_confirmation"])

    def test_review_status_blocks_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1])
            state.set_episode_review(1, "blocked", True, 2)

            episode = state.get_pending_script_batch()["episode_reviews"]["1"]
            self.assertTrue(episode["blocked"])
            self.assertEqual(episode["severe_count"], 2)

    def test_rewrite_attempt_counter_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1])

            self.assertEqual(state.mark_episode_rewrite_attempt(1), 1)
            self.assertEqual(state.mark_episode_rewrite_attempt(1), 2)

    def test_waiting_confirmation_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1, 2])
            state.mark_batch_waiting_confirmation("drafts/batch_001/batch_summary.md")

            self.assertTrue(state.has_pending_script_confirmation())
            self.assertEqual(state.get_resume_phase(), "script_confirmation")

    def test_confirm_batch_clears_pending_batch_and_records_promoted_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = StateManager(tmp)
            state.load()
            state.start_script_batch("batch_001", [1])
            state.mark_batch_waiting_confirmation("summary.md")
            state.confirm_script_batch(["scripts/ep_001.txt"])

            self.assertIsNone(state.get_pending_script_batch())
            self.assertEqual(state.state["script_batches"]["confirmed"][-1]["promoted_paths"], ["scripts/ep_001.txt"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.drama.test_state_manager_script_batches -v
```

Expected: FAIL because script-batch methods do not exist.

- [ ] **Step 3: Add script-batch state methods**

Modify `skills/drama/tools/state_manager.py` by adding this field when creating a new state:

```python
"script_batches": {
    "current": None,
    "confirmed": [],
},
```

Add this guard to `load()` after an existing state is loaded:

```python
self._state.setdefault("script_batches", {"current": None, "confirmed": []})
self._state["script_batches"].setdefault("confirmed", [])
if "current" not in self._state["script_batches"]:
    self._state["script_batches"]["current"] = None
```

Add methods:

```python
def start_script_batch(self, batch_id, episodes):
    self.state["script_batches"]["current"] = {
        "batch_id": batch_id,
        "episodes": list(episodes),
        "episode_reviews": {},
        "rewrite_attempts": {},
        "awaiting_confirmation": False,
        "batch_summary_path": "",
        "started": self._now(),
    }
    self.save()


def set_episode_review(self, episode_num, verdict, blocked, severe_count):
    current = self.get_pending_script_batch()
    if current is None:
        return
    current["episode_reviews"][str(episode_num)] = {
        "verdict": verdict,
        "blocked": bool(blocked),
        "severe_count": int(severe_count),
        "timestamp": self._now(),
    }
    self.save()


def mark_episode_rewrite_attempt(self, episode_num):
    current = self.get_pending_script_batch()
    if current is None:
        return 0
    key = str(episode_num)
    attempts = current.setdefault("rewrite_attempts", {})
    attempts[key] = int(attempts.get(key, 0)) + 1
    self.save()
    return attempts[key]


def mark_batch_waiting_confirmation(self, batch_summary_path):
    current = self.get_pending_script_batch()
    if current is None:
        return
    current["awaiting_confirmation"] = True
    current["batch_summary_path"] = str(batch_summary_path)
    current["finished"] = self._now()
    self.save()


def confirm_script_batch(self, promoted_paths):
    current = self.get_pending_script_batch()
    if current is None:
        return
    current["confirmed"] = self._now()
    current["promoted_paths"] = list(promoted_paths)
    self.state["script_batches"]["confirmed"].append(current)
    self.state["script_batches"]["current"] = None
    self.save()


def get_pending_script_batch(self):
    return self.state.setdefault("script_batches", {"current": None, "confirmed": []}).get("current")


def has_pending_script_confirmation(self):
    current = self.get_pending_script_batch()
    return bool(current and current.get("awaiting_confirmation"))
```

Modify `get_resume_phase()` so pending confirmation returns `"script_confirmation"` before the normal phase order loop:

```python
if self.has_pending_script_confirmation():
    return "script_confirmation"
```

- [ ] **Step 4: Run state tests to verify pass**

Run:

```bash
python -m unittest tests.drama.test_state_manager_script_batches -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add skills/drama/tools/state_manager.py tests/drama/test_state_manager_script_batches.py
git commit -m "feat: track script draft batch state"
```

---

### Task 3: Review, Rewrite, And Continuity Prompts

**Files:**
- Create: `skills/drama/prompts/script_review.md`
- Create: `skills/drama/prompts/script_rewrite.md`
- Create: `skills/drama/prompts/continuity_update.md`
- Test: `tests/drama/test_script_workflow.py`

**Interfaces:**
- Consumes:
  - `load_prompt(name: str) -> str` from `pipeline.py`
- Produces:
  - Three prompt files used by `pipeline.py`.

- [ ] **Step 1: Add failing prompt existence tests**

Append to `tests/drama/test_script_workflow.py`:

```python
class ScriptPromptTests(unittest.TestCase):
    def test_script_review_prompt_requires_json_verdict(self):
        text = (Path("skills/drama/prompts/script_review.md")).read_text(encoding="utf-8")
        self.assertIn('"verdict"', text)
        self.assertIn('"severe_issues"', text)
        self.assertIn("blocked", text)

    def test_script_rewrite_prompt_is_targeted(self):
        text = (Path("skills/drama/prompts/script_rewrite.md")).read_text(encoding="utf-8")
        self.assertIn("审核报告", text)
        self.assertIn("保留", text)
        self.assertIn("严重问题", text)

    def test_continuity_prompt_keeps_structured_state(self):
        text = (Path("skills/drama/prompts/continuity_update.md")).read_text(encoding="utf-8")
        self.assertIn('"episodes"', text)
        self.assertIn('"open_hooks"', text)
        self.assertIn('"character_states"', text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.drama.test_script_workflow.ScriptPromptTests -v
```

Expected: ERROR because prompt files do not exist.

- [ ] **Step 3: Create `script_review.md`**

Create `skills/drama/prompts/script_review.md`:

```markdown
# 单集剧本 AI 审核 Agent

你负责审核短剧单集草稿。你的任务不是润色，而是判断这集能否进入下一集生成。

## 阻塞原则

只要存在严重问题，`verdict` 必须是 `"blocked"`。严重问题包括：
- 格式不合格：缺少场景结构、缺少 `△`、不像剧本。
- 连续性冲突：人物关系、状态、伏笔与前文矛盾。
- 未承接上一集钩子。
- 本集没有集末钩子。
- 废笔严重：日常过程、环境铺垫、无效对白占比明显。
- 偏离本集骨架。
- 人设或角色口吻崩坏。
- 字数严重偏离。

普通问题只进入 `non_blocking_issues`，不得阻塞。

## 输出格式

只输出 JSON，不要输出 Markdown 或解释文字：

```json
{
  "verdict": "pass|warning|blocked",
  "summary": "一句话总评",
  "severe_issues": [],
  "non_blocking_issues": [],
  "continuity_issues": [],
  "format_issues": [],
  "rewrite_instructions": []
}
```
```

- [ ] **Step 4: Create `script_rewrite.md`**

Create `skills/drama/prompts/script_rewrite.md`:

```markdown
# 单集剧本定向重写 Agent

你负责基于审核报告修复单集草稿。不要自由重写另一版。

## 重写原则

- 优先修复审核报告中的严重问题。
- 保留原稿中已经成立的核心事件、人物状态、钩子和有效情绪回报。
- 不新增与骨架冲突的桥段。
- 不改变已经确认的前文连续性。
- 修复后仍必须输出完整 `<scriptItem>`。

## 输出格式

只输出重写后的完整 `<scriptItem>`，标签外不得有任何内容。
```

- [ ] **Step 5: Create `continuity_update.md`**

Create `skills/drama/prompts/continuity_update.md`:

```markdown
# 剧本连续性状态更新 Agent

你负责根据已通过审核的单集剧本更新连续性状态。不要复述完整剧情，只保留后续写作必须知道的信息。

## 输出格式

只输出 JSON：

```json
{
  "version": 1,
  "episodes": [
    {
      "id": 1,
      "summary": "本集确认发生的关键事件",
      "ending_hook": "集末钩子",
      "resolved_hooks": [],
      "new_hooks": []
    }
  ],
  "open_hooks": [],
  "character_states": {},
  "relationship_states": {},
  "used_reversals": [],
  "used_emotional_beats": [],
  "notes_for_next_episode": []
}
```
```

- [ ] **Step 6: Run prompt tests to verify pass**

Run:

```bash
python -m unittest tests.drama.test_script_workflow.ScriptPromptTests -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add skills/drama/prompts/script_review.md skills/drama/prompts/script_rewrite.md skills/drama/prompts/continuity_update.md tests/drama/test_script_workflow.py
git commit -m "feat: add script review rewrite prompts"
```

---

### Task 4: Pipeline Orchestration And CLI

**Files:**
- Modify: `skills/drama/tools/pipeline.py`
- Test: `tests/drama/test_pipeline_script_workflow.py`

**Interfaces:**
- Consumes:
  - Task 1 `script_workflow.py` helpers.
  - Task 2 `StateManager` script-batch methods.
  - Existing `call_api`, `extract_script_items`, `extract_episode_from_skeleton`, `get_script_content`.
- Produces:
  - `build_script_user_prompt(...) -> str`
  - `review_script_draft(...) -> dict`
  - `rewrite_script_draft(...) -> str`
  - `update_continuity_state(...) -> dict`
  - `phase_script(...)` writes drafts and pauses at quality gates.
  - `phase_confirm_draft_batch(config: dict, state: StateManager) -> bool`

- [ ] **Step 1: Write failing orchestration tests**

Create `tests/drama/test_pipeline_script_workflow.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills.drama.tools import pipeline
from skills.drama.tools.agent_tools import save_adaptation, save_events, save_skeleton
from skills.drama.tools.script_workflow import load_draft, load_review_report, save_draft
from skills.drama.tools.state_manager import StateManager


def make_config(tmp, episodes=3):
    source_dir = Path(tmp) / "chapters"
    source_dir.mkdir()
    for i in range(1, 4):
        (source_dir / f"第{i}章.txt").write_text(f"第{i}章原文", encoding="utf-8")
    return {
        "novel_name": "测试书",
        "drama_name": "测试剧",
        "source_dir": str(source_dir),
        "output_dir": str(Path(tmp) / "drama"),
        "api_key": "test-key",
        "api_base_url": "http://example.invalid/v1",
        "model": "test-model",
        "script_batch_size": 2,
        "project": {
            "episodes": episodes,
            "episode_duration": 2,
            "chapter_range": [1, 3],
            "platform": "竖屏9:16",
            "style": "测试",
            "paywall": "测试",
        },
    }


def seed_artifacts(config):
    output_dir = config["output_dir"]
    save_events(output_dir, [{"id": 1, "chapter_index": 1, "chapter": "第1章", "event": "事件"}])
    save_skeleton(output_dir, "故事核\n人物小传\n| 1 | 第一集 |")
    save_adaptation(output_dir, "改编策略")


class PipelineScriptWorkflowTests(unittest.TestCase):
    def test_script_phase_saves_drafts_and_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            responses = [
                '<scriptItem name="EP1">1-1 日/内 房间\n人物：甲\n△动作\n甲：来了\n---</scriptItem>',
                json.dumps({"verdict": "pass", "summary": "ok", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 1}], "open_hooks": []}, ensure_ascii=False),
                '<scriptItem name="EP2">2-1 日/内 房间\n人物：甲\n△动作\n甲：继续\n---</scriptItem>',
                json.dumps({"verdict": "pass", "summary": "ok", "severe_issues": [], "non_blocking_issues": []}, ensure_ascii=False),
                json.dumps({"version": 1, "episodes": [{"id": 1}, {"id": 2}], "open_hooks": []}, ensure_ascii=False),
            ]

            with patch.object(pipeline, "call_api", side_effect=responses):
                ok = pipeline.phase_script(config, start=1, end=3, dry_run=False, state=state, batch_size=2)

            self.assertTrue(ok)
            self.assertEqual(load_draft(config["output_dir"], "batch_001", 1).splitlines()[0], "1-1 日/内 房间")
            self.assertFalse((Path(config["output_dir"]) / "scripts" / "ep_001.txt").exists())
            self.assertTrue(state.has_pending_script_confirmation())

    def test_blocked_review_triggers_one_rewrite_then_pauses_if_still_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp, episodes=1)
            seed_artifacts(config)
            state = StateManager(config["output_dir"])
            state.load()
            blocked = {"verdict": "blocked", "summary": "bad", "severe_issues": ["缺少钩子"], "non_blocking_issues": []}
            responses = [
                '<scriptItem name="EP1">坏稿</scriptItem>',
                json.dumps(blocked, ensure_ascii=False),
                '<scriptItem name="EP1">改稿</scriptItem>',
                json.dumps(blocked, ensure_ascii=False),
            ]

            with patch.object(pipeline, "call_api", side_effect=responses):
                ok = pipeline.phase_script(config, start=1, end=1, dry_run=False, state=state, batch_size=1)

            self.assertFalse(ok)
            pending = state.get_pending_script_batch()
            self.assertTrue(pending["episode_reviews"]["1"]["blocked"])
            self.assertEqual(pending["rewrite_attempts"]["1"], 1)

    def test_confirm_draft_batch_copies_to_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(tmp)
            state = StateManager(config["output_dir"])
            state.load()
            state.start_script_batch("batch_001", [1])
            save_draft(config["output_dir"], "batch_001", 1, "confirmed draft")
            state.mark_batch_waiting_confirmation("summary.md")

            ok = pipeline.phase_confirm_draft_batch(config, state)

            self.assertTrue(ok)
            self.assertEqual((Path(config["output_dir"]) / "scripts" / "ep_001.txt").read_text(encoding="utf-8"), "confirmed draft")
            self.assertIsNone(state.get_pending_script_batch())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run orchestration tests to verify they fail**

Run:

```bash
python -m unittest tests.drama.test_pipeline_script_workflow -v
```

Expected: FAIL because `phase_script` lacks `batch_size`, draft behavior, review/rewrite calls, and `phase_confirm_draft_batch`.

- [ ] **Step 3: Import workflow helpers**

Modify `skills/drama/tools/pipeline.py` imports:

```python
from script_workflow import (
    format_batch_id,
    is_review_blocked,
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
```

- [ ] **Step 4: Add JSON parsing helper for AI reports**

Add near review helpers:

```python
def _parse_json_object(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {
                "verdict": "blocked",
                "summary": "AI review did not return valid JSON",
                "severe_issues": ["审核结果不是合法 JSON"],
                "non_blocking_issues": [],
                "rewrite_instructions": ["重新审核或人工检查草稿"],
            }
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {
                "verdict": "blocked",
                "summary": "AI review JSON could not be parsed",
                "severe_issues": ["审核 JSON 解析失败"],
                "non_blocking_issues": [],
                "rewrite_instructions": ["重新审核或人工检查草稿"],
            }
```

- [ ] **Step 5: Extract script prompt builder**

Create `build_script_user_prompt(...)` by moving existing `user_prompt` construction out of the loop. Signature:

```python
def build_script_user_prompt(config, project_info, script_list_str, ep_skeleton, adaptation, events_text, prev_script, novel_text_sample, target_words, ep_num, continuity_state, batch_continuity_state):
    format_prompt = '\n你必须使用如下XML格式写入工作区：\n<scriptItem name="剧本名称">剧本内容</scriptItem>'
    return f"""{project_info}

## 作品名称
{config.get('novel_name', '未命名')}

{script_list_str}

## 正式连续性状态
{json.dumps(continuity_state, ensure_ascii=False, indent=2)}

## 当前草稿批次临时连续性状态
{json.dumps(batch_continuity_state, ensure_ascii=False, indent=2)}

## 本集骨架信息
{ep_skeleton}

## 改编策略
{adaptation}

## 事件表
{events_text[:2000]}

{"## 上一集剧本（用于衔接）" if prev_script else ""}
{prev_script[:3000] if prev_script else ""}

{"## 对应章节原文（参考）" if novel_text_sample else ""}
{novel_text_sample[:3000] if novel_text_sample else ""}

请编写第{ep_num}集的完整剧本。目标字数：约{target_words}字台词。{format_prompt}"""
```

- [ ] **Step 6: Add review function**

```python
def review_script_draft(config, api_key, api_url, model, ep_num, draft_content, ep_skeleton, prev_script, continuity_state, batch_continuity_state):
    system_prompt = load_prompt("script_review.md")
    user_prompt = f"""请审核第{ep_num}集剧本草稿。

## 本集骨架
{ep_skeleton}

## 上一集剧本
{prev_script[:3000] if prev_script else ""}

## 正式连续性状态
{json.dumps(continuity_state, ensure_ascii=False, indent=2)}

## 当前批次连续性状态
{json.dumps(batch_continuity_state, ensure_ascii=False, indent=2)}

## 剧本草稿
{draft_content}
"""
    result = call_api(api_key, model, user_prompt, system_prompt=system_prompt, api_url=api_url, temperature=0.2, max_tokens=2048)
    report = _parse_json_object(result)
    local_issues = validate_script(draft_content, int(config.get("project", {}).get("episode_duration", 2) * 250))
    severe = [issue for issue in local_issues if issue.startswith("严重") or issue.startswith("警告")]
    if severe:
        report.setdefault("severe_issues", []).extend(severe)
        report["verdict"] = "blocked"
    return report
```

- [ ] **Step 7: Add rewrite function**

```python
def rewrite_script_draft(config, api_key, api_url, model, ep_num, draft_content, review_report, ep_skeleton, prev_script, continuity_state, batch_continuity_state):
    system_prompt = load_prompt("script_rewrite.md")
    user_prompt = f"""请定向重写第{ep_num}集。

## 审核报告
{json.dumps(review_report, ensure_ascii=False, indent=2)}

## 本集骨架
{ep_skeleton}

## 上一集剧本
{prev_script[:3000] if prev_script else ""}

## 连续性状态
{json.dumps({"confirmed": continuity_state, "current_batch": batch_continuity_state}, ensure_ascii=False, indent=2)}

## 原始草稿
{draft_content}
"""
    result = call_api(api_key, model, user_prompt, system_prompt=system_prompt, api_url=api_url, temperature=0.55, max_tokens=4096)
    items = extract_script_items(result)
    return items[0]["content"] if items else result.strip()
```

- [ ] **Step 8: Add continuity update function**

```python
def update_continuity_state(config, api_key, api_url, model, ep_num, script_content, current_state):
    system_prompt = load_prompt("continuity_update.md")
    user_prompt = f"""请根据第{ep_num}集已通过审核的剧本，更新连续性状态。

## 当前连续性状态
{json.dumps(current_state, ensure_ascii=False, indent=2)}

## 第{ep_num}集剧本
{script_content}
"""
    result = call_api(api_key, model, user_prompt, system_prompt=system_prompt, api_url=api_url, temperature=0.2, max_tokens=2048)
    parsed = _parse_json_object(result)
    if not parsed.get("episodes"):
        parsed = dict(current_state)
    parsed["version"] = 1
    return parsed
```

- [ ] **Step 9: Rewrite `phase_script` as gated draft workflow**

Change signature to:

```python
def phase_script(config: dict, start: int = 1, end: int = 3, dry_run: bool = False, state: StateManager = None, batch_size: int = None):
```

Implementation requirements:

- Compute `batch_size = batch_size or config.get("script_batch_size", 5)`.
- Refuse to continue if `state.has_pending_script_confirmation()` is true; print the batch summary path and return `False`.
- Create `batch_id` from confirmed count + 1: `format_batch_id(len(state.state["script_batches"]["confirmed"]) + 1)`.
- Limit episodes to `min(end, start + batch_size - 1)`.
- Call `state.start_script_batch(batch_id, episodes)` before the loop.
- For each episode:
  - Get previous episode from current batch draft if present, otherwise official `scripts/`.
  - Generate draft with existing `call_api`.
  - Save to `drafts/batch_XXX/ep_NNN.txt`.
  - Review and save JSON/Markdown.
  - If blocked, archive original via `save_rewrite_attempt`, rewrite once, save draft, review again.
  - If still blocked, set state review as blocked, print review path and return `False`.
  - If pass/warning, update batch continuity and continue.
- After loop, write batch summary, mark waiting confirmation, print OpenClaw-friendly absolute paths and return `True`.

- [ ] **Step 10: Add confirmation phase**

Add:

```python
def phase_confirm_draft_batch(config: dict, state: StateManager):
    pending = state.get_pending_script_batch()
    if not pending:
        print("没有等待确认的草稿批次。")
        return False
    batch_id = pending["batch_id"]
    episodes = pending["episodes"]
    promoted = promote_batch_to_scripts(config["output_dir"], batch_id, episodes)
    batch_state = load_continuity_state(config["output_dir"], batch_id)
    save_continuity_state(config["output_dir"], batch_state)
    state.confirm_script_batch([str(p) for p in promoted])
    for ep in episodes:
        state.episode_completed(ep, chars=len((Path(config["output_dir"]) / "scripts" / f"ep_{ep:03d}.txt").read_text(encoding="utf-8")))
    state.save()
    print("草稿批次已确认并固化到 scripts/:")
    for path in promoted:
        print(f"  {path.resolve()}")
    return True
```

- [ ] **Step 11: Add CLI flags**

Modify `main()` parser:

```python
parser.add_argument("--confirm-draft-batch", action="store_true", help="确认当前草稿批次并固化到 scripts/")
parser.add_argument("--review-draft", action="store_true", help="重新审核指定草稿集")
parser.add_argument("--rewrite-draft", action="store_true", help="重写指定草稿集")
parser.add_argument("--episode", type=int, help="草稿操作的集数")
parser.add_argument("--batch-size", type=int, help="本次剧本草稿批次数")
```

Before phase dispatch:

```python
if args.confirm_draft_batch:
    phase_confirm_draft_batch(config, state)
    return
```

Wire script phase:

```python
elif args.phase == "script":
    _run_phase(state, "script", lambda: phase_script(config, args.start, args.end, args.dry_run, state, args.batch_size))
```

Do not implement `--review-draft` and `--rewrite-draft` as stubs; either wire them fully in Task 5 or reject with a clear message and non-zero return in this task. The Task 5 docs must match the final behavior.

- [ ] **Step 12: Run orchestration tests**

Run:

```bash
python -m unittest tests.drama.test_pipeline_script_workflow -v
```

Expected: PASS.

- [ ] **Step 13: Run all unit tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 14: Commit Task 4**

```bash
git add skills/drama/tools/pipeline.py tests/drama/test_pipeline_script_workflow.py
git commit -m "feat: gate script generation with draft reviews"
```

---

### Task 5: Skill Documentation And Platform Instructions

**Files:**
- Modify: `skills/drama/SKILL.md`
- Modify: `skills/drama/prompts/decision.md`
- Modify: `agents/script-writer.md`
- Modify: `README.md`
- Test: `tests/drama/test_script_workflow.py`

**Interfaces:**
- Consumes:
  - New CLI flags from Task 4.
  - Draft output paths from Task 1.
- Produces:
  - Cross-platform instructions that describe the draft confirmation workflow without assuming OpenClaw-only APIs.

- [ ] **Step 1: Add failing documentation tests**

Append to `tests/drama/test_script_workflow.py`:

```python
class ScriptDocumentationTests(unittest.TestCase):
    def test_skill_docs_describe_draft_confirmation(self):
        text = Path("skills/drama/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("drafts/", text)
        self.assertIn("--confirm-draft-batch", text)
        self.assertIn("OpenClaw", text)

    def test_decision_prompt_blocks_next_episode_on_severe_issue(self):
        text = Path("skills/drama/prompts/decision.md").read_text(encoding="utf-8")
        self.assertIn("当前集未通过", text)
        self.assertIn("不得生成下一集", text)

    def test_script_writer_mentions_draft_first_output(self):
        text = Path("agents/script-writer.md").read_text(encoding="utf-8")
        self.assertIn("草稿", text)
        self.assertIn("严重问题", text)
```

- [ ] **Step 2: Run documentation tests to verify fail**

Run:

```bash
python -m unittest tests.drama.test_script_workflow.ScriptDocumentationTests -v
```

Expected: FAIL because docs do not mention the new workflow.

- [ ] **Step 3: Update `skills/drama/SKILL.md` stage 3 section**

Replace stage 3 script command guidance with:

```markdown
# 阶段3: 剧本编写（用户确认策略后："开始写剧本"）
python tools/pipeline.py --config {config} --phase script --start 1 --end 10 --batch-size 5

阶段3 是串行草稿工作流：
1. 每集先写入 `{output_dir}/drafts/batch_XXX/ep_NNN.txt`
2. 每集写完立即 AI 审核
3. 严重问题自动定向重写一次
4. 重写后仍有严重问题则暂停，必须由编剧选择人工修改或再次 AI 重写
5. 当前集未通过，不得生成下一集
6. 每满 `script_batch_size` 集暂停，等待编剧确认
7. 编剧确认后运行：
   `python tools/pipeline.py --config {config} --confirm-draft-batch`
8. 确认后才复制到 `{output_dir}/scripts/`

OpenClaw 主场景：agent 应直接把 batch summary 和 draft 文件路径发给用户；其他平台至少必须输出绝对路径，方便编剧打开审阅。
```

- [ ] **Step 4: Update `decision.md` stage 3 rules**

Replace the “阶段3 不需要监督层审核” block with rules that say:

```markdown
阶段3 不走骨架/策略监督层审核，但必须执行单集 AI 质量门控。

核心规则：
1. 当前集未通过，不得生成下一集。
2. 草稿先进入 `drafts/`，不得直接进入 `scripts/`。
3. 严重问题自动定向重写一次。
4. 重写后仍有严重问题，决策层必须暂停并引导编剧选择：人工修改、AI 再改一次、调整规则重写、放弃本批。
5. 每批达到 `script_batch_size` 后暂停，展示 batch summary 和草稿路径。
6. 未收到编剧确认，不得运行 `--confirm-draft-batch`。
```

- [ ] **Step 5: Update `agents/script-writer.md`**

Add:

```markdown
## 草稿优先输出

剧本编写 Agent 只负责产出单集草稿，不宣布其为正式剧本。正式固化由决策层在编剧确认批次后执行。

若审核报告指出严重问题，重写时必须围绕严重问题定向修复，保留已成立的核心事件、人物状态和有效情绪回报。
```

- [ ] **Step 6: Update `README.md`**

Add one feature bullet:

```markdown
- **草稿质量门控**：剧本阶段逐集串行生成，先写入 drafts，每集 AI 审核并在严重问题时自动定向重写，编剧确认后才固化到 scripts。
```

Update usage examples:

```markdown
写前5集剧本草稿
确认当前草稿批次
重写第3集草稿
```

- [ ] **Step 7: Run documentation tests**

Run:

```bash
python -m unittest tests.drama.test_script_workflow.ScriptDocumentationTests -v
```

Expected: PASS.

- [ ] **Step 8: Run all tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 5**

```bash
git add skills/drama/SKILL.md skills/drama/prompts/decision.md agents/script-writer.md README.md tests/drama/test_script_workflow.py
git commit -m "docs: document script draft quality gate"
```

---

## Final Verification

- [ ] Run all unit tests:

```bash
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] Run CLI help:

```bash
python skills/drama/tools/pipeline.py --help
```

Expected: help includes `--confirm-draft-batch`, `--review-draft`, `--rewrite-draft`, `--episode`, and `--batch-size`.

- [ ] Run a dry script phase on a fixture config if available:

```bash
python skills/drama/tools/pipeline.py --config path/to/config.json --phase script --start 1 --end 2 --batch-size 2 --dry-run
```

Expected: prints draft prompt lengths and does not write to `scripts/`.

- [ ] Check git status:

```bash
git status --short
```

Expected: clean working tree after final commit.

## Self-Review Notes

- Spec coverage: draft-first output, per-episode AI review, automatic first rewrite, human confirmation, continuity context, CLI confirmation, state resume behavior, and cross-platform constraints are covered.
- Wording scan: no task uses unresolved filler wording; Task 4 explicitly requires either full wiring or clear rejection for draft review/rewrite CLI flags.
- Type consistency: helper names match imports used by later tasks; `StateManager` method names match tests and pipeline usage.


