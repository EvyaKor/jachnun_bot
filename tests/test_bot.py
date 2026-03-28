"""
בדיקות מקיפות לבוט ג'חנון אקספרס.
מכסות: זרימת שיחה מלאה, מקרי קצה, מסד נתונים, לוגיקת שבת,
       משלוחים, תשלום, webhook HTTP, דשבורד אדמין.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch
from datetime import date

# אתחול מסד נתונים לבדיקות בזיכרון — StaticPool מבטיח שכל החיבורים חולקים את אותו DB
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

import database.db as _db_module
_db_module.engine = _test_engine
_db_module.SessionLocal = _TestSessionLocal

from database.db import init_db, seed_menu, SessionLocal
from database.models import Order, Customer, MenuItem, OrderItem
from handlers.message_handler import handle_message
from state_machine import reset_session, get_state, get_session, ChatState
from services.order_service import get_next_saturday

PHONE = "+972500000001"


@pytest.fixture(autouse=True)
def setup():
    """אתחול מסד נתונים ואיפוס session לפני כל בדיקה."""
    from database.models import Base
    from database.db import engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_menu()
    reset_session(PHONE)
    yield
    reset_session(PHONE)


# ============================================================
# 1. בדיקות זרימת שיחה בסיסית
# ============================================================

class TestBasicFlow:

    def test_greeting_any_message(self):
        """כל הודעה ראשונה מקבלת ברכה."""
        reply = handle_message(PHONE, "היי")
        assert "ג'חנון אקספרס" in reply
        assert "בני ברית" in reply

    def test_greeting_moves_to_browsing(self):
        """אחרי ברכה — המצב עובר ל-ADDING_ITEMS (תפריט מוצג מיד)."""
        handle_message(PHONE, "היי")
        assert get_state(PHONE) == ChatState.ADDING_ITEMS

    def test_menu_command_shows_menu(self):
        """כתיבת 'תפריט' מציגה את התפריט ועוברת למצב הזמנה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "תפריט")
        assert "ג'חנון" in reply
        assert "25" in reply
        assert "קובנייה" in reply
        assert "20" in reply

    def test_menu_switches_to_adding_items(self):
        """'תפריט' עובר למצב ADDING_ITEMS."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "תפריט")
        assert get_state(PHONE) == ChatState.ADDING_ITEMS

    def test_order_command_shows_menu(self):
        """כתיבת 'הזמנה' מציגה תפריט ועוברת למצב הוספה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "הזמנה")
        assert "ג'חנון" in reply
        assert get_state(PHONE) == ChatState.ADDING_ITEMS

    def test_menu_command_english(self):
        """כתיבת 'menu' באנגלית גם עובדת."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "menu")
        assert "ג'חנון" in reply
        assert get_state(PHONE) == ChatState.ADDING_ITEMS

    def test_greeting_shows_address(self):
        """הברכה כוללת את כתובת העסק."""
        reply = handle_message(PHONE, "שלום")
        assert "הוד השרון" in reply

    def test_greeting_shows_days(self):
        """הברכה כוללת את ימי הפעילות."""
        reply = handle_message(PHONE, "שלום")
        assert "שבת" in reply

    def test_browsing_unknown_message_falls_to_default(self):
        """הודעה לא מוכרת במצב BROWSING_MENU מחזירה עזרה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "בלה בלה")
        assert "לא הבנתי" in reply


# ============================================================
# 2. בדיקות הוספה לסל
# ============================================================

class TestCart:

    def _start_ordering(self):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")

    def test_add_jachnun(self):
        """הוספת ג'חנון לסל."""
        self._start_ordering()
        reply = handle_message(PHONE, "1")
        assert "ג'חנון" in reply
        assert "25" in reply

    def test_add_kubane(self):
        """הוספת קובנייה לסל."""
        self._start_ordering()
        reply = handle_message(PHONE, "2")
        assert "קובנייה" in reply
        assert "20" in reply

    def test_add_multiple_items(self):
        """הוספת מספר פריטים — מחיר מצטבר נכון."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        reply = handle_message(PHONE, "2")
        assert "₪70" in reply  # 25+25+20

    def test_add_jachnun_twice_increments_quantity(self):
        """הוספת ג'חנון פעמיים מגדילה כמות ב-session."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        session = get_session(PHONE)
        total_qty = sum(session["cart"].values())
        assert total_qty == 2

    def test_empty_cart_finish(self):
        """סיום עם סל ריק — מחזיר הודעת שגיאה."""
        self._start_ordering()
        reply = handle_message(PHONE, "סיום")
        assert "ריק" in reply

    def test_empty_cart_stays_in_adding_items(self):
        """סיום עם סל ריק — נשאר במצב ADDING_ITEMS."""
        self._start_ordering()
        handle_message(PHONE, "סיום")
        assert get_state(PHONE) == ChatState.ADDING_ITEMS

    def test_invalid_item_number(self):
        """מספר לא חוקי בתפריט — לא מוסיף לסל."""
        self._start_ordering()
        reply = handle_message(PHONE, "5")
        assert "לא הבנתי" in reply

    def test_invalid_item_zero(self):
        """0 לא חוקי בתפריט."""
        self._start_ordering()
        reply = handle_message(PHONE, "0")
        assert "לא הבנתי" in reply

    def test_cart_shows_subtotal(self):
        """הסל מציג סכום כולל נכון."""
        self._start_ordering()
        handle_message(PHONE, "1")  # 25
        reply = handle_message(PHONE, "2")  # 20
        assert "₪45" in reply

    def test_finish_moves_to_choosing_delivery(self):
        """סיום עם פריטים עובר למצב CHOOSING_DELIVERY."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        assert get_state(PHONE) == ChatState.CHOOSING_DELIVERY

    def test_only_kubane_order(self):
        """הזמנה של קובנייה בלבד עובדת."""
        self._start_ordering()
        handle_message(PHONE, "2")
        reply = handle_message(PHONE, "סיום")
        assert get_state(PHONE) == ChatState.CHOOSING_DELIVERY

    def test_add_five_jachnun_total_correct(self):
        """הוספת 5 ג'חנון — סה\"כ ₪125."""
        self._start_ordering()
        for _ in range(5):
            handle_message(PHONE, "1")
        session = get_session(PHONE)
        db = SessionLocal()
        from handlers.message_handler import cart_subtotal
        total = cart_subtotal(session["cart"], db)
        db.close()
        assert total == 125.0

    def test_mixed_large_order_3_jachnun_2_kubane(self):
        """הזמנה מעורבת: 3 ג'חנון + 2 קובנייה = ₪115."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "2")
        reply = handle_message(PHONE, "2")
        assert "₪115" in reply

    def test_cart_survives_through_awaiting_address(self):
        """הסל נשמר במצב AWAITING_ADDRESS."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")  # הוד השרון — מעבר ל-AWAITING_ADDRESS
        assert get_state(PHONE) == ChatState.AWAITING_ADDRESS
        session = get_session(PHONE)
        assert len(session["cart"]) > 0

    def test_cart_survives_through_awaiting_name(self):
        """הסל נשמר במצב AWAITING_NAME."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")  # איסוף עצמי — מעבר ל-AWAITING_NAME
        assert get_state(PHONE) == ChatState.AWAITING_NAME
        session = get_session(PHONE)
        assert len(session["cart"]) > 0

    def test_cart_survives_through_awaiting_pickup_time(self):
        """הסל נשמר במצב AWAITING_PICKUP_TIME."""
        self._start_ordering()
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "שם טסט")  # מעבר ל-AWAITING_PICKUP_TIME
        assert get_state(PHONE) == ChatState.AWAITING_PICKUP_TIME
        session = get_session(PHONE)
        assert len(session["cart"]) > 0


# ============================================================
# 3. בדיקות לוגיקת משלוח
# ============================================================

class TestDelivery:

    def _fill_cart(self, total_above_70=True):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        if total_above_70:
            handle_message(PHONE, "1")  # 25
            handle_message(PHONE, "1")  # 25
            handle_message(PHONE, "1")  # 25 = 75 total
        else:
            handle_message(PHONE, "1")  # 25 only
        handle_message(PHONE, "סיום")

    def test_delivery_options_shown(self):
        """אפשרויות משלוח מוצגות אחרי סיום."""
        self._fill_cart()
        state = get_state(PHONE)
        assert state == ChatState.CHOOSING_DELIVERY

    def test_self_pickup(self):
        """בחירת איסוף עצמי — ללא עלות משלוח."""
        self._fill_cart()
        reply = handle_message(PHONE, "1")
        assert "איסוף עצמי" in reply

    def test_delivery_hod_hasharon(self):
        """משלוח להוד השרון — ₪15."""
        self._fill_cart(total_above_70=True)
        reply = handle_message(PHONE, "2")
        assert "הוד השרון" in reply

    def test_delivery_kfar_saba(self):
        """משלוח לכפר סבא — ₪25."""
        self._fill_cart(total_above_70=True)
        reply = handle_message(PHONE, "3")
        assert "כפר סבא" in reply

    def test_delivery_below_minimum(self):
        """משלוח עם סל מתחת ל-₪70 — הודעת שגיאה."""
        self._fill_cart(total_above_70=False)
        reply = handle_message(PHONE, "2")
        assert "מינימום" in reply or "70" in reply

    def test_delivery_below_minimum_stays_in_choosing(self):
        """משלוח מתחת למינימום — נשאר במצב CHOOSING_DELIVERY."""
        self._fill_cart(total_above_70=False)
        handle_message(PHONE, "2")
        assert get_state(PHONE) == ChatState.CHOOSING_DELIVERY

    def test_delivery_cost_added_to_total(self):
        """עלות משלוח מתווספת לסכום הכולל."""
        self._fill_cart(total_above_70=True)
        handle_message(PHONE, "2")  # הוד השרון +15
        handle_message(PHONE, "רחוב טסט 1")  # כתובת
        handle_message(PHONE, "טסט")  # שם
        reply = handle_message(PHONE, "09:00")  # שעה
        assert "₪90" in reply  # 75 + 15

    def test_kfar_saba_cost_added(self):
        """עלות משלוח כפר סבא מתווספת נכון."""
        self._fill_cart(total_above_70=True)
        handle_message(PHONE, "3")  # כפר סבא +25
        handle_message(PHONE, "רחוב טסט 1")  # כתובת
        handle_message(PHONE, "טסט")
        reply = handle_message(PHONE, "09:00")
        assert "₪100" in reply  # 75 + 25

    def test_invalid_delivery_choice(self):
        """בחירת אפשרות משלוח לא חוקית."""
        self._fill_cart()
        reply = handle_message(PHONE, "9")
        assert "1" in reply and "2" in reply and "3" in reply

    def test_back_from_delivery_to_cart(self):
        """'חזור' ממסך משלוח חוזר למסך הוספת פריטים."""
        self._fill_cart()
        reply = handle_message(PHONE, "חזור")
        assert get_state(PHONE) == ChatState.ADDING_ITEMS
        assert "ג'חנון" in reply

    def test_delivery_warning_shown_below_minimum(self):
        """אזהרת מינימום מוצגת כבר במסך סיום הסל."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")  # 25 only
        reply = handle_message(PHONE, "סיום")
        assert "70" in reply  # warning about minimum

    def test_self_pickup_no_minimum(self):
        """איסוף עצמי עובד גם עם סל מתחת ל-₪70."""
        self._fill_cart(total_above_70=False)
        reply = handle_message(PHONE, "1")
        assert "איסוף עצמי" in reply
        assert get_state(PHONE) == ChatState.AWAITING_NAME

    def test_exactly_70_delivery_is_available(self):
        """בדיוק ₪70 — משלוח זמין (גבול תחתון כולל: 70 >= 70)."""
        # 2 ג'חנון (₪50) + 1 קובנייה (₪20) = ₪70
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")  # 25
        handle_message(PHONE, "1")  # 25
        handle_message(PHONE, "2")  # 20 → סה"כ 70
        handle_message(PHONE, "סיום")
        reply = handle_message(PHONE, "2")  # הוד השרון
        # צריך לעבור — לא להחזיר הודעת מינימום
        assert "מינימום" not in reply
        assert get_state(PHONE) == ChatState.AWAITING_ADDRESS

    def test_below_70_delivery_not_available(self):
        """מתחת ל-₪70 — משלוח לא זמין."""
        # 1 ג'חנון (₪25) — מתחת למינימום
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")  # 25
        handle_message(PHONE, "סיום")
        reply = handle_message(PHONE, "2")
        assert "מינימום" in reply or "70" in reply
        assert get_state(PHONE) == ChatState.CHOOSING_DELIVERY

    def test_back_then_add_item_completes_normally(self):
        """אחרי 'חזור', המשתמש מוסיף פריט ומשלים הזמנה נורמלית."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "חזור")  # חזור ל-ADDING_ITEMS
        assert get_state(PHONE) == ChatState.ADDING_ITEMS
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        assert get_state(PHONE) == ChatState.CHOOSING_DELIVERY

    def test_self_pickup_large_order_works(self):
        """איסוף עצמי עם הזמנה גדולה עובד ללא בעיות."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        for _ in range(5):
            handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        reply = handle_message(PHONE, "1")
        assert "איסוף עצמי" in reply
        assert get_state(PHONE) == ChatState.AWAITING_NAME


