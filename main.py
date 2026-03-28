"""
ג'חנון אקספרס — שרת FastAPI ראשי.
מקבל הודעות וואטסאפ דרך Twilio ומחזיר תשובות בעברית.
כולל דשבורד ניהול להזמנות לגבריאל.
"""

from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from twilio.twiml.messaging_response import MessagingResponse
from database.db import init_db, seed_menu, SessionLocal
from database.models import Order, Customer
from handlers.message_handler import handle_message
from services.order_service import get_next_saturday
from collections import defaultdict

app = FastAPI(title="ג'חנון אקספרס", version="1.0.0")
templates = Jinja2Templates(directory="templates")


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
    reply = handle_message(phone, body)
    response = MessagingResponse()
    response.message(reply)
    return str(response)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    """
    דשבורד ניהול להזמנות — מיועד לגבריאל.
    מציג הזמנות מקובצות לפי שבת עם אפשרות אישור/ביטול.
    """
    db = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .join(Customer)
            .order_by(Order.pickup_date, Order.pickup_time)
            .all()
        )

        grouped = defaultdict(list)
        for order in orders:
            grouped[order.pickup_date or "לא ידוע"].append(order)

        pending = sum(1 for o in orders if o.status == "ממתין")
        revenue = sum(o.total_price for o in orders if o.status != "בוטל")

        return templates.TemplateResponse("admin.html", {
            "request": request,
            "grouped_orders": dict(grouped),
            "total_orders": len(orders),
            "pending_orders": pending,
            "total_revenue": int(revenue),
            "next_saturday": get_next_saturday(),
        })
    finally:
        db.close()


@app.post("/admin/update/{order_id}")
def update_order_status(order_id: int, status: str = Form(...)):
    """
    מעדכן סטטוס הזמנה (אושר / בוטל) מהדשבורד.
    מחזיר חזרה לדף האדמין.
    """
    from fastapi.responses import RedirectResponse
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.status = status
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin", status_code=303)
