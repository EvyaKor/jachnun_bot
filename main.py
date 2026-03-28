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
    was_greeting = get_state(phone) == ChatState.GREETING
    reply = handle_message(phone, body)
    response = MessagingResponse()
    response.message(reply)
    if was_greeting and get_state(phone) == ChatState.ADDING_ITEMS:
        for img_url in PRODUCT_IMAGES:
            response.message("").media(img_url)
    return Response(content=str(response), media_type="application/xml")


def _build_admin_html(grouped: dict, total: int, pending: int, revenue: int, next_sat: str, orders_closed: bool) -> str:
    """בונה את ה-HTML של דשבורד האדמין — מותאם מובייל, ללא Jinja2."""

    status_badge = {
        "ממתין": "badge-pending",
        "אושר": "badge-confirmed",
        "בוטל": "badge-cancelled",
    }

    orders_html = ""
    if not grouped:
        orders_html = "<div class='empty'>אין הזמנות עדיין 🕊️</div>"
    else:
        for saturday_date, orders in grouped.items():
            orders_html += f"""
            <div class='week-group'>
              <div class='week-header'>📅 שבת {saturday_date} — {len(orders)} הזמנות</div>"""
            for order in orders:
                badge = status_badge.get(order.status, "")
                items_html = "".join(
                    f"<span class='item-chip'>{oi.menu_item.name} ×{oi.quantity}</span>"
                    for oi in order.items
                )
                delivery_icon = "🚗" if order.delivery_type != "איסוף עצמי" else "🏃"
                address_row = f"<div class='detail-row'>📍 {order.delivery_address}</div>" if order.delivery_address else ""
                action_btns = ""
                if order.status == "ממתין":
                    action_btns = f"""
                    <div class='action-row'>
                      <form method='post' action='/admin/update/{order.id}'>
                        <input type='hidden' name='status' value='אושר'>
                        <button class='btn btn-confirm'>✅ אשר</button>
                      </form>
                      <form method='post' action='/admin/update/{order.id}'>
                        <input type='hidden' name='status' value='בוטל'>
                        <button class='btn btn-cancel'>❌ בטל</button>
                      </form>
                    </div>"""
                orders_html += f"""
              <div class='order-card'>
                <div class='card-top'>
                  <div class='order-meta'>
                    <span class='order-num'>הזמנה #{order.id}</span>
                    <span class='badge {badge}'>{order.status}</span>
                  </div>
                  <div class='customer-name'>{order.customer.name or 'לא צוין'}</div>
                  <a class='phone-link' href='tel:{order.customer.phone_number}'>📱 {order.customer.phone_number}</a>
                </div>
                <div class='card-body'>
                  <div class='detail-row'>🕗 {order.pickup_time} &nbsp;|&nbsp; {delivery_icon} {order.delivery_type}</div>
                  {address_row}
                  <div class='items-row'>{items_html}</div>
                  <div class='total-row'>💰 ₪{order.total_price:.0f}</div>
                </div>
                {action_btns}
              </div>"""
            orders_html += "</div>"

    status_bar_cls = "status-open" if not orders_closed else "status-closed"
    status_bar_txt = "🟢 הזמנות פתוחות — סוגרות שישי ב-11:00" if not orders_closed else "🔴 הזמנות סגורות (נפתחות ביום ראשון)"

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0"/>
  <meta http-equiv="refresh" content="60"/>
  <title>ג'חנון אקספרס — ניהול</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#fff8f0;color:#2d2d2d;padding:12px;max-width:640px;margin:0 auto}}
    .header{{background:#c0392b;color:white;padding:16px 18px;border-radius:14px;margin-bottom:12px;display:flex;align-items:center;gap:12px}}
    .header-icon{{font-size:2rem;line-height:1}}
    .header h1{{font-size:1.25rem;font-weight:700}}
    .header p{{font-size:0.82rem;opacity:0.85;margin-top:2px}}
    .status-bar{{border-radius:10px;padding:10px 14px;margin-bottom:14px;font-weight:600;font-size:0.88rem}}
    .status-open{{background:#d1e7dd;border:1px solid #a3cfbb;color:#0a3622}}
    .status-closed{{background:#fff3cd;border:1px solid #ffc107;color:#664d03}}
    .stats{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:18px}}
    .stat-card{{background:white;border-radius:12px;padding:14px 12px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.07)}}
    .stat-num{{font-size:1.8rem;font-weight:700;color:#c0392b;line-height:1.1}}
    .stat-label{{font-size:0.78rem;color:#888;margin-top:4px}}
    .week-group{{margin-bottom:24px}}
    .week-header{{font-size:1rem;font-weight:700;color:#c0392b;border-bottom:2px solid #c0392b;padding-bottom:8px;margin-bottom:10px}}
    .order-card{{background:white;border-radius:14px;margin-bottom:10px;box-shadow:0 2px 10px rgba(0,0,0,0.07);overflow:hidden}}
    .card-top{{padding:14px 14px 10px}}
    .order-meta{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}}
    .order-num{{font-size:0.78rem;color:#aaa}}
    .badge{{padding:3px 10px;border-radius:20px;font-size:0.78rem;font-weight:600}}
    .badge-pending{{background:#fff3cd;color:#856404}}
    .badge-confirmed{{background:#d1e7dd;color:#155724}}
    .badge-cancelled{{background:#f8d7da;color:#721c24}}
    .customer-name{{font-size:1.05rem;font-weight:700;margin-bottom:2px}}
    .phone-link{{font-size:0.85rem;color:#c0392b;text-decoration:none;display:inline-block}}
    .card-body{{padding:0 14px 12px;border-top:1px solid #f5f5f5;margin-top:10px;padding-top:10px}}
    .detail-row{{font-size:0.85rem;color:#555;margin-bottom:4px}}
    .items-row{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}}
    .item-chip{{background:#fff0e6;color:#c0392b;border-radius:20px;padding:3px 10px;font-size:0.82rem;font-weight:500}}
    .total-row{{font-size:1rem;font-weight:700;color:#c0392b;margin-top:4px}}
    .action-row{{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #f0f0f0}}
    .action-row form{{margin:0}}
    .btn{{width:100%;padding:14px 0;font-size:1rem;font-weight:700;border:none;cursor:pointer;letter-spacing:0.3px}}
    .btn-confirm{{background:#198754;color:white}}
    .btn-confirm:active{{background:#146c43}}
    .btn-cancel{{background:#dc3545;color:white}}
    .btn-cancel:active{{background:#b02a37}}
    .empty{{text-align:center;color:#aaa;padding:48px 0;font-size:1rem}}
    .refresh-note{{text-align:center;font-size:0.75rem;color:#bbb;margin-top:16px;padding-bottom:24px}}
  </style>
</head>
<body>
  <div class='header'>
    <div class='header-icon'>🫓</div>
    <div>
      <h1>ג'חנון אקספרס</h1>
      <p>שלום גבריאל! כאן כל ההזמנות שלך</p>
    </div>
  </div>
  <div class='status-bar {status_bar_cls}'>{status_bar_txt}</div>
  <div class='stats'>
    <div class='stat-card'><div class='stat-num'>{total}</div><div class='stat-label'>הזמנות בסה"כ</div></div>
    <div class='stat-card'><div class='stat-num'>{pending}</div><div class='stat-label'>ממתינות לאישור</div></div>
    <div class='stat-card'><div class='stat-num'>₪{revenue}</div><div class='stat-label'>הכנסה צפויה</div></div>
    <div class='stat-card'><div class='stat-num' style='font-size:1.1rem'>{next_sat}</div><div class='stat-label'>שבת קרובה</div></div>
  </div>
  {orders_html}
  <div class='refresh-note'>מתרענן אוטומטית כל דקה</div>
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
