"""
מטפל בהודעות נכנסות מוואטסאפ ומנתב אותן לפי מצב השיחה.
תפריט דינמי מ-DB, מכונת מצבים חסינה, ביטול גלובלי בכל שלב.
"""

import os
from sqlalchemy.orm import Session
from database.models import Customer, MenuItem
from database.db import SessionLocal
from state_machine import ChatState, get_session, get_state, set_state, reset_session, save_session
from services.order_service import create_order, notify_gabriel, get_next_saturday, is_orders_closed

GITHUB_RAW = "https://raw.githubusercontent.com/EvyaKor/jachnun_bot/main/images"
PRODUCT_IMAGES = [
    f"{GITHUB_RAW}/image1.jpg",
    f"{GITHUB_RAW}/image2.jpg",
]

BUSINESS_INFO = {
    "address": "בני ברית 17, הוד השרון",
}

GABRIEL_PAYMENT_PHONE = os.getenv("GABRIEL_PAYMENT_PHONE", "054-2380330")

DELIVERY_OPTIONS = {
    "1": {"label": "איסוף עצמי", "cost": 0.0},
    "2": {"label": "משלוח להוד השרון", "cost": 15.0},
    "3": {"label": "משלוח לכפר סבא", "cost": 25.0},
}

DELIVERY_MIN = 70.0

# מצבים שבהם הזמנה פעילה — ביטול רלוונטי
ACTIVE_ORDER_STATES = {
    ChatState.ADDING_ITEMS,
    ChatState.CHOOSING_DELIVERY,
    ChatState.AWAITING_ADDRESS,
    ChatState.AWAITING_NAME,
    ChatState.AWAITING_PICKUP_TIME,
    ChatState.CONFIRMING_ORDER,
    ChatState.CHOOSING_PAYMENT,
}

EMOJI_NUMBERS = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}

CANCEL_HINT = "\n\n_כתוב *ביטול* לביטול ההזמנה_"
RESET_KEYWORDS = {"שלום", "התחל מחדש", "restart", "start", "היי", "הי", "hello", "hi"}

ORDERS_CLOSED_MSG = (
    "ההזמנות לשבת הקרובה נסגרו 🙏\n\n"
    "ניתן ליצור קשר ישירות בטלפון לבדיקת זמינות:\n"
    f"📱 *{GABRIEL_PAYMENT_PHONE}*\n\n"
    "נשמח לראותכם בשבוע הבא! ❤️🫓"
)


# ── עזר: תפריט ──────────────────────────────────────────────

def get_ordered_items(db: Session) -> list:
    """מחזיר פריטי תפריט זמינים לפי סדר: מנות עיקריות, אחר כך תוספות."""
    mains = (
        db.query(MenuItem)
        .filter(MenuItem.is_available == True, MenuItem.is_extra == False)
        .order_by(MenuItem.id)
        .all()
    )
    extras = (
        db.query(MenuItem)
        .filter(MenuItem.is_available == True, MenuItem.is_extra == True)
        .order_by(MenuItem.id)
        .all()
    )
    return mains + extras


def get_item_by_number(number: str, db: Session):
    """מחזיר פריט לפי מספרו בתפריט (1, 2, 3, ...). None אם לא קיים."""
    items = get_ordered_items(db)
    item_map = {str(i + 1): item for i, item in enumerate(items)}
    return item_map.get(number)


def build_menu_text(db: Session) -> str:
    """בונה את טקסט התפריט דינמית מה-DB."""
    items = get_ordered_items(db)
    mains = [i for i in items if not i.is_extra]
    extras = [i for i in items if i.is_extra]

    lines = ["📋 *מה נכין לכם היום?*\n"]

    for idx, item in enumerate(mains, 1):
        dairy = " (חלבי)" if item.is_dairy else ""
        lines.append(f"{EMOJI_NUMBERS[idx]} {item.name}{dairy} — ₪{item.price:.0f}")
        lines.append(f"   עם ביצה, רסק עגניות וסחוג 🍅🥚\n")

    if extras:
        lines.append("➕ *תוספות:*")
        offset = len(mains)
        for idx, item in enumerate(extras, 1):
            lines.append(f"{EMOJI_NUMBERS[offset + idx]} {item.name} — ₪{item.price:.0f}")

    lines.append("\n*כתוב מספר להוסיף לסל*")
    lines.append("\u200F*סיום* — לסיום הבחירה")
    lines.append("\u200F*ביטול* — לביטול ההזמנה")

    return "\n".join(lines)


