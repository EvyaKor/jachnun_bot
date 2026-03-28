# Jachnun Express – AI Agent (WhatsApp)

## Project Identity
**Project Name:** Jachnun Express
**Type:** WhatsApp-based AI Agent for a food delivery business
**Stack:** Python · FastAPI · Twilio (WhatsApp) · SQLAlchemy · SQLite
**Goal:** A conversational AI agent that handles orders, customer management, and delivery scheduling entirely over WhatsApp.

---

## Architecture Overview
- **Entry point:** WhatsApp webhook via Twilio → FastAPI
- **AI brain:** Claude API (claude-sonnet-4-6) for NLU and response generation
- **State Machine:** Every conversation has a state (e.g. `GREETING`, `BROWSING_MENU`, `AWAITING_ADDRESS`, `CONFIRMING_ORDER`, `ORDER_PLACED`, `AWAITING_PAYMENT`)
- **Database:** SQLite via SQLAlchemy (tables: `customers`, `orders`, `order_items`, `menu_items`)
- **Scheduling:** Delivery time slots managed via the Time MCP

---

## Core Rules (Always Follow)

1. **Python style:** `snake_case` for all variables, functions, and file names
2. **Docstrings:** Every function and class must have a clear docstring
3. **Git discipline:** Commit after every major feature or milestone with a meaningful message
4. **State Machine:** All chat logic must go through the state machine — no ad-hoc if/else trees
5. **Secrets:** All API keys and tokens go in `.env` — never hardcoded, never committed
6. **Modularity:** Keep files small and single-purpose (routes, models, services, handlers)
7. **Error handling:** Always return a user-friendly WhatsApp message on failure — never expose stack traces

---

## Project Structure (Target)
```
jachnun_bot/
├── CLAUDE.md
├── README.md
├── .env                  # secrets (gitignored)
├── .gitignore
├── requirements.txt
├── main.py               # FastAPI app + Twilio webhook
├── state_machine.py      # Chat state logic
├── database/
│   ├── models.py         # SQLAlchemy models
│   └── db.py             # DB connection
├── services/
│   ├── order_service.py
│   ├── menu_service.py
│   └── delivery_service.py
├── handlers/
│   └── message_handler.py
└── jachnun.db            # SQLite DB (gitignored)
```

---

## Available Skills

### MCP Servers
| # | Skill | Source | Purpose | Needs Key? |
|---|-------|--------|---------|------------|
| 1 | GitHub | `@modelcontextprotocol/server-github` | Repo, PRs, issues, branch management | Yes — `GITHUB_PERSONAL_ACCESS_TOKEN` |
| 2 | Git | `@modelcontextprotocol/server-git` | Local git ops: log, diff, blame | No |
| 3 | Memory | `@modelcontextprotocol/server-memory` | Persistent knowledge graph across sessions | No |
| 4 | Sequential Thinking | `@modelcontextprotocol/server-sequential-thinking` | Structured planning before coding | No |
| 5 | Fetch | `@modelcontextprotocol/server-fetch` | Read any URL, doc, or API | No |
| 6 | Brave Search | `@modelcontextprotocol/server-brave-search` | Web research for any topic | Yes — `BRAVE_API_KEY` |
| 7 | Filesystem | `@modelcontextprotocol/server-filesystem` | Safe file read/write with access controls | No |
| 8 | Playwright | `microsoft/playwright-mcp` | Browser automation & UI testing | No |
| 9 | Time | `@modelcontextprotocol/server-time` | Scheduling, timezones, deadlines | No |
| 10 | Google Maps | `@modelcontextprotocol/server-google-maps` | Address validation & routing | Yes — `GOOGLE_MAPS_API_KEY` |
| 11 | Figma | `figma/mcp-server` | Convert Figma designs to production code | Yes — Figma token |

### Claude Code Skills
| # | Skill | Source | Purpose |
|---|-------|--------|---------|
| 1 | Skill Creator | `anthropics/skills` | Interactively build new Claude Code skills |
| 2 | MCP Builder | `ComposioHQ/awesome-claude-skills` | Build production-ready MCP servers |
| 3 | Self-Healing | `PolarOrchid/ClaudeWatch` | Auto-detect and fix broken code/config |
| 4 | Frontend Design | `anthropics/skills` | Build distinctive, production-grade UIs |
| 5 | Webapp Testing | `ComposioHQ/awesome-claude-skills` | Test web apps with Playwright + screenshots |
| 6 | Researcher | `altmbr/claude-research-skill` | Multi-agent deep research & synthesis |
| 7 | Trail of Bits Security | `trailofbits/skills` | Security audit & vulnerability detection |
| 8 | Figma-to-Code | `figma/mcp-server-guide` | Figma design → production code conversion |
| 9 | Superpowers | `obra/superpowers` | TDD, debugging, brainstorming enhancements |
| 10 | Cost Reducer | community | Token & cloud cost optimization |

> API keys live in `~/.claude/settings.json`. Never hardcode or commit them.

---

## Progress Log

### Done
- [x] Git repository initialized
- [x] Connected to GitHub (`EvyaKor/jachnun_bot`)
- [x] README.md created and pushed
- [x] CLAUDE.md initialized
- [x] `.gitignore` created
- [x] `requirements.txt` created
- [x] Python virtual environment set up
- [x] MCP servers configured

### In Progress
- [ ] Scaffold project directory structure
- [ ] Create SQLAlchemy models (`customers`, `orders`, `menu_items`)
- [ ] Set up FastAPI app with Twilio webhook endpoint
- [ ] Build state machine core logic

### Up Next
- [ ] Connect Claude API as the AI brain
- [ ] Build menu browsing flow
- [ ] Build order placement flow
- [ ] Add address validation via Google Maps MCP
- [ ] Add delivery scheduling logic
- [ ] Admin dashboard (optional, via Puppeteer)
- [ ] Deploy to cloud (Railway / Render)
