"""
מכונת המצבים של השיחה — מבוססת DB עם cache בזיכרון.
Session נשמר בטבלת הלקוחות: current_state + temp_order_data (JSON).
כך המצב לא אובד בהפעלה מחדש של השרת.
"""

import json
from enum import Enum


class ChatState(str, Enum):
    """כל המצבים האפשריים של שיחה עם הלקוח."""
    GREETING = "ברכה"
    BROWSING_MENU = "עיון_בתפריט"       # נשמר לתאימות לאחור
    ADDING_ITEMS = "הוספת_פריטים"
    CHOOSING_DELIVERY = "בחירת_משלוח"
    AWAITING_ADDRESS = "ממתין_לכתובת"
    AWAITING_NAME = "ממתין_לשם"
    AWAITING_PICKUP_TIME = "ממתין_לשעת_איסוף"
    CONFIRMING_ORDER = "אישור_הזמנה"
    CHOOSING_PAYMENT = "בחירת_תשלום"
    ORDER_PLACED = "הזמנה_בוצעה"
    CANCELLED = "בוטל"


# Cache בזיכרון — מפתח: מספר טלפון
_sessions: dict = {}


def _empty_session() -> dict:
    """מחזיר session ריק עם ערכי ברירת מחדל."""
    return {
        "state": ChatState.GREETING,
        "cart": {},            # {menu_item_id (int): quantity}
        "name": None,
        "pickup_time": None,
        "delivery_type": None,
        "delivery_cost": 0.0,
        "delivery_address": None,
        "payment_method": None,
    }


def _load_from_db(phone: str):
    """טוען session מה-DB לזיכרון. יוצר רשומת לקוח אם לא קיימת."""
    from database.db import SessionLocal
    from database.models import Customer

    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.phone_number == phone).first()

        if not customer:
            # לקוח חדש — יצירה עם מצב ברכה
            customer = Customer(
                phone_number=phone,
                current_state=ChatState.GREETING.value,
                temp_order_data=None,
            )
            db.add(customer)
            db.commit()
            _sessions[phone] = _empty_session()
            return

        sess = _empty_session()

        # שחזור מצב
        try:
            sess["state"] = ChatState(customer.current_state or ChatState.GREETING.value)
        except ValueError:
            sess["state"] = ChatState.GREETING

        # שחזור נתוני הזמנה זמניים
        if customer.temp_order_data:
            try:
                data = json.loads(customer.temp_order_data)
                # JSON מחזיר מפתחות כ-string — ממירים לint
                if "cart" in data and isinstance(data["cart"], dict):
                    data["cart"] = {int(k): v for k, v in data["cart"].items()}
                for key in ("name", "pickup_time", "delivery_type",
                            "delivery_cost", "delivery_address", "payment_method"):
                    if key in data:
                        sess[key] = data[key]
                sess["cart"] = data.get("cart", {})
            except (json.JSONDecodeError, ValueError):
                pass

        _sessions[phone] = sess

    finally:
        db.close()


def _persist_to_db(phone: str):
    """שומר את ה-session הנוכחי ל-DB."""
    if phone not in _sessions:
        return

    from database.db import SessionLocal
    from database.models import Customer

    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.phone_number == phone).first()
        if not customer:
            return

        sess = _sessions[phone]
        customer.current_state = sess["state"].value

        # סריאליזציה — מפתחות cart חייבים להיות string ב-JSON
        data = {
            "cart": {str(k): v for k, v in sess["cart"].items()},
            "name": sess.get("name"),
            "pickup_time": sess.get("pickup_time"),
            "delivery_type": sess.get("delivery_type"),
            "delivery_cost": sess.get("delivery_cost", 0.0),
            "delivery_address": sess.get("delivery_address"),
            "payment_method": sess.get("payment_method"),
        }
        customer.temp_order_data = json.dumps(data, ensure_ascii=False)
        db.commit()

    finally:
        db.close()


def get_session(phone: str) -> dict:
    """מחזיר את ה-session של הלקוח (מ-cache או מ-DB)."""
    if phone not in _sessions:
        _load_from_db(phone)
    return _sessions[phone]


def get_state(phone: str) -> ChatState:
    """מחזיר את המצב הנוכחי של השיחה."""
    return get_session(phone)["state"]


def set_state(phone: str, state: ChatState):
    """מעדכן מצב ושומר ל-DB."""
    session = get_session(phone)
    session["state"] = state
    _persist_to_db(phone)


def save_session(phone: str):
    """שומר את נתוני ה-session ל-DB (לאחר שינוי בסל וכו')."""
    _persist_to_db(phone)


def reset_session(phone: str):
    """מאפס session — בזיכרון ובDB."""
    _sessions.pop(phone, None)

    from database.db import SessionLocal
    from database.models import Customer

    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.phone_number == phone).first()
        if customer:
            customer.current_state = ChatState.GREETING.value
            customer.temp_order_data = None
            db.commit()
    finally:
        db.close()