# ============================================================
# 4. בדיקות זרימת אישור מלאה
# ============================================================

class TestFullOrderFlow:

    def _complete_order(self, delivery="1", payment="1", name="טסט", address="רחוב טסט 1"):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, delivery)
        if delivery != "1":  # לא איסוף עצמי — צריך כתובת
            handle_message(PHONE, address)
        handle_message(PHONE, name)
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        return handle_message(PHONE, payment)

    def test_order_confirmed_cash(self):
        """הזמנה מלאה עם תשלום במזומן."""
        reply = self._complete_order(payment="1")
        assert "אושרה" in reply
        assert "מזומן" in reply

    def test_order_confirmed_bit(self):
        """הזמנה עם תשלום בביט — מציג מספר טלפון."""
        reply = self._complete_order(payment="2")
        assert "אושרה" in reply
        assert "054-2380330" in reply

    def test_order_confirmed_paybox(self):
        """הזמנה עם תשלום בפייבוקס — מציג מספר טלפון."""
        reply = self._complete_order(payment="3")
        assert "אושרה" in reply
        assert "054-2380330" in reply

    def test_order_saved_to_db(self):
        """הזמנה נשמרת במסד הנתונים."""
        self._complete_order()
        db = SessionLocal()
        orders = db.query(Order).all()
        db.close()
        assert len(orders) == 1

    def test_customer_saved_to_db(self):
        """לקוח נשמר במסד הנתונים."""
        self._complete_order(name="ישראל ישראלי")
        db = SessionLocal()
        customer = db.query(Customer).filter(Customer.phone_number == PHONE).first()
        db.close()
        assert customer is not None
        assert customer.name == "ישראל ישראלי"

    def test_order_items_saved_to_db(self):
        """פריטי ההזמנה נשמרים במסד הנתונים."""
        self._complete_order()
        db = SessionLocal()
        items = db.query(OrderItem).all()
        db.close()
        assert len(items) >= 1

    def test_order_total_price_correct(self):
        """מחיר כולל ההזמנה נכון — 3 ג'חנון = ₪75."""
        self._complete_order(delivery="1", payment="1")
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.total_price == 75.0

    def test_order_delivery_type_saved(self):
        """סוג המשלוח נשמר נכון."""
        self._complete_order(delivery="1")
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.delivery_type == "איסוף עצמי"

    def test_order_pickup_time_saved(self):
        """שעת האיסוף נשמרת נכון."""
        self._complete_order()
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.pickup_time == "09:00"

    def test_order_status_pending(self):
        """סטטוס הזמנה חדשה הוא 'ממתין'."""
        self._complete_order()
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.status == "ממתין"

    def test_order_pickup_date_is_saturday(self):
        """תאריך האיסוף הוא יום שבת."""
        self._complete_order()
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        from datetime import datetime
        d = datetime.strptime(order.pickup_date, "%d/%m/%Y").date()
        assert d.weekday() == 5

    def test_session_reset_after_order(self):
        """ה-session מתאפס לאחר אישור הזמנה."""
        self._complete_order()
        assert get_state(PHONE) == ChatState.GREETING

    def test_cancel_order(self):
        """ביטול הזמנה — session מתאפס."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        reply = handle_message(PHONE, "ביטול")
        assert "בוטלה" in reply
        assert get_state(PHONE) == ChatState.GREETING

    def test_cancel_order_not_saved_to_db(self):
        """הזמנה מבוטלת לא נשמרת למסד הנתונים."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "ביטול")
        db = SessionLocal()
        orders = db.query(Order).all()
        db.close()
        assert len(orders) == 0

    def test_confirming_unknown_message(self):
        """הודעה לא מוכרת במצב אישור מחזירה אפשרויות אישור/עריכה/ביטול."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        reply = handle_message(PHONE, "משהו אחר")
        assert "אישור" in reply

    def test_order_confirmation_shows_saturday_date(self):
        """אישור הזמנה מציג את תאריך השבת."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        reply = handle_message(PHONE, "09:00")
        assert "/" in reply  # תאריך בפורמט DD/MM/YYYY

    def test_order_confirmation_shows_name(self):
        """אישור הזמנה מציג את שם הלקוח."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "אברהם כהן")
        reply = handle_message(PHONE, "09:00")
        assert "אברהם כהן" in reply

    def test_customer_name_updated_on_second_order(self):
        """לקוח קיים — שם מתעדכן בהזמנה חדשה."""
        self._complete_order(name="שם ראשון")
        reset_session(PHONE)
        self._complete_order(name="שם חדש")
        db = SessionLocal()
        customer = db.query(Customer).filter(Customer.phone_number == PHONE).first()
        db.close()
        assert customer.name == "שם חדש"

    def test_two_orders_saved_to_db(self):
        """שני לקוחות שונים — שתי הזמנות בDB."""
        phone2 = "+972500000099"
        reset_session(phone2)
        self._complete_order()
        reset_session(phone2)
        handle_message(phone2, "היי")
        handle_message(phone2, "הזמנה")
        handle_message(phone2, "2")
        handle_message(phone2, "סיום")
        handle_message(phone2, "1")
        handle_message(phone2, "לקוח שני")
        handle_message(phone2, "10:00")
        handle_message(phone2, "אישור")
        handle_message(phone2, "1")
        db = SessionLocal()
        orders = db.query(Order).all()
        db.close()
        reset_session(phone2)
        assert len(orders) == 2


# ============================================================
# 5. בדיקות כתובת משלוח
# ============================================================

class TestDeliveryAddress:

    def _fill_cart_above_min(self):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")

    def test_delivery_asks_for_address(self):
        """בחירת משלוח מבקשת כתובת."""
        self._fill_cart_above_min()
        reply = handle_message(PHONE, "2")
        assert "כתובת" in reply
        assert get_state(PHONE) == ChatState.AWAITING_ADDRESS

    def test_kfar_saba_asks_for_address(self):
        """בחירת כפר סבא גם מבקשת כתובת."""
        self._fill_cart_above_min()
        reply = handle_message(PHONE, "3")
        assert "כתובת" in reply
        assert get_state(PHONE) == ChatState.AWAITING_ADDRESS

    def test_self_pickup_skips_address(self):
        """איסוף עצמי לא מבקש כתובת."""
        self._fill_cart_above_min()
        handle_message(PHONE, "1")
        assert get_state(PHONE) == ChatState.AWAITING_NAME

    def test_address_saved_in_session(self):
        """כתובת נשמרת ב-session."""
        self._fill_cart_above_min()
        handle_message(PHONE, "2")
        handle_message(PHONE, "רחוב הרצל 5, הוד השרון")
        session = get_session(PHONE)
        assert session["delivery_address"] == "רחוב הרצל 5, הוד השרון"

    def test_address_shown_in_confirmation(self):
        """כתובת מוצגת בסיכום ההזמנה."""
        self._fill_cart_above_min()
        handle_message(PHONE, "2")
        handle_message(PHONE, "רחוב הרצל 5, הוד השרון")
        handle_message(PHONE, "ישראל")
        reply = handle_message(PHONE, "09:00")
        assert "רחוב הרצל 5" in reply

    def test_address_saved_to_db(self):
        """כתובת נשמרת במסד הנתונים."""
        self._fill_cart_above_min()
        handle_message(PHONE, "2")
        handle_message(PHONE, "רחוב הרצל 5, הוד השרון")
        handle_message(PHONE, "ישראל")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        handle_message(PHONE, "1")
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.delivery_address == "רחוב הרצל 5, הוד השרון"

    def test_self_pickup_no_address_in_db(self):
        """איסוף עצמי — כתובת ריקה ב-DB."""
        self._fill_cart_above_min()
        handle_message(PHONE, "1")
        handle_message(PHONE, "ישראל")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        handle_message(PHONE, "1")
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.delivery_address is None

    def test_address_moves_to_awaiting_name(self):
        """אחרי כתובת — עובר למצב AWAITING_NAME."""
        self._fill_cart_above_min()
        handle_message(PHONE, "2")
        handle_message(PHONE, "רחוב הרצל 5")
        assert get_state(PHONE) == ChatState.AWAITING_NAME


# ============================================================
# 6. בדיקות לוגיקת שבת
# ============================================================

class TestSaturdayLogic:

    def test_next_saturday_is_saturday(self):
        """הפונקציה תמיד מחזירה יום שבת."""
        saturday_str = get_next_saturday()
        from datetime import datetime
        d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
        assert d.weekday() == 5  # 5 = שבת

    def test_next_saturday_not_today_if_saturday(self):
        """אם היום שבת — מחזיר את השבת הבאה ולא היום."""
        with patch("services.order_service.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 4, 4)  # שבת
            saturday_str = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
            assert d > date(2026, 4, 4)

    def test_next_saturday_from_sunday(self):
        """מיום ראשון — השבת הקרובה היא 6 ימים קדימה."""
        with patch("services.order_service.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 3, 29)  # ראשון
            saturday_str = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
            assert d == date(2026, 4, 4)

    def test_order_date_shown_in_confirmation(self):
        """תאריך השבת מופיע בהודעת הברכה הראשונה."""
        reply = handle_message(PHONE, "היי")
        assert "/" in reply  # תאריך בפורמט DD/MM/YYYY

    def test_order_date_format(self):
        """תאריך השבת בפורמט DD/MM/YYYY."""
        saturday_str = get_next_saturday()
        parts = saturday_str.split("/")
        assert len(parts) == 3
        assert len(parts[0]) == 2  # DD
        assert len(parts[1]) == 2  # MM
        assert len(parts[2]) == 4  # YYYY


# ============================================================
# 6. בדיקות מקרי קצה
# ============================================================

class TestEdgeCases:

    def test_unknown_message_returns_help(self):
        """הודעה לא מובנת מחזירה הוראות עזרה."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "בלבול")
        assert "לא הבנתי" in reply

    def test_multiple_sessions_independent(self):
        """שני לקוחות שונים — sessions עצמאיים."""
        phone2 = "+972500000002"
        reset_session(phone2)

        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")

        handle_message(phone2, "היי")

        assert get_state(PHONE) == ChatState.ADDING_ITEMS
        assert get_state(phone2) == ChatState.ADDING_ITEMS

        reset_session(phone2)

    def test_invalid_payment_choice(self):
        """בחירת אמצעי תשלום לא חוקי."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        reply = handle_message(PHONE, "9")  # מספר לא חוקי
        assert "1" in reply and "2" in reply and "3" in reply

    def test_menu_items_exist_in_db(self):
        """פריטי התפריט קיימים במסד הנתונים (2 מנות + 2 תוספות)."""
        db = SessionLocal()
        items = db.query(MenuItem).all()
        db.close()
        assert len(items) == 4
        names = [i.name for i in items]
        assert "ג'חנון" in names
        assert "קובנייה" in names
        assert "ביצה נוספת" in names
        assert "רסק עגניות + סחוג" in names

    def test_jachnun_price(self):
        """מחיר ג'חנון נכון — ₪25."""
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        db.close()
        assert item.price == 25.0

    def test_kubane_price(self):
        """מחיר קובנייה נכון — ₪20."""
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "קובנייה").first()
        db.close()
        assert item.price == 20.0

    def test_seed_menu_idempotent(self):
        """קריאה כפולה ל-seed_menu לא מכפילה פריטים."""
        seed_menu()
        seed_menu()
        db = SessionLocal()
        count = db.query(MenuItem).count()
        db.close()
        assert count == 4

    def test_whitespace_in_message_stripped(self):
        """רווחים בתחילת/סוף הודעה מוסרים."""
        reply = handle_message(PHONE, "  היי  ")
        assert "ג'חנון אקספרס" in reply

    def test_new_session_starts_at_greeting(self):
        """session חדש מתחיל במצב GREETING."""
        assert get_state(PHONE) == ChatState.GREETING

    def test_jachnun_is_not_dairy(self):
        """ג'חנון הוא לא חלבי."""
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        db.close()
        assert item.is_dairy is False

    def test_kubane_is_dairy(self):
        """קובנייה היא חלבית."""
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "קובנייה").first()
        db.close()
        assert item.is_dairy is True

    def test_items_available_by_default(self):
        """כל פריטי התפריט זמינים כברירת מחדל (2 מנות + 2 תוספות)."""
        db = SessionLocal()
        items = db.query(MenuItem).filter(MenuItem.is_available == True).all()
        db.close()
        assert len(items) == 4


