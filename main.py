"""
ג'חנון אקספרס — שרת FastAPI ראשי.
מקבל הודעות וואטסאפ דרך Twilio ומחזיר תשובות בעברית.
כולל דשבורד ניהול להזמנות לגבריאל.
"""

from fastapi import FastAPI, Form, Query
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


@app.get("/health")
def health():
    """נקודת קצה לבדיקת בריאות — משמשת את Render keep-alive."""
    return {"status": "ok"}


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


def _calc_prep(orders: list) -> dict:
    """מחשב כמויות הכנה מצטברות מרשימת הזמנות (לא בוטלות)."""
    totals = {}
    for order in orders:
        if order.status == "בוטל":
            continue
        for oi in order.items:
            name = oi.menu_item.name
            totals[name] = totals.get(name, 0) + oi.quantity
    return totals


def _build_admin_html(
    grouped: dict,
    next_sat: str,
    orders_closed: bool,
    show_history: bool,
    prep: dict,
    total: int,
    pending: int,
    revenue: int,
) -> str:
    """בונה את ה-HTML של דשבורד האדמין — מותאם אייפון, ללא Jinja2."""

    status_badge = {
        "ממתין": "badge-pending",
        "אושר": "badge-confirmed",
        "בוטל": "badge-cancelled",
    }

    # ── סיכום הכנה ──
    prep_items = {
        "ג'חנון": ("🫓", prep.get("ג'חנון", 0)),
        "קובנייה": ("🧀", prep.get("קובנייה", 0)),
        "ביצה נוספת": ("🥚", prep.get("ביצה נוספת", 0)),
        "רסק עגניות + סחוג": ("🍅", prep.get("רסק עגניות + סחוג", 0)),
    }
    prep_html = "".join(
        f"<div class='prep-item'><span class='prep-emoji'>{emoji}</span>"
        f"<span class='prep-count'>{count}</span>"
        f"<span class='prep-name'>{name}</span></div>"
        for name, (emoji, count) in prep_items.items()
    )

    # ── הזמנות ──
    orders_html = ""
    if not grouped:
        label = "שבת הקרובה" if not show_history else "המערכת"
        orders_html = f"<div class='empty'>אין הזמנות ל{label} עדיין 🕊️</div>"
    else:
        for saturday_date, orders in grouped.items():
            active = [o for o in orders if o.status != "בוטל"]
            orders_html += f"""
            <div class='week-group'>
              <div class='week-header'>
                <span>שבת {saturday_date}</span>
                <span class='week-count'>{len(active)} הזמנות פעילות</span>
              </div>"""
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
                    <span class='order-num'>#{order.id}</span>
                    <span class='badge {badge}'>{order.status}</span>
                  </div>
                  <div class='customer-name'>{order.customer.name or 'לא צוין'}</div>
                  <a class='phone-link' href='tel:{order.customer.phone_number}'>📱 {order.customer.phone_number}</a>
                </div>
                <div class='card-body'>
                  <div class='detail-row'>🕗 {order.pickup_time} &nbsp;·&nbsp; {delivery_icon} {order.delivery_type}</div>
                  {address_row}
                  <div class='items-row'>{items_html}</div>
                  <div class='total-row'>💰 ₪{order.total_price:.0f}</div>
                </div>
                {action_btns}
              </div>"""
            orders_html += "</div>"

    status_bar_cls = "status-open" if not orders_closed else "status-closed"
    status_bar_txt = "🟢 הזמנות פתוחות — נסגרות שישי ב-11:00" if not orders_closed else "🔴 הזמנות סגורות — נפתחות ביום ראשון"
    tab_current = "tab-active" if not show_history else "tab"
    tab_history = "tab-active" if show_history else "tab"

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0"/>
  <meta http-equiv="refresh" content="60"/>
  <title>ג'חנון אקספרס</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f7;color:#1c1c1e;padding:12px;max-width:600px;margin:0 auto}}
    .header{{background:linear-gradient(135deg,#c0392b,#e74c3c);color:white;padding:18px;border-radius:16px;margin-bottom:12px}}
    .header-top{{display:flex;align-items:center;gap:12px;margin-bottom:4px}}
    .header-icon{{font-size:2.2rem;line-height:1}}
    .header h1{{font-size:1.3rem;font-weight:700;letter-spacing:-0.3px}}
    .header-sub{{font-size:0.82rem;opacity:0.85;margin-right:52px}}
    .status-bar{{border-radius:10px;padding:9px 14px;margin-bottom:12px;font-weight:600;font-size:0.85rem;display:flex;align-items:center;gap:6px}}
    .status-open{{background:#d1f5e0;color:#0a5c2a}}
    .status-closed{{background:#fff3cd;color:#664d03}}
    .tabs{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:14px}}
    .tab,.tab-active{{display:block;text-align:center;padding:10px;border-radius:10px;font-size:0.9rem;font-weight:600;text-decoration:none;transition:all .15s}}
    .tab{{background:white;color:#666;border:1.5px solid #e0e0e0}}
    .tab-active{{background:#c0392b;color:white;border:1.5px solid #c0392b}}
    .stats{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:14px}}
    .stat-card{{background:white;border-radius:12px;padding:12px 8px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06)}}
    .stat-num{{font-size:1.7rem;font-weight:700;color:#c0392b;line-height:1.1}}
    .stat-label{{font-size:0.72rem;color:#999;margin-top:3px}}
    .prep-card{{background:white;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,0.06)}}
    .prep-title{{font-size:0.8rem;font-weight:700;color:#999;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px}}
    .prep-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
    .prep-item{{background:#fdf5f0;border-radius:10px;padding:10px 12px;display:flex;align-items:center;gap:10px}}
    .prep-emoji{{font-size:1.5rem;line-height:1}}
    .prep-count{{font-size:1.5rem;font-weight:700;color:#c0392b;min-width:28px}}
    .prep-name{{font-size:0.78rem;color:#555;line-height:1.3}}
    .week-group{{margin-bottom:20px}}
    .week-header{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:2px solid #c0392b;margin-bottom:10px}}
    .week-header span{{font-size:0.95rem;font-weight:700;color:#c0392b}}
    .week-count{{font-size:0.78rem;color:#888;font-weight:500}}
    .order-card{{background:white;border-radius:14px;margin-bottom:8px;box-shadow:0 1px 6px rgba(0,0,0,0.07);overflow:hidden}}
    .card-top{{padding:12px 14px 10px}}
    .order-meta{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}}
    .order-num{{font-size:0.75rem;color:#bbb;font-weight:600}}
    .badge{{padding:3px 10px;border-radius:20px;font-size:0.75rem;font-weight:700}}
    .badge-pending{{background:#fff3cd;color:#856404}}
    .badge-confirmed{{background:#d1f5e0;color:#0a5c2a}}
    .badge-cancelled{{background:#fde8e8;color:#9b1c1c}}
    .customer-name{{font-size:1.05rem;font-weight:700;margin-bottom:3px}}
    .phone-link{{font-size:0.83rem;color:#c0392b;text-decoration:none}}
    .card-body{{padding:10px 14px 12px;border-top:1px solid #f2f2f2}}
    .detail-row{{font-size:0.83rem;color:#555;margin-bottom:4px}}
    .items-row{{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 6px}}
    .item-chip{{background:#fdf0eb;color:#c0392b;border-radius:20px;padding:3px 10px;font-size:0.8rem;font-weight:500}}
    .total-row{{font-size:1rem;font-weight:700;color:#1c1c1e}}
    .action-row{{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #f2f2f2}}
    .action-row form{{margin:0}}
    .btn{{width:100%;padding:14px 0;font-size:0.95rem;font-weight:700;border:none;cursor:pointer}}
    .btn-confirm{{background:#2ecc71;color:white}}
    .btn-confirm:active{{background:#27ae60}}
    .btn-cancel{{background:#e74c3c;color:white}}
    .btn-cancel:active{{background:#c0392b}}
    .empty{{text-align:center;color:#bbb;padding:48px 0;font-size:0.95rem}}
    .refresh-note{{text-align:center;font-size:0.72rem;color:#ccc;margin-top:12px;padding-bottom:28px}}
  </style>
</head>
<body>
  <div class='header'>
    <div class='header-top'>
      <div class='header-icon'>🫓</div>
      <h1>ג'חנון אקספרס</h1>
    </div>
    <div class='header-sub'>שלום גבריאל! שבת הקרובה: {next_sat}</div>
  </div>

  <div class='status-bar {status_bar_cls}'>{status_bar_txt}</div>

  <div class='tabs'>
    <a href='/admin' class='{tab_current}'>📋 שבת הקרובה</a>
    <a href='/admin?history=1' class='{tab_history}'>🗂️ היסטוריה</a>
  </div>

  <div class='stats'>
    <div class='stat-card'><div class='stat-num'>{total}</div><div class='stat-label'>הזמנות</div></div>
    <div class='stat-card'><div class='stat-num'>{pending}</div><div class='stat-label'>ממתינות</div></div>
    <div class='stat-card'><div class='stat-num'>₪{revenue}</div><div class='stat-label'>הכנסה</div></div>
  </div>

  <div class='prep-card'>
    <div class='prep-title'>מה להכין לשבת</div>
    <div class='prep-grid'>{prep_html}</div>
  </div>

  {orders_html}
  <div class='refresh-note'>מתרענן אוטומטית כל דקה</div>
</body>
</html>"""


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(history: int = Query(default=0)):
    """דשבורד ניהול להזמנות — מיועד לגבריאל.
    ברירת מחדל: שבת הקרובה בלבד. ?history=1 להצגת כל ההיסטוריה.
    """
    db = SessionLocal()
    try:
        next_sat = get_next_saturday()
        show_history = bool(history)

        all_orders = (
            db.query(Order)
            .options(
                joinedload(Order.customer),
                joinedload(Order.items).joinedload(OrderItem.menu_item),
            )
            .order_by(Order.pickup_date, Order.pickup_time)
            .all()
        )

        # סיכום הכנה תמיד מחושב על השבת הקרובה בלבד
        current_sat_orders = [o for o in all_orders if o.pickup_date == next_sat]
        prep = _calc_prep(current_sat_orders)

        # פילטר תצוגה
        display_orders = all_orders if show_history else current_sat_orders

        grouped = defaultdict(list)
        for order in display_orders:
            grouped[order.pickup_date or "לא ידוע"].append(order)

        active = [o for o in display_orders if o.status != "בוטל"]
        pending = sum(1 for o in display_orders if o.status == "ממתין")
        revenue = sum(o.total_price for o in display_orders if o.status != "בוטל")

        html = _build_admin_html(
            grouped=dict(grouped),
            next_sat=next_sat,
            orders_closed=is_orders_closed(),
            show_history=show_history,
            prep=prep,
            total=len(active),
            pending=pending,
            revenue=int(revenue),
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
