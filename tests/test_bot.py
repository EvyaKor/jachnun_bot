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
        """אחרי ברכה — המצב עובר ל-BROWSING_MENU."""
        handle_message(PHONE, "היי")
        assert get_state(PHONE) == ChatState.BROWSING_MENU

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
        handle_message(PHONE, "טסט")  # שם
        reply = handle_message(PHONE, "09:00")  # שעה
        assert "₪90" in reply  # 75 + 15

    def test_kfar_saba_cost_added(self):
        """עלות משלוח כפר סבא מתווספת נכון."""
        self._fill_cart(total_above_70=True)
        handle_message(PHONE, "3")  # כפר סבא +25
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


# ============================================================
# 4. בדיקות זרימת אישור מלאה
# ============================================================

class TestFullOrderFlow:

    def _complete_order(self, delivery="1", payment="1", name="טסט"):
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, delivery)
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
        """הודעה לא מוכרת במצב אישור מחזירה עזרה."""
        handle_message(PHONE, "היי")
        handle_message(PHONE, "הזמנה")
        handle_message(PHONE, "1")
        handle_message(PHONE, "סיום")
        handle_message(PHONE, "1")
        handle_message(PHONE, "טסט")
        handle_message(PHONE, "09:00")
        reply = handle_message(PHONE, "משהו אחר")
        assert "לא הבנתי" in reply

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
# 5. בדיקות לוגיקת שבת
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
        with patch("services.order_service.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 4)  # שבת
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            saturday_str = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
            assert d > date(2026, 4, 4)

    def test_next_saturday_from_sunday(self):
        """מיום ראשון — השבת הקרובה היא 6 ימים קדימה."""
        with patch("services.order_service.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 29)  # ראשון
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            saturday_str = get_next_saturday()
            from datetime import datetime
            d = datetime.strptime(saturday_str, "%d/%m/%Y").date()
            assert d == date(2026, 4, 4)

    def test_order_date_shown_in_confirmation(self):
        """תאריך השבת מופיע בהודעת האישור."""
        handle_message(PHONE, "היי")
        reply = handle_message(PHONE, "הזמנה")
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
        assert get_state(phone2) == ChatState.BROWSING_MENU

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
        """פריטי התפריט קיימים במסד הנתונים."""
        db = SessionLocal()
        items = db.query(MenuItem).all()
        db.close()
        assert len(items) == 2
        names = [i.name for i in items]
        assert "ג'חנון" in names
        assert "קובנייה" in names

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
        assert count == 2

    def test_whitespace_in_message_stripped(self):
        """רווחים בתחילת/סוף הודעה מוסרים."""
        reply = handle_message(PHONE, "  היי  ")
        assert "ג'חנון אקספרס" in reply

    def test_new_session_starts_at_greeting(self):
        """session חדש מתחיל במצב GREETING."""
        assert get_state(PHONE) == ChatState.GREETING

    def test_jachnun_is_pareve(self):
        """ג'חנון הוא פרווה."""
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
        """כל פריטי התפריט זמינים כברירת מחדל."""
        db = SessionLocal()
        items = db.query(MenuItem).filter(MenuItem.is_available == True).all()
        db.close()
        assert len(items) == 2


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
        assert state == ChatState.BROWSING_MENU
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