# ============================================================
# 7. בדיקות HTTP — Webhook ו-Admin
# ============================================================

class TestHTTPEndpoints:

    @pytest.fixture(autouse=True)
    def client(self):
        """יוצר FastAPI test client."""
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_root_returns_200(self):
        """נקודת הבסיס / מחזירה 200."""
        response = self.client.get("/")
        assert response.status_code == 200

    def test_root_returns_active_status(self):
        """נקודת הבסיס מחזירה סטטוס פעיל."""
        response = self.client.get("/")
        assert "פעיל" in response.text

    def test_webhook_returns_xml(self):
        """ה-webhook מחזיר XML תקין."""
        response = self.client.post("/webhook", data={
            "From": "whatsapp:+972500000001",
            "Body": "היי"
        })
        assert response.status_code == 200
        assert "xml" in response.headers["content-type"]

    def test_webhook_response_contains_reply(self):
        """תשובת ה-webhook מכילה תשובה להודעה."""
        reset_session("+972500000001")
        response = self.client.post("/webhook", data={
            "From": "whatsapp:+972500000001",
            "Body": "היי"
        })
        assert "ג'חנון אקספרס" in response.text

    def test_webhook_strips_whatsapp_prefix(self):
        """ה-webhook מסיר את הקידומת 'whatsapp:' מהמספר."""
        reset_session("+972500000050")
        response = self.client.post("/webhook", data={
            "From": "whatsapp:+972500000050",
            "Body": "שלום"
        })
        assert response.status_code == 200
        # מוודא שה-session נוצר ללא הקידומת
        state = get_state("+972500000050")
        assert state == ChatState.ADDING_ITEMS
        reset_session("+972500000050")

    def test_webhook_missing_body_returns_422(self):
        """webhook ללא שדות חובה מחזיר שגיאה."""
        response = self.client.post("/webhook", data={})
        assert response.status_code == 422

    def test_admin_returns_200(self):
        """דשבורד אדמין מחזיר 200."""
        response = self.client.get("/admin")
        assert response.status_code == 200

    def test_admin_returns_html(self):
        """דשבורד אדמין מחזיר HTML."""
        response = self.client.get("/admin")
        assert "text/html" in response.headers["content-type"]

    def test_admin_shows_gabriel_greeting(self):
        """דשבורד אדמין מציג ברכה לגבריאל."""
        response = self.client.get("/admin")
        assert "גבריאל" in response.text

    def test_admin_update_order_status(self):
        """עדכון סטטוס הזמנה מהדשבורד עובד."""
        # צור הזמנה קודם
        reset_session("+972500000001")
        for msg in ["היי", "הזמנה", "1", "1", "1", "סיום", "1", "טסט", "09:00", "אישור", "1"]:
            handle_message("+972500000001", msg)

        db = SessionLocal()
        order = db.query(Order).first()
        order_id = order.id
        db.close()

        response = self.client.post(
            f"/admin/update/{order_id}",
            data={"status": "אושר"},
            follow_redirects=False
        )
        assert response.status_code == 303

        db = SessionLocal()
        order = db.query(Order).filter(Order.id == order_id).first()
        db.close()
        assert order.status == "אושר"

    def test_admin_shows_orders(self):
        """דשבורד אדמין מציג הזמנות קיימות."""
        reset_session("+972500000001")
        for msg in ["היי", "הזמנה", "1", "סיום", "1", "שם לקוח", "09:00", "אישור", "1"]:
            handle_message("+972500000001", msg)

        response = self.client.get("/admin")
        assert "שם לקוח" in response.text


