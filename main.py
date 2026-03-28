"""
ג'חנון אקספרס — שרת FastAPI ראשי.
מקבל הודעות וואטסאפ דרך Twilio ומחזיר תשובות בעברית.
"""

from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from database.db import init_db, seed_menu
from handlers.message_handler import handle_message
from state_machine import get_state, set_state, ChatState

app = FastAPI(title="ג'חנון אקספרס", version="1.0.0")


@app.on_event("startup")
def startup():
    """אתחול מסד הנתונים וזריעת התפריט בעת הפעלת השרת."""
    init_db()
    seed_menu()


@app.get("/")
def root():
    """בדיקת חיים."""
    return {"status": "פעיל", "service": "ג'חנון אקספרס 🫓"}


@app.post("/webhook", response_class=PlainTextResponse)
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(...),
):
    """
    נקודת הכניסה לכל הודעת וואטסאפ נכנסת מ-Twilio.
    מחלץ מספר טלפון וגוף ההודעה, מחזיר TwiML עם התשובה.
    """
    phone = From.replace("whatsapp:", "").strip()
    body = Body.strip()

    # הזמנה ראשונה — אם אין session עדיין, נתחיל מברכה
    state = get_state(phone)
    if state == ChatState.GREETING and body.lower() not in ["שלום", "היי", "הי", "hello", "hi"]:
        # לקוח חדש שכתב משהו אחר — עדיין נברך אותו
        pass

    reply = handle_message(phone, body)

    response = MessagingResponse()
    response.message(reply)
    return str(response)
