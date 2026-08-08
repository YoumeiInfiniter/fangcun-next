# Script Serial Quality Gate Design

## Objective

Improve the drama script-writing stage by replacing batch-style generation with a controlled serial workflow. The new workflow must prevent low-quality or inconsistent episodes from contaminating later episodes, while keeping the writer in control before drafts become official scripts.

## Current Problem

The current script stage writes a requested episode range directly into `scripts/ep_NNN.txt`. It passes only limited previous context and has no dedicated per-episode review gate. This creates several quality risks:

- Episodes can drift in character state, relationship progress, and unresolved hooks.
- A bad episode can become the context for later episodes.
- The writer cannot review a small batch before the output is treated as official.
- Existing validation only catches shallow format and length issues.

## Recommended Approach

Use serial generation with two quality gates:

1. Per-episode AI review gate.
2. Per-batch human confirmation gate.

The workflow writes episodes into `drafts/` first. Drafts are only copied or promoted into `scripts/` after the writer confirms the batch.

## Workflow

```text
Generate episode N draft
→ Save to drafts/batch_XXX/ep_NNN.txt
→ AI reviews the draft
→ If no severe issues: update temporary continuity state and continue
→ If severe issues: AI rewrites using the review report
→ AI reviews again
→ If severe issues remain: pause and ask the writer to choose the next action
→ Continue only after episode N passes
→ After batch_size episodes: pause for writer confirmation
→ On confirmation: promote drafts to scripts/ and persist continuity state
```

The key rule is:

**The current episode must pass its quality gate before the next episode can be generated.**

## Writer Decisions

When a rewrite still has severe issues, the workflow pauses and asks the writer to choose one of these actions:

- Manually edit the draft, then rerun AI review.
- Ask AI to rewrite again using the latest review report.
- Adjust writing rules or episode-specific requirements, then rewrite.
- Abandon the current batch.

When a batch is complete, the workflow pauses and asks the writer to choose one of these actions:

- Confirm and promote the batch into `scripts/`.
- Rewrite specific episodes.
- Change `batch_size` or writing rules before continuing.
- Abandon the batch.

No timeout or missing reply should promote drafts automatically.

## Draft And Official Output

Recommended output structure:

```text
output_dir/
  scripts/
    ep_001.txt
  drafts/
    batch_001/
      ep_001.txt
      ep_002.txt
      reviews/
        ep_001_review.md
        ep_002_review.md
      rewrites/
        ep_001_attempt_01.txt
      continuity_state.json
      batch_summary.md
  state.json
```

`scripts/` contains only writer-confirmed episodes. `drafts/` contains pending work and review artifacts.

## Continuity Context

Do not pass all previous episode text indefinitely. Maintain a structured continuity state and combine it with focused episode context.

Each generated episode should receive:

- Current episode skeleton fragment.
- Adaptation strategy.
- Relevant event table excerpt.
- Relevant original novel excerpts.
- Previous confirmed continuity state.
- Current batch temporary continuity state.
- Previous episode draft or official script.
- Open hooks and unresolved payoffs.
- Character state table.
- Repetition blacklist for used plot devices, reversals, and emotional beats.

Draft episodes inside the same pending batch may inform later drafts in that batch. They must not become official context for the next batch until the writer confirms them.

## AI Review Gate

The AI review should produce a structured report with at least:

- Overall verdict: pass, warning, or blocked.
- Severe issues.
- Non-blocking issues.
- Continuity issues.
- Hook and opening checks.
- Format checks.
- Rewrite instructions when blocked.

Severe issues block progress. Non-blocking issues are saved for the writer but do not stop the workflow.

Initial severe issue categories:

- Invalid script format: missing scene structure, missing `△`, malformed episode text.
- Continuity conflict with previous episode or continuity state.
- Failure to resolve or acknowledge the previous episode hook.
- Missing episode-ending hook.
- Severe filler: excessive daily process, environment padding, or empty dialogue.
- Drift from episode skeleton.
- Character voice or relationship collapse.
- Severe length mismatch.

## Rewrite Behavior

Automatic rewrite must be targeted, not a free second draft. The rewrite prompt should include:

- The original draft.
- The review report.
- The current episode requirements.
- The continuity state.
- A clear instruction to fix severe issues while preserving approved beats.

After rewriting, the episode must be reviewed again. If severe issues remain, the system pauses for writer decision instead of continuing.

## Configuration

Recommended config fields:

```json
{
  "script_batch_size": 5,
  "script_review": true,
  "script_auto_rewrite": true,
  "script_context_mode": "continuity_state_plus_previous_episode"
}
```

`script_batch_size` can be set at project start and adjusted during conversation before continuing the next batch.

The design intentionally does not cap AI rewrite attempts in configuration at first. After a failed automatic rewrite, the writer explicitly chooses whether AI should try again.

## Command Surface

The existing `--phase script --start N --end M` command can remain, but its behavior should become gated:

- Generate up to `script_batch_size` drafts.
- Stop at the batch confirmation gate.
- Do not write to `scripts/` until confirmation.

Additional operations should be supported with these command flags:

- `--confirm-draft-batch`: confirm the current pending batch and copy drafts into `scripts/`.
- `--review-draft --episode N`: rerun AI review for a manually edited draft.
- `--rewrite-draft --episode N`: ask AI to rewrite a blocked draft episode.
- `--batch-size N`: override `script_batch_size` for the next script run.

## State Management

State should record:

- Current script batch id.
- Draft episodes in the current batch.
- Per-episode review status.
- Whether an episode is blocked.
- Whether a batch is awaiting writer confirmation.
- Confirmed episodes.
- Continuity state version.

Resume should never skip a pending writer confirmation. If the workflow is waiting for confirmation, resume should report the pending batch and required action.

## Testing Strategy

Use focused tests around pure helper functions and state transitions:

- Draft paths are separated from official `scripts/` paths.
- Severe review result blocks the next episode.
- Passing review permits the next episode.
- Failed rewrite pauses for writer decision.
- Batch completion pauses before promotion.
- Promotion copies or moves drafts to `scripts/`.
- Resume reports pending confirmation instead of continuing.

Prompt behavior should be pressure-tested with small fixture drafts:

- A draft with no ending hook should be blocked.
- A draft that ignores the previous episode hook should be blocked.
- A draft with minor polish issues should warn but not block.

## Non-Goals

- Do not redesign skeleton or adaptation generation in this change.
- Do not add a full human UI.
- Do not make drafts auto-promote after inactivity.
- Do not pass all prior scripts as raw context forever.

## Implementation Decisions

- Draft promotion copies files into `scripts/` and preserves draft history.
- AI review writes both `ep_NNN_review.json` for automation and `ep_NNN_review.md` for the writer.
- The first blocked review triggers one automatic targeted rewrite. If the rewritten draft remains blocked, the workflow pauses for writer decision. Additional AI rewrites happen only after the writer explicitly requests them.
- CLI names are `--confirm-draft-batch`, `--review-draft --episode N`, `--rewrite-draft --episode N`, and `--batch-size N`.