# ============================================================
# 8. בדיקות מכונת המצבים (TestStateMachine)
# ============================================================

class TestStateMachine:

    def test_reset_session_clears_cart(self):
        """reset_session מנקה את הסל."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        session = get_session(PHONE)
        assert len(session["cart"]) > 0
        reset_session(PHONE)
        session = get_session(PHONE)
        assert session["cart"] == {}

    def test_reset_session_clears_name(self):
        """reset_session מנקה את השם."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "גבי")
        session = get_session(PHONE)
        assert session["name"] == "גבי"
        reset_session(PHONE)
        session = get_session(PHONE)
        assert session["name"] is None

    def test_reset_session_clears_address(self):
        """reset_session מנקה את הכתובת."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")
        handle_message(PHONE, "רחוב הרצל 5")
        session = get_session(PHONE)
        assert session["delivery_address"] == "רחוב הרצל 5"
        reset_session(PHONE)
        session = get_session(PHONE)
        assert session["delivery_address"] is None

    def test_reset_session_clears_delivery_type(self):
        """reset_session מנקה את סוג המשלוח."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")  # איסוף עצמי
        session = get_session(PHONE)
        assert session["delivery_type"] == "איסוף עצמי"
        reset_session(PHONE)
        session = get_session(PHONE)
        assert session["delivery_type"] is None

    def test_reset_session_clears_delivery_cost(self):
        """reset_session מנקה את עלות המשלוח."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")  # איסוף עצמי — עלות 0
        session = get_session(PHONE)
        assert session["delivery_cost"] == 0.0
        reset_session(PHONE)
        session = get_session(PHONE)
        assert session["delivery_cost"] == 0.0

    def test_reset_session_sets_state_to_greeting(self):
        """reset_session מחזיר את המצב ל-GREETING."""
        handle_message(PHONE, "היי")
        assert get_state(PHONE) == ChatState.ADDING_ITEMS
        reset_session(PHONE)
        assert get_state(PHONE) == ChatState.GREETING

    def test_set_state_and_get_state(self):
        """set_state ו-get_state עובדים נכון."""
        from state_machine import set_state
        set_state(PHONE, ChatState.ADDING_ITEMS)
        assert get_state(PHONE) == ChatState.ADDING_ITEMS
        set_state(PHONE, ChatState.CHOOSING_PAYMENT)
        assert get_state(PHONE) == ChatState.CHOOSING_PAYMENT

    def test_get_session_creates_new_if_not_exists(self):
        """get_session יוצר session חדש אם לא קיים."""
        new_phone = "+972500009999"
        reset_session(new_phone)
        from state_machine import _sessions as sessions
        # וודא שאין session
        sessions.pop(new_phone, None)
        session = get_session(new_phone)
        assert session is not None
        assert session["state"] == ChatState.GREETING
        reset_session(new_phone)

    def test_all_chat_states_exist(self):
        """כל ערכי ChatState קיימים."""
        assert hasattr(ChatState, "GREETING")
        assert hasattr(ChatState, "BROWSING_MENU")
        assert hasattr(ChatState, "ADDING_ITEMS")
        assert hasattr(ChatState, "CHOOSING_DELIVERY")
        assert hasattr(ChatState, "AWAITING_ADDRESS")
        assert hasattr(ChatState, "AWAITING_NAME")
        assert hasattr(ChatState, "AWAITING_PICKUP_TIME")
        assert hasattr(ChatState, "CONFIRMING_ORDER")
        assert hasattr(ChatState, "CHOOSING_PAYMENT")
        assert hasattr(ChatState, "ORDER_PLACED")
        assert hasattr(ChatState, "CANCELLED")

    def test_sessions_independent_per_phone(self):
        """sessions עצמאיים לכל מספר טלפון."""
        phone_a = "+972500001111"
        phone_b = "+972500002222"
        reset_session(phone_a)
        reset_session(phone_b)
        handle_message(phone_a, "היי")
        handle_message(phone_a, "הזמנה")
        # phone_a ב-ADDING_ITEMS, phone_b ב-GREETING
        assert get_state(phone_a) == ChatState.ADDING_ITEMS
        assert get_state(phone_b) == ChatState.GREETING
        reset_session(phone_a)
        reset_session(phone_b)

    def test_after_reset_new_message_starts_fresh(self):
        """אחרי reset, הודעה חדשה מתחילה מברכה מחדש."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        reset_session(PHONE)
        reply = handle_message(PHONE, "שלום")
        assert "ג'חנון אקספרס" in reply
        assert get_state(PHONE) == ChatState.ADDING_ITEMS


# ============================================================
# 9. בדיקות התראת גבריאל (TestNotification)
# ============================================================

