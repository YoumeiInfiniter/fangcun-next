# Installing fangcun for Codex

Enable fangcun in Codex via native skill discovery. Just clone and symlink.

## Prerequisites

- Git
- Python 3.10+

## Installation

1. **Ensure fangcun is available** (clone or copy to a permanent location):
   ```bash
   # If using Clawdbot/OpenClaw:
   # Already at ~/.agents/skills/fangcun/ — skip this step

   # Otherwise, clone or copy to ~/.codex/fangcun:
   git clone <your-repo-url> ~/.codex/fangcun
   ```

2. **Create the skills symlink:**
   ```bash
   mkdir -p ~/.agents/skills
   ln -s ~/.codex/fangcun/skills ~/.agents/skills/fangcun
   ```

   **Windows (PowerShell):**
   ```powershell
   New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.agents\skills"
   cmd /c mklink /J "$env:USERPROFILE\.agents\skills\fangcun" "$env:USERPROFILE\.codex\fangcun\skills"
   ```

3. **Restart Codex** (quit and relaunch) to discover the skills.

## Verify

```bash
ls ~/.agents/skills/fangcun
```

You should see the `drama/` directory.

## Tool Mapping

Fangcun skills use `python` commands. Codex natively supports shell execution.
See `references/platform-tools.md` for full tool mapping across platforms.
