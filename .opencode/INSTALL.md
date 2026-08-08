# Installing fangcun for OpenCode

## Prerequisites

- [OpenCode.ai](https://opencode.ai) installed
- Python 3.10+

## Installation

Add fangcun to the `plugin` array in your `opencode.json` (global or project-level):

```json
{
  "plugin": ["fangcun@git+https://github.com/YOUR_USER/fangcun.git"]
}
```

Restart OpenCode. The plugin auto-installs and registers all skills.

**Or for local development**, copy the `.opencode/plugins/fangcun.js` file to `~/.config/opencode/plugins/fangcun.js` and add the skills path to your `opencode.json`:

```json
{
  "skills": {
    "paths": ["~/.claude/skills/fangcun/skills"]
  }
}
```

## Usage

Use OpenCode's native `skill` tool:

```
use skill tool to list skills
use skill tool to load fangcun/drama
```

## Tool Mapping

When skills reference Claude Code tools:
- `Bash(python *)` → Shell execution (`python ...`) — natively supported
- `Read`/`Write`/`Edit` → OpenCode's native file tools
- `Skill` → OpenCode's native `skill` tool

See `references/platform-tools.md` for full mapping.