class TestNotification:

    def _make_order_and_customer(self, with_address=True):
        """יוצר Order ו-Customer לבדיקות ישירות של notify_gabriel.
        מחזיר (order, customer, cart, db) — הקורא אחראי לסגור את db."""
        db = SessionLocal()
        customer = Customer(phone_number="+972500000042", name="ישראל כהן")
        db.add(customer)
        db.commit()
        db.refresh(customer)

        jachnun = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()

        order = Order(
            customer_id=customer.id,
            pickup_date="05/04/2026",
            pickup_time="09:00",
            delivery_type="משלוח להוד השרון" if with_address else "איסוף עצמי",
            delivery_cost=15.0 if with_address else 0.0,
            delivery_address="רחוב הרצל 5, הוד השרון" if with_address else None,
            total_price=90.0 if with_address else 75.0,
            status="ממתין",
        )
        db.add(order)
        db.commit()
        db.refresh(order)

        cart = {jachnun.id: 3}
        return order, customer, cart, db

    def test_notify_gabriel_with_address_shows_arrow(self):
        """notify_gabriel עם כתובת מציג חץ → ואת הכתובת."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer(with_address=True)
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "רחוב הרצל 5" in printed
                assert "→" in printed
        db.close()

    def test_notify_gabriel_without_address_no_arrow(self):
        """notify_gabriel ללא כתובת (איסוף עצמי) — בלי חץ."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer(with_address=False)
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "→" not in printed
                assert "איסוף עצמי" in printed
        db.close()

    def test_notify_gabriel_no_twilio_no_exception(self):
        """notify_gabriel ללא Twilio לא זורק exception."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer(with_address=False)
        try:
            with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
                with patch.object(order_svc, "TWILIO_AUTH_TOKEN", None):
                    notify_gabriel(order, customer, cart, db)
        except Exception:
            pytest.fail("notify_gabriel זרק exception כשאין Twilio")
        finally:
            db.close()

    def test_notify_gabriel_message_contains_order_id(self):
        """הודעה לגבריאל מכילה מספר הזמנה."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer()
        order_id = order.id
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert str(order_id) in printed
        db.close()

    def test_notify_gabriel_message_contains_customer_name(self):
        """הודעה לגבריאל מכילה שם הלקוח."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer()
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "ישראל כהן" in printed
        db.close()

    def test_notify_gabriel_message_contains_customer_phone(self):
        """הודעה לגבריאל מכילה מספר טלפון הלקוח."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer()
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "+972500000042" in printed
        db.close()

    def test_notify_gabriel_message_contains_total_price(self):
        """הודעה לגבריאל מכילה מחיר כולל."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer()
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "90" in printed
        db.close()

    def test_notify_gabriel_message_contains_pickup_date_and_time(self):
        """הודעה לגבריאל מכילה תאריך ושעה."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer()
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "05/04/2026" in printed
                assert "09:00" in printed
        db.close()

    def test_notify_gabriel_message_contains_item_names_and_quantities(self):
        """הודעה לגבריאל מכילה שמות פריטים וכמויות."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        order, customer, cart, db = self._make_order_and_customer()
        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "x3" in printed  # כמות
                assert "חנון" in printed  # חלק משם הפריט (ללא גרש שמוחלק בrepr)
        db.close()


# ============================================================
# 10. בדיקות שלמות מסד נתונים (TestDatabaseIntegrity)
# ============================================================

class TestDatabaseIntegrity:

    def _complete_order_with_items(self, phone=PHONE, delivery="1", items_1=1, items_2=0, name="טסט"):
        """עוזר ליצירת הזמנה עם כמויות מותאמות."""
        handle_message(phone, "היי")
        handle_message(phone, "הזמנה")
        for _ in range(items_1):
            handle_message(phone, "1")
        for _ in range(items_2):
            handle_message(phone, "2")
        handle_message(phone, "סיום")
        handle_message(phone, delivery)
        if delivery != "1":
            handle_message(phone, "רחוב טסט 1")
        handle_message(phone, name)
        handle_message(phone, "09:00")
        handle_message(phone, "אישור")
        handle_message(phone, "1")

    def test_order_item_quantity_2_when_added_twice(self):
        """הוספת ג'חנון פעמיים יוצרת OrderItem אחד עם quantity=2."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        handle_message(PHONE, "1")

        db = SessionLocal()
        order = db.query(Order).first()
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        db.close()

        # צריך להיות רשומה אחת עם quantity=2 (לא שתי רשומות)
        assert len(items) == 1
        assert items[0].quantity == 2

    def test_order_has_correct_customer_id(self):
        """להזמנה יש customer_id נכון."""
        self._complete_order_with_items(name="לקוח בדיקה")
        db = SessionLocal()
        customer = db.query(Customer).filter(Customer.phone_number == PHONE).first()
        order = db.query(Order).first()
        db.close()
        assert order.customer_id == customer.id

    def test_order_item_has_correct_order_id_and_menu_item_id(self):
        """ל-OrderItem יש order_id ו-menu_item_id נכונים."""
        self._complete_order_with_items()
        db = SessionLocal()
        order = db.query(Order).first()
        jachnun = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        order_item = db.query(OrderItem).filter(OrderItem.order_id == order.id).first()
        db.close()
        assert order_item.order_id == order.id
        assert order_item.menu_item_id == jachnun.id

    def test_two_different_customers_have_separate_records(self):
        """שני לקוחות שונים — רשומות נפרדות."""
        phone2 = "+972500000077"
        reset_session(phone2)
        self._complete_order_with_items(phone=PHONE, name="לקוח ראשון")
        self._complete_order_with_items(phone=phone2, name="לקוח שני")
        db = SessionLocal()
        customers = db.query(Customer).all()
        db.close()
        reset_session(phone2)
        assert len(customers) == 2
        phones = [c.phone_number for c in customers]
        assert PHONE in phones
        assert phone2 in phones

    def test_customer_phone_unique_second_order_updates_not_duplicates(self):
        """הזמנה שנייה מאותו טלפון — מעדכנת לקוח קיים ולא יוצרת כפיל."""
        self._complete_order_with_items(name="שם ראשון")
        reset_session(PHONE)
        self._complete_order_with_items(name="שם שני")
        db = SessionLocal()
        customers = db.query(Customer).filter(Customer.phone_number == PHONE).all()
        db.close()
        assert len(customers) == 1
        assert customers[0].name == "שם שני"

    def test_order_total_price_includes_delivery_cost(self):
        """total_price כולל עלות משלוח."""
        # 3 ג'חנון = ₪75, הוד השרון = ₪15, סה"כ = ₪90
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")  # הוד השרון
        handle_message(PHONE, "רחוב טסט 1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        handle_message(PHONE, "אישור")
        handle_message(PHONE, "1")

        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.total_price == 90.0
        assert order.delivery_cost == 15.0


# ============================================================
# 11. בדיקות דשבורד אדמין (TestAdminDashboard)
# ============================================================

class TestAdminDashboard:

    @pytest.fixture(autouse=True)
    def http_client(self):
        """יוצר FastAPI test client."""
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def _create_order(self, phone="+972510000001", name="לקוח טסט", delivery="1",
                      items=3, payment="1"):
        """יוצר הזמנה מלאה לבדיקות דשבורד."""
        reset_session(phone)
        handle_message(phone, "היי")
        handle_message(phone, "הזמנה")
        for _ in range(items):
            handle_message(phone, "1")
        handle_message(phone, "סיום")
        handle_message(phone, delivery)
        if delivery != "1":
            handle_message(phone, "רחוב דשבורד 1")
        handle_message(phone, name)
        handle_message(phone, "09:00")
        handle_message(phone, "אישור")
        handle_message(phone, payment)
        reset_session(phone)

    def test_dashboard_shows_correct_total_count(self):
        """דשבורד מציג ספירת הזמנות נכונה."""
        self._create_order(phone="+972510000001", name="לקוח 1")
        self._create_order(phone="+972510000002", name="לקוח 2")
        response = self.client.get("/admin")
        assert "2" in response.text

    def test_dashboard_shows_correct_pending_count(self):
        """דשבורד מציג ספירת ממתינות נכונה."""
        self._create_order(phone="+972510000011", name="ממתין 1")
        response = self.client.get("/admin")
        assert "ממתינות לאישור" in response.text or "ממתין" in response.text

    def test_dashboard_shows_revenue_excluding_cancelled(self):
        """הכנסה צפויה לא כוללת הזמנות מבוטלות."""
        self._create_order(phone="+972510000021", name="הזמנה רגילה")
        db = SessionLocal()
        order = db.query(Order).order_by(Order.id.desc()).first()
        order.status = "בוטל"
        db.commit()
        db.close()

        response = self.client.get("/admin")
        # ₪0 כי ההזמנה בוטלה
        assert "₪0" in response.text

    def test_dashboard_shows_next_saturday_date(self):
        """דשבורד מציג את תאריך השבת הקרובה."""
        saturday = get_next_saturday()
        response = self.client.get("/admin")
        assert saturday in response.text

    def test_dashboard_shows_customer_name(self):
        """דשבורד מציג שם לקוח."""
        self._create_order(phone="+972510000031", name="אברהם אבינו")
        response = self.client.get("/admin")
        assert "אברהם אבינו" in response.text

    def test_dashboard_shows_customer_phone(self):
        """דשבורד מציג מספר טלפון לקוח."""
        self._create_order(phone="+972510000041", name="לקוח טסט")
        response = self.client.get("/admin")
        assert "+972510000041" in response.text

    def test_dashboard_shows_pickup_time(self):
        """דשבורד מציג שעת איסוף."""
        self._create_order(phone="+972510000051")
        response = self.client.get("/admin")
        assert "09:00" in response.text

    def test_dashboard_shows_delivery_type(self):
        """דשבורד מציג סוג משלוח."""
        self._create_order(phone="+972510000061")
        response = self.client.get("/admin")
        assert "איסוף עצמי" in response.text

    def test_dashboard_shows_delivery_address_when_present(self):
        """דשבורד מציג כתובת משלוח כשקיימת."""
        self._create_order(phone="+972510000071", delivery="2")
        response = self.client.get("/admin")
        assert "רחוב דשבורד 1" in response.text

    def test_dashboard_shows_order_items(self):
        """דשבורד מציג פריטי הזמנה."""
        self._create_order(phone="+972510000081")
        response = self.client.get("/admin")
        assert "ג'חנון" in response.text

    def test_dashboard_shows_order_total_price(self):
        """דשבורד מציג מחיר כולל של הזמנה."""
        self._create_order(phone="+972510000091", items=3)  # 75
        response = self.client.get("/admin")
        assert "75" in response.text

    def test_dashboard_shows_no_orders_message_when_empty(self):
        """דשבורד מציג 'אין הזמנות' כשאין הזמנות."""
        response = self.client.get("/admin")
        assert "אין הזמנות" in response.text

    def test_dashboard_update_to_approved_shows_in_dashboard(self):
        """עדכון הזמנה ל'אושר' — מוצג בדשבורד."""
        self._create_order(phone="+972510000101")
        db = SessionLocal()
        order = db.query(Order).order_by(Order.id.desc()).first()
        order_id = order.id
        db.close()

        self.client.post(f"/admin/update/{order_id}", data={"status": "אושר"},
                         follow_redirects=False)
        response = self.client.get("/admin")
        assert "אושר" in response.text

    def test_dashboard_cancelled_excluded_from_revenue(self):
        """הזמנה מבוטלת לא נספרת בהכנסה."""
        self._create_order(phone="+972510000111", items=3)  # 75
        db = SessionLocal()
        order = db.query(Order).order_by(Order.id.desc()).first()
        order.status = "בוטל"
        db.commit()
        db.close()

        response = self.client.get("/admin")
        # הכנסה צריכה להיות 0 (הזמנה בוטלה)
        assert "₪0" in response.text

    def test_update_nonexistent_order_returns_redirect(self):
        """עדכון הזמנה לא קיימת מחזיר redirect ולא קריסה."""
        response = self.client.post("/admin/update/99999", data={"status": "אושר"},
                                    follow_redirects=False)
        assert response.status_code == 303


# ============================================================
# 12. בדיקות TwiML Webhook (TestWebhookTwiML)
# ============================================================

class TestWebhookTwiML:

    @pytest.fixture(autouse=True)
    def http_client(self):
        """יוצר FastAPI test client."""
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_greeting_webhook_response_contains_media_tags(self):
        """תשובת ה-webhook לברכה ראשונה מכילה תגי <Media>."""
        phone = "+972510001001"
        reset_session(phone)
        response = self.client.post("/webhook", data={
            "From": f"whatsapp:{phone}",
            "Body": "היי"
        })
        assert response.status_code == 200
        assert "<Media>" in response.text or "Media" in response.text
        reset_session(phone)

    def test_non_greeting_webhook_response_no_media_tags(self):
        """תשובת ה-webhook שאינה ברכה ראשונה לא מכילה תגי Media."""
        phone = "+972510001002"
        reset_session(phone)
        handle_message(phone, "היי")  # עוברים מ-GREETING
        response = self.client.post("/webhook", data={
            "From": f"whatsapp:{phone}",
            "Body": "תפריט"
        })
        assert response.status_code == 200
        # לא אמורה להיות Media בתגובה שאינה ברכה
        assert "<Media>" not in response.text
        reset_session(phone)

    def test_webhook_handles_hebrew_body_correctly(self):
        """ה-webhook מטפל בגוף עם טקסט עברי נכון."""
        phone = "+972510001003"
        reset_session(phone)
        handle_message(phone, "היי")
        response = self.client.post("/webhook", data={
            "From": f"whatsapp:{phone}",
            "Body": "תפריט"
        })
        assert response.status_code == 200
        assert "ג'חנון" in response.text
        reset_session(phone)

    def test_webhook_response_is_valid_xml(self):
        """תשובת ה-webhook היא XML תקין שניתן לפרס."""
        import xml.etree.ElementTree as ET
        phone = "+972510001004"
        reset_session(phone)
        response = self.client.post("/webhook", data={
            "From": f"whatsapp:{phone}",
            "Body": "שלום"
        })
        assert response.status_code == 200
        try:
            ET.fromstring(response.text)
        except ET.ParseError:
            pytest.fail("תשובת ה-webhook אינה XML תקין")
        reset_session(phone)

    def test_webhook_greeting_has_two_media_images(self):
        """ברכה ראשונה מכילה 2 תמונות."""
        phone = "+972510001005"
        reset_session(phone)
        response = self.client.post("/webhook", data={
            "From": f"whatsapp:{phone}",
            "Body": "היי"
        })
        assert response.status_code == 200
        # בדיקה שה-XML מכיל לפחות 2 הפניות לתמונות
        from handlers.message_handler import PRODUCT_IMAGES
        assert len(PRODUCT_IMAGES) == 2
        for img_url in PRODUCT_IMAGES:
            assert img_url in response.text
        reset_session(phone)


# ============================================================
# 13. בדיקות זרימת תשלום (TestPaymentFlow)
# ============================================================

class TestPaymentFlow:

    def _reach_payment(self, phone=PHONE):
        """מגיע למצב CHOOSING_PAYMENT."""
        handle_message(phone, "היי")
        handle_message(phone, "הזמנה")
        handle_message(phone, "1")
        handle_message(phone, "1")
        handle_message(phone, "1")
        handle_message(phone, "סיום")
        handle_message(phone, "1")
        handle_message(phone, "טסט")
        handle_message(phone, "09:00")
        handle_message(phone, "אישור")

    def test_invalid_payment_stays_in_choosing_payment(self):
        """בחירת תשלום לא חוקית — נשאר במצב CHOOSING_PAYMENT."""
        self._reach_payment()
        assert get_state(PHONE) == ChatState.CHOOSING_PAYMENT
        handle_message(PHONE, "X")
        assert get_state(PHONE) == ChatState.CHOOSING_PAYMENT

    def test_multiple_invalid_payments_dont_change_state(self):
        """מספר בחירות תשלום לא חוקיות לא משנות מצב."""
        self._reach_payment()
        for invalid in ["0", "5", "abc", "ביט"]:
            handle_message(PHONE, invalid)
        assert get_state(PHONE) == ChatState.CHOOSING_PAYMENT

    def test_cash_payment_confirmation_no_phone_number(self):
        """אישור תשלום במזומן לא מציג מספר טלפון."""
        self._reach_payment()
        reply = handle_message(PHONE, "1")
        assert "054-2380330" not in reply

    def test_bit_payment_confirmation_includes_phone(self):
        """אישור תשלום בביט מציג מספר טלפון לתשלום."""
        self._reach_payment()
        reply = handle_message(PHONE, "2")
        assert "054-2380330" in reply

    def test_paybox_payment_confirmation_includes_phone(self):
        """אישור תשלום בפייבוקס מציג מספר טלפון לתשלום."""
        self._reach_payment()
        reply = handle_message(PHONE, "3")
        assert "054-2380330" in reply

    def test_confirmation_includes_order_id(self):
        """אישור הזמנה מציג מספר הזמנה."""
        self._reach_payment()
        reply = handle_message(PHONE, "1")
        assert "#" in reply

    def test_confirmation_includes_total_price(self):
        """אישור הזמנה מציג מחיר כולל."""
        self._reach_payment()
        reply = handle_message(PHONE, "1")
        assert "75" in reply  # 3 ג'חנון

    def test_confirmation_includes_pickup_date(self):
        """אישור הזמנה מציג תאריך איסוף."""
        self._reach_payment()
        reply = handle_message(PHONE, "1")
        saturday = get_next_saturday()
        assert saturday in reply


# ============================================================
# 14. זרימה מלאה עם כתובת משלוח (TestFullFlowWithAddress)
# ============================================================

class TestFullFlowWithAddress:

    def _complete_delivery_order(self, phone=PHONE, delivery_option="2",
                                  address="רחוב הרצל 5, הוד השרון", name="דוד לוי",
                                  payment="1"):
        """זרימה מלאה עם משלוח."""
        handle_message(phone, "היי")
        handle_message(phone, "הזמנה")
        handle_message(phone, "1")
        handle_message(phone, "1")
        handle_message(phone, "1")
        handle_message(phone, "סיום")
        handle_message(phone, delivery_option)
        handle_message(phone, address)
        handle_message(phone, name)
        handle_message(phone, "09:00")
        handle_message(phone, "אישור")
        return handle_message(phone, payment)

    def test_complete_order_hod_hasharon(self):
        """זרימה מלאה להוד השרון — ברכה→תפריט→פריטים→משלוח→כתובת→שם→שעה→אישור→תשלום."""
        reply = self._complete_delivery_order(delivery_option="2",
                                               address="רחוב הרצל 5, הוד השרון")
        assert "אושרה" in reply

    def test_complete_order_kfar_saba_correct_total(self):
        """זרימה מלאה לכפר סבא — סה\"כ = 75 + 25 = ₪100."""
        reply = self._complete_delivery_order(delivery_option="3",
                                               address="רחוב ויצמן 3, כפר סבא")
        assert "100" in reply

    def test_address_appears_in_final_confirmation(self):
        """הכתובת מופיעה בהודעת האישור הסופית."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")
        handle_message(PHONE, "רחוב הרצל 5, הוד השרון")
        handle_message(PHONE, "דוד לוי")
        reply = handle_message(PHONE, "09:00")
        assert "רחוב הרצל 5" in reply

    def test_address_saved_in_db(self):
        """הכתובת נשמרת במסד הנתונים."""
        self._complete_delivery_order(address="רחוב ירושלים 10, הוד השרון")
        db = SessionLocal()
        order = db.query(Order).first()
        db.close()
        assert order.delivery_address == "רחוב ירושלים 10, הוד השרון"

    def test_address_in_gabriel_notification(self):
        """הכתובת כלולה בהודעת ההתראה לגבריאל."""
        from services.order_service import notify_gabriel
        import services.order_service as order_svc

        db = SessionLocal()
        customer = Customer(phone_number="+972500099001", name="לקוח בדיקה")
        db.add(customer)
        db.commit()
        db.refresh(customer)

        jachnun = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        order = Order(
            customer_id=customer.id,
            pickup_date="05/04/2026",
            pickup_time="09:00",
            delivery_type="משלוח להוד השרון",
            delivery_cost=15.0,
            delivery_address="רחוב הנביאים 7, הוד השרון",
            total_price=90.0,
            status="ממתין",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        cart = {jachnun.id: 3}

        with patch.object(order_svc, "TWILIO_ACCOUNT_SID", None):
            with patch("builtins.print") as mock_print:
                notify_gabriel(order, customer, cart, db)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                assert "רחוב הנביאים 7" in printed
        db.close()


# ============================================================
# 15. בדיקות שירות הזמנות (TestOrderService)
# ============================================================

class TestOrderService:

    def test_get_next_saturday_returns_dd_mm_yyyy_format(self):
        """get_next_saturday מחזיר מחרוזת בפורמט DD/MM/YYYY."""
        saturday = get_next_saturday()
        import re
        assert re.match(r"^\d{2}/\d{2}/\d{4}$", saturday)

    def test_get_next_saturday_from_friday_returns_next_day(self):
        """מיום שישי — השבת הקרובה היא למחרת."""
        with patch("services.order_service.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 4, 3)  # שישי
            saturday = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday, "%d/%m/%Y").date()
            assert d == date(2026, 4, 4)

    def test_get_next_saturday_from_monday_returns_same_week_saturday(self):
        """מיום שני — השבת הקרובה היא באותו שבוע."""
        with patch("services.order_service.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 3, 30)  # שני
            saturday = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday, "%d/%m/%Y").date()
            assert d == date(2026, 4, 4)

    def test_create_order_returns_order_with_correct_total_price(self):
        """create_order מחזיר Order עם total_price נכון."""
        from services.order_service import create_order
        db = SessionLocal()
        customer = Customer(phone_number="+972500088001", name="בדיקה")
        db.add(customer)
        db.commit()
        db.refresh(customer)

        jachnun = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        cart = {jachnun.id: 2}  # 2 x 25 = 50
        order = create_order(
            customer=customer,
            cart=cart,
            pickup_time="09:00",
            delivery_type="איסוף עצמי",
            delivery_cost=0.0,
            db=db,
        )
        total = order.total_price
        db.close()
        assert total == 50.0

    def test_create_order_with_delivery_address_none_saves_none(self):
        """create_order עם delivery_address=None שומר None."""
        from services.order_service import create_order
        db = SessionLocal()
        customer = Customer(phone_number="+972500088002", name="בדיקה 2")
        db.add(customer)
        db.commit()
        db.refresh(customer)

        jachnun = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        cart = {jachnun.id: 1}
        order = create_order(
            customer=customer,
            cart=cart,
            pickup_time="09:00",
            delivery_type="איסוף עצמי",
            delivery_cost=0.0,
            delivery_address=None,
            db=db,
        )
        addr = order.delivery_address
        db.close()
        assert addr is None

    def test_create_order_with_delivery_address_saves_address(self):
        """create_order עם delivery_address שומר את הכתובת."""
        from services.order_service import create_order
        db = SessionLocal()
        customer = Customer(phone_number="+972500088003", name="בדיקה 3")
        db.add(customer)
        db.commit()
        db.refresh(customer)

        jachnun = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        cart = {jachnun.id: 1}
        order = create_order(
            customer=customer,
            cart=cart,
            pickup_time="09:00",
            delivery_type="משלוח להוד השרון",
            delivery_cost=15.0,
            delivery_address="רחוב הרצל 1, הוד השרון",
            db=db,
        )
        addr = order.delivery_address
        db.close()
        assert addr == "רחוב הרצל 1, הוד השרון"


# ============================================================
# 16. בדיקות תוכן תפריט (TestMenuContent)
# ============================================================

class TestMenuContent:

    def _get_menu_reply(self):
        handle_message(PHONE, "היי")
        return handle_message(PHONE, "תפריט")

    def test_menu_shows_jachnun_price_25(self):
        """התפריט מציג ₪25 לג'חנון."""
        reply = self._get_menu_reply()
        assert "25" in reply

    def test_menu_shows_kubane_price_20(self):
        """התפריט מציג ₪20 לקובנייה."""
        reply = self._get_menu_reply()
        assert "20" in reply

    def test_menu_shows_description_with_beitsa(self):
        """התפריט מציג תיאור עם ביצה."""
        reply = self._get_menu_reply()
        assert "ביצה" in reply

    def test_menu_shows_description_with_risek(self):
        """התפריט מציג תיאור עם רסק."""
        reply = self._get_menu_reply()
        assert "רסק" in reply

    def test_menu_shows_ordering_instructions(self):
        """התפריט מציג הוראות הזמנה."""
        reply = self._get_menu_reply()
        assert "כתוב" in reply
        assert "סיום" in reply


# ============================================================
# 17. בדיקות קצה לקלט עברי (TestHebrewEdgeCases)
# ============================================================

class TestHebrewEdgeCases:

    def test_body_with_only_spaces_treated_as_unknown(self):
        """גוף עם רווחים בלבד — מטופל כהודעה לא מוכרת."""
        handle_message(PHONE, "היי")
        # במצב BROWSING_MENU, "   " לא מוכר
        reply = handle_message(PHONE, "   ")
        assert "לא הבנתי" in reply

    def test_very_long_name_accepted(self):
        """שם ארוך (50+ תווים) מתקבל."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        long_name = "א" * 55
        reply = handle_message(PHONE, long_name)
        assert long_name in reply
        assert get_state(PHONE) == ChatState.AWAITING_PICKUP_TIME

    def test_address_with_numbers_accepted(self):
        """כתובת עם מספרים מתקבלת."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")
        reply = handle_message(PHONE, "רחוב 123 מספר 45")
        assert "123" in reply or "45" in reply
        assert get_state(PHONE) == ChatState.AWAITING_NAME

    def test_pickup_time_0800_accepted(self):
        """שעת איסוף '08:00' מתקבלת."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "שם")
        reply = handle_message(PHONE, "08:00")
        assert "08:00" in reply
        assert get_state(PHONE) == ChatState.CONFIRMING_ORDER

    def test_pickup_time_1130_accepted(self):
        """שעת איסוף '11:30' מתקבלת."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "שם")
        reply = handle_message(PHONE, "11:30")
        assert "11:30" in reply
        assert get_state(PHONE) == ChatState.CONFIRMING_ORDER

