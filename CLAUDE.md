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
