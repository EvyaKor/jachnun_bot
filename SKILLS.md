# Claude Code Skills — Jachnun Express

This document lists all configured skills for this project and how they're used.

---

## Available Skills

### Built-in Claude Code Skills

| Skill | Purpose | Trigger |
|---|---|---|
| **update-config** | Configure Claude Code settings.json, set env vars, manage permissions, setup hooks | Use when: need to set up recurring tasks, configure settings, grant permissions |
| **simplify** | Review code for quality, reuse, efficiency; fix issues found | After major refactors or when touching multiple files |
| **loop** | Run commands/prompts on recurring intervals (e.g., `loop 5m /status`) | Use for: monitoring, status checks, recurring health checks |
| **claude-api** | Build apps with Claude API or Anthropic SDK | Trigger when: code imports `anthropic`, or user asks to use Claude API/Agent SDK |

### Project-Specific Skills

| Skill | Purpose | Created |
|---|---|---|
| **grillme** | Ask clarifying questions before implementing features — ensures alignment on requirements | Custom for Jachnun Express |

---

## How We Use Skills

### `grillme` (PreToolUse Hook)
**When:** Before writing new code in core files (main.py, services/, handlers/)

**What it does:** Prompts to clarify:
1. What is the requirement?
2. What should this do?
3. Any edge cases?

**Hook config:** `.claude/settings.local.json` → `PreToolUse` on `Write|Edit`

### `simplify`
**When:** After major refactors (like the audit we just did)

**How:**
```
Use the Skill tool with:
skill: "simplify"
```

### `loop`
**When:** Monitor Render deployment health, check test status regularly, poll Postgres connection

**How:**
```
loop 5m /render-status  (every 5 minutes)
loop 10m /tests        (every 10 minutes)
```

### `update-config`
**When:**
- Set up environment variables
- Configure permissions
- Set up recurring hooks
- Configure recurring tasks

**How:**
```
Use the Skill tool with:
skill: "update-config"
args: "set MY_VAR=value" or "add permission X"
```

### `claude-api`
**When:**
- Need to call Claude API from within Python code
- Building features that use Claude models

**How:** Automatically triggers if code imports `anthropic`

---

## Setup & Configuration

All skills are installed via `update-config` in settings.json.

To verify installed skills, check:
- `~/.claude/settings.json` (global) or
- `.claude/settings.local.json` (project-specific)

---

## Future Skills (Candidates)

- **security-scan** — audit code for vulnerabilities
- **performance-check** — profile code for bottlenecks
- **playwright-test** — automate browser testing
