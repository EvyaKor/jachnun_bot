"""
מטפל בהודעות נכנסות מוואטסאפ ומנתב אותן לפי מצב השיחה.
כל לוגיקת השיחה עוברת דרך כאן.
"""

from sqlalchemy.orm import Session
from database.models import Customer, MenuItem, Order, OrderItem
from database.db import SessionLocal
from state_machine import ChatState, get_session, get_state, set_state, reset_session

BUSINESS_INFO = {
    "name": "ג'חנון אקספרס",
    "address": "בני ברית 17/1 דירה 21 קומה 5, הוד השרון",
    "pickup_from": "08:00",
    "days": "שבת בלבד",
    "contact": "גבריאל 054-2380330",
}

MENU_TEXT = (
    "📋 *התפריט שלנו:*\n\n"
    "1️⃣ ג'חנון (פרווה) — ₪25\n"
    "   מוגש עם רסק, ביצה וסחוג 🍅🥚\n\n"
    "2️⃣ קובנייה (חלבי) — ₪15\n"
    "   מוגשת עם רסק, ביצה וסחוג 🍅🥚\n\n"
    "כתוב *1* להזמין ג'חנון, *2* להזמין קובנייה\n"
    "כתוב *סיום* לסיים את ההזמנה"
)

WELCOME_TEXT = (
    "שלום וברוכים הבאים לג'חנון אקספרס! 🎉\n\n"
    "ג'חנונים וקובניות טריים וחמים שלא תוכלו להפסיק ללקק את האצבעות 😁\n\n"
    "📍 {address}\n"
    "🕗 איסוף מ-{pickup_from} | {days}\n\n"
    "כתוב *תפריט* לצפייה בתפריט\n"
    "כתוב *הזמנה* להתחיל להזמין"
).format(**BUSINESS_INFO)


def get_or_create_customer(phone: str, db: Session) -> Customer:
    """מחזיר לקוח קיים או יוצר חדש לפי מספר הטלפון."""
    customer = db.query(Customer).filter(Customer.phone_number == phone).first()
    if not customer:
        customer = Customer(phone_number=phone)
        db.add(customer)
        db.commit()
        db.refresh(customer)
    return customer


def format_cart(cart: dict, db: Session) -> str:
    """מחזיר תיאור טקסטואלי של סל הקניות הנוכחי."""
    if not cart:
        return "הסל שלך ריק."
    lines = ["🛒 *הסל שלך:*"]
    total = 0.0
    for item_id, qty in cart.items():
        item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
        if item:
            subtotal = item.price * qty
            total += subtotal
            lines.append(f"  {item.name} x{qty} — ₪{subtotal:.0f}")
    lines.append(f"\n💰 *סה\"כ: ₪{total:.0f}*")
    return "\n".join(lines)


def handle_message(phone: str, body: str) -> str:
    """
    נקודת הכניסה הראשית לטיפול בהודעה נכנסת.
    מקבל מספר טלפון וגוף ההודעה, מחזיר תשובה בעברית.
    """
    body = body.strip()
    state = get_state(phone)
    session = get_session(phone)
    db = SessionLocal()

    try:
        # ---- מצב: ברכה ראשונית ----
        if state == ChatState.GREETING:
            set_state(phone, ChatState.BROWSING_MENU)
            return WELCOME_TEXT

        # ---- מצב: עיון בתפריט ----
        if state == ChatState.BROWSING_MENU:
            if body in ["תפריט", "menu"]:
                return MENU_TEXT
            if body == "הזמנה":
                set_state(phone, ChatState.ADDING_ITEMS)
                return MENU_TEXT + "\n\nכתוב את מספר הפריט כדי להוסיף לסל:"

        # ---- מצב: הוספת פריטים לסל ----
        if state == ChatState.ADDING_ITEMS:
            if body == "1":
                item = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
                if item:
                    session["cart"][item.id] = session["cart"].get(item.id, 0) + 1
                return f"✅ ג'חנון נוסף לסל!\n\n{format_cart(session['cart'], db)}\n\nהמשך להוסיף פריטים או כתוב *סיום*"

            if body == "2":
                item = db.query(MenuItem).filter(MenuItem.name == "קובנייה").first()
                if item:
                    session["cart"][item.id] = session["cart"].get(item.id, 0) + 1
                return f"✅ קובנייה נוספה לסל!\n\n{format_cart(session['cart'], db)}\n\nהמשך להוסיף פריטים או כתוב *סיום*"

            if body == "סיום":
                if not session["cart"]:
                    return "הסל שלך ריק. כתוב *1* או *2* כדי להוסיף פריטים."
                set_state(phone, ChatState.AWAITING_NAME)
                return f"{format_cart(session['cart'], db)}\n\nמה השם שלך לצורך ההזמנה?"

        # ---- מצב: ממתין לשם ----
        if state == ChatState.AWAITING_NAME:
            session["name"] = body
            set_state(phone, ChatState.AWAITING_PICKUP_TIME)
            return f"תודה {body}! 😊\n\nבאיזו שעה תרצה לאסוף? (איסוף אפשרי החל מ-08:00)"

        # ---- מצב: ממתין לשעת איסוף ----
        if state == ChatState.AWAITING_PICKUP_TIME:
            session["pickup_time"] = body
            set_state(phone, ChatState.CONFIRMING_ORDER)
            cart_text = format_cart(session["cart"], db)
            return (
                f"{cart_text}\n\n"
                f"👤 שם: {session['name']}\n"
                f"🕗 שעת איסוף: {body}\n"
                f"📍 {BUSINESS_INFO['address']}\n\n"
                f"לאישור ההזמנה כתוב *אישור*\nלביטול כתוב *ביטול*"
            )

        # ---- מצב: אישור הזמנה ----
        if state == ChatState.CONFIRMING_ORDER:
            if body == "אישור":
                customer = get_or_create_customer(phone, db)
                customer.name = session["name"]
                db.commit()

                total = sum(
                    db.query(MenuItem).filter(MenuItem.id == item_id).first().price * qty
                    for item_id, qty in session["cart"].items()
                )

                order = Order(
                    customer_id=customer.id,
                    pickup_time=session["pickup_time"],
                    total_price=total,
                    status="ממתין",
                )
                db.add(order)
                db.commit()
                db.refresh(order)

                for item_id, qty in session["cart"].items():
                    order_item = OrderItem(order_id=order.id, menu_item_id=item_id, quantity=qty)
                    db.add(order_item)
                db.commit()

                reset_session(phone)
                return (
                    f"✅ *ההזמנה שלך אושרה!*\n\n"
                    f"מספר הזמנה: #{order.id}\n"
                    f"סה\"כ לתשלום: ₪{total:.0f}\n"
                    f"שעת איסוף: {session['pickup_time'] if session.get('pickup_time') else body}\n"
                    f"📍 {BUSINESS_INFO['address']}\n\n"
                    f"מחכים לך! ❤️"
                )

            if body == "ביטול":
                reset_session(phone)
                return "ההזמנה בוטלה. כתוב *שלום* כדי להתחיל מחדש."

        # ---- ברירת מחדל ----
        return (
            "לא הבנתי 🤔\n\n"
            "כתוב *תפריט* לצפייה בתפריט\n"
            "כתוב *הזמנה* להתחיל להזמין\n"
            "כתוב *שלום* להתחיל מחדש"
        )

    finally:
        db.close()
