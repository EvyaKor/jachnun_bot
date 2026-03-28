# Jachnun Express – WhatsApp Order Bot

## Project Identity
**Project Name:** Jachnun Express (ג'חנון אקספרס)
**Type:** WhatsApp ordering bot for a Jachnun/Kubenia home food business
**Stack:** Python · FastAPI · Twilio (WhatsApp) · SQLAlchemy · SQLite · pytest
**Deployed on:** Render (free tier — SQLite resets on redeploy; migrate to Postgres before going live)

---

## Architecture Overview

```
WhatsApp user → Twilio → POST /webhook → FastAPI → handle_message()
                                                        ↓
                                               state_machine (DB-backed)
                                                        ↓
                                               order_service / menu_service
                                                        ↓
                                               SQLite (SQLAlchemy ORM)
```

- **Webhook:** `POST /webhook` receives Twilio form fields (`From`, `Body`), returns TwiML XML
- **State machine:** DB-backed — `current_state` + `temp_order_data` (JSON) stored on `Customer` row; in-memory cache (`_sessions` dict) with write-through to DB
- **Menu:** Dynamic from DB (`MenuItem` table). `is_extra=True` for add-ons; mains listed first, extras after.
- **Admin dashboard:** `GET /admin` — orders grouped by Saturday date, with ✅ Confirm / ❌ Cancel buttons
- **Keep-alive:** Pings `RENDER_EXTERNAL_URL/` every 14 min to prevent Render sleep

---

## State Machine Flow

```
GREETING
  └─► (orders open) → ADDING_ITEMS
  └─► (orders closed) → stays GREETING, sends closure message

ADDING_ITEMS
  └─► user types item number/name → adds to cart
  └─► "סיום" / "הזמנה" → CHOOSING_DELIVERY

CHOOSING_DELIVERY
  └─► "1" → self-pickup → AWAITING_NAME
  └─► "2" / "3" → delivery → AWAITING_ADDRESS

AWAITING_ADDRESS
  └─► validates: ≥2 words AND at least 1 digit → AWAITING_NAME

AWAITING_NAME
  └─► any text → saves name → AWAITING_PICKUP_TIME

AWAITING_PICKUP_TIME
  └─► validates against PICKUP_SLOTS → CONFIRMING_ORDER

CONFIRMING_ORDER
  └─► "כן" → creates order in DB, notifies Gabriel → ORDER_PLACED (then resets to GREETING)
  └─► "לא" → ADDING_ITEMS (back to cart)

ORDER_PLACED → immediately resets to GREETING
```

---

## Key Constants (handlers/message_handler.py)

| Constant | Value |
|---|---|
| `DELIVERY_OPTIONS["1"]` | איסוף עצמי — cost 0 |
| `DELIVERY_OPTIONS["2"]` | משלוח רגיל — cost 15 |
| `DELIVERY_OPTIONS["3"]` | משלוח מהיר — cost 25 |
| `PICKUP_SLOTS` | `["09:00", "10:00", "11:00", "12:00"]` |
| `BUSINESS_INFO["address"]` | רחוב הרב קוק 12, רמת גן |
| `PRODUCT_IMAGES` | List of CDN image URLs for menu items |

---

## Order Cutoff Logic (services/order_service.py)

- `is_orders_closed()` returns `True` if:
  - Friday (`weekday == 4`) AND `hour >= 11`
  - Saturday (`weekday == 5`) — all day
- Auto-reopens Sunday morning (no action needed)
- Gabriel does NOT type any commands — fully automatic
- Closure message: `"ההזמנות לשבת הקרובה נסגרו..."` (see `ORDERS_CLOSED_MSG`)
- Images are only sent when state transitions from GREETING → ADDING_ITEMS (not when closed)

---

## Database Models (database/models.py)

| Table | Key fields |
|---|---|
| `customers` | `phone_number`, `name`, `current_state`, `temp_order_data` (JSON) |
| `menu_items` | `name`, `description`, `price`, `is_dairy`, `is_available`, `is_extra` |
| `orders` | `customer_id`, `pickup_date`, `pickup_time`, `delivery_type`, `delivery_cost`, `delivery_address`, `total_price`, `status` |
| `order_items` | `order_id`, `menu_item_id`, `quantity` |

Menu seed (db.py): ג'חנון ₪25, קובנייה ₪20 (חלבי), ביצה נוספת ₪3 (extra), רסק עגניות+סחוג ₪3 (extra)

---

## Testing (tests/test_bot.py)

- **~190 tests** covering full conversation flows, edge cases, and cutoff logic
- Uses `StaticPool` SQLite in-memory DB shared across test session
- **autouse fixture** patches `handlers.message_handler.is_orders_closed` → `False` so tests don't depend on real day/time
- `TestOrderCutoff`: patches `handlers.message_handler.is_orders_closed` directly per test
- Run: `python -m pytest tests/test_bot.py -v`

---

## Core Rules (Always Follow)

1. **Python style:** `snake_case` for all variables, functions, and file names
2. **Docstrings:** Every function and class must have a clear docstring
3. **Git discipline:** Commit after every major feature or milestone with a meaningful message
4. **State Machine:** All chat logic must go through the state machine — no ad-hoc if/else trees
5. **Secrets:** All API keys and tokens go in `.env` — never hardcoded, never committed
6. **Modularity:** Keep files small and single-purpose (routes, models, services, handlers)
7. **Error handling:** Always return a user-friendly WhatsApp message on failure — never expose stack traces
8. **No "פרווה":** The business is not labeled pareve — never use this word anywhere in messages, menu, or UI

---

## Project Structure

```
jachnun_bot/
├── CLAUDE.md
├── README.md
├── .env                        # secrets (gitignored)
├── .gitignore
├── requirements.txt
├── main.py                     # FastAPI app, Twilio webhook, admin dashboard
├── state_machine.py            # DB-backed state machine with in-memory cache
├── database/
│   ├── models.py               # SQLAlchemy models
│   └── db.py                   # DB engine, SessionLocal, seed_menu
├── services/
│   └── order_service.py        # create_order, notify_gabriel, is_orders_closed, get_next_saturday
├── handlers/
│   └── message_handler.py      # handle_message — all chat state logic
├── tests/
│   └── test_bot.py             # ~190 pytest tests
└── jachnun.db                  # SQLite DB (gitignored)
```

---

## Deployment Notes

- **Platform:** Render (free tier)
- **Keep-alive:** `RENDER_EXTERNAL_URL` env var → pings `/` every 14 min
- **Database:** PostgreSQL on Render (free tier) — `DATABASE_URL` env var set in Render dashboard, data persists across deploys
- **Twilio sandbox:** Set webhook URL to `https://<render-url>/webhook`
- **Gabriel's phone:** `whatsapp:+972539475881` (hardcoded in order_service.py — move to `.env` if needed)

---

## Progress Log

### Done
- [x] Full project scaffolded and deployed
- [x] DB-backed state machine
- [x] Dynamic menu from DB
- [x] Full ordering flow (cart → delivery → address → name → time → confirm → payment)
- [x] Address validation (≥2 words + digit)
- [x] Automatic order cutoff (Friday 11:00 AM, all Saturday)
- [x] Admin dashboard with ✅/❌ per order, revenue stats
- [x] Gabriel WhatsApp notification on new order
- [x] Israel timezone (Asia/Jerusalem) for all date/time logic
- [x] ~190 passing tests with time-mocked fixtures
- [x] System audit: removed dead code, fixed images-when-closed bug, updated type hints
- [x] Migrated DB to PostgreSQL (Render Postgres free tier) — data persists across deploys
- [x] Admin dashboard mobile-first redesign (iPhone optimized, auto-refresh, clickable phone)

### Up Next
- [ ] Real customer onboarding + end-to-end test with real WhatsApp messages
- [ ] Optional: SMS fallback if WhatsApp unavailable
