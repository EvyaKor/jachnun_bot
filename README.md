# ג'חנון אקספרס — WhatsApp Order Bot

בוט וואטסאפ לעסק ביתי של ג'חנון וקובנייה. לקוחות מזמינים ישירות דרך וואטסאפ, גבריאל מאשר דרך דשבורד ניהול.

---

## Tech Stack

| שכבה | טכנולוגיה |
|------|-----------|
| Backend | Python 3 + FastAPI |
| WhatsApp | Twilio (sandbox) → Meta WhatsApp Cloud API (בייצור) |
| Database | PostgreSQL (Render Postgres) |
| ORM | SQLAlchemy 2.0 |
| Hosting | Render (free tier) |
| Tests | pytest — 206 טסטים |

---

## הרצה מקומית

```bash
# שכפל והתקן
git clone https://github.com/EvyaKor/jachnun_bot.git
cd jachnun_bot
python -m venv venv
venv/Scripts/activate  # Windows
pip install -r requirements.txt

# הגדר משתני סביבה
cp .env.example .env
# ערוך .env עם הערכים שלך

# הפעל
uvicorn main:app --reload
```

---

## משתני סביבה

ראה `.env.example` לרשימה מלאה. משתנים חיוניים:

| משתנה | תיאור |
|-------|-------|
| `DATABASE_URL` | PostgreSQL connection string |
| `TWILIO_ACCOUNT_SID` | Twilio credentials |
| `TWILIO_AUTH_TOKEN` | Twilio credentials (גם לאימות webhook) |
| `GABRIEL_PHONE` | וואטסאפ של גבריאל לקבלת התראות |
| `GABRIEL_PAYMENT_PHONE` | מספר לתשלום (מוצג ללקוחות) |
| `ADMIN_USERNAME` | שם משתמש לדשבורד (ברירת מחדל: גבריאל) |
| `ADMIN_PASSWORD` | סיסמה לדשבורד (ברירת מחדל: גבריאל123) |

---

## הרצת טסטים

```bash
venv/Scripts/python.exe -m pytest tests/test_bot.py -v
```

206 טסטים המכסים: זרימת שיחה מלאה, מכונת מצבים, DB, webhook, דשבורד, rate limiting, אבטחה.

---

## ארכיטקטורה

```
WhatsApp → Twilio → POST /webhook → FastAPI → handle_message()
                                                    ↓
                                         state_machine (DB-backed)
                                                    ↓
                                       order_service / menu_service
                                                    ↓
                                       PostgreSQL (SQLAlchemy ORM)
```

**8 מצבי שיחה:** GREETING → ADDING_ITEMS → CHOOSING_DELIVERY → AWAITING_ADDRESS → AWAITING_NAME → AWAITING_PICKUP_TIME → CONFIRMING_ORDER → CHOOSING_PAYMENT

---

## דשבורד ניהול

`GET /admin` — מוגן עם HTTP Basic Auth (גבריאל / גבריאל123)

- הזמנות לשבת הקרובה + היסטוריה
- סיכום כמויות הכנה (רק הזמנות מאושרות)
- ✅ אשר / ❌ בטל לכל הזמנה
- מתרענן אוטומטית כל דקה

---

## Deployment (Render)

Auto-deploy בכל `git push` לענף `main`.

| נקודת קצה | תיאור |
|-----------|-------|
| `GET /` | בדיקת חיים |
| `GET /health` | health check לRender |
| `POST /webhook` | קבלת הודעות מ-Twilio |
| `GET /admin` | דשבורד ניהול |

---

## שלבים הבאים

- [ ] מעבר מ-Twilio sandbox ל-Meta WhatsApp Cloud API
- [ ] בדיקה end-to-end עם לקוחות אמיתיים