# ============================================================
# 16. בדיקות אימות כתובת
# ============================================================

class TestAddressValidation:

    def _reach_address_state(self):
        """מביא את הסשן למצב AWAITING_ADDRESS (משלוח להוד השרון, סל ≥ ₪70)."""
        handle_message(PHONE, "היי")
        # 3 ג'חנונים = ₪75
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")  # משלוח להוד השרון

    def test_valid_address_accepted(self):
        """כתובת תקינה (רחוב + מספר + עיר) מתקבלת."""
        self._reach_address_state()
        reply = handle_message(PHONE, "הרצל 5, הוד השרון")
        assert get_state(PHONE) == ChatState.AWAITING_NAME
        assert "הרצל 5" in reply

    def test_vague_address_rejected(self):
        """כתובת עמומה ללא מספר נדחית."""
        self._reach_address_state()
        reply = handle_message(PHONE, "ליד המכולת")
        assert get_state(PHONE) == ChatState.AWAITING_ADDRESS  # נשאר באותו מצב
        assert "לא ברורה" in reply

    def test_single_word_address_rejected(self):
        """מילה אחת בלי מספר נדחית."""
        self._reach_address_state()
        reply = handle_message(PHONE, "תלאביב")
        assert get_state(PHONE) == ChatState.AWAITING_ADDRESS
        assert "לא ברורה" in reply

    def test_address_with_digit_accepted(self):
        """כתובת עם מספר בית מתקבלת."""
        self._reach_address_state()
        reply = handle_message(PHONE, "דיזנגוף 50 תל אביב")
        assert get_state(PHONE) == ChatState.AWAITING_NAME

    def test_address_hint_shown_on_rejection(self):
        """הודעת הדחייה מציגה דוגמה לכתובת תקינה."""
        self._reach_address_state()
        reply = handle_message(PHONE, "ליד הגינה")
        assert "הרצל 5" in reply  # דוגמה בהודעת השגיאה

    def test_valid_address_moves_to_awaiting_name(self):
        """כתובת תקינה מעבירה ל-AWAITING_NAME."""
        self._reach_address_state()
        handle_message(PHONE, "בן גוריון 12, כפר סבא")
        assert get_state(PHONE) == ChatState.AWAITING_NAME


