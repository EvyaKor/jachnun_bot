"""
מכונת המצבים של השיחה עבור ג'חנון אקספרס.
כל שיחת וואטסאפ עוברת דרך מצבים מוגדרים בלבד.
"""

from enum import Enum


class ChatState(str, Enum):
    """כל המצבים האפשריים של שיחה עם הלקוח."""
    GREETING = "ברכה"
    BROWSING_MENU = "עיון_בתפריט"
    ADDING_ITEMS = "הוספת_פריטים"
    CHOOSING_DELIVERY = "בחירת_משלוח"
    AWAITING_ADDRESS = "ממתין_לכתובת"
    AWAITING_NAME = "ממתין_לשם"
    AWAITING_PICKUP_TIME = "ממתין_לשעת_איסוף"
    CONFIRMING_ORDER = "אישור_הזמנה"
    CHOOSING_PAYMENT = "בחירת_תשלום"
    ORDER_PLACED = "הזמנה_בוצעה"
    CANCELLED = "בוטל"


# מילון session בזיכרון — מפתח: מספר טלפון, ערך: מצב + סל קניות
# בסביבת ייצור יש להחליף ב-Redis או DB
sessions: dict = {}


def get_session(phone: str) -> dict:
    """
    מחזיר את ה-session של הלקוח.
    אם לא קיים — יוצר חדש.
    """
    if phone not in sessions:
        sessions[phone] = {
            "state": ChatState.GREETING,
            "cart": {},            # {menu_item_id: quantity}
            "name": None,
            "pickup_time": None,
            "delivery_type": None,  # איסוף עצמי / הוד השרון / כפר סבא
            "delivery_cost": 0.0,
            "delivery_address": None,  # כתובת למשלוח (רק אם לא איסוף עצמי)
            "payment_method": None, # מזומן / ביט / פייבוקס
        }
    return sessions[phone]


def set_state(phone: str, state: ChatState):
    """מעדכן את מצב השיחה של לקוח."""
    session = get_session(phone)
    session["state"] = state


def get_state(phone: str) -> ChatState:
    """מחזיר את המצב הנוכחי של שיחת הלקוח."""
    return get_session(phone)["state"]


def reset_session(phone: str):
    """מאפס את ה-session של הלקוח לאחר סיום הזמנה או ביטול."""
    sessions.pop(phone, None)
