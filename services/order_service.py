"""
שירות הזמנות — לוגיקת עסקים מרכזית.
כולל: חישוב שבת קרובה, יצירת הזמנה, שליחת התראה לגבריאל.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from database.models import Customer, MenuItem, Order, OrderItem
from twilio.rest import Client
import os
from dotenv import load_dotenv

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

load_dotenv()

GABRIEL_PHONE = "whatsapp:+972539475881"
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")


def is_orders_closed() -> bool:
    """
    מחזיר True אם ההזמנות סגורות לשבת הקרובה.
    ההזמנות נסגרות אוטומטית ביום שישי בשעה 11:00 (שעון ישראל)
    ונשארות סגורות כל יום שבת. נפתחות מחדש ביום ראשון.
    """
    now = datetime.now(ISRAEL_TZ)
    weekday = now.weekday()  # 0=שני, 4=שישי, 5=שבת, 6=ראשון
    if weekday == 4 and now.hour >= 11:  # שישי אחרי 11:00
        return True
    if weekday == 5:  # שבת — כל היום
        return True
    return False


def get_next_saturday() -> str:
    """
    מחשב את תאריך השבת הקרובה לפי שעון ישראל (Asia/Jerusalem).
    תמיד מחזיר את השבת הבאה — גם אם היום שבת (אז יחזיר שבת הבאה).
    משתמש ב-timezone ישראלי כדי שמשתמש שמזמין ב-23:00 ישראלי
    יקבל את השבת הנכונה (ולא UTC שכבר עבר לשישי/שבת).
    """
    today = datetime.now(ISRAEL_TZ).date()
    days_until_saturday = (5 - today.weekday()) % 7  # שבת = 5 ב-Python
    if days_until_saturday == 0:
        days_until_saturday = 7  # אם היום שבת — קח את השבת הבאה
    next_saturday = today + timedelta(days=days_until_saturday)
    return next_saturday.strftime("%d/%m/%Y")


def create_order(
    customer: Customer,
    cart: dict,
    pickup_time: str,
    delivery_type: str,
    delivery_cost: float,
    db: Session,
    delivery_address: str | None = None,
) -> Order:
    """
    יוצר הזמנה חדשה במסד הנתונים עם תאריך שבת אוטומטי.
    מחזיר את אובייקט ההזמנה השמורה.
    """
    pickup_date = get_next_saturday()

    subtotal = sum(
        db.query(MenuItem).filter(MenuItem.id == item_id).first().price * qty
        for item_id, qty in cart.items()
    )
    total = subtotal + delivery_cost

    order = Order(
        customer_id=customer.id,
        pickup_date=pickup_date,
        pickup_time=pickup_time,
        delivery_type=delivery_type,
        delivery_cost=delivery_cost,
        delivery_address=delivery_address,
        total_price=total,
        status="ממתין",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    for item_id, qty in cart.items():
        order_item = OrderItem(order_id=order.id, menu_item_id=item_id, quantity=qty)
        db.add(order_item)
    db.commit()

    return order


def notify_gabriel(order: Order, customer: Customer, cart: dict, db: Session):
    """
    שולח הודעת וואטסאפ לגבריאל עם פרטי ההזמנה החדשה.
    אם Twilio לא מוגדר — מדפיס ללוג בלבד.
    """
    lines = [f"🔔 *הזמנה חדשה #{order.id}*\n"]
    lines.append(f"👤 {customer.name or 'לא צוין'} | {customer.phone_number}")
    lines.append(f"📅 {order.pickup_date} בשעה {order.pickup_time}")
    if order.delivery_address:
        lines.append(f"🚗 {order.delivery_type} → {order.delivery_address}\n")
    else:
        lines.append(f"🚗 {order.delivery_type}\n")
    lines.append("🛒 פריטים:")

    for item_id, qty in cart.items():
        item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
        if item:
            lines.append(f"  {item.name} x{qty}")

    lines.append(f"\n💰 סה\"כ: ₪{order.total_price:.0f}")

    message_body = "\n".join(lines)

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print(f"[התראה לגבריאל — לא נשלחה, Twilio לא מוגדר]\n{message_body}")
        return

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=GABRIEL_PHONE,
            body=message_body,
        )
    except Exception as e:
        print(f"שגיאה בשליחת הודעה לגבריאל: {e}")