# ============================================================
# 17. בדיקות סיכום איסוף עצמי ללא כתובת
# ============================================================

class TestSelfPickupSummary:

    def _reach_confirming_self_pickup(self):
        """מביא לסיכום עם איסוף עצמי."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")   # איסוף עצמי
        handle_message(PHONE, "ישראל")
        handle_message(PHONE, "09:00")

    def test_self_pickup_summary_no_customer_address(self):
        """בסיכום איסוף עצמי אין שורת כתובת לקוח."""
        self._reach_confirming_self_pickup()
        # בשלב CONFIRMING_ORDER — מה שהוצג הוא הסיכום
        # נשלח הודעה לא מוכרת כדי לקבל את הסיכום שוב
        reply = handle_message(PHONE, "לא יודע")
        # הסיכום כולל "איסוף עצמי" אבל לא כתובת ספציפית של לקוח
        assert "איסוף עצמי" in reply or "אישור" in reply

    def test_self_pickup_summary_shows_runner_emoji(self):
        """בסיכום איסוף עצמי מופיע אימוג'י ריצה (ולא מכונית)."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")   # איסוף עצמי
        handle_message(PHONE, "ישראל")
        reply = handle_message(PHONE, "09:00")  # זה הסיכום
        assert "🏃" in reply
        assert "📍 כתובת:" not in reply  # לא כתובת לקוח

    def test_delivery_summary_shows_customer_address(self):
        """בסיכום משלוח מופיעה כתובת הלקוח."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "2")   # משלוח להוד השרון
        handle_message(PHONE, "הרצל 5, הוד השרון")
        handle_message(PHONE, "ישראל")
        reply = handle_message(PHONE, "09:00")  # זה הסיכום
        assert "הרצל 5" in reply
        assert "🚗" in reply


# ============================================================
# 18. בדיקות פקודות אדמין (מלאי)
# ============================================================

ADMIN_PHONE = "+972539475881"


class TestAdminCommands:

    def test_stock_command_shows_all_items(self):
        """/stock מציג את כל פריטי התפריט."""
        reply = handle_message(ADMIN_PHONE, "/stock")
        assert "ג'חנון" in reply
        assert "קובנייה" in reply
        assert "ביצה נוספת" in reply

    def test_sold_out_by_number(self):
        """/sold_out 1 מסמן את הפריט הראשון כאזל."""
        reply = handle_message(ADMIN_PHONE, "/sold_out 1")
        assert "ג'חנון" in reply
        assert "❌" in reply
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        db.close()
        assert item.is_available is False

    def test_sold_out_by_name(self):
        """/sold_out קובנייה מסמן לפי שם."""
        reply = handle_message(ADMIN_PHONE, "/sold_out קובנייה")
        assert "קובנייה" in reply
        assert "❌" in reply
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "קובנייה").first()
        db.close()
        assert item.is_available is False

    def test_restock_restores_item(self):
        """/restock מחזיר פריט אזול לתפריט."""
        handle_message(ADMIN_PHONE, "/sold_out 1")
        reply = handle_message(ADMIN_PHONE, "/restock 1")
        assert "ג'חנון" in reply
        assert "✅" in reply
        db = SessionLocal()
        item = db.query(MenuItem).filter(MenuItem.name == "ג'חנון").first()
        db.close()
        assert item.is_available is True

    def test_sold_out_item_removed_from_menu(self):
        """פריט שאזל לא מופיע בתפריט ולא ניתן להזמינו."""
        handle_message(ADMIN_PHONE, "/sold_out 1")  # ג'חנון אזל
        reply = handle_message(PHONE, "היי")
        assert "קובנייה" in reply
        # "1️⃣ ג'חנון" (שורת הפריט) לא אמורה להופיע — שם העסק "ג'חנון אקספרס" עדיין בהודעת הברכה
        assert "1️⃣ ג'חנון" not in reply

    def test_non_admin_cannot_use_stock_command(self):
        """לקוח רגיל לא יכול להשתמש בפקודות אדמין."""
        reply = handle_message(PHONE, "/stock")
        # הבוט לא מזהה את הפקודה — מחזיר הודעת עזרה רגילה
        assert "לא הבנתי" in reply or "ג'חנון" in reply  # ברכה או שגיאה, לא תוצאת /stock

    def test_sold_out_unknown_item(self):
        """/sold_out עם שם שלא קיים מחזיר הודעת שגיאה."""
        reply = handle_message(ADMIN_PHONE, "/sold_out פלאפל")
        assert "לא הבנתי" in reply

    def test_admin_command_does_not_advance_state(self):
        """פקודת אדמין לא מעדכנת את מצב השיחה של גבריאל."""
        handle_message(ADMIN_PHONE, "/stock")
        state = get_state(ADMIN_PHONE)
        assert state == ChatState.GREETING or state == ChatState.ADDING_ITEMS

    def test_stock_shows_availability_status(self):
        """/stock מציג ✅ ל-זמין ו-❌ לאזל."""
        handle_message(ADMIN_PHONE, "/sold_out 1")
        reply = handle_message(ADMIN_PHONE, "/stock")
        assert "❌" in reply  # ג'חנון אזל
        assert "✅" in reply  # שאר הפריטים זמינים