def build_welcome_with_menu(db: Session) -> str:
    """הודעת ברוכים הבאים + תפריט מלא."""
    next_sat = get_next_saturday()
    header = (
        f"ברוכים הבאים לג'חנון אקספרס! ☀️🫓\n\n"
        f"ג'חנונים וקובניות טריים, חמים ומפנקים 😍\n"
        f"📍 {BUSINESS_INFO['address']}\n"
        f"🗓️ ההזמנה תהיה לשבת *{next_sat}*\n\n"
    )
    return header + build_menu_text(db)


# ── עזר: סל קניות ───────────────────────────────────────────

def cart_subtotal(cart: dict, db: Session) -> float:
    """מחשב סכום סל ללא משלוח."""
    total = 0.0
    for item_id, qty in cart.items():
        item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
        if item:
            total += item.price * qty
    return total


def format_cart(cart: dict, db: Session, delivery_cost: float = 0.0) -> str:
    """מחזיר תיאור טקסטואלי של הסל."""
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


# ── עזר: לקוח ───────────────────────────────────────────────

def get_or_create_customer(phone: str, db: Session) -> Customer:
    """מחזיר לקוח קיים או יוצר חדש."""
    customer = db.query(Customer).filter(Customer.phone_number == phone).first()
    if not customer:
        customer = Customer(phone_number=phone)
        db.add(customer)
        db.commit()
        db.refresh(customer)
    return customer


# ── אימות כתובת ─────────────────────────────────────────────

def is_valid_address(address: str) -> bool:
    """
    בודק שהכתובת מכילה לפחות רחוב ומספר (לא תיאור כללי כמו 'ליד המכולת').
    דרישות: לפחות 2 מילים + לפחות ספרה אחת (מספר בית).
    """
    words = address.strip().split()
    has_digit = any(char.isdigit() for char in address)
    return len(words) >= 2 and has_digit


# ── הטיפול הראשי ─────────────────────────────────────────────

