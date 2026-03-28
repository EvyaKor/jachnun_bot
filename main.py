"""
ג'חנון אקספרס — שרת FastAPI ראשי.
מקבל הודעות וואטסאפ דרך Twilio ומחזיר תשובות בעברית.
כולל דשבורד ניהול להזמנות לגבריאל.
"""

from fastapi import FastAPI, Form
from fastapi.responses import Response, HTMLResponse, RedirectResponse
from twilio.twiml.messaging_response import MessagingResponse
from database.db import init_db, seed_menu, SessionLocal
from database.models import Order, OrderItem
from sqlalchemy.orm import joinedload
from handlers.message_handler import handle_message, PRODUCT_IMAGES
from state_machine import get_state, ChatState
from services.order_service import get_next_saturday, is_orders_closed
from collections import defaultdict
import asyncio
import httpx
import os

app = FastAPI(title="ג'חנון אקספרס", version="1.0.0")


async def keep_alive():
    """שולח ping לשרת עצמו כל 14 דקות כדי למנוע שינה ב-Render."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    await asyncio.sleep(60)
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(f"{url}/", timeout=10)
        except Exception:
            pass
        await asyncio.sleep(14 * 60)


@app.on_event("startup")
async def startup():
    """אתחול מסד הנתונים, זריעת התפריט, והפעלת ה-keep-alive."""
    init_db()
    seed_menu()
    asyncio.create_task(keep_alive())


@app.get("/")
def root():
    """בדיקת חיים."""
    return {"status": "פעיל", "service": "ג'חנון אקספרס 🫓"}


@app.post("/webhook")
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(...),
):
    """מקבל הודעת וואטסאפ מ-Twilio ומחזיר תשובה."""
    phone = From.replace("whatsapp:", "").strip()
    body = Body.strip()
    is_greeting = get_state(phone) == ChatState.GREETING
    reply = handle_message(phone, body)
    response = MessagingResponse()
    response.message(reply)
    if is_greeting:
        for img_url in PRODUCT_IMAGES:
            response.message("").media(img_url)
    return Response(content=str(response), media_type="application/xml")


def _build_admin_html(grouped: dict, total: int, pending: int, revenue: int, next_sat: str, orders_closed: bool) -> str:
    """בונה את ה-HTML של דשבורד האדמין כ-string ישיר — ללא Jinja2."""

    status_colors = {"ממתין": "#856404;background:#fff3cd", "אושר": "#155724;background:#d1e7dd", "בוטל": "#721c24;background:#f8d7da"}

    orders_html = ""
    if not grouped:
        orders_html = "<div style='text-align:center;color:#aaa;padding:40px'>אין הזמנות עדיין 🕊️</div>"
    else:
        for saturday_date, orders in grouped.items():
            orders_html += f"<div style='margin-bottom:32px'>"
            orders_html += f"<div style='font-size:1.1rem;font-weight:bold;color:#c0392b;border-bottom:2px solid #c0392b;padding-bottom:8px;margin-bottom:12px'>📅 שבת {saturday_date} — {len(orders)} הזמנות</div>"
            for order in orders:
                color = status_colors.get(order.status, "#000")
                items_html = "".join(f"{oi.menu_item.name} x{oi.quantity}<br>" for oi in order.items)
                delivery_icon = "🚗" if order.delivery_type != "איסוף עצמי" else "🏃"
                confirm_btn = ""
                if order.status == "ממתין":
                    confirm_btn = f"""
                        <form method='post' action='/admin/update/{order.id}' style='margin:0'>
                            <input type='hidden' name='status' value='אושר'>
                            <button style='padding:6px 14px;background:#198754;color:white;border:none;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:bold;width:80px;margin-bottom:4px'>✅ אשר</button>
                        </form>
                        <form method='post' action='/admin/update/{order.id}' style='margin:0'>
                            <input type='hidden' name='status' value='בוטל'>
                            <button style='padding:6px 14px;background:#dc3545;color:white;border:none;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:bold;width:80px'>❌ בטל</button>
                        </form>"""
                orders_html += f"""
                <div style='background:white;border-radius:10px;padding:16px;margin-bottom:10px;box-shadow:0 2px 8px rgba(0,0,0,0.06);display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap'>
                    <div style='flex:1'>
                        <div style='font-size:0.8rem;color:#aaa'>הזמנה #{order.id}</div>
                        <div style='font-weight:bold'>{order.customer.name or 'לא צוין'}</div>
                        <div style='font-size:0.85rem;color:#666'>📱 {order.customer.phone_number}</div>
                        <div style='font-size:0.85rem;color:#444;margin-top:6px'>🕗 {order.pickup_time} | {delivery_icon} {order.delivery_type}</div>
                        {'<div style=\'font-size:0.85rem;color:#444;margin-top:2px\'>📍 ' + order.delivery_address + '</div>' if order.delivery_address else ''}
                        <div style='font-size:0.85rem;color:#444;margin-top:4px;line-height:1.6'>{items_html}</div>
                        <div style='font-weight:bold;color:#c0392b'>💰 ₪{order.total_price:.0f}</div>
                    </div>
                    <div style='display:flex;flex-direction:column;align-items:center;gap:6px'>
                        <span style='padding:4px 12px;border-radius:20px;font-size:0.8rem;font-weight:bold;color:{color}'>{order.status}</span>
                        {confirm_btn}
                    </div>
                </div>"""
            orders_html += "</div>"

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>ג'חנון אקספרס — ניהול</title>
  <style>* {{box-sizing:border-box;margin:0;padding:0}} body {{font-family:'Segoe UI',Arial,sans-serif;background:#fff8f0;color:#2d2d2d;padding:20px}}</style>
</head>
<body>
  <div style='background:#c0392b;color:white;padding:20px 24px;border-radius:12px;margin-bottom:16px;display:flex;align-items:center;gap:12px'>
    <div style='font-size:2rem'>🫓</div>
    <div><h1 style='font-size:1.5rem'>ג'חנון אקספרס — לוח ניהול</h1><p style='font-size:0.9rem;opacity:0.85;margin-top:4px'>שלום גבריאל! כאן כל ההזמנות שלך</p></div>
  </div>
  <div style='background:{"#d1e7dd;border:1px solid #a3cfbb;color:#0a3622" if not orders_closed else "#fff3cd;border:1px solid #ffc107;color:#664d03"};border-radius:8px;padding:10px 16px;margin-bottom:16px;font-weight:bold;font-size:0.9rem'>
    {"🟢 הזמנות פתוחות — סוגרות שישי ב-11:00" if not orders_closed else "🔴 הזמנות סגורות לשבת הקרובה (נפתחות ביום ראשון)"}
  </div>
  <div style='display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap'>
    <div style='background:white;border-radius:10px;padding:16px 20px;flex:1;min-width:130px;box-shadow:0 2px 8px rgba(0,0,0,0.07);text-align:center'>
      <div style='font-size:2rem;font-weight:bold;color:#c0392b'>{total}</div><div style='font-size:0.85rem;color:#888;margin-top:4px'>הזמנות בסה"כ</div>
    </div>
    <div style='background:white;border-radius:10px;padding:16px 20px;flex:1;min-width:130px;box-shadow:0 2px 8px rgba(0,0,0,0.07);text-align:center'>
      <div style='font-size:2rem;font-weight:bold;color:#c0392b'>{pending}</div><div style='font-size:0.85rem;color:#888;margin-top:4px'>ממתינות לאישור</div>
    </div>
    <div style='background:white;border-radius:10px;padding:16px 20px;flex:1;min-width:130px;box-shadow:0 2px 8px rgba(0,0,0,0.07);text-align:center'>
      <div style='font-size:2rem;font-weight:bold;color:#c0392b'>₪{revenue}</div><div style='font-size:0.85rem;color:#888;margin-top:4px'>הכנסה צפויה</div>
    </div>
    <div style='background:white;border-radius:10px;padding:16px 20px;flex:1;min-width:130px;box-shadow:0 2px 8px rgba(0,0,0,0.07);text-align:center'>
      <div style='font-size:1.2rem;font-weight:bold;color:#c0392b'>{next_sat}</div><div style='font-size:0.85rem;color:#888;margin-top:4px'>שבת קרובה</div>
    </div>
  </div>
  {orders_html}
</body>
</html>"""


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    """דשבורד ניהול להזמנות — מיועד לגבריאל."""
    db = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .options(
                joinedload(Order.customer),
                joinedload(Order.items).joinedload(OrderItem.menu_item),
            )
            .order_by(Order.pickup_date, Order.pickup_time)
            .all()
        )

        grouped = defaultdict(list)
        for order in orders:
            grouped[order.pickup_date or "לא ידוע"].append(order)

        pending = sum(1 for o in orders if o.status == "ממתין")
        revenue = sum(o.total_price for o in orders if o.status != "בוטל")

        html = _build_admin_html(
            grouped=dict(grouped),
            total=len(orders),
            pending=pending,
            revenue=int(revenue),
            next_sat=get_next_saturday(),
            orders_closed=is_orders_closed(),
        )
        return HTMLResponse(content=html)
    finally:
        db.close()


@app.post("/admin/update/{order_id}")
def update_order_status(order_id: int, status: str = Form(...)):
    """מעדכן סטטוס הזמנה מהדשבורד."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.status = status
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin", status_code=303)
