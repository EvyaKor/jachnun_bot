# Jachnun Express — WhatsApp Order Bot

## Project Identity
**Project Name:** Jachnun Express (ג'חנון אקספרס)
**Type:** WhatsApp ordering bot for a Jachnun/Kubenia home food business
**Stack:** Python · FastAPI · Twilio (WhatsApp) · SQLAlchemy · PostgreSQL · pytest
**Deployed on:** Render (free tier) — Render Postgres for persistent storage

---

## Architecture Overview

```
WhatsApp user → Twilio → POST /webhook → FastAPI → handle_message()
                                                        ↓
                                               state_machine (DB-backed)
                                                        ↓
                                          order_service / menu_service
                                                        ↓
                                          PostgreSQL (SQLAlchemy ORM)
```

- **Webhook:** `POST /webhook` receives Twilio form fields (`From`, `Body`), returns TwiML XML
- **State machine:** DB-backed — `current_state` + `temp_order_data` (JSON) on `Customer` row; in-memory cache (`_sessions` dict) with write-through to DB on every state change
- **Menu:** Dynamic from DB (`MenuItem` table). `is_extra=True` for add-ons; mains listed first, extras after
- **Admin dashboard:** `GET /admin` — orders grouped by Saturday date, with ✅ Confirm / ❌ Cancel buttons; auto-refreshes every 60s
- **Keep-alive:** Pings `RENDER_EXTERNAL_URL/` every 14 min to prevent Render sleep

---

## Full State Machine (8 States)

```
GREETING
  └─► (orders open)   → ADDING_ITEMS  [sends welcome + menu + product images]
  └─► (orders closed) → stays GREETING, sends closure message

ADDING_ITEMS
  └─► user types item number (1–4) → adds to cart, shows updated cart
  └─► "תפריט" / "menu" / "הזמנה" → shows menu without losing cart
  └─► "סיום" (cart empty) → error, stays ADDING_ITEMS
  └─► "סיום" (cart has items) → CHOOSING_DELIVERY
  └─► unrecognized input → friendly re-prompt

CHOOSING_DELIVERY
  └─► "1" → self-pickup (free) → AWAITING_NAME
  └─► "2" → delivery to Hod HaSharon (₪15) → [if subtotal < ₪70: block] → AWAITING_ADDRESS
  └─► "3" → delivery to Kfar Saba (₪25)    → [if subtotal < ₪70: block] → AWAITING_ADDRESS
  └─► "חזור" → back to ADDING_ITEMS (cart preserved)
  └─► unrecognized → re-prompt with options

AWAITING_ADDRESS
  └─► validates: ≥2 words AND at least 1 digit → AWAITING_NAME
  └─► invalid → re-prompt with example

AWAITING_NAME
  └─► any text → saves name → AWAITING_PICKUP_TIME

AWAITING_PICKUP_TIME
  └─► any text → saves pickup time → CONFIRMING_ORDER

CONFIRMING_ORDER
  └─► "אישור" → CHOOSING_PAYMENT
  └─► "עריכה" or "2" → ADDING_ITEMS (back to cart)
  └─► unrecognized → re-prompt

CHOOSING_PAYMENT
  └─► "1" (מזומן) → create order in DB, notify Gabriel → reset to GREETING
  └─► "2" (ביט)    → create order in DB, notify Gabriel, send Gabriel's payment number → reset to GREETING
  └─► "3" (פייבוקס)→ create order in DB, notify Gabriel, send Gabriel's payment number → reset to GREETING
  └─► unrecognized → re-prompt
```

**Global overrides (work from any state):**
- Reset keywords (`שלום`, `היי`, `הי`, `hello`, `hi`, `start`, etc.) → full session reset → GREETING
- `"ביטול"` (in any active order state) → cancel and reset

---

## Business Rules

| Rule | Value |
|---|---|
| Delivery minimum | ₪70 subtotal (before delivery cost) |
| Self-pickup cost | ₪0 |
| Delivery to Hod HaSharon | ₪15 |
| Delivery to Kfar Saba | ₪25 |
| Business address | בני ברית 17, הוד השרון |
| Pickup time | Free text (no slot validation) |
| Order cutoff | Friday 11:00 AM Israel time |
| Orders reopen | Sunday automatically |

---

## Order Cutoff Logic (`services/order_service.py`)

- `is_orders_closed()` returns `True` if:
  - Friday (`weekday == 4`) AND `hour >= 11` (Israel time)
  - Saturday (`weekday == 5`) — all day
- Auto-reopens Sunday morning — no admin action needed
- Gabriel does NOT type any commands — fully automatic
- `get_next_saturday()` always returns the upcoming Saturday in `DD/MM/YYYY` format using `Asia/Jerusalem` timezone

---

## Payment Flow

1. Customer confirms order → prompted for payment method (cash / bit / paybox)
2. Order is saved to DB with status `"ממתין"` immediately
3. For bit/paybox: customer receives Gabriel's payment phone number
4. Gabriel receives WhatsApp notification including the payment method
5. Gabriel reviews in dashboard and manually confirms (✅) once payment is received
6. Status transitions: `ממתין` → `אושר` or `בוטל`

---

## Database Models (`database/models.py`)

| Table | Key fields |
|---|---|
| `customers` | `phone_number`, `name`, `current_state`, `temp_order_data` (JSON) |
| `menu_items` | `name`, `description`, `price`, `is_dairy`, `is_available`, `is_extra` |
| `orders` | `customer_id`, `pickup_date`, `pickup_time`, `delivery_type`, `delivery_cost`, `delivery_address`, `total_price`, `status` |
| `order_items` | `order_id`, `menu_item_id`, `quantity` |

**Menu seed** (`db.py`): ג'חנון ₪25, קובנייה ₪20 (חלבי), ביצה נוספת ₪3 (extra), רסק עגניות+סחוג ₪3 (extra)

---

## Environment Variables (`.env` / Render Dashboard)

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (Render Postgres) |
| `TWILIO_ACCOUNT_SID` | Yes | Twilio credentials |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio credentials |
| `TWILIO_WHATSAPP_NUMBER` | No | Defaults to sandbox number |
| `GABRIEL_PHONE` | No | Gabriel's WhatsApp (`whatsapp:+972...`), has default |
| `GABRIEL_PAYMENT_PHONE` | No | Gabriel's payment phone shown to customers, has default |
| `RENDER_EXTERNAL_URL` | No | Enables keep-alive pings on Render |

---

## Core Rules (Always Follow)

1. **Python style:** `snake_case` for all variables, functions, and file names
2. **Docstrings:** Every function and class must have a clear docstring
3. **Git discipline:** Commit after every major feature or milestone with a meaningful message
4. **State Machine:** All chat logic must go through the state machine — no ad-hoc if/else trees
5. **Secrets:** All API keys and tokens go in `.env` — never hardcoded, never committed
6. **Modularity:** Keep files small and single-purpose (routes, models, services, handlers)
7. **Error handling:** Always return a user-friendly Hebrew WhatsApp message on failure — never expose stack traces
8. **No "פרווה":** The business is not labeled pareve — never use this word anywhere in messages, menu, or UI
9. **Hebrew RTL:** All user-facing messages are in Hebrew. Formatting must read right-to-left. Never mix Hebrew and English within a single sentence.
10. **No magic numbers:** All business constants (delivery costs, minimum order, etc.) must be named constants at the top of the file

---

## Testing (`tests/test_bot.py`)

- **~190 tests** covering full conversation flows, edge cases, and cutoff logic
- Uses `StaticPool` SQLite in-memory DB shared across test session
- **autouse fixture** patches `handlers.message_handler.is_orders_closed` → `False` so tests don't depend on real day/time
- `TestOrderCutoff`: patches `handlers.message_handler.is_orders_closed` directly per test
- Run: `python -m pytest tests/test_bot.py -v`

---

## File Structure

```
jachnun_bot/
├── CLAUDE.md
├── README.md
├── .env                        # secrets (gitignored)
├── .gitignore
├── requirements.txt
├── main.py                     # FastAPI app, webhook, admin dashboard, /health
├── state_machine.py            # DB-backed state machine with in-memory cache
├── database/
│   ├── models.py               # SQLAlchemy models
│   └── db.py                   # DB engine, SessionLocal, seed_menu
├── services/
│   └── order_service.py        # create_order, notify_gabriel, is_orders_closed, get_next_saturday
├── handlers/
│   └── message_handler.py      # handle_message — all chat state logic
└── tests/
    └── test_bot.py             # ~190 pytest tests
```

---

## Deployment

| Item | Value |
|---|---|
| Platform | Render (free tier) |
| Database | Render Postgres (free tier) — `DATABASE_URL` set in Render dashboard |
| Keep-alive | `RENDER_EXTERNAL_URL` env var → pings `/` every 14 min |
| Twilio webhook | `https://<render-url>/webhook` |
| Health check | `GET /health` → `{"status": "ok"}` |
| Auto-deploy | On every `git push` to `main` |

---

## Progress Log

### Done
- [x] Full project scaffolded and deployed
- [x] DB-backed state machine (8 states)
- [x] Dynamic menu from DB
- [x] Full ordering flow (cart → delivery → address → name → time → confirm → payment)
- [x] Address validation (≥2 words + digit)
- [x] Delivery minimum ₪70 enforced
- [x] 3-option payment flow (cash / bit / paybox)
- [x] Gabriel notified on new order (includes payment method)
- [x] Automatic order cutoff (Friday 11:00 AM, all Saturday)
- [x] Admin dashboard with ✅/❌ per order, revenue stats, mobile-first
- [x] Israel timezone (Asia/Jerusalem) for all date/time logic
- [x] ~190 passing tests with time-mocked fixtures
- [x] System audit: removed dead code, fixed images-when-closed bug
- [x] Migrated DB to PostgreSQL (Render Postgres) — data persists across deploys
- [x] Admin dashboard mobile-first redesign (iPhone optimized, auto-refresh, clickable phone)
- [x] Phone numbers moved to env vars (GABRIEL_PHONE, GABRIEL_PAYMENT_PHONE)
- [x] /health endpoint added

### Up Next
- [ ] Add `GABRIEL_PHONE` and `GABRIEL_PAYMENT_PHONE` to Render env vars dashboard
- [ ] Real customer onboarding + end-to-end test with real WhatsApp messages