def handle_message(phone: str, body: str) -> str:
    """
    נקודת הכניסה לטיפול בהודעה נכנסת.
    מחזיר תשובה בעברית.
    """
    body = body.strip()
    state = get_state(phone)
    session = get_session(phone)
    db = SessionLocal()

    try:

        # ════ פקודות גלובליות — עובדות מכל מצב ════

        # איפוס מלא + ברכה מחדש
        if body in RESET_KEYWORDS and state not in (ChatState.GREETING,):
            reset_session(phone)
            if is_orders_closed():
                return ORDERS_CLOSED_MSG
            set_state(phone, ChatState.ADDING_ITEMS)
            return build_welcome_with_menu(db)

        # ביטול הזמנה פעילה
        if body == "ביטול" and state in ACTIVE_ORDER_STATES:
            reset_session(phone)
            return "ההזמנה בוטלה ✅\n\nכתוב *הזמנה* או *שלום* להתחיל מחדש."

        # ════ GREETING — הודעה ראשונה ════
        if state == ChatState.GREETING:
            if is_orders_closed():
                return ORDERS_CLOSED_MSG
            set_state(phone, ChatState.ADDING_ITEMS)
            return build_welcome_with_menu(db)

        # תאימות לאחור — BROWSING_MENU מתנהג כמו ADDING_ITEMS
        if state == ChatState.BROWSING_MENU:
            set_state(phone, ChatState.ADDING_ITEMS)
            state = ChatState.ADDING_ITEMS

        # ════ ADDING_ITEMS — בחירת פריטים ════
        if state == ChatState.ADDING_ITEMS:

            # הצגת תפריט מחדש (ללא איבוד סל)
            if body in ["תפריט", "menu", "הזמנה"]:
                cart_text = format_cart(session["cart"], db)
                prefix = f"{cart_text}\n\n" if session["cart"] else ""
                return prefix + build_menu_text(db)

            # הוספת פריט לסל לפי מספר
            item = get_item_by_number(body, db)
            if item:
                session["cart"][item.id] = session["cart"].get(item.id, 0) + 1
                save_session(phone)
                return (
                    f"✅ *{item.name}* נוסף לסל!\n\n"
                    f"{format_cart(session['cart'], db)}\n\n"
                    f"המשך לבחור פריטים, או כתוב *סיום* להמשך"
                    f"{CANCEL_HINT}"
                )

            # סיום בחירה
            if body == "סיום":
                if not session["cart"]:
                    return f"הסל שלך ריק 🛒\n\nכתוב מספר להוסיף פריט:{CANCEL_HINT}"
                set_state(phone, ChatState.CHOOSING_DELIVERY)
                subtotal = cart_subtotal(session["cart"], db)
                delivery_note = (
                    f"\n\n_⚠️ משלוח זמין מהזמנה מעל ₪{DELIVERY_MIN:.0f} בלבד_"
                    if subtotal < DELIVERY_MIN else ""
                )
                opt1 = DELIVERY_OPTIONS["1"]
                opt2 = DELIVERY_OPTIONS["2"]
                opt3 = DELIVERY_OPTIONS["3"]
                return (
                    f"{format_cart(session['cart'], db)}\n\n"
                    f"📦 *איך תרצו לקבל את ההזמנה?*\n\n"
                    f"1️⃣ {opt1['label']} (חינם)\n"
                    f"   📍 {BUSINESS_INFO['address']}\n\n"
                    f"2️⃣ {opt2['label']} — ₪{opt2['cost']:.0f}\n"
                    f"3️⃣ {opt3['label']} — ₪{opt3['cost']:.0f}"
                    f"{delivery_note}"
                    f"{CANCEL_HINT}"
                )

            # הודעה לא מוכרת
            return (
                f"לא הבנתי 🤔\n\n"
                f"כתוב *מספר* להוסיף פריט (1, 2, 3, 4)\n"
                f"כתוב *תפריט* לראות את התפריט\n"
                f"כתוב *סיום* לסיים את הבחירה"
                f"{CANCEL_HINT}"
            )

        # ════ CHOOSING_DELIVERY — סוג משלוח ════
        if state == ChatState.CHOOSING_DELIVERY:

            if body == "חזור":
                set_state(phone, ChatState.ADDING_ITEMS)
                return f"{format_cart(session['cart'], db)}\n\n{build_menu_text(db)}"

            if body not in DELIVERY_OPTIONS:
                return (
                    f"כתוב *1* לאיסוף עצמי\n"
                    f"כתוב *2* למשלוח להוד השרון\n"
                    f"כתוב *3* למשלוח לכפר סבא"
                    f"{CANCEL_HINT}"
                )

            option = DELIVERY_OPTIONS[body]
            subtotal = cart_subtotal(session["cart"], db)

            if body in ("2", "3") and subtotal < DELIVERY_MIN:
                return (
                    f"⚠️ מינימום להזמנה למשלוח: ₪{DELIVERY_MIN:.0f}\n"
                    f"סכום הסל כרגע: ₪{subtotal:.0f}\n\n"
                    f"כתוב *חזור* להוסיף פריטים, או *1* לאיסוף עצמי."
                    f"{CANCEL_HINT}"
                )

            session["delivery_type"] = option["label"]
            session["delivery_cost"] = option["cost"]
            save_session(phone)

            if option["cost"] > 0:
                set_state(phone, ChatState.AWAITING_ADDRESS)
                return (
                    f"בחרת: *{option['label']}* 🚗\n\n"
                    f"לאיזו כתובת לשלוח?\n"
                    f"(רחוב + מספר בית + עיר)"
                    f"{CANCEL_HINT}"
                )
            else:
                set_state(phone, ChatState.AWAITING_NAME)
                return (
                    f"בחרת: *{option['label']}* 🏃\n\n"
                    f"מה שמך לצורך ההזמנה?"
                    f"{CANCEL_HINT}"
                )

        # ════ AWAITING_ADDRESS ════
        if state == ChatState.AWAITING_ADDRESS:
            if not is_valid_address(body):
                return (
                    f"הכתובת לא ברורה 🤔\n\n"
                    f"נא לכתוב כתובת מלאה הכוללת רחוב, מספר בית ועיר.\n"
                    f"לדוגמה: *הרצל 5, הוד השרון*"
                    f"{CANCEL_HINT}"
                )
            session["delivery_address"] = body
            save_session(phone)
            set_state(phone, ChatState.AWAITING_NAME)
            return (
                f"📍 נשלח אל: *{body}*\n\n"
                f"מה שמך לצורך ההזמנה?"
                f"{CANCEL_HINT}"
            )

        # ════ AWAITING_NAME ════
        if state == ChatState.AWAITING_NAME:
            session["name"] = body
            save_session(phone)
            set_state(phone, ChatState.AWAITING_PICKUP_TIME)
            action = "לאסוף" if session["delivery_type"] == "איסוף עצמי" else "לקבל את המשלוח"
            return (
                f"תודה *{body}*! 😊\n\n"
                f"באיזו שעה תרצה {action} ביום שבת?\n"
                f"(החל מ-08:00)"
                f"{CANCEL_HINT}"
            )

        # ════ AWAITING_PICKUP_TIME ════
        if state == ChatState.AWAITING_PICKUP_TIME:
            session["pickup_time"] = body
            save_session(phone)
            set_state(phone, ChatState.CONFIRMING_ORDER)

            cart_text = format_cart(session["cart"], db, session["delivery_cost"])
            next_saturday = get_next_saturday()

            if session["delivery_type"] != "איסוף עצמי":
                delivery_line = (
                    f"🚗 {session['delivery_type']}\n"
                    f"📍 כתובת: {session['delivery_address']}"
                )
            else:
                delivery_line = "🏃 איסוף עצמי"

            return (
                f"📋 *סיכום ההזמנה שלך:*\n\n"
                f"{cart_text}\n\n"
                f"👤 שם: {session['name']}\n"
                f"📅 תאריך: שבת {next_saturday}\n"
                f"🕗 שעה: {body}\n"
                f"{delivery_line}\n\n"
                f"השיבו:\n"
                f"*אישור* — לאישור ✅\n"
                f"*עריכה* — לחזרה לסל ✏️\n"
                f"*ביטול* — לביטול ❌"
            )

        # ════ CONFIRMING_ORDER ════
        if state == ChatState.CONFIRMING_ORDER:

            if body == "אישור":
                set_state(phone, ChatState.CHOOSING_PAYMENT)
                return (
                    "מעולה! 🎉\n\n"
                    "💳 *איך תרצה לשלם?*\n\n"
                    "1️⃣ מזומן\n"
                    "2️⃣ ביט\n"
                    "3️⃣ פייבוקס"
                    f"{CANCEL_HINT}"
                )

            if body in ("עריכה", "2"):
                set_state(phone, ChatState.ADDING_ITEMS)
                return (
                    f"חזרת לסל ✏️\n\n"
                    f"{format_cart(session['cart'], db)}\n\n"
                    f"{build_menu_text(db)}"
                )

            return (
                f"כתוב *אישור* לאישור ✅\n"
                f"כתוב *עריכה* לחזרה לסל ✏️\n"
                f"כתוב *ביטול* לביטול ❌"
            )

        # ════ CHOOSING_PAYMENT ════
        if state == ChatState.CHOOSING_PAYMENT:
            payment_map = {"1": "מזומן", "2": "ביט", "3": "פייבוקס"}

            if body not in payment_map:
                return (
                    f"כתוב *1* למזומן, *2* לביט, *3* לפייבוקס."
                    f"{CANCEL_HINT}"
                )

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
            notify_gabriel(order, customer, session["cart"], db, session.get("payment_method"))
            reset_session(phone)

            confirmation = (
                f"✅ *ההזמנה אושרה!*\n\n"
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

        # ════ ברירת מחדל ════
        return (
            "לא הבנתי 🤔\n\n"
            "כתוב *שלום* להתחלה מחדש."
        )

    finally:
        db.close()
