"""
מטפל בהודעות נכנסות מוואטסאפ ומנתב אותן לפי מצב השיחה.
כל לוגיקת השיחה עוברת דרך כאן.
"""

from sqlalchemy.orm import Session
from database.models import Customer, MenuItem
from database.db import SessionLocal
from state_machine import ChatState, get_session, get_state, set_state, reset_session
from services.order_service import create_order, notify_gabriel, get_next_saturday

GITHUB_RAW = "https://raw.githubusercontent.com/EvyaKor/jachnun_bot/main/images"
PRODUCT_IMAGES = [
    f"{GITHUB_RAW}/image1.jpg",
    f"{GITHUB_RAW}/image2.jpg",
]

BUSINESS_INFO = {
    "name": "ג'חנון אקספרס",
    "address": "בני ברית 17, הוד השרון",
    "pickup_from": "08:00",
    "days": "שבת בלבד",
    "contact": "גבריאל 053-9475881",
}

GABRIEL_PAYMENT_PHONE = "054-2380330"  # מספר פרטי לביט/פייבוקס

DELIVERY_OPTIONS = {
    "1": {"label": "איסוף עצמי", "cost": 0.0},
    "2": {"label": "משלוח להוד השרון", "cost": 15.0},
    "3": {"label": "משלוח לכפר סבא", "cost": 25.0},
}

DELIVERY_MIN = 70.0  # מינימום הזמנה למשלוח

MENU_TEXT = (
    "📋 *התפריט שלנו:*\n\n"
    "1️⃣ ג'חנון (פרווה) — ₪25\n"
    "   מוגש עם רסק, ביצה וסחוג 🍅🥚\n\n"
    "2️⃣ קובנייה (חלבי) — ₪20\n"
    "   מוגשת עם רסק, ביצה וסחוג 🍅🥚\n\n"
    "כתוב *1* להזמין ג'חנון\n"
    "כתוב *2* להזמין קובנייה\n"
    "כתוב *סיום* לסיים את ההזמנה"
)

WELCOME_TEXT = (
    "שלום וברוכים הבאים לג'חנון אקספרס! 🎉\n\n"
    "ג'חנונים וקובניות טריים וחמים שלא תוכלו להפסיק ללקק את האצבעות 😁\n\n"
    "📍 {address}\n"
    "🕗 {days} מ-{pickup_from}\n\n"
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


def cart_subtotal(cart: dict, db: Session) -> float:
    """מחשב את סכום הסל ללא משלוח."""
    total = 0.0
    for item_id, qty in cart.items():
        item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
        if item:
            total += item.price * qty
    return total


def format_cart(cart: dict, db: Session, delivery_cost: float = 0.0) -> str:
    """מחזיר תיאור טקסטואלי של סל הקניות הנוכחי."""
    if not cart:
        return "הסל שלך ריק."
    lines = ["🛒 *הסל שלך:*"]
    subtotal = 0.0
    for item_id, qty in cart.items():
        item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
        if item:
            line_total = item.price * qty
            subtotal += line_total
            lines.append(f"  {item.name} x{qty} — ₪{line_total:.0f}")
    if delivery_cost > 0:
        lines.append(f"  🚗 משלוח — ₪{delivery_cost:.0f}")
    lines.append(f"\n💰 *סה\"כ: ₪{subtotal + delivery_cost:.0f}*")
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
            if body in ["תפריט", "menu", "הזמנה"]:
                set_state(phone, ChatState.ADDING_ITEMS)
                return (
                    f"מעולה! ההזמנה תהיה לשבת ה-{get_next_saturday()} 📅\n\n"
                    + MENU_TEXT
                )

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
                set_state(phone, ChatState.CHOOSING_DELIVERY)
                subtotal = cart_subtotal(session["cart"], db)
                delivery_note = ""
                if subtotal < DELIVERY_MIN:
                    delivery_note = f"\n\n_⚠️ משלוח זמין בהזמנה מעל ₪{DELIVERY_MIN:.0f} בלבד_"
                return (
                    f"{format_cart(session['cart'], db)}\n\n"
                    f"איך תרצה לקבל את ההזמנה? 🚗\n\n"
                    f"1️⃣ איסוף עצמי (חינם)\n"
                    f"   📍 {BUSINESS_INFO['address']}\n\n"
                    f"2️⃣ משלוח להוד השרון — ₪15\n"
                    f"3️⃣ משלוח לכפר סבא — ₪25"
                    + delivery_note
                )

        # ---- מצב: בחירת סוג משלוח ----
        if state == ChatState.CHOOSING_DELIVERY:
            if body == "חזור":
                set_state(phone, ChatState.ADDING_ITEMS)
                return MENU_TEXT + "\n\nהמשך להוסיף פריטים וכתוב *סיום* בסיום:"

            if body not in DELIVERY_OPTIONS:
                return "כתוב *1* לאיסוף עצמי, *2* למשלוח להוד השרון, או *3* למשלוח לכפר סבא."

            option = DELIVERY_OPTIONS[body]
            subtotal = cart_subtotal(session["cart"], db)

            if body in ("2", "3") and subtotal < DELIVERY_MIN:
                return (
                    f"⚠️ המינימום למשלוח הוא ₪{DELIVERY_MIN:.0f}.\n"
                    f"סכום הסל שלך כרגע: ₪{subtotal:.0f}.\n\n"
                    f"כתוב *חזור* כדי להוסיף עוד פריטים, או *1* לאיסוף עצמי."
                )

            session["delivery_type"] = option["label"]
            session["delivery_cost"] = option["cost"]

            if option["cost"] > 0:
                set_state(phone, ChatState.AWAITING_ADDRESS)
                return (
                    f"בחרת: *{option['label']}* 🚗\n\n"
                    f"לאיזו כתובת לשלוח? (רחוב, מספר בית, עיר)"
                )
            else:
                set_state(phone, ChatState.AWAITING_NAME)
                return f"בחרת: *{option['label']}* 🏃\n\nמה השם שלך לצורך ההזמנה?"

        # ---- חזור להוספת פריטים ----
        if body == "חזור" and state == ChatState.CHOOSING_DELIVERY:
            set_state(phone, ChatState.ADDING_ITEMS)
            return MENU_TEXT + "\n\nהמשך להוסיף פריטים וכתוב *סיום* בסיום:"

        # ---- מצב: ממתין לכתובת משלוח ----
        if state == ChatState.AWAITING_ADDRESS:
            session["delivery_address"] = body
            set_state(phone, ChatState.AWAITING_NAME)
            return f"תודה! 📍 נשלח אל: *{body}*\n\nמה השם שלך לצורך ההזמנה?"

        # ---- מצב: ממתין לשם ----
        if state == ChatState.AWAITING_NAME:
            session["name"] = body
            set_state(phone, ChatState.AWAITING_PICKUP_TIME)
            return f"תודה {body}! 😊\n\nבאיזו שעה תרצה {'לאסוף' if session['delivery_type'] == 'איסוף עצמי' else 'לקבל את המשלוח'} ביום שבת?\n(החל מ-08:00)"

        # ---- מצב: ממתין לשעת איסוף/משלוח ----
        if state == ChatState.AWAITING_PICKUP_TIME:
            session["pickup_time"] = body
            set_state(phone, ChatState.CONFIRMING_ORDER)
            cart_text = format_cart(session["cart"], db, session["delivery_cost"])
            next_saturday = get_next_saturday()
            if session["delivery_type"] != "איסוף עצמי":
                delivery_line = (
                    f"🚗 {session['delivery_type']}\n"
                    f"📍 כתובת: {session['delivery_address']}"
                )
            else:
                delivery_line = f"📍 איסוף עצמי — {BUSINESS_INFO['address']}"

            return (
                f"{cart_text}\n\n"
                f"👤 שם: {session['name']}\n"
                f"📅 תאריך: שבת {next_saturday}\n"
                f"🕗 שעה: {body}\n"
                f"{delivery_line}\n\n"
                f"לאישור כתוב *אישור* ✅\n"
                f"לביטול כתוב *ביטול* ❌"
            )

        # ---- מצב: אישור הזמנה ----
        if state == ChatState.CONFIRMING_ORDER:
            if body == "אישור":
                set_state(phone, ChatState.CHOOSING_PAYMENT)
                return (
                    "איך תרצה לשלם? 💳\n\n"
                    "1️⃣ מזומן\n"
                    "2️⃣ ביט\n"
                    "3️⃣ פייבוקס"
                )

            if body == "ביטול":
                reset_session(phone)
                return "ההזמנה בוטלה. כתוב *שלום* כדי להתחיל מחדש."

        # ---- מצב: בחירת אמצעי תשלום ----
        if state == ChatState.CHOOSING_PAYMENT:
            payment_map = {"1": "מזומן", "2": "ביט", "3": "פייבוקס"}

            if body not in payment_map:
                return "כתוב *1* למזומן, *2* לביט, או *3* לפייבוקס."

            session["payment_method"] = payment_map[body]
            customer = get_or_create_customer(phone, db)
            customer.name = session["name"]
            db.commit()

            order = create_order(
                customer=customer,
                cart=session["cart"],
                pickup_time=session["pickup_time"],
                delivery_type=session["delivery_type"],
                delivery_cost=session["delivery_cost"],
                delivery_address=session.get("delivery_address"),
                db=db,
            )
            notify_gabriel(order, customer, session["cart"], db)
            reset_session(phone)

            confirmation = (
                f"✅ *ההזמנה שלך אושרה!*\n\n"
                f"מספר הזמנה: #{order.id}\n"
                f"📅 שבת {order.pickup_date}\n"
                f"🕗 שעה: {order.pickup_time}\n"
                f"🚗 {order.delivery_type}\n"
                f"💳 תשלום: {payment_map[body]}\n"
                f"💰 סה\"כ: ₪{order.total_price:.0f}\n"
            )

            if body in ("2", "3"):
                confirmation += (
                    f"\nלתשלום ב{payment_map[body]} שלח ₪{order.total_price:.0f} למספר:\n"
                    f"📱 *{GABRIEL_PAYMENT_PHONE}*\n"
                )

            confirmation += "\nמחכים לך! ❤️🫓"
            return confirmation

        # ---- ברירת מחדל ----
        return (
            "לא הבנתי 🤔\n\n"
            "כתוב *תפריט* לצפייה בתפריט\n"
            "כתוב *הזמנה* להתחיל להזמין\n"
            "כתוב *שלום* להתחיל מחדש"
        )

    finally:
        db.close()
